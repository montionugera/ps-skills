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
    # The harness exports CLAUDE_CODE_SESSION_ID. self_ids() reads it, so clear it by
    # default or every exact-equality assertion on self_ids() picks up the real session.
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
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
    # A bare `origin` remote: new_release/ship/promote fetch + push against it
    # (fetch_and_ff_main, release-branch push, finalize push). Without it every
    # remote op raises GitError. Kept local (bare repo) so tests stay offline.
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True, capture_output=True)
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
    subprocess.run(["git", "push", "origin", "main"], cwd=tmp_repo, check=True, capture_output=True)
    return tmp_repo


@pytest.fixture
def fixed_owner(monkeypatch) -> str:
    """Pins $CLAUDE_SESSION_ID to a stable value for the test."""
    owner = "test-owner-abc123"
    monkeypatch.setenv("CLAUDE_SESSION_ID", owner)
    return owner


@pytest.fixture
def tmp_repo_in_release(tmp_repo_with_release: Path) -> Path:
    """An opted-in temp repo with release/1.1 open and its _release worktree present."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.init_work_new_release import new_release
    new_release(tmp_repo_with_release)
    return tmp_repo_with_release


def _release_wt(repo: Path) -> Path:
    return repo / ".claude" / "worktrees" / "_release"


@pytest.fixture
def epic_repo_raw(tmp_repo_in_release: Path, fixed_owner: str) -> Path:
    """release/1.1 open; epic E-001 fanned out into I-001 'alpha' and I-002 'beta'.

    The slice specs are the untouched fanout skeletons and there is no
    scripts/precheck.sh, so `epic plan` must refuse this repo until both are fixed."""
    from scripts.epic import epic_fanout, epic_open
    epic_open(tmp_repo_in_release, "E")
    epic_fanout(tmp_repo_in_release, "E-001", ["alpha", "beta"])
    return tmp_repo_in_release


@pytest.fixture
def idea_spec():
    """Callable (repo, idea_id) -> Path of that idea's spec.md on release/<v>."""
    def path(repo: Path, idea_id: str) -> Path:
        from lib.slug import slugify
        folder = _release_wt(repo) / ".claude" / "idea_backlog"
        catalog = json.loads((folder / "_catalog.json").read_text())
        title = next(i["title"] for i in catalog if i["id"] == idea_id)
        return folder / f"{idea_id}-{slugify(title)}" / "spec.md"
    return path


@pytest.fixture
def epic_repo(epic_repo_raw: Path, idea_spec) -> Path:
    """epic_repo_raw plus real content in both slice specs and a passing precheck.sh,
    all committed on release/<v>. `epic plan` accepts this repo as-is."""
    from lib.git_ops import commit_all
    repo = epic_repo_raw
    for idea_id in ("I-001", "I-002"):
        idea_spec(repo, idea_id).write_text(f"# {idea_id}\n\nApproved design content.\n")
    script = _release_wt(repo) / "scripts" / "precheck.sh"
    script.parent.mkdir(exist_ok=True)
    script.write_text("#!/usr/bin/env bash\nexit 0\n")
    script.chmod(0o755)
    commit_all(_release_wt(repo), "test: fill slice specs, add precheck")
    return repo
