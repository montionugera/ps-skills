"""Opt-in Gate 1 pass cache (lib/gate_cache.py, wired into _run_precheck)."""
import json
import subprocess
from pathlib import Path

import pytest

from lib import gate_cache
from scripts import ship_current_work_to_release as ship

HOUR = 3600.0


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def _commit_all(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def _write_gate(repo: Path, counter: Path, rcfile: Path, rel: str = "scripts/precheck.sh") -> None:
    """A precheck that appends to `counter` (outside the tree) and exits with rcfile's value."""
    sh = repo / rel
    sh.parent.mkdir(parents=True, exist_ok=True)
    sh.write_text(f"#!/bin/sh\necho run >> {counter}\nexit $(cat {rcfile})\n")
    sh.chmod(0o755)


def _release_json(repo: Path, **extra) -> None:
    (repo / ".release.json").write_text(json.dumps(
        {"version": "1.0", "in_progress": False, **extra}))


class Gate:
    """A committed, cache-enabled repo whose precheck counts its real runs."""

    def __init__(self, repo: Path, tmp_path: Path):
        self.repo = repo
        self.counter = tmp_path / "runs.txt"
        self.rcfile = tmp_path / "rc.txt"
        self.rcfile.write_text("0")
        self.state = repo / ".claude" / "state" / "gate-pass-cache.json"
        (repo / ".gitignore").write_text(".claude/state/\n")
        _release_json(repo, gate_cache={"enabled": True, "ttl_hours": 24})
        _write_gate(repo, self.counter, self.rcfile)
        _commit_all(repo, "gate")

    @property
    def runs(self) -> int:
        return len(self.counter.read_text().split()) if self.counter.exists() else 0

    def set_rc(self, rc: int) -> None:
        self.rcfile.write_text(str(rc))

    def records(self) -> dict:
        return json.loads(self.state.read_text())["entries"]

    def run(self, tree: Path | None = None) -> int | None:
        return ship._run_precheck(tree or self.repo)


@pytest.fixture
def gate(tmp_repo: Path, tmp_path: Path, monkeypatch) -> Gate:
    monkeypatch.delenv("PSRW_GATE_CACHE", raising=False)
    return Gate(tmp_repo, tmp_path)


@pytest.fixture
def clock(monkeypatch):
    """Controllable gate_cache clock."""
    t = {"now": 1_800_000_000.0}
    monkeypatch.setattr(gate_cache, "_now", lambda: t["now"])
    return t


# ── miss -> run -> pass -> record, then HIT ────────────────────────────────────


def test_miss_runs_gate_and_records_the_pass(gate: Gate, clock):
    assert gate.run() == 0
    assert gate.runs == 1
    recs = gate.records()
    assert len(recs) == 1
    rec = next(iter(recs.values()))
    assert rec["tree"] == _git(gate.repo, "rev-parse", "HEAD^{tree}")
    assert len(rec["gate_hash"]) == 64
    assert rec["passed_at"] and rec["version"] == gate_cache.SCHEMA_VERSION


def test_second_call_on_identical_tree_hits_and_skips(gate: Gate, clock, capsys):
    gate.run()
    capsys.readouterr()
    clock["now"] += 90
    assert gate.run() == 0
    assert gate.runs == 1, "a HIT must not re-run the precheck"
    tree8 = _git(gate.repo, "rev-parse", "HEAD^{tree}")[:8]
    assert (f"gate cache HIT (tree {tree8}, passed 1m ago) — skipping precheck"
            in capsys.readouterr().out)


def test_hit_is_shared_across_worktrees_of_the_same_tree(gate: Gate, clock, tmp_path):
    """Gate 1 runs in the feature worktree then the _release worktree: the cache is
    keyed by tree content, not by checkout path."""
    gate.run()
    wt = tmp_path / "wt2"
    _git(gate.repo, "worktree", "add", "-q", "--detach", str(wt), "HEAD")
    assert gate.run(wt) == 0
    assert gate.runs == 1


def test_changed_tree_misses(gate: Gate, clock):
    gate.run()
    (gate.repo / "new.txt").write_text("x\n")
    _commit_all(gate.repo, "change")
    gate.run()
    assert gate.runs == 2
    assert len(gate.records()) == 2


def test_changed_precheck_contents_misses_on_the_same_tree(tmp_repo: Path, tmp_path, clock, monkeypatch):
    """Gate script is gitignored => editing it leaves HEAD^{tree} AND status unchanged;
    only the gate hash can invalidate the record."""
    monkeypatch.delenv("PSRW_GATE_CACHE", raising=False)
    (tmp_repo / ".gitignore").write_text(".claude/state/\nci/local.sh\n")
    _release_json(tmp_repo, hooks={"precheck": "ci/local.sh"},
                  gate_cache={"enabled": True})
    _commit_all(tmp_repo, "cfg")
    counter, rcfile = tmp_path / "runs.txt", tmp_path / "rc.txt"
    rcfile.write_text("0")
    _write_gate(tmp_repo, counter, rcfile, rel="ci/local.sh")

    assert ship._run_precheck(tmp_repo) == 0
    assert ship._run_precheck(tmp_repo) == 0
    assert len(counter.read_text().split()) == 1          # HIT
    with (tmp_repo / "ci" / "local.sh").open("a") as fh:
        fh.write("# edited gate\n")
    assert ship._run_precheck(tmp_repo) == 0
    assert len(counter.read_text().split()) == 2          # MISS: gate changed


def test_gate_hash_depends_on_contents_and_relative_path_not_location(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        (d / "scripts").mkdir(parents=True)
        (d / "scripts" / "precheck.sh").write_text("same\n")
    assert (gate_cache.gate_hash(a, a / "scripts" / "precheck.sh")
            == gate_cache.gate_hash(b, b / "scripts" / "precheck.sh"))
    (b / "scripts" / "precheck.sh").write_text("different\n")
    assert (gate_cache.gate_hash(a, a / "scripts" / "precheck.sh")
            != gate_cache.gate_hash(b, b / "scripts" / "precheck.sh"))
    (a / "other.sh").write_text("same\n")
    assert (gate_cache.gate_hash(a, a / "scripts" / "precheck.sh")
            != gate_cache.gate_hash(a, a / "other.sh"))


# ── failures ───────────────────────────────────────────────────────────────────


def test_fail_is_never_cached(gate: Gate, clock):
    gate.set_rc(1)
    assert gate.run() == 1
    assert not gate.state.exists() or gate.records() == {}
    assert gate.run() == 1
    assert gate.runs == 2, "a FAIL must not produce a HIT"


def test_fail_clears_a_stale_pass_record(gate: Gate, clock, monkeypatch):
    gate.run()
    assert len(gate.records()) == 1
    gate.set_rc(1)
    monkeypatch.setenv("PSRW_GATE_CACHE", "off")          # force a real run
    assert gate.run() == 1
    assert gate.records() == {}
    monkeypatch.delenv("PSRW_GATE_CACHE")
    assert gate.run() == 1
    assert gate.runs == 3, "the cleared record must not hit"


def test_gate_exception_is_not_cached(gate: Gate, clock):
    (gate.repo / "scripts" / "precheck.sh").write_text("#!/nonexistent/interpreter\n")
    _commit_all(gate.repo, "unrunnable gate")
    with pytest.raises(OSError):
        gate.run()
    assert not gate.state.exists() or gate.records() == {}


# ── TTL ────────────────────────────────────────────────────────────────────────


def test_record_expires_after_ttl(gate: Gate, clock):
    gate.run()
    clock["now"] += 24 * HOUR - 1
    gate.run()
    assert gate.runs == 1
    clock["now"] += 2
    gate.run()
    assert gate.runs == 2, "past the 24h TTL the record must be ignored"


def test_ttl_hours_is_configurable(gate: Gate, clock):
    _release_json(gate.repo, gate_cache={"enabled": True, "ttl_hours": 0.5})
    _commit_all(gate.repo, "ttl")
    gate.run()
    clock["now"] += 0.4 * HOUR
    gate.run()
    assert gate.runs == 1
    clock["now"] += 0.2 * HOUR
    gate.run()
    assert gate.runs == 2


def test_future_dated_record_is_not_trusted(gate: Gate, clock):
    gate.run()
    clock["now"] -= HOUR                                   # clock went backwards
    gate.run()
    assert gate.runs == 2


# ── opt-in ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("cfg", [
    None,                                                  # block absent
    {"enabled": False, "ttl_hours": 24},
    {"ttl_hours": 24},                                     # enabled missing
    {"enabled": "true"},                                   # not a real bool
    {"enabled": 1},
    "yes",                                                 # block of the wrong type
])
def test_not_opted_in_always_runs_and_writes_nothing(gate: Gate, clock, cfg):
    extra = {} if cfg is None else {"gate_cache": cfg}
    _release_json(gate.repo, **extra)
    _commit_all(gate.repo, "no cache")
    gate.run()
    gate.run()
    assert gate.runs == 2
    assert not gate.state.exists()


