"""Opt-in cache of PASSED Gate 1 (precheck) runs, keyed by git tree content.

A gate that already passed on an identical tree need not run again: re-ships,
sync-main re-verifications and post-merge re-checks routinely present a tree
whose precheck already passed minutes or hours earlier.

Strictly opt-in. Off unless the verified tree's .release.json has
    "gate_cache": {"enabled": true, "ttl_hours": 24}
Absent / not literally `true` => the gate runs exactly as before and no state
file is touched. Applies to Gate 1 (precheck) only — never Gate 2, integration,
epic checks or promote.

Key = sha256(`git rev-parse HEAD^{tree}` + hash of the precheck script's
tree-relative path and bytes). Tree content (not commit, not checkout path), so
the feature worktree and the _release worktree share hits. Only PASS records
are stored (state: <repo>/.claude/state/gate-pass-cache.json, gitignored, TTL,
capped at MAX_ENTRIES oldest-dropped). A FAIL never writes a record and
removes a stale one for that key. Dirty trees, non-git trees and any cache I/O
error fail OPEN to a real run.

Overrides: `--no-gate-cache` (ship, sync-main) sets PSRW_GATE_CACHE=off; the
env var forces a real run (the result still refreshes / clears the record).

Risks accepted by enabling it:
  * Environment drift — same tree, different toolchain, deps, services, env
    vars or gitignored files: the old PASS says nothing about the new setup.
    Use --no-gate-cache after upgrading the toolchain or when a flake is suspected.
  * A skipped run on a push that previously had its only re-check: a HIT means
    the verification you rely on is the earlier one, up to ttl_hours old.
"""
import hashlib
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from lib.git_ops import _run as git_run
from lib.repo import RepoNotFoundError, find_repo_root
from lib.state import mutate_state

SCHEMA_VERSION = 1
MAX_ENTRIES = 200
DEFAULT_TTL_HOURS = 24.0
STATE_REL = Path(".claude/state/gate-pass-cache.json")
_OFF_VALUES = {"off", "0", "false", "no"}


@dataclass(frozen=True)
class Config:
    enabled: bool
    ttl_seconds: float


def _now() -> float:
    return time.time()


def load_config(tree: Path) -> Config:
    """Read the gate_cache block from `tree`/.release.json (disabled on any doubt)."""
    off = Config(False, DEFAULT_TTL_HOURS * 3600)
    try:
        data = json.loads((Path(tree) / ".release.json").read_text())
    except (OSError, ValueError):
        return off
    block = data.get("gate_cache") if isinstance(data, dict) else None
    if not isinstance(block, dict) or block.get("enabled") is not True:
        return off
    ttl = block.get("ttl_hours")
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or ttl <= 0:
        ttl = DEFAULT_TTL_HOURS
    return Config(True, float(ttl) * 3600)


def gate_hash(tree: Path, precheck: Path) -> str:
    """Hash of the precheck's tree-relative path + bytes (location-independent)."""
    rel = Path(precheck).resolve().relative_to(Path(tree).resolve())
    h = hashlib.sha256(str(rel).encode())
    h.update(b"\0")
    h.update(Path(precheck).read_bytes())
    return h.hexdigest()


def _forced_off() -> bool:
    import os
    return os.environ.get("PSRW_GATE_CACHE", "").strip().lower() in _OFF_VALUES


def _tree_sha(tree: Path) -> str | None:
    r = git_run(tree, "rev-parse", "HEAD^{tree}", check=False)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _is_clean(tree: Path) -> bool | None:
    """True/False for a clean/dirty worktree, None when git cannot say.

    The cache's own state dir is excluded so recording a pass never dirties the
    tree in a repo that forgot to gitignore .claude/state/.
    """
    r = git_run(tree, "status", "--porcelain", "--", ".", ":(top,exclude).claude/state", check=False)
    if r.returncode != 0:
        return None
    return not r.stdout.strip()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _ts(rec: object) -> float | None:
    try:
        return datetime.fromisoformat(rec["passed_at"]).timestamp()  # type: ignore[index]
    except (TypeError, KeyError, ValueError):
        return None


def _fmt_age(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    h, m = divmod(s // 60, 60)
    return f"{h}h {m}m" if m else f"{h}h"


def _entries(state: object) -> dict:
    ent = state.get("entries") if isinstance(state, dict) else None
    return ent if isinstance(ent, dict) else {}


def _read_entries(path: Path) -> dict:
    try:
        return _entries(json.loads(path.read_text()))
    except (OSError, ValueError):
        return {}


def _valid(rec: object, tree_sha: str, ghash: str) -> bool:
    return (isinstance(rec, dict) and rec.get("version") == SCHEMA_VERSION
            and rec.get("tree") == tree_sha and rec.get("gate_hash") == ghash
            and _ts(rec) is not None)


def _mutate(path: Path, fn: Callable[[dict], dict]) -> None:
    def apply(state: object) -> dict:
        return {"version": SCHEMA_VERSION, "entries": fn(dict(_entries(state)))}
    try:
        mutate_state(path, apply, default={})
    except ValueError:                      # corrupt JSON: heal by starting over
        path.unlink(missing_ok=True)
        mutate_state(path, apply, default={})


def _record_pass(path: Path, key: str, tree_sha: str, ghash: str) -> None:
    def add(entries: dict) -> dict:
        entries[key] = {"tree": tree_sha, "gate_hash": ghash,
                        "passed_at": _iso(_now()), "version": SCHEMA_VERSION}
        newest = sorted(entries.items(), key=lambda kv: _ts(kv[1]) or 0.0, reverse=True)
        return dict(newest[:MAX_ENTRIES])
    _mutate(path, add)


def _forget(path: Path, key: str) -> None:
    if key in _read_entries(path):
        _mutate(path, lambda entries: {k: v for k, v in entries.items() if k != key})


def run_cached(tree: Path, precheck: Path, run: Callable[[], int]) -> int:
    """Run the gate via `run()` unless a fresh PASS record for this tree exists.

    Returns the gate's exit code (0 on a HIT). Exceptions from `run()` propagate
    uncached. Every cache-side problem degrades to a plain `run()`.
    """
    tree = Path(tree)
    cfg = load_config(tree)
    if not cfg.enabled:
        return run()
    try:
        tsha = _tree_sha(tree)
        clean = _is_clean(tree) if tsha else None
        if tsha is None or clean is None:
            return run()
        if not clean:
            print("gate cache bypassed: working tree is dirty — running precheck", file=sys.stderr)
            return run()
        ghash = gate_hash(tree, precheck)
        path = find_repo_root(tree) / STATE_REL
        key = hashlib.sha256(f"{tsha}\0{ghash}".encode()).hexdigest()
    except (OSError, ValueError, RepoNotFoundError) as e:
        print(f"gate cache unavailable ({e}) — running precheck", file=sys.stderr)
        return run()

    if not _forced_off():
        rec = _read_entries(path).get(key)
        if _valid(rec, tsha, ghash):
            age = _now() - _ts(rec)  # type: ignore[arg-type]
            if 0 <= age <= cfg.ttl_seconds:
                print(f"gate cache HIT (tree {tsha[:8]}, passed {_fmt_age(age)} ago) — skipping precheck")
                return 0

    rc = run()
    try:
        if rc == 0:
            _record_pass(path, key, tsha, ghash)
        else:
            _forget(path, key)
    except Exception as e:                  # cache I/O must never change the gate's verdict
        print(f"gate cache: could not update {path} ({e}) — ignored", file=sys.stderr)
    return rc
