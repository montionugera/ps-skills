"""Test backlog-mutation target resolution (always the _release worktree)."""
import json
from pathlib import Path

import pytest

from lib.backlog_paths import (
    get_release_worktree,
    get_backlog_catalog_path,
    NoReleaseInProgressError,
)


def _make_release_worktree(repo: Path) -> Path:
    """Fabricate the long-lived _release worktree with backlog dirs."""
    wt = repo / ".claude" / "worktrees" / "_release"
    (wt / ".claude" / "idea_backlog").mkdir(parents=True)
    (wt / ".claude" / "refined_backlog").mkdir(parents=True)
    return wt


def _set_in_progress(repo: Path, value: bool) -> None:
    rj = json.loads((repo / ".release.json").read_text())
    rj["in_progress"] = value
    (repo / ".release.json").write_text(json.dumps(rj))


def test_returns_worktree_when_in_progress(tmp_repo_with_release: Path):
    _set_in_progress(tmp_repo_with_release, True)
    wt = _make_release_worktree(tmp_repo_with_release)
    assert get_release_worktree(tmp_repo_with_release) == wt


def test_raises_when_not_in_progress(tmp_repo_with_release: Path):
    _set_in_progress(tmp_repo_with_release, False)
    with pytest.raises(NoReleaseInProgressError):
        get_release_worktree(tmp_repo_with_release)


def test_raises_when_worktree_missing(tmp_repo_with_release: Path):
    _set_in_progress(tmp_repo_with_release, True)
    # do not create the _release worktree dir
    with pytest.raises(NoReleaseInProgressError):
        get_release_worktree(tmp_repo_with_release)


def test_idea_catalog_path(tmp_repo_with_release: Path):
    _set_in_progress(tmp_repo_with_release, True)
    wt = _make_release_worktree(tmp_repo_with_release)
    assert get_backlog_catalog_path(tmp_repo_with_release, "idea") == (
        wt / ".claude" / "idea_backlog" / "_catalog.json"
    )


def test_refined_catalog_path(tmp_repo_with_release: Path):
    _set_in_progress(tmp_repo_with_release, True)
    wt = _make_release_worktree(tmp_repo_with_release)
    assert get_backlog_catalog_path(tmp_repo_with_release, "refined") == (
        wt / ".claude" / "refined_backlog" / "_catalog.json"
    )
