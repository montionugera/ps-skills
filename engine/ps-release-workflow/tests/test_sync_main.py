"""Unit and integration tests for scripts/sync_main.py."""
import json
import subprocess
from pathlib import Path

import pytest

from lib.backlog_paths import NoReleaseInProgressError
from scripts.init_work_new_release import new_release
from scripts.sync_main import Gate1FailedError, sync_main_command


def test_sync_main_no_release_raises(tmp_repo_with_release: Path):
    with pytest.raises(NoReleaseInProgressError):
        sync_main_command(tmp_repo_with_release)


def test_sync_main_noop_when_up_to_date(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    res = sync_main_command(tmp_repo_with_release)
    assert res["ok"]
    assert not res["synced"]
    assert res["behind"] == 0


def test_sync_main_absorbs_commits_and_runs_gate1(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    repo = tmp_repo_with_release

    # Add passing Gate 1 script
    pre = rel_wt / "scripts" / "precheck.sh"
    pre.parent.mkdir(parents=True, exist_ok=True)
    pre.write_text("#!/bin/sh\nexit 0\n")
    pre.chmod(0o755)
    subprocess.run(["git", "add", "scripts/precheck.sh"], cwd=rel_wt, check=True)
    subprocess.run(["git", "commit", "-m", "add precheck on release"], cwd=rel_wt, check=True)

    # Commit hotfix on main and push to origin
    (repo / "hotfix.txt").write_text("hotfix\n")
    subprocess.run(["git", "add", "hotfix.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "hotfix on main"], cwd=repo, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True)

    res = sync_main_command(repo)
    assert res["ok"]
    assert res["synced"]
    assert res["behind"] == 1
    assert (rel_wt / "hotfix.txt").exists()


def test_sync_main_gate1_failure_rolls_back(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    repo = tmp_repo_with_release

    # Add failing Gate 1 script
    pre = rel_wt / "scripts" / "precheck.sh"
    pre.parent.mkdir(parents=True, exist_ok=True)
    pre.write_text("#!/bin/sh\nexit 1\n")
    pre.chmod(0o755)
    subprocess.run(["git", "add", "scripts/precheck.sh"], cwd=rel_wt, check=True)
    subprocess.run(["git", "commit", "-m", "add failing precheck on release"], cwd=rel_wt, check=True)
    pre_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rel_wt,
                             capture_output=True, text=True, check=True).stdout.strip()

    # Commit hotfix on main and push to origin
    (repo / "hotfix.txt").write_text("hotfix\n")
    subprocess.run(["git", "add", "hotfix.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "hotfix on main"], cwd=repo, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True)

    with pytest.raises(Gate1FailedError):
        sync_main_command(repo)

    # release worktree should be rolled back to pre_sha
    curr_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rel_wt,
                              capture_output=True, text=True, check=True).stdout.strip()
    assert curr_sha == pre_sha
    assert not (rel_wt / "hotfix.txt").exists()
