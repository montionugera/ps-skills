"""init_work_refined_backlog: atomic claim of F-NNN + per-feature worktree (D11/SR-1/D12)."""
import json
import subprocess
from pathlib import Path

import pytest

from scripts.init_work_new_release import new_release
from scripts.new_idea import new_idea
from scripts.promote_idea_to_refined import promote_idea_to_refined
from scripts.init_work_refined_backlog import (
    claim_feature,
    AlreadyClaimedError,
    NoFreeFeatureError,
    NoReleaseInProgressError,
)


def _setup_feature(repo: Path, title: str = "X") -> dict:
    """Open a release (so the _release worktree exists), capture+promote one idea."""
    idea = new_idea(repo, title=title)
    return promote_idea_to_refined(repo, idea["id"])


def test_claim_creates_worktree_with_marker(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)
    result = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    assert Path(result["worktree"]).is_dir()
    assert result["feature"] == feat["id"]
    assert result["branch"] == f"feat/{feat['id']}"


def test_claim_writes_marker_in_git_worktree_metadata(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)
    result = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    wt_dir = Path(result["worktree"]).name  # <F-id>-<slug>
    marker = tmp_repo_with_release / ".git" / "worktrees" / wt_dir / "working-feature.json"
    assert marker.exists()
    marker_data = json.loads(marker.read_text())
    assert marker_data["feature"] == feat["id"]
    assert marker_data["owner"] == fixed_owner


def test_claim_updates_claims_json(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)
    claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    claims = json.loads(
        (tmp_repo_with_release / ".claude" / "state" / "claims.json").read_text()
    )
    assert feat["id"] in claims
    assert claims[feat["id"]]["owner"] == fixed_owner


def test_claim_marks_feature_status_claimed(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)
    claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    # Read the catalog in the _RELEASE worktree (not the main checkout).
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    cat = json.loads((wt / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    entry = next(e for e in cat if e["id"] == feat["id"])
    assert entry["status"] == "claimed"
    assert entry["claimed_by"] == fixed_owner

    # _release worktree must be clean (no stray .lock / .tmp, commit landed).
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"], cwd=wt, capture_output=True, text=True
    )
    assert porcelain.stdout.strip() == ""


def test_claim_collision_raises_already_claimed(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)
    claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    with pytest.raises(AlreadyClaimedError):
        claim_feature(tmp_repo_with_release, feat["id"], owner="another-owner")


def test_claim_next_picks_first_unclaimed(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    for t in ["A", "B", "C"]:
        idea = new_idea(tmp_repo_with_release, title=t)
        promote_idea_to_refined(tmp_repo_with_release, idea["id"])
    claim_feature(tmp_repo_with_release, "F-001", owner=fixed_owner)
    result = claim_feature(tmp_repo_with_release, None, owner="other", select_next=True)
    assert result["feature"] == "F-002"


def test_claim_next_with_no_unclaimed_raises(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)
    claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    with pytest.raises(NoFreeFeatureError):
        claim_feature(tmp_repo_with_release, None, owner="other", select_next=True)


def test_claim_refuses_when_no_release_in_progress(tmp_repo_with_release: Path, fixed_owner: str):
    # No new_release() -> .release.json.in_progress is False (fixture default).
    # Release check happens before feature lookup, so no feature need exist.
    with pytest.raises(NoReleaseInProgressError):
        claim_feature(tmp_repo_with_release, "F-001", owner=fixed_owner)
