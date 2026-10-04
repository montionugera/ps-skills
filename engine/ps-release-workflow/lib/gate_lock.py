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

LOCK_DIR = Path(os.environ.get("PSRW_GATE_LOCK_DIR", Path.home() / ".cache/psrw/gate-locks"))


def _slots_from_env():
    try:
        return max(1, int(os.environ.get("PSRW_GATE_SLOTS", "2")))
    except ValueError:
        return 2


SLOTS = _slots_from_env()


@contextlib.contextmanager
def gate_slot(label, poll=5.0, timeout=3600.0):
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    announced = False
    while True:
        for i in range(SLOTS):
            fd = os.open(LOCK_DIR / f"slot{i}.lock", os.O_CREAT | os.O_RDWR)
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