def test_invalid_ttl_falls_back_to_default(gate: Gate, clock):
    for bad in ("soon", -1, 0, None, True):
        assert gate_cache.load_config(_cfg_tree(gate.repo, {"enabled": True, "ttl_hours": bad})
                                      ).ttl_seconds == 24 * HOUR


def _cfg_tree(repo: Path, block) -> Path:
    _release_json(repo, gate_cache=block)
    return repo


# ── overrides ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("val", ["off", "OFF", "0", "false", "no"])
def test_env_off_forces_a_real_run(gate: Gate, clock, monkeypatch, val):
    gate.run()
    monkeypatch.setenv("PSRW_GATE_CACHE", val)
    gate.run()
    assert gate.runs == 2


def test_env_other_values_do_not_disable(gate: Gate, clock, monkeypatch):
    gate.run()
    monkeypatch.setenv("PSRW_GATE_CACHE", "on")
    gate.run()
    assert gate.runs == 1


def test_forced_pass_refreshes_the_record(gate: Gate, clock, monkeypatch):
    gate.run()
    first = next(iter(gate.records().values()))["passed_at"]
    clock["now"] += HOUR
    monkeypatch.setenv("PSRW_GATE_CACHE", "off")
    gate.run()
    assert next(iter(gate.records().values()))["passed_at"] != first


