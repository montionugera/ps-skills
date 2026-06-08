"""ps-release-workflow:claim — atomically claim F-NNN + cut a feature worktree (D11/SR-1/D12).

Atomicity: the host-local claim ledger (.claude/state/claims.json) lives in the MAIN
checkout and is gitignored — the flock-guarded try_claim runs there. The refined-backlog
catalog read (for --next / lookup) AND the status=claimed mutation + commit all happen on
the long-lived `_release` worktree (release/<v>), never the main checkout (SR-1). Refuses
before any feature lookup if no release is in progress (D12).
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib.backlog_paths import (
    NoReleaseInProgressError,
    get_backlog_catalog_path,
    get_release_worktree,
)
from lib.catalog import find_entry, list_entries
from lib.git_ops import add_worktree_new_branch, commit_all
from lib.owner import resolve_owner_id
from lib.repo import find_repo_root, is_ps_release_workflow_repo
from lib.slug import slugify
from lib.state import mutate_state


class AlreadyClaimedError(Exception): pass
class NoFreeFeatureError(Exception): pass
class FeatureNotFoundError(Exception): pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def claim_feature(
    repo: Path, feature_id: Optional[str], *, owner: str, select_next: bool = False
) -> dict:
    repo = Path(repo)
    if not is_ps_release_workflow_repo(repo):
        raise RuntimeError(f"{repo} not opted into ps-release-workflow")

    # Release-in-progress check FIRST — before any feature lookup (D12).
    # Raises NoReleaseInProgressError if .release.json not in_progress or _release missing.
    wt = get_release_worktree(repo)

    # Catalog reads + the status mutation/commit all target the _release worktree (SR-1).
    refined_cat = get_backlog_catalog_path(repo, "refined")
    # The claim ledger stays in the MAIN checkout (gitignored, host-local).
    claims_file = repo / ".claude" / "state" / "claims.json"

    if select_next:
        feature_id = None
        for e in list_entries(refined_cat):
            if e.get("status") == "open":
                feature_id = e["id"]
                break
        if not feature_id:
            raise NoFreeFeatureError("no unclaimed open features in refined_backlog")

    if feature_id is None:
        raise ValueError("must pass feature_id or select_next=True")

    feat = find_entry(refined_cat, feature_id)
    if feat is None:
        raise FeatureNotFoundError(feature_id)

    slug = slugify(feat["title"])
    worktree_path = repo / ".claude" / "worktrees" / f"{feature_id}-{slug}"
    branch_name = f"feat/{feature_id}"

    # Atomic claim attempt — flock around claims.json (in the main checkout).
    def try_claim(claims: dict) -> dict:
        if feature_id in claims:
            raise AlreadyClaimedError(
                f"{feature_id} held by owner={claims[feature_id]['owner']}"
            )
        claims[feature_id] = {
            "owner": owner,
            "worktree": str(worktree_path),
            "claimed_at": _now(),
        }
        return claims

    mutate_state(claims_file, try_claim, default={})

    # Create the feature worktree on a new branch off main.
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    add_worktree_new_branch(repo, worktree_path, branch_name, "main")

    # Write working-feature.json marker into .git/worktrees/<id>-<slug>/.
    wt_meta = repo / ".git" / "worktrees" / f"{feature_id}-{slug}"
    marker = wt_meta / "working-feature.json"
    marker.write_text(
        json.dumps(
            {"feature": feature_id, "owner": owner, "claimed_at": _now()}, indent=2
        )
    )

    # SR-1: mark catalog status=claimed in the _release worktree and commit THERE.
    def mark_claimed(entries: list) -> list:
        for e in entries:
            if e["id"] == feature_id:
                e["status"] = "claimed"
                e["claimed_by"] = owner
                e["claimed_at"] = _now()
        return entries

    mutate_state(refined_cat, mark_claimed, default=[])
    commit_all(wt, f"chore(catalog): claim {feature_id}")

    return {
        "feature": feature_id,
        "worktree": str(worktree_path),
        "branch": branch_name,
        "owner": owner,
    }


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("feature_id", nargs="?", help="F-NNN; required unless --next")
    p.add_argument("--next", action="store_true", dest="select_next")
    p.add_argument("--owner", default=None)
    args = p.parse_args()

    owner = args.owner or resolve_owner_id()
    repo = find_repo_root(Path.cwd())
    try:
        result = claim_feature(
            repo, args.feature_id, owner=owner, select_next=args.select_next
        )
    except (
        AlreadyClaimedError,
        NoFreeFeatureError,
        NoReleaseInProgressError,
        FeatureNotFoundError,
        ValueError,
        RuntimeError,
    ) as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(json.dumps({"ok": True, **result}))
    print(f"\n✅ Claimed {result['feature']} (worktree: {result['worktree']})")
    print("   Implement: /superpowers:subagent-driven-development")
    print(f"   (reads {result['worktree']}/plan.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
