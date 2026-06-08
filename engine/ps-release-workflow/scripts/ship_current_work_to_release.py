"""ps-release-workflow:ship — Gate 1 + merge feat/F-NNN into release/<v>.

D11/SR-1: the populated catalog lives ONLY in the _release worktree; MAIN's
catalog is []. So the catalog mutation/commit must target the _release worktree
in place — never the main checkout, and never copy main's catalog over it.
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import subprocess
import sys
from pathlib import Path

from lib.backlog_paths import (
    NoReleaseInProgressError,
    get_backlog_catalog_path,
    get_release_worktree,
)
from lib.catalog import mark_shipped
from lib.git_ops import GitError, _run as git_run, commit_all, is_dirty
from lib.repo import is_ps_release_workflow_repo
from lib.state import file_lock


class DirtyTreeError(Exception): pass
class GateFailedError(Exception): pass
class NotInFeatureWorktreeError(Exception): pass


def _find_marker(worktree: Path) -> dict:
    """Read .git/worktrees/<id>/working-feature.json for this worktree."""
    # Resolve the worktree's .git pointer.
    git_pointer = worktree / ".git"
    if git_pointer.is_file():
        # `gitdir: /path/to/.git/worktrees/<id>` format
        content = git_pointer.read_text().strip()
        gitdir = Path(content.split("gitdir:", 1)[1].strip())
        marker = gitdir / "working-feature.json"
        if marker.exists():
            return json.loads(marker.read_text())
    raise NotInFeatureWorktreeError(f"{worktree} has no working-feature.json marker")


def ship_current_work(worktree: Path) -> dict:
    worktree = Path(worktree).resolve()
    marker = _find_marker(worktree)
    feature_id = marker["feature"]

    if is_dirty(worktree):
        raise DirtyTreeError(f"{worktree} has uncommitted changes; commit or stash first")

    # Find repo root from the worktree's git common dir.
    common_dir = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], cwd=worktree, capture_output=True, text=True, check=True
    ).stdout.strip()
    repo = Path(common_dir).parent.resolve()
    if not is_ps_release_workflow_repo(repo):
        raise RuntimeError(f"{repo} not opted into ps-release-workflow")

    rj = json.loads((repo / ".release.json").read_text())
    if not rj.get("in_progress"):
        raise NoReleaseInProgressError("No release in progress")
    release_version = rj["version"]
    release_branch = f"release/{release_version}"

    # The _release worktree (release/<v>) — also enforces the in-progress guard.
    rel_wt = get_release_worktree(repo)

    # Run Gate 1.
    precheck = repo / "scripts" / "precheck.sh"
    if precheck.exists():
        cp = subprocess.run([str(precheck)], cwd=worktree)
        if cp.returncode != 0:
            raise GateFailedError(f"Gate 1 (scripts/precheck.sh) failed in {worktree}")
    # If precheck missing, allow (some repos may not have it yet).

    # Merge feat/<feature_id> into release/<v> in the _release worktree.
    # Serialize the whole merge → re-verify → rollback → mark critical section on
    # the shared _release worktree so two concurrent ships can't corrupt the tree
    # or roll back the wrong commit.
    feat_branch = f"feat/{feature_id}"
    with file_lock(rel_wt):
        try:
            git_run(rel_wt, "merge", "--no-ff", "-m", f"merge {feat_branch} into {release_branch}", feat_branch)
        except GitError as e:
            # Abort any partial/conflicted merge before surfacing the failure.
            git_run(rel_wt, "merge", "--abort", check=False)
            raise GateFailedError(f"merge of {feat_branch} into {release_branch} failed: {e}")

        # Re-verify Gate 1 in release worktree.
        if precheck.exists():
            cp = subprocess.run([str(precheck)], cwd=rel_wt)
            if cp.returncode != 0:
                # Roll back the merge: hard reset to release HEAD~1
                git_run(rel_wt, "reset", "--hard", "HEAD~1")
                raise GateFailedError(f"Gate 1 failed on combined release after merge — rolled back")

        # Mark catalog status=shipped IN PLACE in the _release worktree (D11/SR-1).
        # The populated catalog lives only here; main's is []. No copy step.
        refined_cat = get_backlog_catalog_path(repo, "refined")
        mark_shipped(refined_cat, feature_id, release_version)
        commit_all(rel_wt, f"chore(catalog): {feature_id} status=shipped on {release_version}")

    return {"ok": True, "feature": feature_id, "release": release_version}


def main() -> int:
    cwd = Path.cwd()
    try:
        result = ship_current_work(cwd)
    except (DirtyTreeError, GateFailedError, NotInFeatureWorktreeError, NoReleaseInProgressError, RuntimeError) as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    print(f"\n✅ Shipped {result['feature']} to release/{result['release']}")
    print(f"   Continue with next feature, or promote: /ps-release-workflow:promote")
    return 0


if __name__ == "__main__":
    sys.exit(main())
