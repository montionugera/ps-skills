"""cleanup_legacy_worktrees: enumerate marker-less worktrees + interactive prompts."""
import json
import subprocess
from pathlib import Path

import pytest

from scripts.cleanup_legacy_worktrees import enumerate_legacy_worktrees, is_branch_merged_to_main


def test_enumerate_finds_marker_less_worktrees(tmp_repo_with_release: Path):
    # Create a legacy worktree (no marker).
    legacy = tmp_repo_with_release / ".claude" / "worktrees" / "legacy-feat"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "worktree", "add", "-b", "feat/legacy", str(legacy)],
                   cwd=tmp_repo_with_release, check=True, capture_output=True)
    found = enumerate_legacy_worktrees(tmp_repo_with_release)
    assert any(w["path"] == str(legacy) for w in found)


def test_enumerate_excludes_marked_worktrees(tmp_repo_with_release: Path, fixed_owner: str):
    """A worktree with working-feature.json marker is NOT legacy."""
    from scripts.init_work_new_release import new_release
    from scripts.new_idea import new_idea
    from scripts.promote_idea_to_refined import promote_idea_to_refined
    from scripts.init_work_refined_backlog import claim_feature
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="X")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea["id"], allow_empty_spec=True)
    claim = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    found = enumerate_legacy_worktrees(tmp_repo_with_release)
    assert all(claim["worktree"] not in w["path"] for w in found)


def test_is_branch_merged_to_main(tmp_repo_with_release: Path):
    """A branch fully merged into main is reported as merged."""
    # main HEAD is auto-merged into itself.
    assert is_branch_merged_to_main(tmp_repo_with_release, "main") is True
    # A new branch with extra commits is not merged.
    subprocess.run(["git", "branch", "feat/unmerged"], cwd=tmp_repo_with_release, check=True)
    subprocess.run(["git", "checkout", "feat/unmerged"], cwd=tmp_repo_with_release, check=True, capture_output=True)
    (tmp_repo_with_release / "x.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=tmp_repo_with_release, check=True)
    subprocess.run(["git", "commit", "-m", "x"], cwd=tmp_repo_with_release, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "main"], cwd=tmp_repo_with_release, check=True, capture_output=True)
    assert is_branch_merged_to_main(tmp_repo_with_release, "feat/unmerged") is False
