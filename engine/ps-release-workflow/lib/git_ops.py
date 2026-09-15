"""Subprocess wrappers around git commands."""
import subprocess
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


def add_worktree(cwd: Path, path: Path, branch: str) -> None:
    _run(cwd, "worktree", "add", str(path), branch)


def add_worktree_new_branch(cwd: Path, path: Path, new_branch: str, start_point: str = "HEAD") -> None:
    _run(cwd, "worktree", "add", "-b", new_branch, str(path), start_point)


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
