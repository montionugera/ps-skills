"""Detect a catalogued-shipped feature whose branch has commits the release lacks."""
from pathlib import Path

from lib.git_ops import GitError, _run


def unmerged_commits(repo: Path, version: str, feature_id: str) -> int:
    """Commits on feat/<id> not reachable from release/<v> (0 when unknown — never raises).

    Missing feature branch, missing release branch (e.g. deleted after promote)
    or any git failure all read as 0: no warning rather than a false alarm.
    """
    try:
        res = _run(
            repo, "rev-list", "--count",
            f"refs/heads/release/{version}..refs/heads/feat/{feature_id}", check=False,
        )
        return int(res.stdout.strip()) if res.returncode == 0 else 0
    except (OSError, ValueError, GitError):
        return 0


def unmerged_warning(feature_id: str, version: str, n: int) -> str:
    return f"shipped but {n} commit(s) on feat/{feature_id} not in release/{version}"
