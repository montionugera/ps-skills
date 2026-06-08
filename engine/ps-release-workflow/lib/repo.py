"""Repo root discovery + ps-release-workflow opt-in detection."""
from pathlib import Path


class RepoNotFoundError(Exception):
    """Raised when no .git/ ancestor is found."""


def find_repo_root(start: Path) -> Path:
    """Walk up from `start` until a directory containing .git is found.

    Returns the repo root (the dir containing .git/). If the nearest .git is a
    worktree pointer file (``gitdir: .../.git/worktrees/<id>``), resolve it to
    the *main* worktree root so that paths inside ``.claude/worktrees/`` are
    correctly seen as belonging to the parent repo rather than a standalone one.
    """
    cur = Path(start).resolve()
    while True:
        git = cur / ".git"
        if git.exists():
            main = _main_root_from_git(git)
            return main if main is not None else cur
        if cur.parent == cur:
            raise RepoNotFoundError(f"no .git/ ancestor found from {start}")
        cur = cur.parent


def _main_root_from_git(git: Path) -> Path | None:
    """If `git` is a worktree pointer file, return the main worktree root.

    Returns None when `git` is an ordinary .git directory (normal repo root).
    """
    if not git.is_file():
        return None
    try:
        content = git.read_text().strip()
        gitdir = Path(content.split("gitdir:", 1)[1].strip())
    except (IndexError, OSError):
        return None
    # gitdir points at <maindotgit>/worktrees/<id>; commondir → the main .git.
    commondir_file = gitdir / "commondir"
    if commondir_file.is_file():
        try:
            common = (gitdir / commondir_file.read_text().strip()).resolve()
            return common.parent
        except OSError:
            return None
    return None


def is_ps_release_workflow_repo(root: Path) -> bool:
    """Detect whether the repo at `root` has opted into ps-release-workflow."""
    return (Path(root) / ".release.json").is_file()
