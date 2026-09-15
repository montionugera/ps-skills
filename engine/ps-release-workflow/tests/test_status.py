"""status: one-screen "what's in flight" report + Next hint chosen by state."""
import json
import subprocess
import sys
from pathlib import Path

from scripts.status import collect_status, render_brief, render_full

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "status.py"


def _run_script(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd, capture_output=True, text=True,
    )


def _setup_release_with_features(repo: Path, owner: str) -> list[dict]:
    """Release 1.1 in progress; F-001 claimed by `owner`, F-002 open, I-003 unpromoted."""
    from scripts.init_work_new_release import new_release
    from scripts.new_idea import new_idea
    from scripts.promote_idea_to_refined import promote_idea_to_refined
    from scripts.init_work_refined_backlog import claim_feature

    new_release(repo, version="1.1")
    feats = []
    for title in ("First feature", "Second feature"):
        idea = new_idea(repo, title=title)
        feats.append(promote_idea_to_refined(repo, idea["id"]))
    new_idea(repo, title="Unpromoted idea")
    claim_feature(repo, feats[0]["id"], owner=owner)
    return feats


def _refined_catalog_path(repo: Path) -> Path:
    return repo / ".claude" / "worktrees" / "_release" / ".claude" / "refined_backlog" / "_catalog.json"


def _set_statuses(repo: Path, statuses: dict[str, str]) -> None:
    cat = _refined_catalog_path(repo)
    entries = json.loads(cat.read_text())
    for e in entries:
        if e["id"] in statuses:
            e["status"] = statuses[e["id"]]
    cat.write_text(json.dumps(entries, indent=2) + "\n")


def _end_release(repo: Path, version: str = "1.1") -> None:
    """Simulate post-promote (PR squash landed): in_progress=False everywhere,
    last_promoted stamped on main, but cleanup NOT yet run."""
    for rj_path in (
        repo / ".claude" / "worktrees" / "_release" / ".release.json",
        repo / ".release.json",
    ):
        rj = json.loads(rj_path.read_text())
        rj["in_progress"] = False
        rj["last_promoted_version"] = version
        rj["last_promoted_at"] = "2026-07-03T00:00:00+00:00"
        rj_path.write_text(json.dumps(rj, indent=2) + "\n")


# ── not opted in ──────────────────────────────────────────────────────────


def test_not_opted_in_prints_single_line_and_exits_zero(tmp_repo: Path):
    cp = _run_script(tmp_repo)
    assert cp.returncode == 0
    assert cp.stdout.strip() == "not a ps-release-workflow repo"


def test_no_git_repo_at_all_exits_zero(tmp_path: Path):
    cp = _run_script(tmp_path)
    assert cp.returncode == 0
    assert cp.stdout.strip() == "not a ps-release-workflow repo"


# ── release in progress, mixed feature states ─────────────────────────────


def test_mixed_states_counts_and_claim_hint(tmp_repo_with_release: Path, fixed_owner: str):
    feats = _setup_release_with_features(tmp_repo_with_release, fixed_owner)
    st = collect_status(tmp_repo_with_release)

    assert st["opted_in"] is True
    assert st["release"]["in_progress"] is True
    assert st["release"]["version"] == "1.1"
    assert st["counts"]["open"] == 1
    assert st["counts"]["claimed"] == 1
    assert st["ideas"]["total"] == 3
    assert st["ideas"]["unpromoted"] == 1
    assert st["own_claims"] == [feats[0]["id"]]
    # An open feature exists → claim is the next step.
    assert "claim" in st["next"]

    full = render_full(st)
    assert feats[0]["id"] in full
    assert feats[1]["id"] in full
    assert "1.1" in full
    assert "Next:" in full


def test_claimed_only_hints_ship(tmp_repo_with_release: Path, fixed_owner: str):
    feats = _setup_release_with_features(tmp_repo_with_release, fixed_owner)
    _set_statuses(tmp_repo_with_release, {feats[1]["id"]: "claimed"})
    st = collect_status(tmp_repo_with_release)
    assert "ship" in st["next"]


def test_all_shipped_hints_promote(tmp_repo_with_release: Path, fixed_owner: str):
    feats = _setup_release_with_features(tmp_repo_with_release, fixed_owner)
    _set_statuses(tmp_repo_with_release, {f["id"]: "shipped" for f in feats})
    st = collect_status(tmp_repo_with_release)
    assert "promote" in st["next"]
    assert "cleanup-only" not in st["next"]


