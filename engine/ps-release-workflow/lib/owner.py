"""Owner ID resolution for cross-session worktree claims."""
import os
import uuid
from pathlib import Path


def _cache_path() -> Path:
    home = Path(os.environ.get("HOME", str(Path.home())))
    return home / ".cache" / "ps-release-workflow" / "session-id"


def _read_cache() -> str | None:
    """Cached machine id, or None when the file is absent OR empty.

    An existing-but-empty cache file must never become the (empty) owner id —
    it is treated exactly like an absent file.
    """
    cache = _cache_path()
    try:
        cached = cache.read_text().strip()
    except OSError:
        return None
    return cached or None


def resolve_owner_id() -> str:
    """Return a stable owner-id for this Claude session.

    Priority: $CLAUDE_SESSION_ID > ~/.cache/ps-release-workflow/session-id > generate+cache.

    NOTE: this is a WRITE path (it may create the cache file). Read-only
    callers (the guard, status) must use self_ids(..., generate=False).

    The generate+cache step is race-safe: the new id is written to a temp file
    and atomically linked into place (os.link fails if the file already exists).
    A process that loses the race re-reads and adopts the winner's id instead of
    clobbering it.
    """
    env = os.environ.get("CLAUDE_SESSION_ID")
    if env:
        return env

    cached = _read_cache()
    if cached:
        return cached

    cache = _cache_path()
    new_id = f"claude-{uuid.uuid4().hex[:8]}"
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(f".session-id.{uuid.uuid4().hex}.tmp")
    tmp.write_text(new_id + "\n")
    try:
        os.link(tmp, cache)  # atomic create-if-absent
        return new_id
    except FileExistsError:
        winner = _read_cache()
        if winner:
            return winner  # lost the race: adopt the winner's id
        # The existing file is EMPTY (corrupt) — replace it atomically.
        os.replace(tmp, cache)
        return new_id
    finally:
        tmp.unlink(missing_ok=True)


def self_ids(payload_session_id: str | None = None, *, generate: bool = True) -> set[str]:
    """Every identity this session may be known by in worktree claim markers.

    Union of: the hook payload's `session_id` (the only reliably-real session id
    — $CLAUDE_SESSION_ID is not exported to child processes on all setups),
    $CLAUDE_SESSION_ID if set, $CLAUDE_CODE_SESSION_ID if set (the variable the
    harness actually exports in practice), and the machine-cached fallback id
    that resolve_owner_id() uses when neither env var is present (all
    historical claims were created with the cached id).

    generate=False (READ-ONLY mode, used by the guard and status): when no
    identity exists anywhere, return an EMPTY set instead of generating and
    persisting a new id — read paths must never write.
    """
    ids: set[str] = set()
    if payload_session_id:
        ids.add(payload_session_id)
    env = os.environ.get("CLAUDE_SESSION_ID")
    if env:
        ids.add(env)
    # The harness actually exports CLAUDE_CODE_SESSION_ID; CLAUDE_SESSION_ID is
    # unset in practice. self_ids() is a UNION, so adding this can only ever add
    # an identity — it can never orphan a claim created with the cached id.
    env_code = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if env_code:
        ids.add(env_code)
    # Read the cache directly: resolve_owner_id() short-circuits on the env
    # var, but the cached id must count as "self" regardless.
    cached = _read_cache()
    if cached:
        ids.add(cached)
    if not ids and generate:
        # Nothing known at all: generate + cache one (same as claim creation).
        ids.add(resolve_owner_id())
    return ids
