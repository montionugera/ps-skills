"""Run the epic_check hook against an immutable snapshot of the release tree.

The shared _release worktree is mutated by every concurrent ship (merge --no-ff,
reset --hard HEAD~1, commit_all — ship_current_work_to_release.py:112-145).
Running a multi-minute outcome suite there yields false failures, or a pass
against a tree that is then reset. So the hook runs in a throwaway worktree
detached at a captured sha, which nothing can move underneath it.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from lib.epic import mark_epic_failed, mark_epic_verified
from lib.git_ops import _run as git_run          # NOTE: the public name is `_run`;
from lib.git_ops import commit_all               # every caller aliases it this way
from lib.hooks import HookPathError, resolve_hook
from lib.state import file_lock


def run_epic_check(
    repo: Path, rel_wt: Path, epic_id: str, features: list[str], sha: str,
    epic_dir: Path | None = None, release_version: str = "",
) -> int | None:
    """Returns the hook's exit code, or None when the script is absent or unusable.

    Absent -> warn loudly and skip, mirroring Gate 1
    (ship_current_work_to_release.py:52-59). Never silently green.
    """
    with tempfile.TemporaryDirectory(prefix="psrw-epic-") as tmp:
        snapshot = Path(tmp) / "snapshot"
        git_run(repo, "worktree", "add", "--detach", str(snapshot), sha)
        try:
            # resolve_hook returns an ABSOLUTE path inside the tree it is given
            # (lib/hooks.py:74-86) and does NOT check existence. Resolving against
            # `snapshot` is load-bearing: resolving against rel_wt and then doing
            # `snapshot / hook` is a no-op, because pathlib drops the left side
            # when the right is absolute — the hook would run in the SHARED tree
            # and the immutable-snapshot guarantee would be silently void.
            try:
                hook = resolve_hook(snapshot, "epic_check")
            except HookPathError as e:
                print(f"WARNING: hooks.epic_check unusable ({e}) — {epic_id} "
                      f"outcome check SKIPPED. Completeness is still enforced at "
                      f"promote.", file=sys.stderr)
                return None
            if not hook.exists():
                print(f"WARNING: hooks.epic_check not found at {hook} — {epic_id} "
                      f"outcome check SKIPPED. Completeness is still enforced at "
                      f"promote.", file=sys.stderr)
                return None

            env = {
                "PSRW_EPIC_ID": epic_id,
                "PSRW_EPIC_FEATURES": ",".join(sorted(features)),
                "PSRW_EPIC_DIR": str(epic_dir) if epic_dir else "",
                "PSRW_EPIC_SHA": sha,
                "PSRW_RELEASE_VERSION": release_version,
            }
            proc = subprocess.run([str(hook)], cwd=snapshot, env={**os.environ, **env})
            return proc.returncode
        finally:
            git_run(repo, "worktree", "remove", "--force", str(snapshot))


def run_and_record(
    repo: Path, rel_wt: Path, epic_cat: Path, epic_id: str, features: list[str],
    sha: str, epic_dir: Path | None, release_version: str,
) -> tuple[int | None, dict]:
    """Run the check OUTSIDE any lock, then record the outcome under a short one.

    The caller must already have WON try_begin_verification for `sha` — this is
    the losing-CAS-free second half, shared by the ship-time gate and
    `psrw epic verify` so exactly one place decides verified vs failed.

    The check itself can take minutes, so holding the _release lock across it
    would stall every concurrent ship; only the catalog write is serialized.

    Nothing is rolled back on failure. The epic catalog is a tracked file in this
    tree, so a `reset --hard` would erase the very write recording the failure. A
    failing epic stays on release/<v>; that is safe because release/<v> is not
    production, and G-E3 guards the way to main.
    """
    rc = run_epic_check(repo, rel_wt, epic_id, features, sha,
                        epic_dir=epic_dir, release_version=release_version)
    with file_lock(rel_wt):
        if rc is None or rc == 0:
            entry = mark_epic_verified(epic_cat, epic_id, sha, release_version)
        else:
            entry = mark_epic_failed(epic_cat, epic_id, release_version)
        commit_all(rel_wt, f"chore(epic): {epic_id} verification result")
    return rc, entry
