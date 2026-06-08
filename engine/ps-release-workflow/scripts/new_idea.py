"""ps-release-workflow:idea — capture a new idea into the _release worktree backlog (D11/SR-1).

While a release is in progress, backlog metadata lives on release/<v> via the
long-lived `_release` worktree. This script reads/writes/commits the idea catalog
and folder THERE, not in the main checkout. It refuses if no release is in progress
(D12).
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import sys
from pathlib import Path

from lib.backlog_paths import (
    NoReleaseInProgressError,
    get_backlog_catalog_path,
    get_release_worktree,
)
from lib.catalog import add_idea_entry
from lib.git_ops import commit_all
from lib.repo import find_repo_root, is_ps_release_workflow_repo
from lib.slug import slugify


SPEC_TEMPLATE = """\
---
title: "{title}"
id: {id}
status: idea
---

# {title}

## Problem

(what hurts; concrete examples)

## Why now

(opportunity; deadline; constraint)

## Sketch

(rough shape; not a design yet)
"""

PLAN_TEMPLATE = """\
# {title} — plan placeholder

Empty until promoted to F-NNN and filled via `/superpowers:writing-plans`.
"""

RESEARCH_TEMPLATE = """\
# {title} — research notes

(prior art, related issues, open questions)
"""


def new_idea(repo: Path, title: str) -> dict:
    repo = Path(repo)
    if not is_ps_release_workflow_repo(repo):
        raise RuntimeError(
            f"{repo} has not adopted ps-release-workflow (no .release.json). "
            f"Run /ps-release-workflow:init."
        )

    # Resolve the _release worktree (raises NoReleaseInProgressError if no release).
    wt = get_release_worktree(repo)

    cat = get_backlog_catalog_path(repo, "idea")
    entry = add_idea_entry(cat, title=title)

    folder = wt / ".claude" / "idea_backlog" / f"{entry['id']}-{slugify(title)}"
    folder.mkdir(parents=True)
    (folder / "spec.md").write_text(SPEC_TEMPLATE.format(title=title, id=entry["id"]))
    (folder / "plan.md").write_text(PLAN_TEMPLATE.format(title=title))
    (folder / "research.md").write_text(RESEARCH_TEMPLATE.format(title=title))

    commit_all(wt, f"chore(backlog): add {entry['id']} {title}")
    return entry


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: new_idea.py 'title'", file=sys.stderr)
        return 1
    title = sys.argv[1]
    repo = find_repo_root(Path.cwd())
    try:
        entry = new_idea(repo, title)
    except (RuntimeError, NoReleaseInProgressError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    wt = get_release_worktree(repo)
    folder = wt / ".claude" / "idea_backlog" / f"{entry['id']}-{slugify(title)}"
    print(json.dumps({"ok": True, "id": entry["id"], "folder": str(folder)}))
    print(f"\n✅ Captured idea {entry['id']}: {title}")
    print(f"   Refine when ready: /ps-release-workflow:refine {entry['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
