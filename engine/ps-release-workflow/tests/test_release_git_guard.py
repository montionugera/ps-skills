"""release_git_guard.py: hand-run git writes on release/<v> are refused."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parent.parent / "scripts" / "release_git_guard.py"


def _git(cwd: Path, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path):
    """Opted-in repo on main, with a _release worktree on release/1.0."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / ".release.json").write_text("{}")
    _git(r, "add", ".")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    _git(r, "branch", "release/1.0")
    rel = tmp_path / "_release"
    _git(r, "worktree", "add", "-q", str(rel), "release/1.0")
    return r, rel


def _run(command: str, cwd: Path, tool: str = "Bash"):
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": str(cwd)})
    return subprocess.run([sys.executable, str(GUARD)], input=payload, capture_output=True, text=True)


@pytest.mark.parametrize("command", [
    "git merge --no-ff feat/x",
    "git commit -m wip",
    "git cherry-pick abc123",
    "FOO=1 git reset --hard HEAD~1",
    "echo hi && git pull",
])
def test_blocks_writes_in_release_worktree(repo, command):
    _, rel = repo
    r = _run(command, rel)
    assert r.returncode == 2, r.stderr
    assert "psrw ship" in r.stderr


def test_blocks_cd_into_release_worktree(repo, tmp_path):
    _, rel = repo
    assert _run(f"cd {rel} && git merge --no-ff x < /dev/null", tmp_path).returncode == 2


def test_blocks_git_dash_c_into_release_worktree(repo, tmp_path):
    _, rel = repo
    assert _run(f"git -C {rel} merge x", tmp_path).returncode == 2


@pytest.mark.parametrize("command", [
    "git status",
    "git log --oneline -3",
    "git merge --abort",
    "git rebase --quit",
    "PSRW_ALLOW_RELEASE_GIT=1 git merge origin/main",
    "psrw ship",
    "git worktree remove ../x",
])
def test_allows_reads_cleanup_escape_and_psrw(repo, command):
    _, rel = repo
    assert _run(command, rel).returncode == 0


def test_allows_writes_on_other_branches(repo):
    r, _ = repo
    assert _run("git commit -m x", r).returncode == 0


def test_allows_release_branch_without_opt_in(tmp_path):
    r = tmp_path / "plain"
    r.mkdir()
    _git(r, "init", "-q", "-b", "release/2.0")
    assert _run("git commit -m x", r).returncode == 0


def test_ignores_other_tools_and_bad_input(repo):
    _, rel = repo
    assert _run("git merge x", rel, tool="Edit").returncode == 0
    bad = subprocess.run([sys.executable, str(GUARD)], input="not json", capture_output=True, text=True)
    assert bad.returncode == 0
