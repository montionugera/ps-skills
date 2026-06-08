"""Shared pytest fixtures for ps-release-workflow tests."""
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch) -> Path:
    """Point HOME at a fresh empty dir for EVERY test.

    Without this, tests that call init_repo() without setting HOME would read and
    APPEND to the developer's real ~/.claude/CLAUDE.md (init_repo installs the
    routing convention there). This guard makes that impossible: by default HOME
    is an empty temp dir with no ~/.claude/CLAUDE.md, so the install step no-ops.
    Tests that need a specific CLAUDE.md set HOME themselves and override this.
    """
    home = tmp_path / "_home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """A temp directory initialized as a git repo with an initial commit."""
    repo = tmp_path / "tmp_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("test\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    return repo


@pytest.fixture
def tmp_repo_with_release(tmp_repo: Path) -> Path:
    """A temp repo that has been opted into ps-release-workflow (`.release.json` present)."""
    (tmp_repo / ".release.json").write_text(json.dumps({
        "version": "1.0",
        "in_progress": False,
        "started_at": None,
        "started_by": None,
    }))
    (tmp_repo / ".claude").mkdir()
    (tmp_repo / ".claude" / "idea_backlog").mkdir()
    (tmp_repo / ".claude" / "idea_backlog" / "_catalog.json").write_text("[]")
    (tmp_repo / ".claude" / "refined_backlog").mkdir()
    (tmp_repo / ".claude" / "refined_backlog" / "_catalog.json").write_text("[]")
    (tmp_repo / ".claude" / "state").mkdir()
    (tmp_repo / ".claude" / "state" / "claims.json").write_text("{}")
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "opt in"], cwd=tmp_repo, check=True, capture_output=True)
    return tmp_repo


@pytest.fixture
def fixed_owner(monkeypatch) -> str:
    """Pins $CLAUDE_SESSION_ID to a stable value for the test."""
    owner = "test-owner-abc123"
    monkeypatch.setenv("CLAUDE_SESSION_ID", owner)
    return owner
