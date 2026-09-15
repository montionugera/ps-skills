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


# --- Fix #1: NotebookEdit sends notebook_path, not file_path ---

def test_blocks_notebook_edit_on_main_checkout(tmp_repo_with_release: Path, fixed_owner: str):
    """NotebookEdit payloads carry `notebook_path`; the guard must still see them."""
    nb = tmp_repo_with_release / "analysis.ipynb"
    assert check_tool_call(
        {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": str(nb)}}
    ) == ExitCode.BLOCK


# --- Fix #2: self-identity set (payload session_id / env / cached id) ---

def test_allows_worktree_when_payload_session_id_matches_owner(tmp_repo_with_release: Path, monkeypatch):
    """CLAUDE_SESSION_ID is not exported to hook children, but the hook payload
    carries a real `session_id` — a marker owned by that id must be editable."""
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    wt = _make_claimed_worktree(tmp_repo_with_release, owner="payload-sess-123")
    file_path = wt / "src" / "foo.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    call = {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(file_path)},
        "session_id": "payload-sess-123",
    }
    assert check_tool_call(call) == ExitCode.ALLOW


def test_allows_worktree_when_cached_id_matches_owner(tmp_repo_with_release: Path, monkeypatch):
    """Claims created with the machine-cached id stay editable even when the
    payload carries a different (real) session_id — backward compatibility."""
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    from lib.owner import resolve_owner_id
    cached = resolve_owner_id()  # generates + caches under the isolated HOME
    wt = _make_claimed_worktree(tmp_repo_with_release, owner=cached)
    file_path = wt / "src" / "foo.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    call = {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(file_path)},
        "session_id": "totally-different-payload-id",
    }
    assert check_tool_call(call) == ExitCode.ALLOW


def test_blocks_worktree_when_no_self_identity_matches(tmp_repo_with_release: Path, monkeypatch, capsys):
    """True mismatch: owner differs from payload id, env id, and cached id → block."""
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    wt = _make_claimed_worktree(tmp_repo_with_release, owner="owner-A")
    file_path = wt / "src" / "foo.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    call = {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(file_path)},
        "session_id": "owner-B",
    }
    assert check_tool_call(call) == ExitCode.BLOCK
    err = capsys.readouterr().err
    # Fix #4: the block message must offer BOTH recovery paths.
    assert "claim --resume" in err
    assert "claim --next" in err


# --- M3: the guard is a READ path — it must never write the identity cache ---

def test_guard_never_writes_identity_cache(tmp_repo_with_release: Path, monkeypatch, tmp_path):
    """With no identity anywhere (no payload id, no env, no cache), the guard
    must NOT generate + persist a session id as a side effect — it judges with
    an empty identity set (anonymous → mismatch → block) and stays read-only."""
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    home = Path(os.environ["HOME"])  # isolated per-test HOME from conftest
    cache = home / ".cache" / "ps-release-workflow" / "session-id"
    wt = _make_claimed_worktree(tmp_repo_with_release, owner="owner-A")
    # Setup (new_release) legitimately generates an id — claims are a WRITE
    # path. Wipe it so the guard run below starts identity-less.
    cache.unlink(missing_ok=True)
    file_path = wt / "src" / "foo.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    assert check_tool_call(
        {"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}
    ) == ExitCode.BLOCK
    assert not cache.exists(), "guard wrote the identity cache — read path must not write"


# --- Fix #3: fail-open crash handling in main() ---

def test_main_malformed_stdin_allows_with_warning(monkeypatch, capsys):
    import io
    from scripts import guard_check
    monkeypatch.setattr(sys, "stdin", io.StringIO("{this is not json"))
    assert guard_check.main() == 0
    assert capsys.readouterr().err.strip() != ""


def test_main_crash_after_target_known_blocks_in_workflow_repo(tmp_repo_with_release: Path, monkeypatch, capsys):
    import io
    from scripts import guard_check
    file_path = tmp_repo_with_release / "src" / "foo.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))

    def boom(_):
        raise RuntimeError("injected crash")

    monkeypatch.setattr(guard_check, "check_tool_call", boom)
    assert guard_check.main() == 2
    err = capsys.readouterr().err
    assert "guard crashed" in err
    assert "injected crash" in err


def test_main_crash_outside_workflow_repo_allows_with_warning(tmp_path: Path, monkeypatch, capsys):
    import io
    from scripts import guard_check
    file_path = tmp_path / "plain" / "foo.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))

    def boom(_):
        raise RuntimeError("injected crash")

    monkeypatch.setattr(guard_check, "check_tool_call", boom)
    assert guard_check.main() == 0
    assert "injected crash" in capsys.readouterr().err


def test_main_crash_before_target_known_allows_with_warning(monkeypatch, capsys):
    import io
    from scripts import guard_check
    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "/nowhere/foo.py"}})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))

    def boom(_):
        raise RuntimeError("crash before target resolution")

    monkeypatch.setattr(guard_check, "_find_target_path", boom)
    assert guard_check.main() == 0
    assert "crash before target resolution" in capsys.readouterr().err
