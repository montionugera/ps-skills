"""Machine-wide counting lock so only N heavy gates run at once.

flock is released by the kernel when the process dies, so a crashed gate
never leaves a stale lock.
"""
import contextlib
import fcntl
import os
import sys
import time
from pathlib import Path

_DEFAULT_LOCK_DIR = Path.home() / ".cache/psrw/gate-locks"
LOCK_DIR = _DEFAULT_LOCK_DIR
SLOTS = 2
DEFAULT_TIMEOUT = 120.0


def _lock_dir() -> Path:
    if LOCK_DIR != _DEFAULT_LOCK_DIR:
        return Path(LOCK_DIR)
    env_dir = os.environ.get("PSRW_GATE_LOCK_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".cache/psrw/gate-locks"


def _slots_from_env():
    if SLOTS != 2:
        return SLOTS
    try:
        return max(1, int(os.environ.get("PSRW_GATE_SLOTS", str(SLOTS))))
    except ValueError:
        return 2


def _timeout_from_env(timeout=None) -> float:
    if timeout is not None:
        return float(timeout)
    raw = os.environ.get("PSRW_GATE_LOCK_TIMEOUT")
    if raw:
        try:
            return max(0.1, float(raw))
        except ValueError:
            pass
    return DEFAULT_TIMEOUT


def _active_holders(lock_dir: Path, slots: int) -> str:
    holders = []
    for i in range(slots):
        p = lock_dir / f"slot{i}.lock"
        try:
            txt = p.read_text(encoding="utf-8", errors="replace").strip()
            if txt:
                holders.append(f"slot{i}={txt}")
        except OSError:
            pass
    return ", ".join(holders) if holders else "unknown"


@contextlib.contextmanager
def gate_slot(label, poll=5.0, timeout=None):
    lock_dir = _lock_dir()
    lock_dir.mkdir(parents=True, exist_ok=True)
    slots = _slots_from_env()
    effective_timeout = _timeout_from_env(timeout)
    deadline = time.monotonic() + effective_timeout
    announced = False
    while True:
        for i in range(slots):
            fd = os.open(lock_dir / f"slot{i}.lock", os.O_CREAT | os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                continue
            except BaseException:
                os.close(fd)
                raise
            try:
                os.ftruncate(fd, 0)
                os.write(fd, f"{os.getpid()} {label}\n".encode())
                yield i
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            return
        holders = _active_holders(lock_dir, slots)
        if time.monotonic() >= deadline:
            raise TimeoutError(f"no gate slot free after {effective_timeout}s ({label}); active holders: {holders}")
        if not announced:
            print(
                f"[gate-lock] {label}: waiting for a free slot (max {slots} concurrent gates; active: {holders})",
                file=sys.stderr,
            )
            announced = True
        time.sleep(poll)
