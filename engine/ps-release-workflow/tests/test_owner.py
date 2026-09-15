"""Owner ID resolution: $CLAUDE_SESSION_ID > cache file > fresh-generated."""
import os
from pathlib import Path

from lib.owner import resolve_owner_id, self_ids


def test_uses_env_var_when_set(monkeypatch):
    monkeypatch.setenv("CLAUDE_SESSION_ID", "explicit-owner-xyz")
    assert resolve_owner_id() == "explicit-owner-xyz"


def test_falls_back_to_cache_file(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    cache = tmp_path / ".cache" / "ps-release-workflow" / "session-id"
    cache.parent.mkdir(parents=True)
    cache.write_text("cached-owner-456\n")
    assert resolve_owner_id() == "cached-owner-456"


def test_generates_and_caches_when_neither_present(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    owner = resolve_owner_id()
    assert owner.startswith("claude-")
    cache = tmp_path / ".cache" / "ps-release-workflow" / "session-id"
    assert cache.read_text().strip() == owner


def test_generated_owner_is_stable_within_process(monkeypatch, tmp_path):
    """Two calls in the same process return the same owner."""
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    o1 = resolve_owner_id()
    o2 = resolve_owner_id()
    assert o1 == o2


def test_lost_creation_race_adopts_winners_id(monkeypatch, tmp_path):
    """If another process wins the create race between our existence check and
    our write, we must adopt the winner's id, not clobber it with our own."""
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    cache = tmp_path / ".cache" / "ps-release-workflow" / "session-id"
    cache.parent.mkdir(parents=True)
    cache.write_text("claude-winner1\n")

    # Simulate the race window: the initial existence check saw no file
    # (the winner had not written yet), but by write time the file exists.
    real_exists = Path.exists
    monkeypatch.setattr(
        Path, "exists",
        lambda self: False if self == cache else real_exists(self),
    )
    assert resolve_owner_id() == "claude-winner1"
    monkeypatch.undo()
    # Winner's file must be untouched.
    assert cache.read_text().strip() == "claude-winner1"


def test_self_ids_includes_payload_env_and_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    cache = tmp_path / ".cache" / "ps-release-workflow" / "session-id"
    cache.parent.mkdir(parents=True)
    cache.write_text("claude-cached1\n")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "env-id-1")
    ids = self_ids(payload_session_id="payload-id-1")
    assert {"payload-id-1", "env-id-1", "claude-cached1"} <= ids


def test_self_ids_without_payload_or_env(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    cache = tmp_path / ".cache" / "ps-release-workflow" / "session-id"
    cache.parent.mkdir(parents=True)
    cache.write_text("claude-cached2\n")
    assert self_ids() == {"claude-cached2"}
    assert self_ids(payload_session_id=None) == {"claude-cached2"}


# ── M3: read-only identity path (guard + status must never write) ──────────


def test_self_ids_generate_false_returns_empty_set_without_writing(monkeypatch, tmp_path):
    """generate=False with no identity anywhere → empty set, and the cache file
    must NOT be created (read paths promise to be read-only)."""
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    cache = tmp_path / ".cache" / "ps-release-workflow" / "session-id"
    assert self_ids(generate=False) == set()
    assert not cache.exists()
    assert not cache.parent.exists()  # not even the directory


def test_self_ids_generate_false_still_reads_existing_identities(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAUDE_SESSION_ID", "env-id-9")
    cache = tmp_path / ".cache" / "ps-release-workflow" / "session-id"
    cache.parent.mkdir(parents=True)
    cache.write_text("claude-cached9\n")
    assert self_ids(payload_session_id="payload-9", generate=False) == {
        "payload-9", "env-id-9", "claude-cached9",
    }


def test_resolve_owner_id_treats_empty_cache_file_as_absent(monkeypatch, tmp_path):
    """An existing-but-empty cache file must not become the (empty) owner id —
    it is regenerated as if absent."""
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    cache = tmp_path / ".cache" / "ps-release-workflow" / "session-id"
    cache.parent.mkdir(parents=True)
    cache.write_text("")
    owner = resolve_owner_id()
    assert owner.startswith("claude-")
    assert cache.read_text().strip() == owner


def test_self_ids_ignores_empty_cache_file(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    cache = tmp_path / ".cache" / "ps-release-workflow" / "session-id"
    cache.parent.mkdir(parents=True)
    cache.write_text("\n")
    assert self_ids(generate=False) == set()
    assert cache.read_text() == "\n"  # untouched


# ── Task 15: the harness exports CLAUDE_CODE_SESSION_ID, not CLAUDE_SESSION_ID ──


def test_self_ids_includes_claude_code_session_id(monkeypatch, tmp_path):
    """CLAUDE_CODE_SESSION_ID is what the harness actually sets; the old code read
    only CLAUDE_SESSION_ID, which is unset in practice."""
    from lib.owner import self_ids
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "harness-abc")
    ids = self_ids(generate=False)
    assert "harness-abc" in ids


def test_self_ids_is_union_never_replacement(monkeypatch):
    """Adding an identity must never REMOVE the cached one — that would orphan
    every existing claim marker."""
    from lib.owner import self_ids, resolve_owner_id
    cached = resolve_owner_id()          # creates/reads the cache in the isolated HOME
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "harness-xyz")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "legacy-env")
    ids = self_ids(payload_session_id="payload-1", generate=False)
    assert {"harness-xyz", "legacy-env", "payload-1", cached} <= ids


def test_resolve_owner_id_ignores_claude_code_session_id(monkeypatch):
    """The WRITE path must not change: new claims keep using the cached id, or
    CLAUDE_SESSION_ID if set. Otherwise resuming your own worktree would break."""
    from lib.owner import resolve_owner_id
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "harness-should-be-ignored")
    assert resolve_owner_id() != "harness-should-be-ignored"
