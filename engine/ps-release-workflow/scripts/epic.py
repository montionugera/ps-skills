"""psrw epic — open an epic, fan it out into ideas, verify it."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import shutil
import sys
from pathlib import Path

from lib.backlog_paths import (
    NoReleaseInProgressError, get_backlog_catalog_path, get_release_worktree,
    read_release_state,
)
from lib.catalog import CatalogEntryNotFoundError, add_idea_entry, find_entry
from lib.epic import add_epic_entry, epic_children, epic_folder_path, try_begin_verification
from lib.epic_gate import run_and_record
from lib.git_ops import GitError, _run as git_run, commit_all
from lib.hooks import HookPathError, resolve_hook
from lib.repo import find_repo_root
from lib.slug import SlugError, slugify
from lib.state import file_lock, mutate_state
from scripts.new_idea import SPEC_TEMPLATE as IDEA_SPEC_TEMPLATE
from scripts.promote_idea_to_refined import _is_untouched_skeleton


class EpicNotVerifiableError(Exception):
    """try_begin_verification lost the CAS: without --force this means someone
    else is already verifying epic_id, or it is already verified."""


class EpicPlanError(Exception):
    """A preflight refusal: `epic run` must not start."""


_SPEC_SKELETON = """---
title: {yaml_title}
id: {epic_id}
status: epic
---

# {title}

## Outcome

<!-- What is true once every slice has shipped? -->

## Slices

<!-- One line per slice. `psrw epic fanout` turns these into ideas. -->
"""

_VERIFICATION_SKELETON = """---
title: {yaml_title}
id: {epic_id}
---

# How we will know {epic_id} works

Prose for humans. `scripts/epic-check.sh` implements these assertions; the
toolkit never parses this file.

## Assertions

1. <!-- end-to-end assertion -->
"""


def _sanitize(title: str) -> str:
    """Collapse to a single line so a stray newline can't break out of the
    YAML front matter or the markdown heading. YAML-significant characters
    (quotes, colons) are handled at the point of use by _yaml_quote, not here."""
    return " ".join(title.split())


def _yaml_quote(s: str) -> str:
    """Render as a YAML double-quoted scalar. An unquoted `title: {title}` plain
    scalar breaks on a colon (e.g. "Epic: Payment gateway"), not just on quotes —
    docs/known-issues.md's fix only stripped quotes, which is moot since the
    skeleton was unquoted to begin with. Quoting closes both bugs at once."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _fanout_idea_spec(title: str, idea_id: str) -> str:
    """The exact spec.md `epic fanout` writes for a new slice idea. One source of
    truth: epic_fanout writes it and epic_plan compares against it, so the two
    cannot drift."""
    return (f"---\ntitle: {_yaml_quote(title)}\nid: {idea_id}\n"
            f"status: idea\n---\n\n# {title}\n")


def _rollback_epic(epic_cat: Path, epic_id: str, folder: Path) -> None:
    """Mirror of promote_idea_to_refined's rollback: drop the minted catalog
    entry, then best-effort remove the folder, so a retry re-mints the SAME id
    instead of orphaning it and minting the next one."""

    def drop_minted(entries: list) -> list:
        return [e for e in entries if e.get("id") != epic_id]

    mutate_state(epic_cat, drop_minted, default=[])
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)


def _rollback_ideas(idea_cat: Path, minted: list[dict], folders: list[Path]) -> None:
    """Mirror of promote_idea_to_refined's rollback, generalized to a batch: drop
    every minted idea from the catalog, then best-effort remove every folder that
    was created, so a retry re-mints the SAME ids instead of orphaning them."""
    minted_ids = {idea["id"] for idea in minted}

    def drop_minted(entries: list) -> list:
        return [e for e in entries if e.get("id") not in minted_ids]

    mutate_state(idea_cat, drop_minted, default=[])
    for folder in folders:
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)


