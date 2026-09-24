"""status: one-screen "what's in flight" report + Next hint chosen by state."""
import json
import shutil
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
        feats.append(promote_idea_to_refined(repo, idea["id"], allow_empty_spec=True))
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


# ── epic rollup ───────────────────────────────────────────────────────────


def _setup_epic_with_three_slices(repo: Path) -> list[dict]:
    """Release 1.1 in progress; E-001 fanned out into 3 ideas, each refined
    into F-001..F-003 (all 'open'). Returns the three feature entries."""
    from scripts.epic import epic_fanout, epic_open
    from scripts.init_work_new_release import new_release
    from scripts.promote_idea_to_refined import promote_idea_to_refined

    new_release(repo, version="1.1")
    epic_open(repo, "Multi-account risk limits")
    ideas = epic_fanout(repo, "E-001", ["per-account cap", "aggregate cap", "breach alert"])["ideas"]
    return [promote_idea_to_refined(repo, i["id"], allow_empty_spec=True) for i in ideas]


def test_status_groups_features_under_their_epic(tmp_repo_with_release: Path, fixed_owner: str):
    feats = _setup_epic_with_three_slices(tmp_repo_with_release)
    _set_statuses(tmp_repo_with_release, {feats[0]["id"]: "shipped", feats[1]["id"]: "shipped"})

    st = collect_status(tmp_repo_with_release)
    out = render_full(st)

    assert "E-001" in out
    assert "2/3 slices shipped" in out
    assert [e["id"] for e in st["epics"]] == ["E-001"]
    # Existing counts are untouched by the added section.
    assert st["counts"]["shipped"] == 2 and st["counts"]["total"] == 3


def test_status_warns_when_two_siblings_are_claimed_at_once(
    tmp_repo_with_release: Path, fixed_owner: str
):
    """Mitigation for F2: epic branches are cut off main, so siblings are
    developed blind to each other."""
    from scripts.init_work_refined_backlog import claim_feature

    feats = _setup_epic_with_three_slices(tmp_repo_with_release)
    claim_feature(tmp_repo_with_release, feats[0]["id"], owner=fixed_owner)
    st = collect_status(tmp_repo_with_release)
    assert "siblings" not in render_full(st).lower(), "one claimed sibling must not warn"

    claim_feature(tmp_repo_with_release, feats[1]["id"], owner=fixed_owner)
    st = collect_status(tmp_repo_with_release)
    assert "two siblings of e-001 are claimed" in render_full(st).lower()
    assert "two siblings of e-001 are claimed" in render_brief(st).lower()


def _release_wt(repo: Path) -> Path:
    return repo / ".claude" / "worktrees" / "_release"


def _edit_catalog(path: Path, mutate) -> None:
    entries = json.loads(path.read_text())
    mutate(entries)
    path.write_text(json.dumps(entries, indent=2) + "\n")


def test_rollup_does_not_assume_plan_md_exists(tmp_repo_with_release: Path, fixed_owner: str):
    """'All three files always exist' is explicitly NOT an invariant (F-015).
    Real feature folders: one with plan.md deleted, one with no files at all,
    one with the folder itself gone."""
    feats = _setup_epic_with_three_slices(tmp_repo_with_release)
    refined = _release_wt(tmp_repo_with_release) / ".claude" / "refined_backlog"

    folders = [next(refined.glob(f"{f['id']}-*")) for f in feats]
    assert all(d.is_dir() for d in folders), "fixture must create real feature folders"
    assert (folders[0] / "plan.md").exists(), "fixture must start with a plan.md to delete"
    (folders[0] / "plan.md").unlink()
    for child in folders[1].iterdir():
        child.unlink()
    shutil.rmtree(folders[2])

    st = collect_status(tmp_repo_with_release)
    out = render_full(st)
    assert st["epics"][0]["slices_total"] == 3
    assert [s["status"] for s in st["epics"][0]["slices"]] == ["open", "open", "open"]
    assert "0/3 slices shipped" in out


def test_rollup_tolerates_legacy_entries_without_epic_key(
    tmp_repo_with_release: Path, fixed_owner: str
):
    """Legacy ideas/features (no `epic` key) coexist with a real epic and are
    neither counted as its slices nor break the rollup."""
    from scripts.epic import epic_fanout, epic_open

    legacy = _setup_release_with_features(tmp_repo_with_release, fixed_owner)
    assert all("epic" not in f for f in legacy)
    epic_open(tmp_repo_with_release, "Multi-account risk limits")
    epic_fanout(tmp_repo_with_release, "E-001", ["per-account cap", "aggregate cap"])

    st = collect_status(tmp_repo_with_release)
    assert [e["id"] for e in st["epics"]] == ["E-001"]
    assert st["epics"][0]["slices_total"] == 2
    assert st["epics"][0]["slices_shipped"] == 0
    assert st["epics"][0]["claimed_siblings"] == []  # legacy claimed F-001 is not a sibling
    assert "0/2 slices shipped" in render_full(st)


def _promote_epic(repo: Path, epic_id: str) -> None:
    cat = _release_wt(repo) / ".claude" / "epic_backlog" / "_catalog.json"

    def mutate(entries):
        for e in entries:
            if e["id"] == epic_id:
                e["status"] = "promoted"

    _edit_catalog(cat, mutate)


def test_promoted_epics_are_summarised_not_listed(tmp_repo_with_release: Path, fixed_owner: str):
    from scripts.epic import epic_fanout, epic_open

    _setup_epic_with_three_slices(tmp_repo_with_release)  # E-001
    epic_open(tmp_repo_with_release, "Second epic")  # E-002
    epic_fanout(tmp_repo_with_release, "E-002", ["only slice"])
    _promote_epic(tmp_repo_with_release, "E-001")

    st = collect_status(tmp_repo_with_release)
    out = render_full(st)
    assert {e["id"] for e in st["epics"]} == {"E-001", "E-002"}  # structured state stays complete
    epics_section = out.split("Epics:")[1]
    assert "E-002" in epics_section
    assert "E-001" not in epics_section
    assert "(+1 promoted epic(s) omitted)" in out


