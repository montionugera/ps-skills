"""Test git subprocess wrappers."""
import subprocess
from pathlib import Path

import pytest

from lib.git_ops import (
    current_branch, branch_exists, is_dirty,
    commit_all, create_branch, GitError,
)


def test_current_branch(tmp_repo: Path):
    assert current_branch(tmp_repo) == "main"


def test_branch_exists(tmp_repo: Path):
    assert branch_exists(tmp_repo, "main")
    assert not branch_exists(tmp_repo, "nonexistent")


def test_is_dirty_clean(tmp_repo: Path):
    assert not is_dirty(tmp_repo)


def test_is_dirty_with_untracked(tmp_repo: Path):
    (tmp_repo / "newfile.txt").write_text("x")
    assert is_dirty(tmp_repo)


def test_is_dirty_with_staged(tmp_repo: Path):
    (tmp_repo / "newfile.txt").write_text("x")
    subprocess.run(["git", "add", "newfile.txt"], cwd=tmp_repo, check=True)
    assert is_dirty(tmp_repo)


def test_commit_all_creates_commit(tmp_repo: Path):
    (tmp_repo / "x.txt").write_text("y")
    commit_all(tmp_repo, "test commit")
    log = subprocess.run(["git", "log", "--oneline"], cwd=tmp_repo, capture_output=True, text=True)
    assert "test commit" in log.stdout


def test_create_branch(tmp_repo: Path):
    create_branch(tmp_repo, "feat/foo")
    assert branch_exists(tmp_repo, "feat/foo")