def epic_open(repo: Path, title: str) -> dict:
    title = _sanitize(title)
    slug = slugify(title)  # fail fast before any catalog mutation
    wt = get_release_worktree(repo)
    epic_cat = get_backlog_catalog_path(repo, "epic")
    with file_lock(wt):
        epic = add_epic_entry(epic_cat, title)
        folder = wt / ".claude" / "epic_backlog" / f"{epic['id']}-{slug}"
        try:
            folder.mkdir(parents=True)
            (folder / "spec.md").write_text(
                _SPEC_SKELETON.format(
                    title=title, yaml_title=_yaml_quote(title), epic_id=epic["id"]
                )
            )
            (folder / "verification.md").write_text(
                _VERIFICATION_SKELETON.format(
                    title=title, yaml_title=_yaml_quote(title), epic_id=epic["id"]
                )
            )
            commit_all(wt, f"chore(epic): open {epic['id']} {title}")
        except BaseException:
            _rollback_epic(epic_cat, epic["id"], folder)
            raise
    return {"epic": epic, "folder": folder}


def epic_fanout(repo: Path, epic_id: str, titles: list[str]) -> dict:
    """Mint one IDEA per slice — never a feature. Minting F-NNN directly would
    break the from_idea invariant and auto-chain idea -> refine."""
    if not titles:
        raise ValueError("epic_fanout requires at least one slice title")
    titles = [_sanitize(t) for t in titles]
    wt = get_release_worktree(repo)
    # A typo'd id must not silently mint N ideas tagged to an epic that does not
    # exist — nothing would ever complete them. This is the same silent-drift
    # class CatalogEntryNotFoundError was introduced to kill (lib/catalog.py:10-22).
    epic_cat = get_backlog_catalog_path(repo, "epic")
    if find_entry(epic_cat, epic_id) is None:
        raise CatalogEntryNotFoundError(epic_id, epic_cat)
    idea_cat = get_backlog_catalog_path(repo, "idea")
    minted: list[dict] = []
    folders: list[Path] = []
    with file_lock(wt):
        try:
            for title in titles:
                idea = add_idea_entry(idea_cat, title, epic=epic_id)
                minted.append(idea)
                folder = wt / ".claude" / "idea_backlog" / f"{idea['id']}-{slugify(title)}"
                folder.mkdir(parents=True)
                folders.append(folder)
                (folder / "spec.md").write_text(_fanout_idea_spec(title, idea["id"]))
                (folder / "research.md").write_text(f"# Research — {title}\n")
            commit_all(wt, f"chore(epic): fan out {epic_id} into {len(minted)} ideas")
        except BaseException:
            _rollback_ideas(idea_cat, minted, folders)
            raise
    return {"epic_id": epic_id, "ideas": minted}


def epic_verify(repo: Path, epic_id: str, force: bool = False) -> dict:
    """Manually (re-)run the G-E2 outcome check against the release's current HEAD.

    Shares the CAS + run-outside-lock/record-under-lock path with ship's
    automatic trigger (lib.epic_gate.run_and_record) so exactly one place
    decides verified vs failed. `force` is the only way to reclaim an epic
    stuck 'verifying' from a crashed run, or to re-check an already-'verified'
    epic whose verified_sha no longer matches release HEAD — see
    try_begin_verification's docstring for why that must be one atomic CAS,
    not demote_epic() + try_begin_verification().
    """
    rel_wt = get_release_worktree(repo)
    state = read_release_state(repo)
    if state is None:
        raise NoReleaseInProgressError("No release in progress")
    release_version = state["version"]
    epic_cat = get_backlog_catalog_path(repo, "epic")
    idea_cat = get_backlog_catalog_path(repo, "idea")
    # Read HEAD and CAS under the same lock ship uses (ship_current_work_to_
    # release.py) — HEAD is only stable there. Unlocked, a concurrent ship's
    # merge -> Gate-1-fails -> `reset --hard HEAD~1` can land between the
    # read and the CAS, pinning verifying_sha to a commit that release/<v>
    # no longer contains (finding 6/14).
    with file_lock(rel_wt):
        sha = git_run(rel_wt, "rev-parse", "HEAD").stdout.strip()
        won = try_begin_verification(epic_cat, epic_id, sha, force=force)
        if won:
            # Same race as ship_current_work's CAS win (finding 1/7): the CAS
            # write is a plain, uncommitted filesystem change. Left uncommitted,
            # a concurrent ship's Gate-1 rollback (`reset --hard HEAD~1`) wipes
            # it and reverts the epic to its prior status while this run's
            # multi-minute check is still in flight.
            commit_all(rel_wt, f"chore(epic): {epic_id} verification claimed at {sha}")
    if not won:
        raise EpicNotVerifiableError(
            f"{epic_id} is already verifying or verified — pass --force to "
            f"reclaim it (e.g. a stale run from a crash)"
        )
    features = [i["promoted_to"] for i in epic_children(idea_cat, epic_id) if i.get("promoted_to")]
    epic_dir = epic_folder_path(repo, epic_id)
    rc, entry = run_and_record(repo, rel_wt, epic_cat, epic_id, features, sha,
                                epic_dir, release_version)
    return {"epic_id": epic_id, "sha": sha, "rc": rc, "entry": entry}


