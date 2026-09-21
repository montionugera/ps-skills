"""ps-release-workflow:refine — promote an idea (I-NNN) to refined (F-NNN) (D11/SR-1).

Reads/writes/commits both the idea and refined catalogs + the refined folder on the
long-lived `_release` worktree (release/<v>), never the main checkout. Refuses if no
release is in progress (D12).

Content written at idea stage is CARRIED FORWARD into the F-NNN folder — only
untouched skeletons are replaced by the F-NNN ones. See `_carry_forward`.
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import re
import shutil
import sys
from pathlib import Path

from lib.backlog_paths import (
    NoReleaseInProgressError,
    get_backlog_catalog_path,
    get_release_worktree,
)
from lib.catalog import (
    CatalogEntryNotFoundError,
    add_refined_entry,
    find_entry,
    mark_promoted,
    update_entry,
)
from lib.git_ops import commit_all
from lib.repo import find_repo_root, is_ps_release_workflow_repo
from lib.slug import slugify
from lib.state import file_lock, mutate_state
from scripts import new_idea as _new_idea
from scripts.new_idea import LEGACY_SPEC_TEMPLATE as LEGACY_IDEA_SPEC_TEMPLATE
from scripts.new_idea import RESEARCH_TEMPLATE as IDEA_RESEARCH_TEMPLATE
from scripts.new_idea import SPEC_TEMPLATE as IDEA_SPEC_TEMPLATE


class IdeaNotFoundError(Exception): pass
class AlreadyPromotedError(Exception): pass
class SpecNotReadyError(Exception): pass


SPEC_TEMPLATE = """\
---
title: "{title}"
id: {id}
from_idea: {from_idea}
status: refined
---

# {title} — design

## Goal

(one sentence)

## Architecture

(2-3 sentences)

## Components

(list — each with one responsibility)

## Data flow / state

## Tests / acceptance criteria
"""

PLAN_TEMPLATE = """\
# {title} Implementation Plan

> Fill via `/superpowers:writing-plans` once the spec is final.
"""

# Ideas captured before plan.md was dropped from the idea skeleton still carry
# this exact text on disk. Kept here (not in new_idea) purely so carry-forward can
# recognise it as an untouched skeleton and let the F-NNN plan skeleton win.
LEGACY_IDEA_PLAN_TEMPLATE = """\
# {title} — plan placeholder

Empty until promoted to F-NNN and filled via `/superpowers:writing-plans`.
"""

# Frontmatter keys that carry F-NNN identity — rewritten on carry-forward.
# Anything else the author added is kept.
_IDENTITY_KEYS = ("title", "id", "from_idea", "status")

# A frontmatter line that starts a new top-level key: unindented, plain key name,
# then a colon. Prose like "We are unsure: really" does not match (keys hold no spaces).
_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_][\w.-]*):(.*)$")

# Values after `key:` that legitimately continue onto indented lines.
_BLOCK_SCALAR_VALUES = ("", ">", "|", ">-", "|-", ">+", "|+")


def _normalized(text: str) -> str:
    """Whitespace-insensitive form used to compare a file against its skeleton."""
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _is_untouched_skeleton(text: str, skeleton: str) -> bool:
    """True only when `text` is the generated skeleton verbatim (modulo whitespace).

    Deliberately conservative: any other difference counts as real content, because
    keeping a skeleton by mistake is harmless and destroying content is not.
    """
    return _normalized(text) == _normalized(skeleton)


_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_CHECKLIST_ITEM_RE = re.compile(r"^\s*[-*] \[[ xX]\]\s+\S")


def _has_acceptance_checklist(text: str, placeholders: list[str]) -> tuple[bool, bool]:
    """(heading present, real checklist item under it). The section ends at the
    next heading of any level, so a checklist elsewhere in the spec does not count;
    neither does an item that is still the skeleton's placeholder."""
    heading = item = in_section = False
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            in_section = "acceptance criteria" in m.group(1).lower()
            heading = heading or in_section
        elif (in_section and _CHECKLIST_ITEM_RE.match(line)
              and not any(ph in line for ph in placeholders)):
            item = True
    return heading, item


def spec_readiness_problems(text: str) -> list[str]:
    """Why this idea spec is not ready to refine; empty when it is.

    Two mechanical checks: no line of the idea skeleton is still unfilled (the
    placeholders are read from new_idea.SPEC_TEMPLATE, never copied here), and
    there is an "Acceptance criteria" heading with at least one `- [ ]` item.
    """
    placeholders = _new_idea.idea_spec_placeholders()
    problems = [
        f"unfilled template placeholder: {placeholder}"
        for placeholder in placeholders
        if placeholder in text
    ]
    heading, item = _has_acceptance_checklist(text, placeholders)
    if not heading:
        problems.append('no "Acceptance criteria" heading')
    elif not item:
        problems.append('"Acceptance criteria" has no checklist item (- [ ] ...)')
    return problems


