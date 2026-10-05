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

LOCK_DIR = Path.home() / ".cache/psrw/gate-locks"
SLOTS = 2


def _lock_dir() -> Path:
    if LOCK_DIR != Path.home() / ".cache/psrw/gate-locks":
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


@contextlib.contextmanager
def gate_slot(label, poll=5.0, timeout=3600.0):
    lock_dir = _lock_dir()
    lock_dir.mkdir(parents=True, exist_ok=True)
    slots = _slots_from_env()
    deadline = time.monotonic() + timeout
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
        if time.monotonic() >= deadline:
            raise TimeoutError(f"no gate slot free after {timeout}s ({label})")
        if not announced:
            print(f"[gate-lock] {label}: waiting for a free slot (max {SLOTS} concurrent gates)", file=sys.stderr)
            announced = True
        time.sleep(poll)
