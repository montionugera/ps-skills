import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path


class GitError(Exception):
    """Raised when a git command fails."""


def _run(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    cp = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True)
    if check and cp.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {cp.stderr}")
    return cp


def current_branch(cwd: Path) -> str:
    return _run(cwd, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def branch_exists(cwd: Path, name: str) -> bool:
    cp = _run(cwd, "rev-parse", "--verify", name, check=False)
    return cp.returncode == 0


def is_dirty(cwd: Path) -> bool:
    return bool(_run(cwd, "status", "--porcelain").stdout.strip())


def create_branch(cwd: Path, name: str, start_point: str = "HEAD") -> None:
    _run(cwd, "branch", name, start_point)


def commit_all(cwd: Path, message: str) -> None:
    _run(cwd, "add", "-A")
    _run(cwd, "commit", "-m", message)


def commit_paths(cwd: Path, message: str, paths: Iterable[str]) -> bool:
    """Commit changes under `paths` and nothing else; True if a commit was made.

    Use this instead of commit_all in a checkout that can hold other people's
    work or untracked build output. Paths with no changes are skipped, so a path
    that does not exist is fine.
    """
    changed = [p for p in paths if _run(cwd, "status", "--porcelain", "--", p).stdout.strip()]
    if not changed:
        return False
    _run(cwd, "add", "-A", "--", *changed)
    _run(cwd, "commit", "-m", message, "--", *changed)
    return True


def _seed_graft_if_present(parent_dir: Path, target_dir: Path) -> None:
    """If the parent repo has a graft context graph, seed it in the new worktree."""
    if (parent_dir / "graft").is_dir() and shutil.which("graft"):
        try:
            subprocess.run(
                ["graft", "build"],
                cwd=str(target_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except Exception:
            pass


def add_worktree(cwd: Path, path: Path, branch: str) -> None:
    _run(cwd, "worktree", "add", str(path), branch)
    _seed_graft_if_present(cwd, path)


def add_worktree_new_branch(cwd: Path, path: Path, new_branch: str, start_point: str = "HEAD") -> None:
    _run(cwd, "worktree", "add", "-b", new_branch, str(path), start_point)
    _seed_graft_if_present(cwd, path)


def fetch_and_ff_main(cwd: Path, remote: str = "origin", branch: str = "main") -> None:
    """Fetch and fast-forward local <branch> to <remote>/<branch>.

    PR-based promote advances ONLY the remote (the squash-merge happens on the
    host); local main is never pulled. Cutting a new release branch from a stale
    local main then silently misses the just-promoted release. Calling this
    before branching guarantees the base carries the latest promoted work, and
    raises (non-ff) instead of silently using a diverged local main.
    """
    _run(cwd, "fetch", remote, branch)
    _run(cwd, "checkout", branch)
    _run(cwd, "merge", "--ff-only", f"{remote}/{branch}")


def remove_worktree(cwd: Path, path: Path, force: bool = False) -> None:
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(path))
    _run(cwd, *args)


def delete_branch_local(cwd: Path, name: str, force: bool = True) -> None:
    flag = "-D" if force else "-d"
    _run(cwd, "branch", flag, name)


def delete_branch_remote(cwd: Path, name: str, remote: str = "origin") -> None:
    _run(cwd, "push", remote, "--delete", name, check=False)  # tolerate missing


def push(cwd: Path, ref: str = "HEAD", remote: str = "origin") -> None:
    _run(cwd, "push", remote, ref)


def has_origin(cwd: Path) -> bool:
    """True if an `origin` remote is configured (False in local-only repos/tests)."""
    return _run(cwd, "remote", "get-url", "origin", check=False).returncode == 0


def is_ancestor(cwd: Path, ancestor: str, descendant: str = "HEAD") -> bool:
    """True if ancestor commit is reachable from descendant."""
    return _run(cwd, "merge-base", "--is-ancestor", ancestor, descendant, check=False).returncode == 0


def unmerged_files(cwd: Path) -> list[str]:
    """List conflicting / unmerged files in the current worktree."""
    out = _run(cwd, "diff", "--name-only", "--diff-filter=U", check=False).stdout.strip()
    return [line.strip() for line in out.splitlines() if line.strip()]


def rev_parse(cwd: Path, rev: str) -> str:
    """Resolve revision or ref to full 40-char SHA."""
    return _run(cwd, "rev-parse", rev).stdout.strip()


def diff_names(cwd: Path, a: str, b: str) -> list[str]:
    """List file names changed between two revisions."""
    out = _run(cwd, "diff", "--name-only", a, b, check=False).stdout.strip()
    return [line.strip() for line in out.splitlines() if line.strip()]


def rev_count(cwd: Path, rev_range: str) -> int:
    """Count commits in revision range, e.g. 'HEAD..origin/main'."""
    out = _run(cwd, "rev-list", "--count", rev_range, check=False).stdout.strip()
    try:
        return int(out)
    except ValueError:
        return 0

