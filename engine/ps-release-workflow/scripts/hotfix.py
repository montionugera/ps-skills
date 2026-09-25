"""ps-release-workflow:hotfix — create the sibling worktree a hotfix requires."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import sys
from pathlib import Path

from lib.backlog_paths import read_release_state
from lib.git_ops import add_worktree_new_branch
from lib.repo import find_repo_root
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


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="psrw hotfix",
        description="Create a sibling hotfix worktree. Does NOT install deps, "
                    "commit, or open a PR — it prints that checklist.",
    )
    p.add_argument("desc", nargs="?", help="short description, e.g. 'mt5 idor'")
    p.add_argument("--sync-release", action="store_true",
                   help="alias for `psrw sync-main`: merge main into the in-progress "
                        "release/<v> and run Gate 1")
    p.add_argument("--deploy", action="store_true",
                   help="with --sync-release: run the local deploy after the sync")
    args = p.parse_args()
    if args.sync_release and args.desc:
        p.error("--sync-release takes no description (it is `psrw sync-main`)")
    if not args.sync_release and not args.desc:
        p.error("a description is required (or pass --sync-release)")
    if args.deploy and not args.sync_release:
        p.error("--deploy only applies with --sync-release")

    repo = find_repo_root(Path.cwd())
    if args.sync_release:
        # One code path: the alias delegates to `psrw sync-main`.
        # One code path: the alias forwards its flags to `psrw sync-main`.
        import scripts.sync_main as sync_main_mod
        return sync_main_mod.main(["--deploy"] if args.deploy else [])

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
    print(f"     7. clean up: git worktree remove {wt}")
    state = read_release_state(repo)
    if state:
        print(f"     8. release/{state['version']} is in progress — the hotfix reaches it "
              f"automatically at the next psrw ship / psrw promote.")
        print("        To absorb it now (e.g. to redeploy locally): psrw sync-main --deploy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