def test_in_flight_epic_is_still_shown_without_omitted_line(
    tmp_repo_with_release: Path, fixed_owner: str
):
    _setup_epic_with_three_slices(tmp_repo_with_release)
    out = render_full(collect_status(tmp_repo_with_release))
    assert "E-001" in out
    assert "epic(s) omitted" not in out


def test_only_promoted_epics_shows_no_empty_epics_table(
    tmp_repo_with_release: Path, fixed_owner: str
):
    _setup_epic_with_three_slices(tmp_repo_with_release)
    _promote_epic(tmp_repo_with_release, "E-001")
    out = render_full(collect_status(tmp_repo_with_release))
    assert "(+1 promoted epic(s) omitted)" in out
    assert "slices shipped" not in out


def test_promoted_idea_whose_feature_is_missing_is_reported_missing(
    tmp_repo_with_release: Path, fixed_owner: str
):
    feats = _setup_epic_with_three_slices(tmp_repo_with_release)
    gone = feats[1]["id"]
    _edit_catalog(
        _refined_catalog_path(tmp_repo_with_release),
        lambda entries: entries.__setitem__(slice(None), [e for e in entries if e["id"] != gone]),
    )

    st = collect_status(tmp_repo_with_release)
    slices = {s["id"]: s["status"] for s in st["epics"][0]["slices"]}
    assert slices[gone] == "missing"
    assert slices[feats[0]["id"]] == "open"
    assert any(gone in w and "missing" in w for w in st["warnings"])
    assert f"{gone} missing" in render_full(st)


def test_unpromoted_slice_stays_idea_with_no_warning(
    tmp_repo_with_release: Path, fixed_owner: str
):
    from scripts.epic import epic_fanout, epic_open
    from scripts.init_work_new_release import new_release

    new_release(tmp_repo_with_release, version="1.1")
    epic_open(tmp_repo_with_release, "Epic")
    epic_fanout(tmp_repo_with_release, "E-001", ["a", "b"])
    st = collect_status(tmp_repo_with_release)
    assert [s["status"] for s in st["epics"][0]["slices"]] == ["idea", "idea"]
    assert st["warnings"] == []


# ── Hotfix pending sync: status flags a release behind main (cached, no fetch) ─


def test_status_reports_release_behind_origin_main(tmp_repo_in_release: Path):
    repo = tmp_repo_in_release
    (repo / "hotfix.txt").write_text("critical patch\n")
    subprocess.run(["git", "add", "hotfix.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fix: hotfix"], cwd=repo, check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=repo, check=True)  # updates origin/main

    st = collect_status(repo)
    assert st["release"]["behind_main"] == 1
    assert st["release"]["main_ref"] == "origin/main"
    for text in (render_brief(st), render_full(st)):
        assert "1 behind origin/main (hotfix pending sync; run psrw sync-main)" in text


def test_status_behind_main_uses_the_cached_ref_and_never_fetches(tmp_repo_in_release: Path):
    """status is read-only and offline: a commit that only exists on the remote
    (not yet fetched) must not be seen, and nothing may be fetched."""
    repo = tmp_repo_in_release
    clone = repo.parent / "other-clone"
    subprocess.run(["git", "clone", "-q", "-b", "main", str(repo.parent / "origin.git"), str(clone)],
                   check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-q",
                    "--allow-empty", "-m", "remote-only"], cwd=clone, check=True)
    subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=clone, check=True)
    before = subprocess.run(["git", "rev-parse", "origin/main"], cwd=repo,
                            capture_output=True, text=True).stdout

    st = collect_status(repo)
    assert st["release"]["behind_main"] == 0
    assert "behind" not in render_brief(st)
    assert subprocess.run(["git", "rev-parse", "origin/main"], cwd=repo,
                          capture_output=True, text=True).stdout == before


def test_status_behind_main_without_any_main_ref(tmp_repo_in_release: Path):
    repo = tmp_repo_in_release
    subprocess.run(["git", "update-ref", "-d", "refs/remotes/origin/main"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-q", "-m", "main", "trunk"], cwd=repo, check=True)
    st = collect_status(repo)
    assert st["release"]["behind_main"] == 0 and st["release"]["main_ref"] is None


def test_status_behind_main_survives_a_git_error(tmp_repo_in_release: Path, monkeypatch):
    import scripts.status as status_mod
    from lib.git_ops import GitError

    def boom(*a, **k):
        raise GitError("broken")
    monkeypatch.setattr(status_mod, "missing_main_commits", boom)
    assert collect_status(tmp_repo_in_release)["release"]["behind_main"] == 0


def test_status_ignores_a_release_dir_that_is_not_a_worktree(tmp_repo_in_release: Path):
    """A leftover plain _release dir would make git walk up to the main
    checkout and count ITS head against origin/main — a wrong number."""
    repo = tmp_repo_in_release
    rel = repo / ".claude" / "worktrees" / "_release"
    (rel / ".git").unlink()
    (repo / "hotfix.txt").write_text("x\n")
    subprocess.run(["git", "add", "hotfix.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "hotfix"], cwd=repo, check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=repo, check=True)
    # Main checkout now 1 behind origin/main: exactly what a walk-up would count.
    subprocess.run(["git", "reset", "-q", "--hard", "HEAD~1"], cwd=repo, check=True)
    st = collect_status(repo)
    assert st["release"]["behind_main"] == 0
