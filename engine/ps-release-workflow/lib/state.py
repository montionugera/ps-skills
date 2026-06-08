"""Flock-guarded JSON state file operations.

flock is host-local. Multi-machine coordination is out of scope (use GitHub).
"""
import contextlib
import fcntl
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional


class StateError(Exception):
    """User-raised error from inside a mutate_state callback; preserves the original file."""


def _lock_path(target: Path) -> Path:
    """Return a stable lockfile path for `target`, kept OUTSIDE the repo tree.

    Keyed by a hash of the resolved absolute path so concurrent mutations of the
    same file serialize, while different files get independent locks. Living in a
    temp dir (not next to `target`) means no `.lock` sidecar ever lands beside a
    committed catalog and gets swept up by a backlog script's `git add -A`.
    """
    key = hashlib.sha1(str(target.resolve()).encode()).hexdigest()
    lockdir = Path(tempfile.gettempdir()) / "ps-release-workflow-locks"
    lockdir.mkdir(parents=True, exist_ok=True)
    return lockdir / f"{key}.lock"


@contextlib.contextmanager
def file_lock(target: Path):
    """Exclusive cross-process lock keyed by `target`'s resolved path.

    The lockfile lives in the same temp dir as mutate_state's locks (never beside
    `target`), so it serializes a multi-step critical section (e.g. a git merge in
    the shared _release worktree) without leaving artifacts in the repo tree.
    """
    lockpath = _lock_path(target)
    with open(lockpath, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def read_state(path: Path, default: Optional[Any] = None) -> Any:
    """Read a JSON state file. Returns `default` on missing or empty file."""
    if not path.exists():
        return default
    raw = path.read_text()
    if not raw.strip():
        return default
    return json.loads(raw)


def mutate_state(path: Path, fn: Callable[[Any], Any], default: Any = None) -> Any:
    """Atomically read → mutate → write a JSON state file under an exclusive flock.

    `fn` receives the current state (or `default` if missing) and must return the new state.
    If `fn` raises, the original file is left untouched.

    Returns the new state.
    """
    if default is None:
        default = {}
    path.parent.mkdir(parents=True, exist_ok=True)
    # Lock a stable lockfile (never replaced) so the exclusive lock survives the
    # atomic tmp.replace() of `path`; locking `path` itself would lock a
    # soon-to-be-orphaned inode and break mutual exclusion across procs. The
    # lockfile lives in a temp dir (not beside `path`) so no `.lock` sidecar is
    # ever committed by a backlog script's `git add -A`.
    lockpath = _lock_path(path)
    with open(lockpath, "a+") as lockfh:
        fcntl.flock(lockfh.fileno(), fcntl.LOCK_EX)
        try:
            raw = path.read_text() if path.exists() else ""
            current = json.loads(raw) if raw.strip() else default
            new = fn(current)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(new, indent=2) + "\n")
            tmp.replace(path)
            return new
        finally:
            fcntl.flock(lockfh.fileno(), fcntl.LOCK_UN)
