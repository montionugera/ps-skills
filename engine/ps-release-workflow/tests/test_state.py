"""Test flock-guarded state file operations."""
import json
import multiprocessing
import time
from pathlib import Path

import pytest

from lib.state import read_state, mutate_state, StateError, file_lock


def test_read_state_returns_dict(tmp_path: Path):
    f = tmp_path / "state.json"
    f.write_text('{"foo": 1}')
    assert read_state(f) == {"foo": 1}


def test_read_state_empty_file_returns_default(tmp_path: Path):
    f = tmp_path / "state.json"
    f.write_text("")
    assert read_state(f, default={}) == {}


def test_read_state_missing_file_returns_default(tmp_path: Path):
    assert read_state(tmp_path / "absent.json", default={}) == {}


def test_mutate_state_atomic_read_modify_write(tmp_path: Path):
    f = tmp_path / "state.json"
    f.write_text('{"a": 1}')
    def add_key(d):
        d["b"] = 2
        return d
    mutate_state(f, add_key)
    assert json.loads(f.read_text()) == {"a": 1, "b": 2}


def _worker(path_str, key):
    """Top-level for multiprocessing.Process."""
    from pathlib import Path
    from lib.state import mutate_state
    def add(d):
        d[key] = True
        time.sleep(0.05)  # hold lock long enough that the other worker must wait
        return d
    mutate_state(Path(path_str), add)


def test_mutate_state_concurrent_safe(tmp_path: Path):
    """Two processes mutating the same file shouldn't lose updates."""
    f = tmp_path / "state.json"
    f.write_text("{}")
    procs = [multiprocessing.Process(target=_worker, args=(str(f), f"k{i}")) for i in range(4)]
    for p in procs: p.start()
    for p in procs: p.join()
    result = json.loads(f.read_text())
    assert set(result.keys()) == {"k0", "k1", "k2", "k3"}


def _lock_worker(lock_target_str, out_str, worker_id):
    """Top-level for multiprocessing.Process: append id while holding file_lock."""
    from pathlib import Path
    from lib.state import file_lock
    with file_lock(Path(lock_target_str)):
        out = Path(out_str)
        # Append a "start" then sleep then "end" marker. If the lock works, no
        # other worker's markers may interleave between this worker's start/end.
        with open(out, "a") as fh:
            fh.write(f"{worker_id}:start\n")
        time.sleep(0.05)
        with open(out, "a") as fh:
            fh.write(f"{worker_id}:end\n")


def test_file_lock_concurrent_safe(tmp_path: Path):
    """N processes serialize on file_lock(same_path); no interleaving/lost writes."""
    lock_target = tmp_path / "release_worktree"  # the key, need not exist
    out = tmp_path / "out.log"
    out.write_text("")
    n = 4
    procs = [
        multiprocessing.Process(target=_lock_worker, args=(str(lock_target), str(out), i))
        for i in range(n)
    ]
    for p in procs: p.start()
    for p in procs: p.join()

    lines = [ln for ln in out.read_text().splitlines() if ln]
    # All N workers ran (2 markers each, none lost).
    assert len(lines) == 2 * n
    ids_started = {ln.split(":")[0] for ln in lines if ln.endswith(":start")}
    assert ids_started == {str(i) for i in range(n)}
    # Mutual exclusion: each worker's start must be immediately followed by its
    # own end (no other worker's marker interleaves while it holds the lock).
    for i in range(0, len(lines), 2):
        start_id, start_tag = lines[i].split(":")
        end_id, end_tag = lines[i + 1].split(":")
        assert start_tag == "start" and end_tag == "end"
        assert start_id == end_id, f"interleaving detected at {lines[i:i+2]}"


def test_mutate_state_callable_raises_does_not_corrupt(tmp_path: Path):
    f = tmp_path / "state.json"
    f.write_text('{"a": 1}')
    def bad(d):
        raise StateError("nope")
    with pytest.raises(StateError):
        mutate_state(f, bad)
    assert json.loads(f.read_text()) == {"a": 1}  # original preserved
