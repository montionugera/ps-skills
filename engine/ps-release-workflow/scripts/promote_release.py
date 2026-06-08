"""ps-release-workflow:promote — Gate 2 + squash-merge → main + auto-cleanup."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib.catalog import list_entries, mark_promoted_to_main
from lib.git_ops import (
    GitError, _run as git_run, commit_all,
    delete_branch_local, delete_branch_remote, push, remove_worktree,
)
from lib.repo import find_repo_root, is_ps_release_workflow_repo
from lib.state import mutate_state


class NoReleaseInProgressError(Exception): pass
class Gate2FailedError(Exception): pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def promote_release(
    repo: Path,
    *,
    run_gate2: bool = True,
    run_deploy: bool = True,
    push: bool = True,
    keep: bool = False,
) -> dict:
    repo = Path(repo).resolve()
    if not is_ps_release_workflow_repo(repo):
        raise RuntimeError(f"{repo} not opted into ps-release-workflow")
    rj_path = repo / ".release.json"
    rj = json.loads(rj_path.read_text())
    if not rj.get("in_progress"):
        raise NoReleaseInProgressError("No release in progress")
    version = rj["version"]
    release_branch = f"release/{version}"
    rel_wt = repo / ".claude" / "worktrees" / "_release"

    if run_deploy:
        deploy = repo / "scripts" / "deploy-local.sh"
        if deploy.exists():
            cp = subprocess.run([str(deploy)], cwd=repo)
            if cp.returncode != 0:
                raise Gate2FailedError("deploy-local.sh failed")

    if run_gate2:
        integ = repo / "scripts" / "integration.sh"
        if integ.exists():
            cp = subprocess.run([str(integ)], cwd=repo)
            if cp.returncode != 0:
                raise Gate2FailedError(f"Gate 2 (scripts/integration.sh) failed for release/{version}")

    # Squash-merge release/<v> into main (in main checkout).
    try:
        git_run(repo, "merge", "--squash", release_branch)
        git_run(repo, "commit", "-m", f"release {version}")
    except GitError as e:
        raise Gate2FailedError(f"squash-merge {release_branch} → main failed: {e}")

    # Bypass guard for subsequent toolkit-driven cleanup.
    os.environ["PS_RELEASE_WORKFLOW_SCRIPTED"] = "1"

    if push:
        from lib.git_ops import push as push_fn
        push_fn(repo, "main")

    if not keep:
        cleanup(repo, version=version)

    return {"ok": True, "version": version}


def cleanup(repo: Path, version: str) -> dict:
    """Idempotent cleanup after promote.

    Each step tolerates already-done state so re-running is safe.

    ORDERING NOTE: a worktree that has a branch checked out must be removed
    BEFORE deleting that branch — git refuses to delete a branch that is
    checked out in a linked worktree. So per-feature and for the release we
    remove the worktree first, then delete the (now-detached) branch.
    """
    repo = Path(repo).resolve()
    refined_cat = repo / ".claude" / "refined_backlog" / "_catalog.json"
    claims_file = repo / ".claude" / "state" / "claims.json"
    archive_root = repo / ".claude" / "refined_backlog" / "_archive" / version
    archive_root.mkdir(parents=True, exist_ok=True)

    # For each F-NNN shipped in this version: archive + remove worktree + delete branches.
    for entry in list_entries(refined_cat):
        if entry.get("release_version") != version:
            continue
        if entry.get("status") not in ("shipped", "promoted"):
            continue

        feature_id = entry["id"]
        # 1. Mark promoted.
        if entry["status"] != "promoted":
            mark_promoted_to_main(refined_cat, feature_id)

        # 2. Archive folder.
        candidates = list((repo / ".claude" / "refined_backlog").glob(f"{feature_id}-*"))
        for src in candidates:
            if src.is_dir() and "_archive" not in src.parts:
                dst = archive_root / src.name
                if not dst.exists():
                    shutil.move(str(src), str(dst))
                    _shipped = {
                        "shipped_at": entry.get("shipped_at"),
                        "promoted_at": _now(),
                        "release_version": version,
                        "original_branch": f"feat/{feature_id}",
                    }
                    (dst / "_shipped.json").write_text(json.dumps(_shipped, indent=2))

        # 3. Remove feature worktree(s) FIRST (must precede local branch deletion).
        for wt_path in (repo / ".claude" / "worktrees").glob(f"{feature_id}-*"):
            try:
                remove_worktree(repo, wt_path, force=True)
            except GitError:
                pass

        # 4. Delete feat branches (worktree is gone, so local delete can succeed).
        feat_branch = f"feat/{feature_id}"
        delete_branch_remote(repo, feat_branch)
        try:
            delete_branch_local(repo, feat_branch)
        except GitError:
            pass

        # 5. Clear claim entry.
        def drop_claim(claims: dict) -> dict:
            claims.pop(feature_id, None)
            return claims
        try:
            mutate_state(claims_file, drop_claim, default={})
        except FileNotFoundError:
            pass

    # Remove _release worktree FIRST (must precede release branch deletion).
    rel_wt = repo / ".claude" / "worktrees" / "_release"
    if rel_wt.exists():
        try:
            remove_worktree(repo, rel_wt, force=True)
        except GitError:
            pass

    # Delete release branch (worktree is gone, so local delete can succeed).
    release_branch = f"release/{version}"
    delete_branch_remote(repo, release_branch)
    try:
        delete_branch_local(repo, release_branch)
    except GitError:
        pass

    # Update .release.json + commit + push.
    rj_path = repo / ".release.json"
    rj = json.loads(rj_path.read_text())
    if rj.get("in_progress"):
        rj["in_progress"] = False
        rj["last_promoted_at"] = _now()
        rj["last_promoted_version"] = version
        rj_path.write_text(json.dumps(rj, indent=2) + "\n")
        commit_all(repo, f"chore(release): finalize {version}")
        # If origin exists, push.
        try:
            git_run(repo, "push", "origin", "main")
        except GitError:
            pass

    return {"ok": True, "version": version}


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--gate2", action="store_true", dest="gate2")
    p.add_argument("--deploy", action="store_true")
    p.add_argument("--push", action="store_true", default=True)
    p.add_argument("--no-push", action="store_false", dest="push")
    p.add_argument("--keep", action="store_true", help="skip auto-cleanup")
    p.add_argument("--cleanup-only", help="run cleanup for a previously-promoted version", default=None)
    args = p.parse_args()
    repo = find_repo_root(Path.cwd())
    try:
        if args.cleanup_only:
            result = cleanup(repo, args.cleanup_only)
        else:
            result = promote_release(repo, run_gate2=args.gate2, run_deploy=args.deploy, push=args.push, keep=args.keep)
    except (NoReleaseInProgressError, Gate2FailedError, RuntimeError) as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    print(f"\n✅ Promoted v{result['version']} to main.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
