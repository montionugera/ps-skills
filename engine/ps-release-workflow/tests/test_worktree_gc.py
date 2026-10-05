"""Tests for lib/worktree_gc.py safety checks (S1-S8, L1-L3)."""
import json
import subprocess
from pathlib import Path

import pytest

from lib.worktree_gc import removable
from scripts.init_work_new_release import new_release
from scripts.new_idea import new_idea
from scripts.promote_idea_to_refined import promote_idea_to_refined
from scripts.init_work_refined_backlog import claim_feature


def test_identity_rejects_release_worktree(tmp_repo_with_release: Path):
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    ok, reason = removable(tmp_repo_with_release, rel_wt)
    assert not ok
    assert "S1: identity is _release worktree" in reason


def test_identity_rejects_main_repo(tmp_repo_with_release: Path):
    ok, reason = removable(tmp_repo_with_release, tmp_repo_with_release)
    assert not ok
    assert "S1: path is main repository checkout" in reason


def test_freshly_claimed_feature_with_uncommitted_edits_is_kept(tmp_repo_with_release: Path, fixed_owner: str):
    """F1 regression: Freshly claimed feature branched from main must NOT be removed."""
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="F1 test")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea["id"], allow_empty_spec=True)
    claim = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    wt = Path(claim["worktree"])

    # Uncommitted edits in freshly claimed worktree
    (wt / "work.txt").write_text("hello")

    ok, reason = removable(tmp_repo_with_release, wt, skip_liveness=True)
    assert not ok
    # Status is 'claimed', not 'shipped'/'promoted'
    assert "S2:" in reason or "S4:" in reason


def test_shipped_feature_clean_is_removable(tmp_repo_with_release: Path, fixed_owner: str):
    """F1 regression (other direction): Shipped feature with matched shipped_sha is removable."""
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="Shipped test")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea["id"], allow_empty_spec=True)
    claim = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    wt = Path(claim["worktree"])

    # Commit work
    (wt / "feature.txt").write_text("done")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "feat: done"], cwd=wt, check=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=wt).decode().strip()

    # Update catalog to status: shipped with shipped_sha
    cat_path = tmp_repo_with_release / ".claude" / "worktrees" / "_release" / ".claude" / "refined_backlog" / "_catalog.json"
    entries = json.loads(cat_path.read_text())
    for e in entries:
        if e["id"] == feat["id"]:
            e["status"] = "shipped"
            e["shipped_sha"] = head_sha
            e["release_version"] = "1.1"
    cat_path.write_text(json.dumps(entries, indent=2))

    ok, reason = removable(tmp_repo_with_release, wt, skip_liveness=True)
    assert ok
    assert reason == "removable"


def test_locked_worktree_is_kept(tmp_repo_with_release: Path, fixed_owner: str):
    """S7 check: Locked worktrees must never be removed."""
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="Locked test")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea["id"], allow_empty_spec=True)
    claim = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    wt = Path(claim["worktree"])

    # Commit work & update catalog
    (wt / "feature.txt").write_text("done")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "feat: done"], cwd=wt, check=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=wt).decode().strip()

    cat_path = tmp_repo_with_release / ".claude" / "worktrees" / "_release" / ".claude" / "refined_backlog" / "_catalog.json"
    entries = json.loads(cat_path.read_text())
    for e in entries:
        if e["id"] == feat["id"]:
            e["status"] = "shipped"
            e["shipped_sha"] = head_sha
    cat_path.write_text(json.dumps(entries, indent=2))

    # Lock worktree
    subprocess.run(["git", "worktree", "lock", "--reason", "pinned by user", str(wt)], cwd=tmp_repo_with_release, check=True)

    ok, reason = removable(tmp_repo_with_release, wt, skip_liveness=True)
    assert not ok
    assert "S7: worktree is locked" in reason


def test_non_allowlisted_ignored_file_is_kept(tmp_repo_with_release: Path, fixed_owner: str):
    """S5 check: Unallowlisted ignored files (.env.local, notes.txt) keep worktree."""
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="Ignored test")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea["id"], allow_empty_spec=True)
    claim = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    wt = Path(claim["worktree"])

    (wt / ".gitignore").write_text(".env.local\nnode_modules/\n.pytest_cache/\n")
    (wt / "feature.txt").write_text("done")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "feat: done"], cwd=wt, check=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=wt).decode().strip()

    cat_path = tmp_repo_with_release / ".claude" / "worktrees" / "_release" / ".claude" / "refined_backlog" / "_catalog.json"
    entries = json.loads(cat_path.read_text())
    for e in entries:
        if e["id"] == feat["id"]:
            e["status"] = "shipped"
            e["shipped_sha"] = head_sha
    cat_path.write_text(json.dumps(entries, indent=2))

    # Allowlisted ignored file (node_modules) should pass S5
    (wt / "node_modules").mkdir()
    (wt / "node_modules" / "dummy.js").write_text("console.log(1)")
    # Nested allowlisted directory should also pass S5
    nested_cache = wt / "packages" / "sub" / ".pytest_cache"
    nested_cache.mkdir(parents=True)
    (nested_cache / "cache.json").write_text("{}")
    ok, reason = removable(tmp_repo_with_release, wt, skip_liveness=True)
    assert ok, reason

    # Non-allowlisted ignored file (.env.local) must fail S5
    (wt / ".env.local").write_text("SECRET=123")
    ok, reason = removable(tmp_repo_with_release, wt, skip_liveness=True)
    assert not ok
    assert "S5: non-allowlisted ignored file present" in reason


def test_shipped_feature_with_post_ship_commits_is_kept(tmp_repo_with_release: Path, fixed_owner: str):
    """S3 check: Extra commits made after shipping keep worktree."""
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="Post-ship commit test")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea["id"], allow_empty_spec=True)
    claim = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    wt = Path(claim["worktree"])

    (wt / "feature.txt").write_text("v1")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "feat: v1"], cwd=wt, check=True)
    shipped_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=wt).decode().strip()

    cat_path = tmp_repo_with_release / ".claude" / "worktrees" / "_release" / ".claude" / "refined_backlog" / "_catalog.json"
    entries = json.loads(cat_path.read_text())
    for e in entries:
        if e["id"] == feat["id"]:
            e["status"] = "shipped"
            e["shipped_sha"] = shipped_sha
    cat_path.write_text(json.dumps(entries, indent=2))

    # Extra commit made after shipping
    (wt / "extra.txt").write_text("extra")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "feat: extra"], cwd=wt, check=True)

    ok, reason = removable(tmp_repo_with_release, wt, skip_liveness=True)
    assert not ok
    assert "S3: worktree HEAD has 1 unpushed/unshipped commit(s)" in reason
