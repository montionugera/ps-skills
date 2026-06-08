"""init_work_new_release: mint release/<v> + _release worktree."""
import json
import subprocess
from pathlib import Path

import pytest

from scripts.init_work_new_release import (
    new_release, ReleaseAlreadyInProgressError, BadVersionError,
)


def test_creates_release_branch(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    out = subprocess.run(["git", "branch"], cwd=tmp_repo_with_release, capture_output=True, text=True)
    assert "release/1.1" in out.stdout


def test_creates_release_worktree(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    assert wt.is_dir()


def test_updates_release_json(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    rj = json.loads((tmp_repo_with_release / ".release.json").read_text())
    assert rj["version"] == "1.1"
    assert rj["in_progress"] is True
    assert rj["started_at"] is not None
    assert rj["started_by"] is not None


def test_auto_bumps_minor_if_no_version(tmp_repo_with_release: Path):
    # Current version is 1.0 → auto-bump to 1.1
    result = new_release(tmp_repo_with_release)
    assert result["version"] == "1.1"


def test_refuses_if_release_in_progress(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    with pytest.raises(ReleaseAlreadyInProgressError):
        new_release(tmp_repo_with_release, version="1.2")


def test_refuses_non_increasing_version(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.5")
    # promote it so in_progress becomes false; for test purposes manually clear:
    p = tmp_repo_with_release / ".release.json"
    rj = json.loads(p.read_text())
    rj["in_progress"] = False
    p.write_text(json.dumps(rj))
    with pytest.raises(BadVersionError):
        new_release(tmp_repo_with_release, version="1.3")
