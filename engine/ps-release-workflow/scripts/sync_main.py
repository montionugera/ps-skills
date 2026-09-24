"""ps-release-workflow:sync-main — absorb main (hotfixes) into release/<v> now.

ship and promote already sync main before they merge, deploy or gate; this
verb is for when the release should carry a hotfix before the next of those
(a local deploy, features that sync from release/<v>). It merges main via
lib.main_sync in the _release worktree and verifies the result with Gate 1,
rolling the sync back if Gate 1 fails. `psrw hotfix --sync-release` is an
alias that calls main() here.
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import subprocess
import sys
from pathlib import Path

from lib.backlog_paths import read_release_state, release_worktree_path
from lib.git_ops import _run as git_run
from lib.hooks import HookPathError, resolve_hook
from lib.main_sync import MainSyncConflictError, resolve_main_ref, sync_main_into_release
from lib.release_freeze import ReleaseFrozenError, frozen_since
from lib.repo import find_repo_root
from lib.state import file_lock
from scripts.ship_current_work_to_release import GateFailedError, _run_precheck


def sync_main(repo: Path) -> dict:
    """Merge main into the in-progress release/<v>, then run Gate 1 on it.

    Returns {"release": <v>|None, "synced": <commits absorbed>, "gate1":
    "passed" | "skipped" (no precheck script) | None (nothing synced)}.
    Raises MainSyncConflictError (release untouched), ReleaseFrozenError, or
    GateFailedError (sync rolled back).
    """
    repo = Path(repo)
    state = read_release_state(repo)
    if state is None:
        return {"release": None, "synced": 0, "gate1": None}
    version = state["version"]
    rel_wt = release_worktree_path(repo)
    branch = f"release/{version}"
    main_ref = resolve_main_ref(repo)  # network, outside the lock
    with file_lock(rel_wt):
        # Promote runs Gate 2 and the push outside this lock; syncing under it
        # would ship a tree Gate 2 never verified. Promote syncs main itself.
        since = frozen_since(repo, version)
        if since:
            raise ReleaseFrozenError(
                f"{branch} is being promoted (frozen since {since}); not syncing "
                f"under it. Re-run psrw promote: it merges main in before its gates."
            )
        pre_sha = git_run(rel_wt, "rev-parse", "HEAD").stdout.strip()
        synced = sync_main_into_release(repo, rel_wt, branch, main_ref)
        if not synced:
            return {"release": version, "synced": 0, "gate1": None}
        # The sync stays ONLY if Gate 1 passed (or has no script): any other
        # outcome — a failing gate, an unusable hooks value, an unrunnable
        # script (OSError), Ctrl-C — resets to the pre-sync head.
        kept = False
        try:
            try:
                rc = _run_precheck(rel_wt)
            except GateFailedError as e:
                raise GateFailedError(f"{e} — sync of {main_ref} into {branch} rolled back") from e
            if rc is not None and rc != 0:
                raise GateFailedError(
                    f"Gate 1 failed on {branch} after syncing {main_ref} — rolled back. "
                    f"Fix main (or the release) so they integrate, then re-run psrw sync-main."
                )
            kept = True
        finally:
            if not kept:
                git_run(rel_wt, "reset", "--hard", pre_sha)
    return {"release": version, "synced": synced, "gate1": "skipped" if rc is None else "passed"}


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="psrw sync-main",
        description="Merge main (e.g. squash-merged hotfixes) into the in-progress "
                    "release/<v> and verify it with Gate 1; rolls back on failure.",
    )
    p.add_argument("--deploy", action="store_true",
                   help="run the local deploy from the _release worktree after a sync")
    args = p.parse_args(argv)

    repo = find_repo_root(Path.cwd())
    try:
        result = sync_main(repo)
    except (MainSyncConflictError, ReleaseFrozenError, GateFailedError, OSError) as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}))
    if result["release"] is None:
        print("\nNo release in progress — nothing to sync.")
        return 0
    if not result["synced"]:
        print(f"\n✅ release/{result['release']} already contains main.")
    else:
        print(f"\n✅ Merged {result['synced']} commit(s) from main into "
              f"release/{result['release']} (Gate 1 {result['gate1']}).")
    if args.deploy:
        rel_wt = release_worktree_path(repo)
        try:
            deploy = resolve_hook(rel_wt, "deploy_local")
        except HookPathError as e:
            print(f"\n❌ Local deploy REFUSED — {e}", file=sys.stderr)
            return 1
        if result["gate1"] == "skipped":
            print("\n⚠️  Gate 1 did not run on the synced tree (no precheck script) — "
                  "deploying it unverified.", file=sys.stderr)
        if not deploy.exists():
            print("\nℹ️  Local deploy skipped: no local deploy configured: add "
                  "scripts/deploy-local.sh or hooks.deploy_local.")
        else:
            print("\n🚀 Running local deployment...")
            rc = subprocess.run([str(deploy)], cwd=rel_wt).returncode
            if rc != 0:
                print(f"\n⚠️  {deploy.name} exited {rc}", file=sys.stderr)
                return 1
    elif result["synced"]:
        print("   Re-deploy locally if you deploy: psrw sync-main --deploy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
