"""guard_check: blocks code edits outside a claimed worktree owned by the session."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.guard_check import check_tool_call, ExitCode


def _make_claimed_worktree(tmp_repo_with_release: Path, owner: str) -> Path:
    """Helper: create a worktree with a working-feature.json marker."""
    from scripts.init_work_new_release import new_release
    from scripts.new_idea import new_idea
    from scripts.promote_idea_to_refined import promote_idea_to_refined
    from scripts.init_work_refined_backlog import claim_feature

    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="X")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea["id"])
    claim = claim_feature(tmp_repo_with_release, feat["id"], owner=owner)
    return Path(claim["worktree"])


def test_allows_edit_outside_workflow_repo(tmp_path: Path):
    """Edit on a path outside any ps-release-workflow repo → allow."""
    file_path = tmp_path / "random.py"
    assert check_tool_call({"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}) == ExitCode.ALLOW


def test_blocks_edit_on_main_when_inside_workflow_repo(tmp_repo_with_release: Path, fixed_owner: str):
    """Edit on a path in main checkout → block."""
    file_path = tmp_repo_with_release / "src" / "foo.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    assert check_tool_call({"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}) == ExitCode.BLOCK


def test_allows_edit_in_claimed_worktree_with_owner_match(tmp_repo_with_release: Path, fixed_owner: str):
    wt = _make_claimed_worktree(tmp_repo_with_release, owner=fixed_owner)
    file_path = wt / "src" / "foo.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    assert check_tool_call({"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}) == ExitCode.ALLOW


def test_blocks_edit_in_claimed_worktree_with_owner_mismatch(tmp_repo_with_release: Path, monkeypatch):
    wt = _make_claimed_worktree(tmp_repo_with_release, owner="owner-A")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "owner-B")
    file_path = wt / "src" / "foo.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    assert check_tool_call({"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}) == ExitCode.BLOCK


def test_bypasses_when_scripted_env_var_set(tmp_repo_with_release: Path, monkeypatch):
    """PS_RELEASE_WORKFLOW_SCRIPTED=1 lets toolkit scripts bypass the guard."""
    monkeypatch.setenv("PS_RELEASE_WORKFLOW_SCRIPTED", "1")
    file_path = tmp_repo_with_release / "src" / "foo.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    assert check_tool_call({"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}) == ExitCode.ALLOW


def test_allows_edit_on_legacy_worktree_with_warn(tmp_repo_with_release: Path, capsys):
    """Worktree without marker → legacy, allow but warn to stderr."""
    # Create a worktree the manual way (no marker).
    subprocess.run(
        ["git", "worktree", "add", "-b", "legacy/foo",
         str(tmp_repo_with_release / ".claude" / "worktrees" / "legacy-foo")],
        cwd=tmp_repo_with_release, check=True, capture_output=True,
    )
    file_path = tmp_repo_with_release / ".claude" / "worktrees" / "legacy-foo" / "src" / "foo.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    assert check_tool_call({"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}) == ExitCode.ALLOW
    captured = capsys.readouterr()
    assert "legacy" in captured.err.lower() or "marker" in captured.err.lower()


def test_ignores_non_code_tool_calls(tmp_repo_with_release: Path):
    """Read calls are never blocked."""
    assert check_tool_call({"tool_name": "Read", "tool_input": {"file_path": str(tmp_repo_with_release / "foo.py")}}) == ExitCode.ALLOW


def test_allows_edit_in_external_worktree_outside_claude_worktrees(tmp_repo_with_release: Path, tmp_path: Path, fixed_owner: str):
    """FIX #2: an ad-hoc linked worktree OUTSIDE .claude/worktrees/ in an opted-in
    repo must NOT be blocked (it's a linked worktree, not the main tree)."""
    sibling = tmp_path / "ext_foo"
    subprocess.run(
        ["git", "worktree", "add", "-b", "ext/foo", str(sibling)],
        cwd=tmp_repo_with_release, check=True, capture_output=True,
    )
    file_path = sibling / "src" / "foo.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    assert check_tool_call({"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}) == ExitCode.ALLOW


def test_allows_edit_in_release_worktree_silently(tmp_repo_with_release: Path, fixed_owner: str, capsys):
    """FIX #4: the toolkit-managed _release worktree is allowed with NO 'legacy' warning."""
    from scripts.init_work_new_release import new_release
    new_release(tmp_repo_with_release, version="1.1")
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    file_path = rel_wt / "src" / "foo.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    assert check_tool_call({"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}) == ExitCode.ALLOW
    captured = capsys.readouterr()
    assert "legacy" not in captured.err.lower()


def test_block_exit_code_is_2_so_claude_code_actually_blocks():
    """Claude Code PreToolUse only blocks on exit 2; exit 1/other are NON-blocking
    (the tool proceeds). BLOCK must therefore be 2 or the guard silently allows."""
    assert int(ExitCode.BLOCK) == 2
    assert int(ExitCode.ALLOW) == 0