# feature.status -> (slice state, action). `promoted` and any other status refuse.
_SLICE_STATE = {
    "open": ("refined", "claim"),
    "claimed": ("claimed", "resume"),
    "shipped": ("shipped", "skip"),
}


def _slice_spec_is_skeleton(rel_wt: Path, idea: dict) -> bool:
    """True when the idea's spec.md is still an untouched generated skeleton.

    Two generators exist: `epic fanout` (what every epic slice starts as) and
    `psrw idea` (IDEA_SPEC_TEMPLATE). Either one, unedited, means nobody wrote
    the slice's spec. Text that cannot be decoded is content we cannot judge, so
    it is NOT a skeleton (the conservative reading refine's carry-forward uses).
    """
    spec = (rel_wt / ".claude" / "idea_backlog"
            / f"{idea['id']}-{slugify(idea['title'])}" / "spec.md")
    try:
        text = spec.read_text()
    except FileNotFoundError:
        raise EpicPlanError(f"{idea['id']}: spec.md not found at {spec}")
    except (OSError, UnicodeDecodeError):
        return False
    skeletons = (
        _fanout_idea_spec(idea["title"], idea["id"]),
        IDEA_SPEC_TEMPLATE.format(title=idea["title"], id=idea["id"]),
    )
    return any(_is_untouched_skeleton(text, skeleton) for skeleton in skeletons)


def _plan_slice(rel_wt: Path, refined_cat: Path, version: str, idea: dict) -> dict:
    feature = None
    if idea.get("promoted_to"):
        feature = find_entry(refined_cat, idea["promoted_to"])
        if feature is None:
            raise EpicPlanError(
                f"{idea['id']} points at {idea['promoted_to']}, which is missing "
                f"from the refined catalog")
    if feature is None:
        state, action = "idea", "refine"
    else:
        status = feature.get("status")
        if status == "promoted":
            raise EpicPlanError(f"{idea['id']} ({feature['id']}) is already promoted")
        if status == "shipped" and feature.get("release_version") != version:
            raise EpicPlanError(
                f"{feature['id']} shipped on {feature.get('release_version')}, "
                f"not on {version}")
        if status not in _SLICE_STATE:
            raise EpicPlanError(f"{feature['id']} has unexpected status {status!r}")
        state, action = _SLICE_STATE[status]
    if state != "shipped" and _slice_spec_is_skeleton(rel_wt, idea):
        raise EpicPlanError(
            f"{idea['id']}: spec.md is still the untouched skeleton — write and "
            f"approve the slice spec before it goes in --slices")
    return {
        "idea": idea["id"],
        "feature": feature["id"] if feature else None,
        "state": state,
        "claimed_by": feature.get("claimed_by") if feature else None,
        "action": action,
    }


def _resolve_precheck(rel_wt: Path, allow_missing: bool) -> str | None:
    """Gate 1 script path, resolved from the _release tree (the one ship's
    post-merge Gate 1 uses). A missing script is a warning-and-skip inside ship,
    which an unattended chain must not inherit, so it refuses unless allowed. An
    unusable hooks.precheck value always refuses, like ship."""
    try:
        hook = resolve_hook(rel_wt, "precheck")
    except HookPathError as e:
        raise EpicPlanError(f"hooks.precheck is unusable: {e}")
    if hook.exists():
        return str(hook)
    if allow_missing:
        return None
    raise EpicPlanError(
        f"Gate 1 script not found at {hook}: ship would skip it with only a "
        f"warning, which an unattended chain must not. Add it, or pass "
        f"--allow-no-precheck to accept that.")