def _check_spec_ready(spec: Path, idea_id: str, *, allow_empty_spec: bool) -> None:
    """Refuse (or, with the escape hatch, warn about) an unready idea spec."""
    text = _read_text(spec)
    if text is None:
        problems = [f"spec.md is missing or not readable as text: {spec}"]
    else:
        problems = spec_readiness_problems(text)
    if not problems:
        return
    listing = "\n".join(f"  - {p}" for p in problems)
    if allow_empty_spec:
        print(
            f"WARNING: refining {idea_id} with an unready spec "
            f"(--allow-empty-spec):\n{listing}",
            file=sys.stderr,
        )
        return
    raise SpecNotReadyError(
        f"{idea_id} spec is not ready to refine ({spec}):\n{listing}\n"
        f"Fill the spec in first, or pass --allow-empty-spec to refine anyway."
    )


def _read_text(path: Path) -> str | None:
    """File text, or None if it is absent or not decodable as UTF-8 text."""
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return None


def _frontmatter_close(lines: list[str]) -> int | None:
    """Index of the closing `---`, or None if this is not frontmatter we may rewrite.

    A leading `---` is usually frontmatter, but it can also be a horizontal rule over
    prose. The tell is YAML that cannot parse — a line that is neither a top-level
    `key:` nor a legal continuation of one (an indented line may only follow a key
    whose value is empty or a block-scalar marker). Anything ambiguous returns None,
    and the caller then leaves the file's own text completely alone.
    """
    if not lines or lines[0].strip() != "---":
        return None
    try:
        close = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None

    saw_key = False
    continuable = False
    for line in lines[1:close]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _TOP_LEVEL_KEY_RE.match(line)
        if match:
            saw_key = True
            continuable = match.group(2).strip() in _BLOCK_SCALAR_VALUES
            continue
        if line[:1].isspace() and continuable:
            continue
        return None
    return close if saw_key else None


def _rewrite_spec_identity(text: str, *, title: str, feat_id: str, idea_id: str) -> str:
    """Keep a filled spec's body; restate its frontmatter as the F-NNN identity.

    Never drops a line: only the identity key lines themselves are rewritten, and a
    leading block that is not parsable frontmatter is left untouched with the identity
    block prepended instead.
    """
    identity = {
        "title": f'title: "{title}"',
        "id": f"id: {feat_id}",
        "from_idea": f"from_idea: {idea_id}",
        "status": "status: refined",
    }
    lines = text.splitlines()
    close = _frontmatter_close(lines)
    if close is None:
        return "---\n" + "\n".join(identity.values()) + "\n---\n\n" + text

    front: list[str] = []
    seen: set[str] = set()
    for line in lines[1:close]:
        match = _TOP_LEVEL_KEY_RE.match(line)
        key = match.group(1) if match else None
        if key in identity:
            front.append(identity[key])
            seen.add(key)
        else:
            front.append(line)
    front.extend(line for key, line in identity.items() if key not in seen)

    # Rejoin from the raw text so the body keeps its exact bytes. `close` is the last
    # line when the frontmatter ends at EOF with no trailing newline — hence the slice
    # rather than an index, which used to raise IndexError.
    body = "\n".join(text.split("\n")[close + 1:])
    return "---\n" + "\n".join(front) + "\n---\n" + body


def _carry_forward(idea_folder: Path, folder: Path, *, title: str,
                   idea_id: str, feat_id: str) -> None:
    """Populate the F-NNN folder from the idea folder, then reconcile skeletons.

    Content written at idea stage survives; untouched skeletons are replaced by the
    F-NNN ones (spec, plan) or dropped (research — refine no longer seeds an empty
    one, but a filled idea research.md must still arrive).
    """
    if idea_folder.is_dir():
        shutil.copytree(idea_folder, folder, dirs_exist_ok=True)

    # NB every branch below distinguishes "absent" (nothing carried — write the
    # skeleton) from "present but not decodable as text" (content we cannot judge —
    # leave it alone). Collapsing the two would overwrite e.g. a cp1252 spec.

    spec = folder / "spec.md"
    carried_spec = _read_text(spec)
    if not spec.exists():
        spec.write_text(SPEC_TEMPLATE.format(title=title, id=feat_id, from_idea=idea_id))
    elif carried_spec is not None:
        if any(
            _is_untouched_skeleton(carried_spec, skeleton.format(title=title, id=idea_id))
            for skeleton in (IDEA_SPEC_TEMPLATE, LEGACY_IDEA_SPEC_TEMPLATE)
        ):
            spec.write_text(
                SPEC_TEMPLATE.format(title=title, id=feat_id, from_idea=idea_id)
            )
        else:
            spec.write_text(
                _rewrite_spec_identity(
                    carried_spec, title=title, feat_id=feat_id, idea_id=idea_id
                )
            )

    plan = folder / "plan.md"
    carried_plan = _read_text(plan)
    if not plan.exists() or (
        carried_plan is not None
        and _is_untouched_skeleton(carried_plan, LEGACY_IDEA_PLAN_TEMPLATE.format(title=title))
    ):
        plan.write_text(PLAN_TEMPLATE.format(title=title))

    research = folder / "research.md"
    carried_research = _read_text(research)
    if carried_research is not None and _is_untouched_skeleton(
        carried_research, IDEA_RESEARCH_TEMPLATE.format(title=title)
    ):
        research.unlink()