def test_no_gate_cache_flag_sets_the_override(monkeypatch, tmp_path):
    monkeypatch.delenv("PSRW_GATE_CACHE", raising=False)
    seen = {}

    def fake_ship(cwd, **kw):
        import os
        seen["env"] = os.environ.get("PSRW_GATE_CACHE")
        raise RuntimeError("stop here")

    monkeypatch.setattr(ship, "ship_current_work", fake_ship)
    monkeypatch.setattr(ship.sys, "argv", ["psrw ship", "--no-gate-cache"])
    assert ship.main() == 1
    assert seen["env"] == "off"


def test_sync_main_accepts_no_gate_cache_flag(monkeypatch, tmp_path):
    from scripts import sync_main as sm
    monkeypatch.delenv("PSRW_GATE_CACHE", raising=False)
    seen = {}

    def fake_sync(repo, strict=False):
        import os
        seen["env"] = os.environ.get("PSRW_GATE_CACHE")
        return {"release": None, "synced": 0, "gate1": None}

    monkeypatch.setattr(sm, "sync_main", fake_sync)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sm, "find_repo_root", lambda p: tmp_path)
    sm.main(["--no-gate-cache"])
    assert seen["env"] == "off"


# ── fail-open on bad state / unusable tree ─────────────────────────────────────


