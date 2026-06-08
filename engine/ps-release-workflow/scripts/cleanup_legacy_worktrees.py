"""ps-release-workflow:cleanup-legacy — interactive GC for marker-less worktrees."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import subprocess
import sys
from pathlib import Path

from lib.git_ops import _run as git_run, GitError
from lib.repo import find_repo_root, is_ps_release_workflow_repo


def enumerate_legacy_worktrees(repo: Path) -> list[dict]:
    """List worktree dirs lacking working-feature.json marker."""
    repo = Path(repo)
    wt_root = repo / ".claude" / "worktrees"
    if not wt_root.is_dir():
        return []
    legacy = []
    for d in wt_root.iterdir():
        if not d.is_dir():
            continue
        if d.name == "_release":
            continue  # skip the long-lived release worktree
        # Check marker
        gp = d / ".git"
        marker_found = False
        if gp.is_file():
            try:
                gitdir = Path(gp.read_text().strip().split("gitdir:", 1)[1].strip())
                if (gitdir / "working-feature.json").exists():
                    marker_found = True
            except (IndexError, OSError):
                pass
        if not marker_found:
            # Get branch name.
            try:
                branch = git_run(d, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            except GitError:
                branch = "?"
            legacy.append({
                "path": str(d),
                "branch": branch,
                "merged_to_main": is_branch_merged_to_main(repo, branch),
            })
    return legacy


def is_branch_merged_to_main(repo: Path, branch: str) -> bool:
    """Return True if `branch` is reachable from main."""
    try:
        cp = subprocess.run(
            ["git", "merge-base", "--is-ancestor", branch, "main"],
            cwd=repo, capture_output=True, check=False,
        )
        return cp.returncode == 0
    except Exception:
        return False


def prompt_user(prompt: str) -> str:
    return input(prompt).strip().lower()


def main() -> int:
    repo = find_repo_root(Path.cwd())
    if not is_ps_release_workflow_repo(repo):
        print(f"ERROR: {repo} not opted into ps-release-workflow", file=sys.stderr)
        return 1
    legacy = enumerate_legacy_worktrees(repo)
    if not legacy:
        print("✅ No legacy worktrees.")
        return 0
    print(f"Found {len(legacy)} legacy worktree(s):\n")
    for w in legacy:
        merged_indicator = "✅ merged to main" if w["merged_to_main"] else "⚠ NOT merged"
        print(f"  {w['path']}")
        print(f"    branch: {w['branch']}")
        print(f"    status: {merged_indicator}")
        choice = prompt_user(f"    [k]eep / [r]emove / [s]kip > ")
        if choice == "r":
            try:
                git_run(repo, "worktree", "remove", "--force", w["path"])
                print(f"    ✅ removed")
            except GitError as e:
                print(f"    ❌ remove failed: {e}")
        else:
            print(f"    (kept)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
