"""ship_current_work_to_release: Gate 1 + merge feat → release."""
import json
import subprocess
from pathlib import Path

import pytest

from scripts.init_work_new_release import new_release
from scripts.new_idea import new_idea
from scripts.promote_idea_to_refined import promote_idea_to_refined
from scripts.init_work_refined_backlog import claim_feature
from scripts.ship_current_work_to_release import (
    ship_current_work, DirtyTreeError, GateFailedError, NotInFeatureWorktreeError,
)


def _make_repo_with_open_release_and_claim(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea["id"])
    claim = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    # Stub Gate 1 script that always passes.
    scripts_dir = tmp_repo_with_release / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    pre = scripts_dir / "precheck.sh"
    pre.write_text("#!/bin/sh\nexit 0\n")
    pre.chmod(0o755)
    subprocess.run(["git", "add", "scripts/precheck.sh"], cwd=tmp_repo_with_release, check=True)
    subprocess.run(["git", "commit", "-m", "scaffold precheck"], cwd=tmp_repo_with_release, check=True, capture_output=True)
    return feat, claim


def test_ship_merges_feat_into_release(tmp_repo_with_release: Path, fixed_owner: str):
    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    # Make a commit in the feature worktree.
    (wt / "feature.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "feat: add feature.txt"], cwd=wt, check=True, capture_output=True)
    ship_current_work(wt)
    # Verify feature.txt is on release/1.1 (the _release worktree is checked out on it).
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    assert (rel_wt / "feature.txt").exists()


def test_ship_refuses_dirty_tree(tmp_repo_with_release: Path, fixed_owner: str):
    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    (wt / "uncommitted.txt").write_text("x")
    with pytest.raises(DirtyTreeError):
        ship_current_work(wt)


def test_ship_marks_catalog_shipped(tmp_repo_with_release: Path, fixed_owner: str):
    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    (wt / "x.txt").write_text("y")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "x"], cwd=wt, check=True, capture_output=True)
    ship_current_work(wt)
    # Read the _RELEASE worktree catalog (NOT main) — that's where the populated catalog lives (D11).
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    cat = json.loads((rel_wt / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    f = next(e for e in cat if e["id"] == feat["id"])
    assert f["status"] == "shipped"
    assert f["release_version"] == "1.1"
    # MAIN's catalog must remain empty — no leakage to main (D11).
    main_cat = json.loads((tmp_repo_with_release / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    assert main_cat == []


def test_ship_fails_loudly_when_gate1_fails(tmp_repo_with_release: Path, fixed_owner: str):
    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    # Replace precheck to exit 1.
    (tmp_repo_with_release / "scripts" / "precheck.sh").write_text("#!/bin/sh\nexit 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_repo_with_release, check=True)
    subprocess.run(["git", "commit", "-m", "broken precheck"], cwd=tmp_repo_with_release, check=True, capture_output=True)
    wt = Path(claim["worktree"])
    (wt / "x.txt").write_text("y")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "x"], cwd=wt, check=True, capture_output=True)
    with pytest.raises(GateFailedError):
        ship_current_work(wt)


def test_two_features_ship_into_same_release(tmp_repo_with_release: Path, fixed_owner: str):
    """Sequential ship of two features into one release — proves the file_lock
    doesn't break the normal path: both end up status=shipped and both feature
    files land on release/<v> in the _release worktree."""
    new_release(tmp_repo_with_release, version="1.1")
    # Stub a passing Gate 1 script.
    scripts_dir = tmp_repo_with_release / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    pre = scripts_dir / "precheck.sh"
    pre.write_text("#!/bin/sh\nexit 0\n")
    pre.chmod(0o755)
    subprocess.run(["git", "add", "scripts/precheck.sh"], cwd=tmp_repo_with_release, check=True)
    subprocess.run(["git", "commit", "-m", "scaffold precheck"], cwd=tmp_repo_with_release, check=True, capture_output=True)

    # Feature A.
    idea_a = new_idea(tmp_repo_with_release, title="Feature A")
    feat_a = promote_idea_to_refined(tmp_repo_with_release, idea_a["id"])
    claim_a = claim_feature(tmp_repo_with_release, feat_a["id"], owner=fixed_owner)
    wt_a = Path(claim_a["worktree"])
    (wt_a / "feature_a.txt").write_text("A")
    subprocess.run(["git", "add", "."], cwd=wt_a, check=True)
    subprocess.run(["git", "commit", "-m", "feat: A"], cwd=wt_a, check=True, capture_output=True)
    ship_current_work(wt_a)

    # Feature B.
    idea_b = new_idea(tmp_repo_with_release, title="Feature B")
    feat_b = promote_idea_to_refined(tmp_repo_with_release, idea_b["id"])
    claim_b = claim_feature(tmp_repo_with_release, feat_b["id"], owner=fixed_owner)
    wt_b = Path(claim_b["worktree"])
    (wt_b / "feature_b.txt").write_text("B")
    subprocess.run(["git", "add", "."], cwd=wt_b, check=True)
    subprocess.run(["git", "commit", "-m", "feat: B"], cwd=wt_b, check=True, capture_output=True)
    ship_current_work(wt_b)

    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    # Both feature files on release/1.1.
    assert (rel_wt / "feature_a.txt").exists()
    assert (rel_wt / "feature_b.txt").exists()
    # Both shipped in the _release catalog.
    cat = json.loads((rel_wt / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    by_id = {e["id"]: e for e in cat}
    assert by_id[feat_a["id"]]["status"] == "shipped"
    assert by_id[feat_b["id"]]["status"] == "shipped"


def test_ship_refuses_when_not_in_feature_worktree(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    with pytest.raises(NotInFeatureWorktreeError):
        ship_current_work(tmp_repo_with_release)  # main checkout, not a feat worktree