def test_release_open_refined_empty_hints_idea(tmp_repo_with_release: Path):
    from scripts.init_work_new_release import new_release
    new_release(tmp_repo_with_release, version="1.1")
    st = collect_status(tmp_repo_with_release)
    assert st["counts"]["total"] == 0
    assert "idea" in st["next"]


def test_no_release_no_leftovers_hints_new_release(tmp_repo_with_release: Path):
    st = collect_status(tmp_repo_with_release)
    assert st["release"]["in_progress"] is False
    assert st["pending_cleanup"] is False
    assert "new-release" in st["next"]


# ── pending cleanup (promoted but uncleaned) ──────────────────────────────


def test_pending_cleanup_detected_after_promote(tmp_repo_with_release: Path, fixed_owner: str):
    _setup_release_with_features(tmp_repo_with_release, fixed_owner)
    _end_release(tmp_repo_with_release, version="1.1")

    st = collect_status(tmp_repo_with_release)
    assert st["release"]["in_progress"] is False
    assert st["pending_cleanup"] is True
    assert "--cleanup-only 1.1" in st["next"]
    # B3: the hint must be conditioned on the PR having merged — a bare
    # "run cleanup" hint told every new session to destroy an open release PR.
    assert "after the release PR merges" in st["next"]

    full = render_full(st)
    assert "--cleanup-only 1.1" in full


def test_pending_cleanup_hint_without_version_never_says_none():
    """Minor: last_promoted_version=None must not render '--cleanup-only None'."""
    from scripts.status import _next_hint
    counts = {"open": 0, "claimed": 0, "shipped": 0, "promoted": 0, "total": 0}
    hint = _next_hint(False, True, None, counts)
    assert "None" not in hint
    assert "--cleanup-only <version>" in hint


# ── drift: claimed but worktree missing ───────────────────────────────────


def test_claimed_but_worktree_missing_flags_drift(tmp_repo_with_release: Path, fixed_owner: str):
    feats = _setup_release_with_features(tmp_repo_with_release, fixed_owner)
    claims = json.loads(
        (tmp_repo_with_release / ".claude" / "state" / "claims.json").read_text()
    )
    wt_path = claims[feats[0]["id"]]["worktree"]
    subprocess.run(
        ["git", "worktree", "remove", "--force", wt_path],
        cwd=tmp_repo_with_release, check=True, capture_output=True,
    )

    st = collect_status(tmp_repo_with_release)
    feat = next(f for f in st["features"] if f["id"] == feats[0]["id"])
    assert feat["drift"], "expected a drift flag on the claimed feature"
    assert "missing" in feat["drift"]

    full = render_full(st)
    assert "missing" in full


# ── --brief ───────────────────────────────────────────────────────────────


def test_brief_stays_within_line_budget(tmp_repo_with_release: Path, fixed_owner: str):
    feats = _setup_release_with_features(tmp_repo_with_release, fixed_owner)
    st = collect_status(tmp_repo_with_release)
    brief = render_brief(st)
    lines = [ln for ln in brief.splitlines() if ln.strip()]
    assert len(lines) <= 6
    assert "1.1" in brief
    assert feats[0]["id"] in brief  # own claim surfaced
    assert "Next:" in brief  # (was a vacuous disjunct: "ext:" ⊂ "Next:")


def test_brief_via_cli_exits_zero(tmp_repo_with_release: Path, fixed_owner: str):
    _setup_release_with_features(tmp_repo_with_release, fixed_owner)
    cp = _run_script(tmp_repo_with_release, "--brief")
    assert cp.returncode == 0
    assert "1.1" in cp.stdout
    assert len([ln for ln in cp.stdout.splitlines() if ln.strip()]) <= 6


def test_status_never_writes_identity_cache(tmp_repo_with_release: Path, monkeypatch):
    """M3: status promises to be read-only — with no identity anywhere it must
    NOT generate + persist a session id; own_claims just comes back empty."""
    import os
    _setup_release_with_features(tmp_repo_with_release, "someone-else")
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    cache = Path(os.environ["HOME"]) / ".cache" / "ps-release-workflow" / "session-id"
    cache.unlink(missing_ok=True)  # setup (new_release) may have generated one

    st = collect_status(tmp_repo_with_release)

    assert st["own_claims"] == []
    assert not cache.exists(), "status wrote the identity cache — read path must not write"


def test_corrupt_release_json_never_raises(tmp_repo: Path):
    (tmp_repo / ".release.json").write_text("{not json")
    cp = _run_script(tmp_repo, "--repo", str(tmp_repo), "--brief")
    assert cp.returncode == 0
    assert "Traceback" not in cp.stderr
