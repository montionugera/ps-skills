"""ps-release-workflow:hotfix — create the sibling worktree a hotfix requires."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import sys
from pathlib import Path

from lib.backlog_paths import read_release_state, release_worktree_path
from lib.git_ops import add_worktree_new_branch
from lib.main_sync import MainSyncConflictError, sync_main_into_release
from lib.release_freeze import frozen_since
from lib.repo import find_repo_root
from lib.state import file_lock
from lib.slug import slugify


class HotfixTargetExistsError(Exception):
    """The sibling worktree directory already exists."""


def create_hotfix_worktree(repo: Path, desc: str) -> dict:
    """Create ../<repo>-hotfix-<slug> on branch hotfix/<slug>, cut from main.

    A sibling — NOT .claude/worktrees/ — because the guard blocks the main
    checkout by filesystem location regardless of branch name, and
    .claude/worktrees/ is the claimed-feature area the guard checks markers in.
    """
    repo = Path(repo)
    slug = slugify(desc)
    branch = f"hotfix/{slug}"
    target = repo.parent / f"{repo.name}-hotfix-{slug}"

    if target.exists():
        raise HotfixTargetExistsError(
            f"{target} already exists — reuse it, or pick a different description"
        )

    add_worktree_new_branch(repo, target, branch, "main")
    return {"branch": branch, "worktree": str(target), "created": True}


def sync_release(repo: Path) -> dict:
    """The last step of the hotfix flow: once the hotfix PR has merged, merge
    main into the in-progress release/<v> (via the _release worktree) so no
    later ship, deploy or promote runs from a release that lacks the hotfix.

    Returns {"release": <v> | None, "synced": <commits absorbed>}. No release
    in progress is a no-op. Raises MainSyncConflictError on a conflict.
    """
    repo = Path(repo)
    state = read_release_state(repo)
    if state is None:
        return {"release": None, "synced": 0}
    rel_wt = release_worktree_path(repo)
    branch = f"release/{state['version']}"
    with file_lock(rel_wt):
        # Promote runs Gate 2 and the push outside this lock; changing the
        # tree under it would ship something Gate 2 never verified. Promote
        # syncs main itself, so a re-run of promote picks the hotfix up.
        since = frozen_since(repo, state["version"])
        if since:
            raise MainSyncConflictError(
                f"{branch} is being promoted (frozen since {since}); not syncing "
                f"under it. Re-run psrw promote: it merges main in before its gates."
            )
        synced = sync_main_into_release(repo, rel_wt, branch)
    return {"release": state["version"], "synced": synced}


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="psrw hotfix",
        description="Create a sibling hotfix worktree. Does NOT install deps, "
                    "commit, or open a PR — it prints that checklist.",
    )
    p.add_argument("desc", nargs="?", help="short description, e.g. 'mt5 idor'")
    p.add_argument("--sync-release", action="store_true",
                   help="after the hotfix PR merged: merge main into the in-progress "
                        "release/<v> so ship/deploy/promote include the hotfix")
    args = p.parse_args()
    if not args.sync_release and not args.desc:
        p.error("a description is required (or pass --sync-release)")

    repo = find_repo_root(Path.cwd())
    if args.sync_release:
        try:
            result = sync_release(repo)
        except MainSyncConflictError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        print(json.dumps({"ok": True, **result}))
        if result["release"] is None:
            print("\nNo release in progress — nothing to sync.")
        elif result["synced"]:
            print(f"\n✅ Merged {result['synced']} commit(s) from main into "
                  f"release/{result['release']}. Re-deploy locally if you deploy.")
        else:
            print(f"\n✅ release/{result['release']} already contains main.")
        return 0

    try:
        result = create_hotfix_worktree(repo, args.desc)
    except HotfixTargetExistsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    wt = result["worktree"]
    print(json.dumps({"ok": True, **result}))
    print(f"\n✅ Hotfix worktree ready: {wt}")
    print(f"   branch: {result['branch']} (cut from main)\n")
    print("   Remaining steps — this script deliberately does none of them:")
    print(f"     1. cd {wt}")
    print("     2. install deps (a fresh worktree has NO node_modules / venv)")
    print("     3. make the fix")
    print("     4. run the repo's verification with VISIBLE exit codes")
    print("     5. commit — a NEW commit, never `git commit --amend`")
    print("     6. push, open a PR to main, babysit CI, squash-merge")
    print("     7. once merged, if a release is in progress: psrw hotfix --sync-release")
    print("        (merges main into release/<v>; ship does this too, but the local")
    print("        deploy and open features should not wait for the next ship)")
    print(f"     8. clean up: git worktree remove {wt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
