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


def test_hotfix_cli_prints_release_sync_hint(tmp_repo_in_release, capsys, monkeypatch):
    from scripts.hotfix import main
    monkeypatch.chdir(tmp_repo_in_release)
    monkeypatch.setattr(sys, "argv", ["hotfix", "cli-test"])
    ret = main()
    assert ret == 0
    captured = capsys.readouterr().out
    assert "8. release/1.1 is in progress" in captured
    assert "psrw sync-main" in captured


def test_hotfix_cli_omits_hint_when_no_release(tmp_repo_with_release, capsys, monkeypatch):
    from scripts.hotfix import main
    monkeypatch.chdir(tmp_repo_with_release)
    monkeypatch.setattr(sys, "argv", ["hotfix", "no-rel-test"])
    ret = main()
    assert ret == 0
    captured = capsys.readouterr().out
    assert "8. release/" not in captured

