"""Helpers for resolving the backlog-mutation target (always _release worktree)."""
from pathlib import Path
from typing import Optional
import json

class NoReleaseInProgressError(Exception): pass


def release_worktree_path(repo: Path) -> Path:
    return Path(repo) / ".claude" / "worktrees" / "_release"


def read_release_state(repo: Path) -> Optional[dict]:
    """Authoritative IN-PROGRESS release state, or None if no release is in progress.

    Source of truth = the _release worktree's .release.json (the release branch).
    main's .release.json only carries the LAST-PROMOTED state (written solely by
    the promote squash / direct-mode finalize), so it is NOT consulted here — that
    separation is what keeps the PR the sole writer of main (fix #2).
    """
    wt = release_worktree_path(repo)
    rjp = wt / ".release.json"
    if not wt.is_dir() or not rjp.exists():
        return None
    rj = json.loads(rjp.read_text())
    return rj if rj.get("in_progress") else None


def get_release_worktree(repo: Path) -> Path:
    """Return path to the _release worktree (release/<v> long-lived worktree).
    Raises NoReleaseInProgressError if release is not in progress.
    """
    if read_release_state(repo) is None:
        raise NoReleaseInProgressError("Run psrw new-release first")
    return release_worktree_path(repo)

def get_backlog_catalog_path(repo: Path, kind: str) -> Path:
    """kind in {idea, refined, epic}. Returns _release_worktree/.claude/<kind>_backlog/_catalog.json."""
    wt = get_release_worktree(repo)
    return wt / ".claude" / f"{kind}_backlog" / "_catalog.json"
