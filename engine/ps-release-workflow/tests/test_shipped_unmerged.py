"""Shipped-but-unmerged detector: feat/F-NNN commits missing from release/<v>."""
import json
from pathlib import Path

from lib.shipped_unmerged import unmerged_commits
from scripts.status import collect_status, render_full
from tests._helpers import git
from tests.test_status import _refined_catalog_path, _setup_release_with_features


def _commit(repo: Path, branch: str, name: str) -> None:
    git(repo, "checkout", "-q", branch)
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)


def _plain_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    (repo / "base").write_text("base")
    git(repo, "add", "base")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "branch", "release/1.1")
    git(repo, "branch", "feat/F-001")
    return repo


def test_clean_branch_merged_is_zero(tmp_path: Path):
    assert unmerged_commits(_plain_repo(tmp_path), "1.1", "F-001") == 0


def test_branch_ahead_counts_commits(tmp_path: Path):
    repo = _plain_repo(tmp_path)
    _commit(repo, "feat/F-001", "a")
    _commit(repo, "feat/F-001", "b")
    assert unmerged_commits(repo, "1.1", "F-001") == 2


def test_missing_feature_branch_is_zero(tmp_path: Path):
    assert unmerged_commits(_plain_repo(tmp_path), "1.1", "F-999") == 0


def test_missing_release_branch_is_zero(tmp_path: Path):
    repo = _plain_repo(tmp_path)
    _commit(repo, "feat/F-001", "a")
    assert unmerged_commits(repo, "9.9", "F-001") == 0


def test_not_a_git_repo_does_not_crash(tmp_path: Path):
    assert unmerged_commits(tmp_path, "1.1", "F-001") == 0


def _ship_with_branch(repo: Path, fid: str, release_version: str) -> None:
    cat = _refined_catalog_path(repo)
    entries = json.loads(cat.read_text())
    for e in entries:
        if e["id"] == fid:
            e["status"], e["release_version"] = "shipped", release_version
    cat.write_text(json.dumps(entries, indent=2) + "\n")


def _extra_commit_on_feat(repo: Path, fid: str, name: str) -> None:
    """Add a commit to feat/<fid> by plumbing (the branch is checked out in its claim worktree)."""
    ref = f"refs/heads/feat/{fid}"
    sha = git(repo, "commit-tree", f"{ref}^{{tree}}", "-p", ref, "-m", name)
    git(repo, "update-ref", ref, sha)


def test_status_flags_current_release_shipped_ahead(tmp_repo_with_release: Path, fixed_owner: str):
    repo = tmp_repo_with_release
    feats = _setup_release_with_features(repo, fixed_owner)
    fid = feats[0]["id"]
    _ship_with_branch(repo, fid, "1.1")
    _extra_commit_on_feat(repo, fid, "late-fix.txt")
    st = collect_status(repo)
    row = next(f for f in st["features"] if f["id"] == fid)
    assert row["drift"] == f"shipped but 1 commit(s) on feat/{fid} not in release/1.1"
    assert fid in st["next"] and "release/1.1" in st["next"]
    assert "!! shipped but 1 commit(s)" in render_full(st)


def test_status_no_flag_when_shipped_branch_deleted(tmp_repo_with_release: Path, fixed_owner: str):
    repo = tmp_repo_with_release
    feats = _setup_release_with_features(repo, fixed_owner)
    fid = feats[0]["id"]
    _ship_with_branch(repo, fid, "1.1")
    git(repo, "update-ref", "-d", f"refs/heads/feat/{fid}")
    row = next(f for f in collect_status(repo)["features"] if f["id"] == fid)
    assert row["drift"] is None


def test_status_ignores_earlier_release_shipped(tmp_repo_with_release: Path, fixed_owner: str):
    """A feature shipped in an earlier (squash-merged) release is never flagged."""
    repo = tmp_repo_with_release
    feats = _setup_release_with_features(repo, fixed_owner)
    fid = feats[0]["id"]
    _ship_with_branch(repo, fid, "1.0")
    _extra_commit_on_feat(repo, fid, "late-fix.txt")  # branch ahead of release/1.1
    row = next(f for f in collect_status(repo)["features"] if f["id"] == fid)
    assert row["drift"] is None
