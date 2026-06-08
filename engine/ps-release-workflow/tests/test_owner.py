"""Owner ID resolution: $CLAUDE_SESSION_ID > cache file > fresh-generated."""
import os
from pathlib import Path

from lib.owner import resolve_owner_id


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
