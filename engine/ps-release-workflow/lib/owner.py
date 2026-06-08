"""Owner ID resolution for cross-session worktree claims."""
import os
import uuid
from pathlib import Path


def resolve_owner_id() -> str:
    """Return a stable owner-id for this Claude session.

    Priority: $CLAUDE_SESSION_ID > ~/.cache/ps-release-workflow/session-id > generate+cache.
    """
    env = os.environ.get("CLAUDE_SESSION_ID")
    if env:
        return env

    home = Path(os.environ.get("HOME", str(Path.home())))
    cache = home / ".cache" / "ps-release-workflow" / "session-id"
    if cache.exists():
        return cache.read_text().strip()

    new_id = f"claude-{uuid.uuid4().hex[:8]}"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(new_id + "\n")
    return new_id
