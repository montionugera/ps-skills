"""ps-release-workflow:sync-main — absorb main into release/<v> and verify."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import subprocess
import sys
from pathlib import Path

from lib.backlog_paths import (
    NoReleaseInProgressError,
    get_release_worktree,
    read_release_state,
)
from lib.git_ops import _run as git_run
from lib.hooks import HookPathError, resolve_hook
from lib.main_sync import (
    MainSyncConflictError,
    MainSyncError,
    ProtectedPathSyncError,
    render_sync_failure,
    resolve_main_sha,
    sync_main_into_release,
)
from lib.repo import find_repo_root, is_ps_release_workflow_repo
from lib.state import file_lock


class Gate1FailedError(Exception):
    pass


def _run_gate1(rel_wt: Path) -> int | None:
    try:
        precheck = resolve_hook(rel_wt, "precheck")
    except HookPathError as e:
        print(f"❌ Gate 1 REFUSED — {e}", file=sys.stderr)
        raise Gate1FailedError(str(e))
    if not precheck.exists():
        print(f"⚠️ Gate 1 SKIPPED — {precheck} not found in {rel_wt}", file=sys.stderr)
        return None
    return subprocess.run([str(precheck)], cwd=rel_wt).returncode


def sync_main_command(
    cwd: Path,
    *,
    strict: bool = False,
    run_deploy: bool = False,
    run_gate1: bool = True,
) -> dict:
    cwd = Path(cwd).resolve()
    repo = find_repo_root(cwd)
    if not is_ps_release_workflow_repo(repo):
        raise RuntimeError(f"{repo} not opted into ps-release-workflow")

    state = read_release_state(repo)
    if state is None:
        raise NoReleaseInProgressError("No release in progress")
    version = state["version"]
    release_branch = f"release/{version}"
    rel_wt = get_release_worktree(repo)

    main_sha, source = resolve_main_sha(repo, strict=strict)

    with file_lock(rel_wt):
        pre_sha = git_run(rel_wt, "rev-parse", "HEAD").stdout.strip()
        try:
            sync_res = sync_main_into_release(repo, rel_wt, release_branch, main_sha, source)
        except (MainSyncConflictError, ProtectedPathSyncError) as e:
            raise RuntimeError(render_sync_failure(e, release_branch, "manual sync"))

        if sync_res.synced and run_gate1:
            try:
                rc = _run_gate1(rel_wt)
            except Gate1FailedError:
                git_run(rel_wt, "reset", "--hard", pre_sha)
                raise
            if rc not in (None, 0):
                git_run(rel_wt, "reset", "--hard", pre_sha)
                raise Gate1FailedError(
                    f"Gate 1 failed after absorbing main@{main_sha[:12]} — rolled back to {pre_sha[:12]}"
                )

    if run_deploy and sync_res.synced:
        try:
            deploy_script = resolve_hook(rel_wt, "deploy_local")
            if deploy_script.exists():
                subprocess.run([str(deploy_script)], cwd=rel_wt, check=True)
        except Exception as e:
            print(f"⚠️ Local deploy failed: {e}", file=sys.stderr)

    return {
        "ok": True,
        "release": version,
        "synced": sync_res.synced,
        "main_sha": sync_res.main_sha,
        "source": sync_res.source,
        "behind": sync_res.behind,
        "files": sync_res.files,
    }


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="psrw sync-main",
        description="Absorb main (e.g. squash-merged hotfixes) into the active release branch.",
    )
    p.add_argument("--strict", action="store_true",
                   help="fail if origin/main cannot be reached")
    p.add_argument("--deploy", action="store_true",
                   help="run local deploy after successful sync")
    p.add_argument("--no-gate1", action="store_true",
                   help="skip running Gate 1 after sync")
    p.add_argument("--json", action="store_true",
                   help="output machine-readable JSON")
    args = p.parse_args()

    try:
        res = sync_main_command(
            Path.cwd(),
            strict=args.strict,
            run_deploy=args.deploy,
            run_gate1=not args.no_gate1,
        )
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(res))
    else:
        if res["synced"]:
            print(
                f"✅ Absorbed {res['behind']} commit(s) from {res['source']}@{res['main_sha'][:12]} "
                f"into release/{res['release']}."
            )
        else:
            print(f"✅ release/{res['release']} is already up to date with {res['source']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
