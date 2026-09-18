"""Run the epic_check hook against an immutable snapshot of the release tree.

The shared _release worktree is mutated by every concurrent ship (merge --no-ff,
reset --hard HEAD~1, commit_all — ship_current_work_to_release.py:112-145).
Running a multi-minute outcome suite there yields false failures, or a pass
against a tree that is then reset. So the hook runs in a throwaway worktree
detached at a captured sha, which nothing can move underneath it.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from lib.epic import mark_epic_failed, mark_epic_verified
from lib.git_ops import GitError
from lib.git_ops import _run as git_run          # NOTE: the public name is `_run`;
from lib.git_ops import commit_all, is_dirty     # every caller aliases it this way
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
        # A scratch dir INSIDE this run's own temp dir, never inside rel_wt —
        # the hook can run for minutes, and every concurrent ship mutates
        # rel_wt underneath it (git add -A, reset --hard HEAD~1) the whole
        # time. Writing PSRW_EPIC_DIR straight into the shared, mutable
        # epic_backlog folder let a slow hook's output get committed into an
        # unrelated feature's commit, or wiped by a rollback, mid-write. The
        # final result is copied onto the real epic_dir in the `finally`
        # below, once the hook has stopped writing.
        scratch = Path(tmp) / "epic_output"
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
                "PSRW_EPIC_FEATURES": ",".join(sorted(f for f in features if f)),
                "PSRW_EPIC_SHA": sha,
                "PSRW_RELEASE_VERSION": release_version,
            }
            # Omit the variable entirely when there is no epic folder (e.g. it
            # was renamed/removed off release/<v>) — setting it to "" resolves
            # to the filesystem root for a hook following the documented
            # `$PSRW_EPIC_DIR/marker` pattern, failing for a reason unrelated
            # to the actual outcome being checked.
            if epic_dir is not None:
                scratch.mkdir(parents=True, exist_ok=True)
                env["PSRW_EPIC_DIR"] = str(scratch)
            proc = subprocess.run([str(hook)], cwd=snapshot, env={**os.environ, **env})
            return proc.returncode
        finally:
            if epic_dir is not None and scratch.exists():
                epic_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(scratch, epic_dir, dirs_exist_ok=True)
            try:
                git_run(repo, "worktree", "remove", "--force", str(snapshot))
            except GitError as e:
                # A failed cleanup must not mask the hook's real pass/fail
                # result by raising out of a `finally` — that replaces the
                # `try` block's return with this exception, turning a
                # legitimately passing (or failing) check into an opaque
                # GitError instead of a recorded epic outcome.
                print(f"WARNING: failed to remove epic-check snapshot worktree "
                      f"{snapshot} ({e}); run 'git worktree prune' in {repo} "
                      f"to clean up.", file=sys.stderr)


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

    Any exception raised while running the check (a hook committed without
    its exec bit, a `git worktree add` failure, ...) is caught and recorded
    as failed_verification instead of propagating — otherwise the epic is
    left pinned in 'verifying' forever, with no timeout, recoverable only by
    a human running `psrw epic verify --force`.
    """
    try:
        rc = run_epic_check(repo, rel_wt, epic_id, features, sha,
                            epic_dir=epic_dir, release_version=release_version)
    except Exception as e:
        print(f"WARNING: {epic_id} outcome check crashed ({type(e).__name__}: {e}) "
              f"— recorded as failed_verification. Investigate hooks.epic_check, "
              f"then re-run with `psrw epic verify --force {epic_id}` once fixed.",
              file=sys.stderr)
        with file_lock(rel_wt):
            entry = mark_epic_failed(epic_cat, epic_id, release_version, sha=sha)
            if is_dirty(rel_wt):
                commit_all(rel_wt, f"chore(epic): {epic_id} verification result (check crashed)")
        return -1, entry
    with file_lock(rel_wt):
        if rc is None or rc == 0:
            entry = mark_epic_verified(epic_cat, epic_id, sha, release_version)
        else:
            entry = mark_epic_failed(epic_cat, epic_id, release_version, sha=sha)
        # _transition no-ops when this run's verifying_sha no longer matches
        # (a stale run losing to a fresher force-reclaim, finding 2/8) or when
        # a concurrent Gate-1 rollback (`reset --hard`) already wiped the
        # uncommitted CAS write and reverted the entry to "open" — either way
        # the tree can be clean here, and commit_all's `git commit` raises
        # GitError on nothing-to-commit (finding 3).
        if is_dirty(rel_wt):
            commit_all(rel_wt, f"chore(epic): {epic_id} verification result")
    return rc, entry
