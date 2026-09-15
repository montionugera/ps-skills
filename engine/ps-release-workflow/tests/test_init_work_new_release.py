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
    # Fix #2: the start-state lives on the RELEASE BRANCH (the _release worktree),
    # NOT main. main is left untouched (only the promote squash writes it).
    rel_rj = tmp_repo_with_release / ".claude" / "worktrees" / "_release" / ".release.json"
    rj = json.loads(rel_rj.read_text())
    assert rj["version"] == "1.1"
    assert rj["in_progress"] is True
    assert rj["started_at"] is not None
    assert rj["started_by"] is not None
    # main's .release.json is unchanged (still the pre-release / last-promoted state)
    main_rj = json.loads((tmp_repo_with_release / ".release.json").read_text())
    assert main_rj["in_progress"] is False


def test_new_release_does_not_commit_to_main(tmp_repo_with_release: Path):
    """Fix #2 invariant: new_release leaves main's HEAD untouched (no 'start'
    commit on main) — the release branch is the sole carrier of in-progress state,
    so local main never diverges from origin."""
    before = subprocess.run(["git", "rev-parse", "main"], cwd=tmp_repo_with_release,
                            capture_output=True, text=True).stdout.strip()
    new_release(tmp_repo_with_release, version="1.1")
    after = subprocess.run(["git", "rev-parse", "main"], cwd=tmp_repo_with_release,
                           capture_output=True, text=True).stdout.strip()
    assert before == after


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
    # Simulate promote: drop the _release worktree (no release in progress) and
    # advance main's recorded version to 1.5 (the last-promoted state). The next
    # version must exceed main's recorded version.
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                   cwd=tmp_repo_with_release, check=True, capture_output=True)
    p = tmp_repo_with_release / ".release.json"
    rj = json.loads(p.read_text())
    rj["version"] = "1.5"
    rj["in_progress"] = False
    p.write_text(json.dumps(rj))
    with pytest.raises(BadVersionError):
        new_release(tmp_repo_with_release, version="1.3")