@pytest.mark.parametrize("garbage", ["{not json", "[]", '{"entries": []}', '"str"', ""])
def test_corrupt_cache_file_fails_open_and_heals(gate: Gate, clock, garbage):
    gate.state.parent.mkdir(parents=True, exist_ok=True)
    gate.state.write_text(garbage)
    assert gate.run() == 0
    assert gate.runs == 1
    assert len(gate.records()) == 1                        # file healed
    gate.run()
    assert gate.runs == 1                                  # and now it hits


def test_missing_cache_file_is_a_plain_miss(gate: Gate, clock):
    assert not gate.state.exists()
    assert gate.run() == 0 and gate.runs == 1


def test_malformed_records_are_ignored(gate: Gate, clock):
    gate.run()
    key, rec = next(iter(gate.records().items()))
    for bad in ({**rec, "version": 999}, {**rec, "passed_at": "garbage"}, {**rec, "tree": "other"}, "x"):
        gate.state.write_text(json.dumps({"version": gate_cache.SCHEMA_VERSION, "entries": {key: bad}}))
        gate.run()
    assert gate.runs == 5                                  # 1 initial + 4 misses, never a HIT


def test_dirty_tree_bypasses_cache_and_records_nothing(gate: Gate, clock, capsys):
    (gate.repo / "scratch.txt").write_text("uncommitted\n")
    gate.run()
    gate.run()
    assert gate.runs == 2
    assert not gate.state.exists()
    assert "dirty" in capsys.readouterr().err


def test_state_file_itself_does_not_make_the_tree_dirty(tmp_repo: Path, tmp_path, clock, monkeypatch):
    """Even in a repo that forgot to gitignore .claude/state/."""
    monkeypatch.delenv("PSRW_GATE_CACHE", raising=False)
    g = Gate(tmp_repo, tmp_path)
    (tmp_repo / ".gitignore").write_text("")
    _commit_all(tmp_repo, "no ignore")
    g.run()
    g.run()
    assert g.runs == 1


def test_non_git_tree_with_cache_enabled_fails_open(tmp_path, clock, monkeypatch):
    monkeypatch.delenv("PSRW_GATE_CACHE", raising=False)
    tree = tmp_path / "plain"
    (tree / "scripts").mkdir(parents=True)
    (tree / ".release.json").write_text(json.dumps({"gate_cache": {"enabled": True}}))
    sh = tree / "scripts" / "precheck.sh"
    sh.write_text("#!/bin/sh\nexit 0\n")
    sh.chmod(0o755)
    assert ship._run_precheck(tree) == 0


def test_missing_precheck_script_is_still_none_with_cache_on(gate: Gate, clock):
    (gate.repo / "scripts" / "precheck.sh").unlink()
    _commit_all(gate.repo, "rm gate")
    assert gate.run() is None


# ── cap ────────────────────────────────────────────────────────────────────────


def test_entries_are_capped_dropping_the_oldest(gate: Gate, clock, monkeypatch):
    monkeypatch.setattr(gate_cache, "MAX_ENTRIES", 3)
    trees = []
    for i in range(5):
        (gate.repo / f"f{i}.txt").write_text(str(i))
        _commit_all(gate.repo, f"c{i}")
        clock["now"] += 60
        gate.run()
        trees.append(_git(gate.repo, "rev-parse", "HEAD^{tree}"))
    kept = {r["tree"] for r in gate.records().values()}
    assert kept == set(trees[-3:])


# ── scope: Gate 1 only ─────────────────────────────────────────────────────────


def test_cache_is_not_wired_into_gate_2_or_promote():
    root = Path(__file__).resolve().parent.parent
    for rel in ("scripts/promote_release.py", "lib/epic_gate.py", "scripts/epic.py"):
        assert "gate_cache" not in (root / rel).read_text(), rel