def promote_idea_to_refined(repo: Path, idea_id: str, *,
                            allow_empty_spec: bool = False) -> dict:
    repo = Path(repo)
    if not is_ps_release_workflow_repo(repo):
        raise RuntimeError(f"{repo} not opted into ps-release-workflow")

    # Resolve the _release worktree (raises NoReleaseInProgressError if no release).
    wt = get_release_worktree(repo)

    idea_cat = get_backlog_catalog_path(repo, "idea")
    idea = find_entry(idea_cat, idea_id)
    if idea is None:
        raise IdeaNotFoundError(idea_id)
    if idea.get("promoted_to"):
        raise AlreadyPromotedError(f"{idea_id} already promoted to {idea['promoted_to']}")

    # The spec gate runs BEFORE anything is minted, so a refusal leaves no state
    # to roll back. It lives here, not in main(), so every caller passes through it.
    idea_folder = wt / ".claude" / "idea_backlog" / f"{idea_id}-{slugify(idea['title'])}"
    _check_spec_ready(idea_folder / "spec.md", idea_id, allow_empty_spec=allow_empty_spec)

    ref_cat = get_backlog_catalog_path(repo, "refined")

    # Serialize the whole mutate+commit on the shared _release worktree (same
    # lock ship/claim take) so a concurrent backlog script can't interleave and
    # `git add -A` commit a half-written snapshot (audit A4).
    with file_lock(wt):
        # F-NNN is minted here, BEFORE mark_promoted. mark_promoted needs the
        # minted id, so the order can't be flipped — instead everything after
        # the mint rolls back on failure (m-4): remove the minted refined entry
        # + folder (and best-effort unstamp the idea) so a retry re-mints the
        # SAME id instead of orphaning it and minting the next one.
        feat = add_refined_entry(
            ref_cat, idea_id=idea_id, title=idea["title"], epic=idea.get("epic")
        )
        folder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-{slugify(idea['title'])}"
        try:
            folder.mkdir(parents=True)
            _carry_forward(
                idea_folder, folder,
                title=idea["title"], idea_id=idea_id, feat_id=feat["id"],
            )

            mark_promoted(idea_cat, idea_id=idea_id, refined_id=feat["id"])

            commit_all(wt, f"chore(backlog): promote {idea_id} → {feat['id']} {idea['title']}")
        except BaseException:
            def drop_minted(entries: list) -> list:
                return [e for e in entries if e.get("id") != feat["id"]]
            mutate_state(ref_cat, drop_minted, default=[])
            shutil.rmtree(folder, ignore_errors=True)
            # If the failure hit AFTER mark_promoted (e.g. the commit), unstamp
            # the idea too so a retry isn't refused as AlreadyPromoted.
            try:
                update_entry(idea_cat, idea_id, lambda e: e.update(promoted_to=None))
            except Exception:
                pass
            raise
    return feat


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="psrw refine",
        description="Promote a captured idea (I-NNN) into a refined feature (F-NNN).",
    )
    p.add_argument("idea_id", metavar="I-NNN", help="the idea id to promote")
    p.add_argument(
        "--allow-empty-spec", action="store_true",
        help="refine even if spec.md still has template placeholders or no "
             "acceptance-criteria checklist (prints a warning)",
    )
    args = p.parse_args()
    idea_id = args.idea_id
    repo = find_repo_root(Path.cwd())
    try:
        feat = promote_idea_to_refined(
            repo, idea_id, allow_empty_spec=args.allow_empty_spec)
    except (IdeaNotFoundError, AlreadyPromotedError, SpecNotReadyError,
            CatalogEntryNotFoundError,
            RuntimeError, NoReleaseInProgressError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "id": feat["id"], "from_idea": idea_id}))
    print(f"\n✅ Promoted {idea_id} → {feat['id']}: {feat['title']}")
    print(
        "   (Refine assumes the idea already had an approved spec under "
        "docs/superpowers/specs/.)"
    )
    print(f"   Next: write the plan → /superpowers:writing-plans, then: psrw claim {feat['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
