"""Helpers for resolving the backlog-mutation target (always _release worktree)."""
from pathlib import Path
import json

class NoReleaseInProgressError(Exception): pass

def get_release_worktree(repo: Path) -> Path:
    """Return path to the _release worktree (release/<v> long-lived worktree).
    Raises NoReleaseInProgressError if release is not in progress.
    """
    rj = json.loads((Path(repo) / ".release.json").read_text())
    if not rj.get("in_progress"):
        raise NoReleaseInProgressError("Run /ps-release-workflow:new-release first")
    wt = Path(repo) / ".claude" / "worktrees" / "_release"
    if not wt.is_dir():
        raise NoReleaseInProgressError(f"_release worktree missing at {wt}")
    return wt

def get_backlog_catalog_path(repo: Path, kind: str) -> Path:
    """kind in {idea, refined}. Returns _release_worktree/.claude/<kind>_backlog/_catalog.json."""
    wt = get_release_worktree(repo)
    return wt / ".claude" / f"{kind}_backlog" / "_catalog.json"