def epic_plan(repo: Path, epic_id: str, slices: str,
              allow_no_precheck: bool = False) -> dict:
    """Read-only preflight for `epic run`. Raises EpicPlanError (or the usual
    NoReleaseInProgressError / CatalogEntryNotFoundError) instead of returning a
    plan the chain must not follow. Writes nothing."""
    allowlist = list(dict.fromkeys(s.strip() for s in slices.split(",") if s.strip()))
    if not allowlist:
        raise EpicPlanError(
            "--slices is required: name the approved slice ideas, e.g. "
            "--slices I-001,I-002 (approval is never inferred)")
    state = read_release_state(repo)
    if state is None:
        raise NoReleaseInProgressError("No release in progress")
    version = state["version"]
    rel_wt = get_release_worktree(repo)
    epic_cat = get_backlog_catalog_path(repo, "epic")
    epic = find_entry(epic_cat, epic_id)
    if epic is None:
        raise CatalogEntryNotFoundError(epic_id, epic_cat)

    status = epic.get("status")
    notes: list[str] = []
    if status in ("verified", "promoted"):
        raise EpicPlanError(f"{epic_id} is already {status}; there is nothing left to run")
    if status == "verifying":
        raise EpicPlanError(
            f"{epic_id} is 'verifying': another outcome check is in flight, or a "
            f"crashed one left its claim. Wait, or clear it with: "
            f"psrw epic verify --force {epic_id}")
    if status == "failed_verification":
        notes.append(
            f"{epic_id} is failed_verification: the ship that completes the epic "
            f"re-runs the outcome check; to re-check now run: psrw epic verify {epic_id}")

    children = epic_children(get_backlog_catalog_path(repo, "idea"), epic_id)
    stray = [i for i in allowlist if i not in {c["id"] for c in children}]
    if stray:
        raise EpicPlanError(f"not slices of {epic_id}: {', '.join(stray)}")
    refined_cat = get_backlog_catalog_path(repo, "refined")
    plan = [_plan_slice(rel_wt, refined_cat, version, idea)
            for idea in children if idea["id"] in allowlist]
    return {
        "epic": epic_id,
        "epic_status": status,
        "release": version,
        "allowlist": allowlist,
        "precheck": _resolve_precheck(rel_wt, allow_no_precheck),
        "notes": notes,
        "slices": plan,
    }


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(prog="psrw epic", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    p_open = sub.add_parser("open", help="mint an epic and its spec skeletons")
    p_open.add_argument("title")

    p_fan = sub.add_parser("fanout", help="mint one idea per slice, tagged to the epic")
    p_fan.add_argument("epic_id", metavar="E-NNN")
    p_fan.add_argument("titles", nargs="+", metavar="SLICE")

    p_ver = sub.add_parser("verify", help="re-run the epic gate")
    p_ver.add_argument("epic_id", metavar="E-NNN")
    p_ver.add_argument("--force", action="store_true",
                       help="clear a stale 'verifying' left by a crashed run")

    p_plan = sub.add_parser(
        "plan", help="preflight for an epic run: print the ordered slice plan (read-only)")
    p_plan.add_argument("epic_id", metavar="E-NNN")
    p_plan.add_argument("--slices", default="", metavar="I-NNN,I-NNN",
                        help="comma-separated approved slice ideas (required)")
    p_plan.add_argument("--allow-no-precheck", action="store_true",
                        help="accept a repo with no Gate 1 script (ship then skips Gate 1)")

    args = p.parse_args()
    repo = find_repo_root(Path.cwd())
    try:
        if args.cmd == "open":
            result = epic_open(repo, args.title)
        elif args.cmd == "fanout":
            result = epic_fanout(repo, args.epic_id, args.titles)
        elif args.cmd == "plan":
            result = epic_plan(repo, args.epic_id, args.slices,
                               allow_no_precheck=args.allow_no_precheck)
        else:
            result = epic_verify(repo, args.epic_id, force=args.force)
    except (NoReleaseInProgressError, CatalogEntryNotFoundError, GitError,
            EpicNotVerifiableError, EpicPlanError, SlugError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
