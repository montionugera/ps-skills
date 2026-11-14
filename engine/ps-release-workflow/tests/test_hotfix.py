"""hotfix.py creates the sibling worktree the guard requires, and nothing more."""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.hotfix import create_hotfix_worktree, HotfixTargetExistsError


def test_creates_sibling_worktree_on_a_hotfix_branch(tmp_repo_with_release):
    result = create_hotfix_worktree(tmp_repo_with_release, "mt5 idor")
    wt = Path(result["worktree"])

    assert wt.is_dir(), "worktree directory was not created"
    assert wt.parent == tmp_repo_with_release.parent, "worktree must be a SIBLING of the repo"
    assert wt.name == f"{tmp_repo_with_release.name}-hotfix-mt5-idor"
    assert result["branch"] == "hotfix/mt5-idor"

    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=wt,
                            capture_output=True, text=True).stdout.strip()
    assert branch == "hotfix/mt5-idor"


def test_worktree_is_not_inside_claude_worktrees(tmp_repo_with_release):
    """The guard blocks the main checkout by LOCATION, so the hotfix tree must be
    a sibling — not under .claude/worktrees/, which is the claimed-feature area."""
    result = create_hotfix_worktree(tmp_repo_with_release, "quick")
    assert ".claude/worktrees" not in result["worktree"]


def test_refuses_when_the_target_already_exists(tmp_repo_with_release):
    create_hotfix_worktree(tmp_repo_with_release, "dupe")
    with pytest.raises(HotfixTargetExistsError):
        create_hotfix_worktree(tmp_repo_with_release, "dupe")


def test_does_not_commit_or_install(tmp_repo_with_release):
    before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_repo_with_release,
                            capture_output=True, text=True).stdout
    result = create_hotfix_worktree(tmp_repo_with_release, "noop")
    after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_repo_with_release,
                           capture_output=True, text=True).stdout
    assert before == after, "hotfix must not commit anything"
    assert not (Path(result["worktree"]) / "node_modules").exists()


def test_hotfix_cli_hints_how_the_open_release_gets_the_hotfix(tmp_repo_in_release, capsys, monkeypatch):
    from scripts.hotfix import main
    monkeypatch.chdir(tmp_repo_in_release)
    monkeypatch.setattr(sys, "argv", ["hotfix", "cli-test"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "release/1.1 is in progress" in out
    assert "next psrw ship / psrw promote" in out
    assert "psrw sync-main" in out


def test_hotfix_cli_omits_the_release_hint_when_no_release(tmp_repo_with_release, capsys, monkeypatch):
    from scripts.hotfix import main
    monkeypatch.chdir(tmp_repo_with_release)
    monkeypatch.setattr(sys, "argv", ["hotfix", "no-rel-test"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "is in progress" not in out and "sync-main" not in out


# --- --cleanup ---------------------------------------------------------------
import scripts.hotfix as hotfix_mod


def _fake_gh(monkeypatch, state):
    real = hotfix_mod._run

    def run(cmd, cwd):
        if cmd[:3] == ["gh", "pr", "view"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{state}\n", stderr="")
        if cmd[:2] == ["git", "fetch"] or cmd[:3] == ["git", "ls-remote", "--exit-code"]:
            return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="")  # no remote
        return real(cmd, cwd)

    monkeypatch.setattr(hotfix_mod, "_run", run)


def test_cleanup_refuses_unless_pr_is_merged(tmp_repo_with_release, monkeypatch):
    create_hotfix_worktree(tmp_repo_with_release, "keepme")
    _fake_gh(monkeypatch, "OPEN")
    with pytest.raises(hotfix_mod.HotfixCleanupError):
        hotfix_mod.cleanup_hotfix(tmp_repo_with_release, "keepme")
    wt = tmp_repo_with_release.parent / f"{tmp_repo_with_release.name}-hotfix-keepme"
    assert wt.is_dir(), "nothing may be removed when the PR is not merged"


def test_cleanup_removes_worktree_and_branch_when_merged(tmp_repo_with_release, monkeypatch):
    create_hotfix_worktree(tmp_repo_with_release, "gone")
    _fake_gh(monkeypatch, "MERGED")
    done = hotfix_mod.cleanup_hotfix(tmp_repo_with_release, "gone")
    wt = tmp_repo_with_release.parent / f"{tmp_repo_with_release.name}-hotfix-gone"
    assert not wt.exists()
    branches = subprocess.run(["git", "branch", "--list", "hotfix/gone"], cwd=tmp_repo_with_release,
                              capture_output=True, text=True).stdout
    assert branches.strip() == ""
    assert any("worktree removed" in d for d in done)


def test_cleanup_keeps_a_dirty_worktree(tmp_repo_with_release, monkeypatch):
    result = create_hotfix_worktree(tmp_repo_with_release, "dirty")
    (Path(result["worktree"]) / "untracked.txt").write_text("x")
    (Path(result["worktree"]) / "tracked.txt").write_text("x")
    subprocess.run(["git", "add", "tracked.txt"], cwd=result["worktree"])
    _fake_gh(monkeypatch, "MERGED")
    with pytest.raises(hotfix_mod.HotfixCleanupError):
        hotfix_mod.cleanup_hotfix(tmp_repo_with_release, "dirty")
    assert Path(result["worktree"]).is_dir()
