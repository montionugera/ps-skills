import threading

import pytest

from lib import gate_lock


def test_second_holder_times_out_when_only_one_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(gate_lock, "LOCK_DIR", tmp_path)
    monkeypatch.setattr(gate_lock, "SLOTS", 1)
    held = threading.Event()
    release = threading.Event()

    def holder():
        with gate_lock.gate_slot("holder"):
            held.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    assert held.wait(5)
    with pytest.raises(TimeoutError):
        with gate_lock.gate_slot("waiter", poll=0.05, timeout=0.3):
            pass
    release.set()
    t.join()


def test_slot_is_reusable_after_release(tmp_path, monkeypatch):
    monkeypatch.setattr(gate_lock, "LOCK_DIR", tmp_path)
    monkeypatch.setattr(gate_lock, "SLOTS", 1)
    with gate_lock.gate_slot("a"):
        pass
    with gate_lock.gate_slot("b", timeout=1):
        pass


def test_two_slots_allow_two_holders(tmp_path, monkeypatch):
    monkeypatch.setattr(gate_lock, "LOCK_DIR", tmp_path)
    monkeypatch.setattr(gate_lock, "SLOTS", 2)
    with gate_lock.gate_slot("a") as a:
        with gate_lock.gate_slot("b", timeout=1) as b:
            assert {a, b} == {0, 1}
