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
)
from lib.catalog import CatalogEntryNotFoundError, add_idea_entry, find_entry
from lib.epic import add_epic_entry
from lib.git_ops import GitError, commit_all
from lib.repo import find_repo_root
from lib.slug import slugify
from lib.state import file_lock, mutate_state

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
    wt = get_release_worktree(repo)
    epic_cat = get_backlog_catalog_path(repo, "epic")
    with file_lock(wt):
        epic = add_epic_entry(epic_cat, title)
        folder = wt / ".claude" / "epic_backlog" / f"{epic['id']}-{slugify(title)}"
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
                (folder / "spec.md").write_text(
                    f"---\ntitle: {_yaml_quote(title)}\nid: {idea['id']}\n"
                    f"status: idea\n---\n\n# {title}\n"
                )
                (folder / "research.md").write_text(f"# Research — {title}\n")
            commit_all(wt, f"chore(epic): fan out {epic_id} into {len(minted)} ideas")
        except BaseException:
            _rollback_ideas(idea_cat, minted, folders)
            raise
    return {"epic_id": epic_id, "ideas": minted}


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

    args = p.parse_args()
    repo = find_repo_root(Path.cwd())
    try:
        if args.cmd == "open":
            result = epic_open(repo, args.title)
        elif args.cmd == "fanout":
            result = epic_fanout(repo, args.epic_id, args.titles)
        else:
            result = epic_verify(repo, args.epic_id, force=args.force)
    except (NoReleaseInProgressError, CatalogEntryNotFoundError, GitError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
