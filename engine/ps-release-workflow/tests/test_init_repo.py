"""init_repo: opts a repo into ps-release-workflow + installs global routing rule."""
import json
from pathlib import Path

import pytest

from scripts.init_repo import init_repo, AlreadyInitializedError, ROUTING_MARKER


def test_creates_release_json(tmp_repo: Path):
    init_repo(tmp_repo)
    rel = json.loads((tmp_repo / ".release.json").read_text())
    assert rel == {"version": "1.0", "in_progress": False, "started_at": None, "started_by": None}


def test_creates_backlog_folders_and_catalogs(tmp_repo: Path):
    init_repo(tmp_repo)
    assert (tmp_repo / ".claude" / "idea_backlog" / "_catalog.json").read_text().strip() == "[]"
    assert (tmp_repo / ".claude" / "refined_backlog" / "_catalog.json").read_text().strip() == "[]"


def test_extends_gitignore(tmp_repo: Path):
    init_repo(tmp_repo)
    gi = (tmp_repo / ".gitignore").read_text()
    assert ".claude/state/" in gi
    assert ".claude/worktrees/" in gi


def test_installs_routing_convention_to_global_claude_md(tmp_repo: Path, monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "CLAUDE.md").write_text("# my rules\n\nfoo\n")
    init_repo(tmp_repo)
    content = (tmp_path / ".claude" / "CLAUDE.md").read_text()
    assert ROUTING_MARKER in content
    assert "ps-release-workflow routing convention" in content


def test_routing_install_idempotent(tmp_repo: Path, monkeypatch, tmp_path: Path):
    """Running init twice does not duplicate the routing section."""
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "CLAUDE.md").write_text("# my rules\n")
    init_repo(tmp_repo)
    first = (tmp_path / ".claude" / "CLAUDE.md").read_text()
    # Second init on a different repo — should not re-append.
    repo2 = tmp_repo.parent / "repo2"
    import subprocess
    repo2.mkdir()
    subprocess.run(["git", "init"], cwd=repo2, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=repo2, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo2, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo2, check=True)
    (repo2 / "README.md").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo2, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo2, check=True, capture_output=True)
    init_repo(repo2)
    second = (tmp_path / ".claude" / "CLAUDE.md").read_text()
    assert first == second  # untouched on second init


def test_refuses_if_already_initialized(tmp_repo: Path):
    init_repo(tmp_repo)
    with pytest.raises(AlreadyInitializedError):
        init_repo(tmp_repo)


def test_commits_the_opt_in(tmp_repo: Path):
    init_repo(tmp_repo)
    import subprocess
    log = subprocess.run(["git", "log", "--oneline"], cwd=tmp_repo, capture_output=True, text=True)
    assert "ps-release-workflow" in log.stdout.lower()
