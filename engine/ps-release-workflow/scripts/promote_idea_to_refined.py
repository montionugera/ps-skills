"""ps-release-workflow:refine — promote an idea (I-NNN) to refined (F-NNN) (D11/SR-1).

Reads/writes/commits both the idea and refined catalogs + the refined folder on the
long-lived `_release` worktree (release/<v>), never the main checkout. Refuses if no
release is in progress (D12).
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
from lib.catalog import add_refined_entry, find_entry, mark_promoted
from lib.git_ops import commit_all
from lib.repo import find_repo_root, is_ps_release_workflow_repo
from lib.slug import slugify


class IdeaNotFoundError(Exception): pass
class AlreadyPromotedError(Exception): pass


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

RESEARCH_TEMPLATE = """\
# {title} — research notes
"""


def promote_idea_to_refined(repo: Path, idea_id: str) -> dict:
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

    ref_cat = get_backlog_catalog_path(repo, "refined")
    feat = add_refined_entry(ref_cat, idea_id=idea_id, title=idea["title"])

    folder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-{slugify(idea['title'])}"
    folder.mkdir(parents=True)
    (folder / "spec.md").write_text(
        SPEC_TEMPLATE.format(title=idea["title"], id=feat["id"], from_idea=idea_id)
    )
    (folder / "plan.md").write_text(PLAN_TEMPLATE.format(title=idea["title"]))
    (folder / "research.md").write_text(RESEARCH_TEMPLATE.format(title=idea["title"]))

    mark_promoted(idea_cat, idea_id=idea_id, refined_id=feat["id"])

    commit_all(wt, f"chore(backlog): promote {idea_id} → {feat['id']} {idea['title']}")
    return feat


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: promote_idea_to_refined.py I-NNN", file=sys.stderr)
        return 1
    idea_id = sys.argv[1]
    repo = find_repo_root(Path.cwd())
    try:
        feat = promote_idea_to_refined(repo, idea_id)
    except (IdeaNotFoundError, AlreadyPromotedError, RuntimeError, NoReleaseInProgressError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "id": feat["id"], "from_idea": idea_id}))
    print(f"\n✅ Promoted {idea_id} → {feat['id']}: {feat['title']}")
    print(
        "   (Refine assumes the idea already had an approved spec under "
        "docs/superpowers/specs/.)"
    )
    print(f"   Next: write the plan → /superpowers:writing-plans, then claim {feat['id']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
