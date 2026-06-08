"""Test repo root discovery + .release.json detection."""
import json
import subprocess
from pathlib import Path

import pytest

from lib.repo import find_repo_root, is_ps_release_workflow_repo, RepoNotFoundError


def test_find_repo_root_at_root(tmp_repo: Path):
    assert find_repo_root(tmp_repo) == tmp_repo


def test_find_repo_root_from_subdir(tmp_repo: Path):
    sub = tmp_repo / "a" / "b"
    sub.mkdir(parents=True)
    assert find_repo_root(sub) == tmp_repo


def test_find_repo_root_outside_git_raises(tmp_path: Path):
    with pytest.raises(RepoNotFoundError):
        find_repo_root(tmp_path)


def test_is_ps_release_workflow_repo_false_when_no_release_json(tmp_repo: Path):
    assert not is_ps_release_workflow_repo(tmp_repo)


def test_is_ps_release_workflow_repo_true_when_release_json_present(tmp_repo_with_release: Path):
    assert is_ps_release_workflow_repo(tmp_repo_with_release)
