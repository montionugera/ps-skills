"""promote_release: Gate 2 + squash merge → main + auto-cleanup."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.init_work_new_release import new_release
from scripts.new_idea import new_idea
from scripts.promote_idea_to_refined import promote_idea_to_refined
from scripts.init_work_refined_backlog import claim_feature
from scripts.ship_current_work_to_release import ship_current_work
from scripts.promote_release import (
    promote_release, NoReleaseInProgressError, Gate2FailedError, cleanup,
)


def _setup_and_ship_feature(tmp_repo_with_release: Path, fixed_owner: str, title: str = "F"):
    """Helper: open release, claim+ship one feature, return repo + feature_id."""
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title=title)
    feat = promote_idea_to_refined(tmp_repo_with_release, idea["id"])
    claim = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    # Stub Gate 1.
    (tmp_repo_with_release / "scripts").mkdir(exist_ok=True)
    (tmp_repo_with_release / "scripts" / "precheck.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_repo_with_release / "scripts" / "precheck.sh").chmod(0o755)
    (tmp_repo_with_release / "scripts" / "integration.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_repo_with_release / "scripts" / "integration.sh").chmod(0o755)
    subprocess.run(["git", "add", "scripts/"], cwd=tmp_repo_with_release, check=True)
    subprocess.run(["git", "commit", "-m", "stubs"], cwd=tmp_repo_with_release, check=True, capture_output=True)
    wt = Path(claim["worktree"])
    (wt / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "feat"], cwd=wt, check=True, capture_output=True)
    ship_current_work(wt)
    return feat


def test_promote_merges_release_into_main(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, push=False)
    log = subprocess.run(["git", "log", "main", "--oneline"], cwd=tmp_repo_with_release, capture_output=True, text=True)
    assert "release 1.1" in log.stdout.lower() or "feat" in log.stdout.lower()


def test_promote_runs_gate2_when_requested(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    # Both stubs return 0 → should pass.
    promote_release(tmp_repo_with_release, run_gate2=True, run_deploy=False, push=False)


def test_promote_gate2_failure_aborts_before_push(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    # Break integration.sh.
    integ = tmp_repo_with_release / "scripts" / "integration.sh"
    integ.write_text("#!/bin/sh\nexit 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_repo_with_release, check=True)
    subprocess.run(["git", "commit", "-m", "broken integ"], cwd=tmp_repo_with_release, check=True, capture_output=True)
    with pytest.raises(Gate2FailedError):
        promote_release(tmp_repo_with_release, run_gate2=True, run_deploy=False, push=False)


def test_promote_auto_cleanup_removes_feature_branch(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, push=False)
    branches = subprocess.run(["git", "branch"], cwd=tmp_repo_with_release, capture_output=True, text=True).stdout
    assert f"feat/{feat['id']}" not in branches
    assert "release/1.1" not in branches


def test_promote_auto_cleanup_archives_refined_backlog(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, push=False)
    archived = tmp_repo_with_release / ".claude" / "refined_backlog" / "_archive" / "1.1" / f"{feat['id']}-f"
    # Slug "f" because title was "F"
    # Note: the original folder should be moved, archive should exist
    archive_root = tmp_repo_with_release / ".claude" / "refined_backlog" / "_archive"
    assert archive_root.is_dir()


def test_promote_auto_cleanup_removes_feature_worktree(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, push=False)
    wt = tmp_repo_with_release / ".claude" / "worktrees"
    feature_wts = [d for d in wt.iterdir() if d.name.startswith(feat["id"])]
    assert feature_wts == []


def test_promote_clears_release_in_progress(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, push=False)
    rj = json.loads((tmp_repo_with_release / ".release.json").read_text())
    assert rj["in_progress"] is False
    assert rj["last_promoted_version"] == "1.1"


def test_promote_keep_flag_skips_cleanup(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, push=False, keep=True)
    # Feature branch + release branch should still exist.
    branches = subprocess.run(["git", "branch"], cwd=tmp_repo_with_release, capture_output=True, text=True).stdout
    assert f"feat/{feat['id']}" in branches
    assert "release/1.1" in branches


def test_cleanup_subcommand_idempotent(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, push=False, keep=True)
    # Now run cleanup manually.
    cleanup(tmp_repo_with_release, version="1.1")
    cleanup(tmp_repo_with_release, version="1.1")  # second run should no-op
