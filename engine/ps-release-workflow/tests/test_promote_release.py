"""promote_release: Gate 2 + squash merge → main + auto-cleanup."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.init_work_new_release import new_release
from scripts.new_idea import new_idea
from scripts.promote_idea_to_refined import promote_idea_to_refined
from scripts.init_work_refined_backlog import claim_feature
from scripts.ship_current_work_to_release import ship_current_work
from scripts.promote_release import (
    promote_release, NoReleaseInProgressError, Gate2FailedError, cleanup,
)


def _gate2_marker(repo: Path) -> Path:
    """Absolute marker path the integration.sh stub touches when it actually runs.

    Lives OUTSIDE the repo so it survives promote's auto-cleanup (which removes
    the _release worktree the gate executes in).
    """
    return repo.parent / "gate2-ran.marker"


def _setup_and_ship_feature(tmp_repo_with_release: Path, fixed_owner: str, title: str = "F",
                            with_integration: bool = True):
    """Helper: open release, claim+ship one feature, return repo + feature_id.

    Gate stubs are committed on main BEFORE the release branch is cut so that
    release/<v> (and therefore the _release worktree Gate 2 executes in)
    actually contains them.
    """
    (tmp_repo_with_release / "scripts").mkdir(exist_ok=True)
    (tmp_repo_with_release / "scripts" / "precheck.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_repo_with_release / "scripts" / "precheck.sh").chmod(0o755)
    if with_integration:
        marker = _gate2_marker(tmp_repo_with_release)
        (tmp_repo_with_release / "scripts" / "integration.sh").write_text(
            f'#!/bin/sh\ntouch "{marker}"\nexit 0\n'
        )
        (tmp_repo_with_release / "scripts" / "integration.sh").chmod(0o755)
    subprocess.run(["git", "add", "scripts/"], cwd=tmp_repo_with_release, check=True)
    subprocess.run(["git", "commit", "-m", "stubs"], cwd=tmp_repo_with_release, check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=tmp_repo_with_release, check=True, capture_output=True)
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title=title)
    feat = promote_idea_to_refined(tmp_repo_with_release, idea["id"])
    claim = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    wt = Path(claim["worktree"])
    (wt / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "feat"], cwd=wt, check=True, capture_output=True)
    ship_current_work(wt)
    return feat


def test_promote_merges_release_into_main(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, push=False, use_pr=False)
    log = subprocess.run(["git", "log", "main", "--oneline"], cwd=tmp_repo_with_release, capture_output=True, text=True)
    assert "release 1.1" in log.stdout.lower() or "feat" in log.stdout.lower()


def test_promote_runs_gate2_when_requested(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    marker = _gate2_marker(tmp_repo_with_release)
    assert not marker.exists()
    promote_release(tmp_repo_with_release, run_gate2=True, run_deploy=False, push=False, use_pr=False)
    # The gate must have ACTUALLY executed, not been silently skipped.
    assert marker.exists(), "integration.sh never ran — Gate 2 was silently skipped"


def test_promote_gate2_failure_aborts_before_push(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    # Break integration.sh IN THE _release WORKTREE — that is where Gate 2
    # resolves and executes the script from.
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    integ = rel_wt / "scripts" / "integration.sh"
    integ.write_text("#!/bin/sh\nexit 1\n")
    subprocess.run(["git", "commit", "-am", "broken integ"], cwd=rel_wt, check=True, capture_output=True)
    with pytest.raises(Gate2FailedError):
        promote_release(tmp_repo_with_release, run_gate2=True, run_deploy=False, push=False, use_pr=False)
    # Aborted BEFORE the merge to main.
    log = subprocess.run(["git", "log", "main", "--oneline"], cwd=tmp_repo_with_release,
                         capture_output=True, text=True).stdout
    assert "release 1.1" not in log.lower()


def test_promote_gate2_missing_script_raises_without_flag(tmp_repo_with_release: Path, fixed_owner: str):
    """A1: Gate 2 requested but integration.sh absent from the release branch must
    NOT silently pass — it must refuse unless --allow-missing-gate2 is given."""
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner, with_integration=False)
    with pytest.raises(Gate2FailedError, match="allow-missing-gate2"):
        promote_release(tmp_repo_with_release, run_gate2=True, run_deploy=False, push=False, use_pr=False)
    # Nothing merged to main.
    log = subprocess.run(["git", "log", "main", "--oneline"], cwd=tmp_repo_with_release,
                         capture_output=True, text=True).stdout
    assert "release 1.1" not in log.lower()


def test_promote_gate2_missing_script_proceeds_with_flag(tmp_repo_with_release: Path, fixed_owner: str, capsys):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner, with_integration=False)
    result = promote_release(tmp_repo_with_release, run_gate2=True, run_deploy=False, push=False,
                             use_pr=False, allow_missing_gate2=True)
    assert result["ok"] is True
    # Loud warning on stderr.
    err = capsys.readouterr().err
    assert "Gate 2 SKIPPED" in err
    assert "UNVERIFIED" in err


def test_promote_auto_cleanup_removes_feature_branch(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, push=False, use_pr=False)
    branches = subprocess.run(["git", "branch"], cwd=tmp_repo_with_release, capture_output=True, text=True).stdout
    assert f"feat/{feat['id']}" not in branches
    assert "release/1.1" not in branches


def test_promote_auto_cleanup_archives_refined_backlog(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, push=False, use_pr=False)
    archived = tmp_repo_with_release / ".claude" / "refined_backlog" / "_archive" / "1.1" / f"{feat['id']}-f"
    # Slug "f" because title was "F"
    # Note: the original folder should be moved, archive should exist
    archive_root = tmp_repo_with_release / ".claude" / "refined_backlog" / "_archive"
    assert archive_root.is_dir()


def test_promote_auto_cleanup_removes_feature_worktree(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, push=False, use_pr=False)
    wt = tmp_repo_with_release / ".claude" / "worktrees"
    feature_wts = [d for d in wt.iterdir() if d.name.startswith(feat["id"])]
    assert feature_wts == []


def test_promote_clears_release_in_progress(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, push=False, use_pr=False)
    rj = json.loads((tmp_repo_with_release / ".release.json").read_text())
    assert rj["in_progress"] is False
    assert rj["last_promoted_version"] == "1.1"


def test_promote_keep_flag_skips_cleanup(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, push=False, keep=True, use_pr=False)
    # Feature branch + release branch should still exist.
    branches = subprocess.run(["git", "branch"], cwd=tmp_repo_with_release, capture_output=True, text=True).stdout
    assert f"feat/{feat['id']}" in branches
    assert "release/1.1" in branches


# ── PR mode: gh failure recovery + pre-existing PR (audit A3) ──────────────────

PR_URL = "https://github.com/o/r/pull/1"


class FakeGh:
    """Stub for the injected gh runner. Records the op sequence (create/view/
    checks/merge); per-op results are (returncode, stdout, stderr) tuples."""

    def __init__(self, results: dict | None = None):
        self.calls: list[str] = []
        self.results = results or {}

    def __call__(self, cmd, **kwargs):
        assert cmd[0] == "gh" and cmd[1] == "pr"
        op = cmd[2]
        self.calls.append(op)
        rc, out, err = self.results.get(op, (0, PR_URL, ""))
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)


def test_promote_pr_mode_gh_failure_leaves_release_in_progress(tmp_repo_with_release: Path, fixed_owner: str):
    """A3: a failed `gh pr create` (network/auth) must NOT finalize the release
    state — otherwise a retry hits NoReleaseInProgressError with no recovery."""
    from lib.backlog_paths import read_release_state
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    gh = FakeGh({"create": (1, "", "connect: network is unreachable"),
                 "view": (1, "", "no pull requests found")})
    with pytest.raises(Gate2FailedError, match="gh pr create failed"):
        promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, gh_runner=gh)
    # Release is still in progress → retry works.
    state = read_release_state(tmp_repo_with_release)
    assert state is not None and state["version"] == "1.1"
    result = promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False,
                             gh_runner=FakeGh())
    assert result["ok"] is True and result["pr_url"] == PR_URL
    assert read_release_state(tmp_repo_with_release) is None  # finalized after success


def test_promote_pr_mode_tolerates_existing_pr(tmp_repo_with_release: Path, fixed_owner: str):
    from lib.backlog_paths import read_release_state
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    gh = FakeGh({"create": (1, "", 'a pull request for branch "release/1.1" into branch "main" already exists'),
                 "view": (0, "https://github.com/o/r/pull/7", "")})
    result = promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, gh_runner=gh)
    assert result["ok"] is True
    assert result["pr_url"] == "https://github.com/o/r/pull/7"
    assert result["note"] == "PR already existed"
    # Treated as success → state finalized.
    assert read_release_state(tmp_repo_with_release) is None


def test_promote_pr_mode_finalized_state_reaches_origin_release_branch(tmp_repo_with_release: Path, fixed_owner: str):
    """Finalize now happens AFTER PR creation — the finalize commit must still be
    pushed so the squash-merge carries in_progress=False to main."""
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, gh_runner=FakeGh())
    origin = tmp_repo_with_release.parent / "origin.git"
    shown = subprocess.run(["git", "show", "release/1.1:.release.json"], cwd=origin,
                           capture_output=True, text=True)
    assert shown.returncode == 0
    rj = json.loads(shown.stdout)
    assert rj["in_progress"] is False
    assert rj["last_promoted_version"] == "1.1"


# ── --babysit: watch checks → squash-merge → cleanup (B4) ──────────────────────

def _record_cleanup(monkeypatch, gh: FakeGh, delegate: bool):
    """Monkeypatch promote's cleanup to record ordering in gh.calls."""
    import scripts.promote_release as pr_mod
    real_cleanup = pr_mod.cleanup

    def recording_cleanup(repo, version, **kwargs):
        gh.calls.append("cleanup")
        if delegate:
            return real_cleanup(repo, version=version, **kwargs)
        return {"ok": True, "version": version}

    monkeypatch.setattr(pr_mod, "cleanup", recording_cleanup)


def test_promote_babysit_runs_checks_merge_cleanup_in_order(tmp_repo_with_release: Path, fixed_owner: str, monkeypatch):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    gh = FakeGh()
    _record_cleanup(monkeypatch, gh, delegate=True)
    result = promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False,
                             babysit=True, gh_runner=gh)
    assert result["ok"] is True
    assert result["merged"] is True
    assert result["cleaned_up"] is True
    assert gh.calls == ["create", "checks", "merge", "cleanup"]
    # Real cleanup ran: release branch + worktrees pruned.
    branches = subprocess.run(["git", "branch"], cwd=tmp_repo_with_release,
                              capture_output=True, text=True).stdout
    assert "release/1.1" not in branches
    assert not (tmp_repo_with_release / ".claude" / "worktrees" / "_release").exists()


def test_promote_babysit_failing_checks_stops_before_merge(tmp_repo_with_release: Path, fixed_owner: str, monkeypatch):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    gh = FakeGh({"checks": (1, "", "X some checks were not successful")})
    _record_cleanup(monkeypatch, gh, delegate=False)
    with pytest.raises(Gate2FailedError, match="NOT merging"):
        promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False,
                        babysit=True, gh_runner=gh)
    assert "merge" not in gh.calls
    assert "cleanup" not in gh.calls
    # Branches survive so the PR can still be fixed + merged manually.
    branches = subprocess.run(["git", "branch"], cwd=tmp_repo_with_release,
                              capture_output=True, text=True).stdout
    assert "release/1.1" in branches


def test_promote_babysit_red_checks_leave_release_in_progress_and_rerunnable(
        tmp_repo_with_release: Path, fixed_owner: str):
    """M1: babysit order is create PR → watch checks → finalize → merge → cleanup.
    Red checks must therefore leave in_progress=True so promote can simply be
    re-run after the fix — no bricked state."""
    from lib.backlog_paths import read_release_state
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    gh = FakeGh({"checks": (1, "", "X some checks were not successful")})
    with pytest.raises(Gate2FailedError, match="NOT merging"):
        promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False,
                        babysit=True, gh_runner=gh)
    assert "merge" not in gh.calls
    # Release still in progress — nothing finalized before green checks.
    state = read_release_state(tmp_repo_with_release)
    assert state is not None and state["version"] == "1.1"
    # And promote is re-runnable end-to-end once checks are green.
    result = promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False,
                             babysit=True, gh_runner=FakeGh())
    assert result["ok"] is True and result["merged"] is True
    assert read_release_state(tmp_repo_with_release) is None


def test_promote_babysit_merge_failure_skips_cleanup_and_names_recovery(
        tmp_repo_with_release: Path, fixed_owner: str, monkeypatch):
    """M1: checks green but `gh pr merge` fails → NO cleanup, state already
    finalized (finalize precedes merge), and the error names the recovery:
    merge manually, then promote --cleanup-only <v>."""
    from lib.backlog_paths import read_release_state
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    gh = FakeGh({"merge": (1, "", "GraphQL: base branch policy prohibits the merge")})
    _record_cleanup(monkeypatch, gh, delegate=False)
    with pytest.raises(Gate2FailedError) as ei:
        promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False,
                        babysit=True, gh_runner=gh)
    assert "cleanup" not in gh.calls
    assert gh.calls == ["create", "checks", "merge"]
    # Finalize happened AFTER green checks, BEFORE the merge attempt.
    assert read_release_state(tmp_repo_with_release) is None
    msg = str(ei.value)
    assert "Merge manually" in msg or "merge manually" in msg.lower()
    assert "--cleanup-only 1.1" in msg


def test_promote_after_finalize_names_cleanup_recovery(tmp_repo_with_release: Path, fixed_owner: str):
    """M1: re-running promote on a finalized-but-uncleaned release must not give
    the bare 'No release in progress' — it must point at --cleanup-only <v>."""
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False,
                    gh_runner=FakeGh())  # PR mode, no babysit: finalized, uncleaned
    with pytest.raises(NoReleaseInProgressError, match="already finalized") as ei:
        promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False,
                        gh_runner=FakeGh())
    assert "--cleanup-only 1.1" in str(ei.value)


def test_promote_fresh_repo_still_gets_bare_no_release_error(tmp_repo_with_release: Path):
    """No leftover worktree/branch at all → the plain error, no bogus hint."""
    with pytest.raises(NoReleaseInProgressError, match="No release in progress"):
        promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False)


def test_cli_gate2_defaults_on_deploy_defaults_off():
    """A1 (continued): README promises Gate 2 always runs at promote — the CLI
    must default --gate2 ON (opt out via --no-gate2). --deploy stays opt-in."""
    from scripts.promote_release import _build_parser
    p = _build_parser()
    args = p.parse_args([])
    assert args.gate2 is True
    assert args.deploy is False
    assert args.use_pr is True
    assert args.allow_missing_gate2 is False
    assert args.babysit is False
    assert p.parse_args(["--no-gate2"]).gate2 is False
    assert p.parse_args(["--gate2"]).gate2 is True
    assert p.parse_args(["--allow-missing-gate2"]).allow_missing_gate2 is True
    assert p.parse_args(["--babysit"]).babysit is True


def test_cleanup_subcommand_idempotent(tmp_repo_with_release: Path, fixed_owner: str):
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, push=False, keep=True, use_pr=False)
    # Now run cleanup manually (no PR exists for this local-only origin).
    gh = FakeGh({"view": (1, "", "no pull requests found")})
    cleanup(tmp_repo_with_release, version="1.1", gh_runner=gh)
    cleanup(tmp_repo_with_release, version="1.1", gh_runner=gh)  # second run should no-op


# ── B3: cleanup must not destroy an open, unmerged release PR ──────────────────


def _promoted_uncleaned(tmp_repo_with_release: Path, fixed_owner: str):
    """PR-mode promote WITHOUT babysit: finalized, PR open, cleanup not yet run."""
    feat = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False, gh_runner=FakeGh())
    return feat


def test_cleanup_refuses_while_release_pr_is_open(tmp_repo_with_release: Path, fixed_owner: str):
    """An OPEN PR means deleting the remote release branch would auto-close it,
    silently destroying an unmerged release. Cleanup must refuse."""
    _promoted_uncleaned(tmp_repo_with_release, fixed_owner)
    gh = FakeGh({"view": (0, "OPEN\n", "")})
    with pytest.raises((RuntimeError, Gate2FailedError), match="OPEN"):
        cleanup(tmp_repo_with_release, version="1.1", gh_runner=gh)
    # Nothing was deleted.
    branches = subprocess.run(["git", "branch"], cwd=tmp_repo_with_release,
                              capture_output=True, text=True).stdout
    assert "release/1.1" in branches
    assert (tmp_repo_with_release / ".claude" / "worktrees" / "_release").exists()


def test_cleanup_proceeds_when_pr_merged(tmp_repo_with_release: Path, fixed_owner: str):
    _promoted_uncleaned(tmp_repo_with_release, fixed_owner)
    gh = FakeGh({"view": (0, "MERGED\n", "")})
    result = cleanup(tmp_repo_with_release, version="1.1", gh_runner=gh)
    assert result["ok"] is True
    branches = subprocess.run(["git", "branch"], cwd=tmp_repo_with_release,
                              capture_output=True, text=True).stdout
    assert "release/1.1" not in branches


def test_cleanup_proceeds_when_no_pr_exists(tmp_repo_with_release: Path, fixed_owner: str):
    _promoted_uncleaned(tmp_repo_with_release, fixed_owner)
    gh = FakeGh({"view": (1, "", "no pull requests found for branch \"release/1.1\"")})
    result = cleanup(tmp_repo_with_release, version="1.1", gh_runner=gh)
    assert result["ok"] is True


def test_cleanup_refuses_when_gh_fails_for_other_reason(tmp_repo_with_release: Path, fixed_owner: str):
    """gh erroring for any other reason = unknown PR state = fail safe, with the
    --force-cleanup override named."""
    _promoted_uncleaned(tmp_repo_with_release, fixed_owner)
    gh = FakeGh({"view": (1, "", "could not determine base repo: no github remotes")})
    with pytest.raises((RuntimeError, Gate2FailedError), match="force-cleanup"):
        cleanup(tmp_repo_with_release, version="1.1", gh_runner=gh)


def test_cleanup_refuses_when_gh_binary_missing(tmp_repo_with_release: Path, fixed_owner: str):
    _promoted_uncleaned(tmp_repo_with_release, fixed_owner)

    def no_gh(cmd, **kwargs):
        raise FileNotFoundError("gh")

    with pytest.raises((RuntimeError, Gate2FailedError), match="force-cleanup"):
        cleanup(tmp_repo_with_release, version="1.1", gh_runner=no_gh)


def test_cleanup_force_overrides_pr_check(tmp_repo_with_release: Path, fixed_owner: str):
    _promoted_uncleaned(tmp_repo_with_release, fixed_owner)

    def must_not_be_called(cmd, **kwargs):
        raise AssertionError("gh must not run when --force-cleanup is given")

    result = cleanup(tmp_repo_with_release, version="1.1", gh_runner=must_not_be_called, force=True)
    assert result["ok"] is True
    branches = subprocess.run(["git", "branch"], cwd=tmp_repo_with_release,
                              capture_output=True, text=True).stdout
    assert "release/1.1" not in branches


def test_cli_has_force_cleanup_flag():
    from scripts.promote_release import _build_parser
    p = _build_parser()
    assert p.parse_args([]).force_cleanup is False
    assert p.parse_args(["--cleanup-only", "1.1", "--force-cleanup"]).force_cleanup is True


def test_cleanup_sweep_warns_and_continues_past_missing_catalog_entry(
    tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys
):
    """A6: the per-feature promote-stamp in the cleanup sweep must not kill the
    whole sweep when one entry drifted — warn (naming the id) and continue."""
    import scripts.promote_release as pr_mod
    from lib.catalog import CatalogEntryNotFoundError, mark_promoted_to_main as real_mark

    feat_a = _setup_and_ship_feature(tmp_repo_with_release, fixed_owner, title="A")
    # Ship a second feature into the same release.
    idea_b = new_idea(tmp_repo_with_release, title="B")
    feat_b = promote_idea_to_refined(tmp_repo_with_release, idea_b["id"])
    claim_b = claim_feature(tmp_repo_with_release, feat_b["id"], owner=fixed_owner)
    wt_b = Path(claim_b["worktree"])
    (wt_b / "b.txt").write_text("b")
    subprocess.run(["git", "add", "."], cwd=wt_b, check=True)
    subprocess.run(["git", "commit", "-m", "feat: b"], cwd=wt_b, check=True, capture_output=True)
    ship_current_work(wt_b)

    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=False,
                    push=False, keep=True, use_pr=False)

    def flaky_mark(cat, fid):
        if fid == feat_a["id"]:
            raise CatalogEntryNotFoundError(fid, cat)
        return real_mark(cat, fid)

    monkeypatch.setattr(pr_mod, "mark_promoted_to_main", flaky_mark)
    gh = FakeGh({"view": (1, "", "no pull requests found")})
    cleanup(tmp_repo_with_release, version="1.1", gh_runner=gh)

    err = capsys.readouterr().err
    assert feat_a["id"] in err  # one-line warning names the drifted id

    cat = json.loads(
        (tmp_repo_with_release / ".claude" / "refined_backlog" / "_catalog.json").read_text()
    )
    by_id = {e["id"]: e for e in cat}
    assert by_id[feat_b["id"]]["status"] == "promoted"  # sweep continued
    # feat_a's remaining cleanup steps still ran (folder archived).
    archive = tmp_repo_with_release / ".claude" / "refined_backlog" / "_archive" / "1.1"
    assert list(archive.glob(f"{feat_a['id']}-*"))


def test_deploy_runs_from_release_worktree_not_main_checkout(tmp_repo_with_release, monkeypatch):
    """--deploy must execute deploy-local.sh from the _release worktree.

    The local DB may already be migrated AHEAD of main by the release's own
    migrations (ship deploys release/<v>), so deploying main's tree fails
    alembic with "Can't locate revision".
    """
    from scripts.init_work_new_release import new_release
    from scripts import promote_release as pr

    new_release(tmp_repo_with_release)
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"

    # A deploy script in BOTH trees, each recording the cwd it ran from.
    receipt = tmp_repo_with_release / "deploy-cwd.txt"
    for tree, tag in ((tmp_repo_with_release, "MAIN"), (rel_wt, "RELEASE")):
        scripts_dir = tree / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        sh = scripts_dir / "deploy-local.sh"
        sh.write_text(f'#!/bin/sh\necho {tag} "$PWD" >> "{receipt}"\n')
        sh.chmod(0o755)

    calls = []
    real_run = pr.subprocess.run

    def spy(cmd, *a, **kw):
        calls.append((cmd, kw.get("cwd")))
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(pr.subprocess, "run", spy)

    try:
        pr.promote_release(tmp_repo_with_release, run_deploy=True, run_gate2=False, use_pr=False)
    except Exception:
        pass  # we only assert on the deploy invocation, not the whole promote

    deploy_calls = [c for c in calls if "deploy-local.sh" in str(c[0])]
    assert deploy_calls, "deploy-local.sh was never invoked"
    # promote_release() does `repo = Path(repo).resolve()`; on macOS tmp_path sits
    # under /private/var while /var is a symlink, so compare RESOLVED paths.
    assert Path(deploy_calls[0][1]).resolve() == rel_wt.resolve(), (
        f"deploy ran from {deploy_calls[0][1]}, expected the _release worktree {rel_wt}"
    )
    assert "RELEASE" in receipt.read_text()
    assert "MAIN" not in receipt.read_text()


# ── Task 14: Gate 2 + deploy resolve their scripts through the hooks block ─────


def _poison_or_point_hooks(rel_wt: Path, hooks: dict, message: str) -> None:
    """Commit a `hooks` block on the release branch, in the _release worktree.

    Gate 2 and the deploy resolve from THIS tree (not the main checkout), so the
    hooks block that governs them is the release branch's own.
    """
    rj = rel_wt / ".release.json"
    state = json.loads(rj.read_text())
    state["hooks"] = hooks
    rj.write_text(json.dumps(state, indent=2) + "\n")
    subprocess.run(["git", "add", "-A"], cwd=rel_wt, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=rel_wt, check=True, capture_output=True)


def test_gate2_honours_a_custom_hooks_path(tmp_repo_with_release: Path, fixed_owner: str):
    """hooks.integration on the release branch is what Gate 2 executes."""
    _setup_and_ship_feature(tmp_repo_with_release, fixed_owner, with_integration=False)
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    marker = tmp_repo_with_release.parent / "custom-gate2.marker"  # outside the repo: survives cleanup
    (rel_wt / "ci").mkdir(parents=True, exist_ok=True)
    sh = rel_wt / "ci" / "integ.sh"
    sh.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 0\n')
    sh.chmod(0o755)
    _poison_or_point_hooks(rel_wt, {"integration": "ci/integ.sh"}, "custom gate2 hook")

    promote_release(tmp_repo_with_release, run_gate2=True, run_deploy=False,
                    push=False, use_pr=False)
    assert marker.exists(), "the hooks.integration script never ran"


def test_gate2_bad_hooks_path_refuses_before_touching_main(
    tmp_repo_with_release: Path, fixed_owner: str
):
    """An unusable hooks.integration must refuse the promote, not skip the gate."""
    from lib.hooks import HookPathError
    _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    _poison_or_point_hooks(rel_wt, {"integration": "../../evil.sh"}, "poison hooks.integration")

    with pytest.raises(HookPathError):
        promote_release(tmp_repo_with_release, run_gate2=True, run_deploy=False,
                        push=False, use_pr=False)
    log = subprocess.run(["git", "log", "main", "--oneline"], cwd=tmp_repo_with_release,
                         capture_output=True, text=True).stdout
    assert "release 1.1" not in log.lower()


def test_deploy_honours_a_custom_hooks_path(tmp_repo_with_release: Path, fixed_owner: str):
    """hooks.deploy_local on the release branch is what --deploy executes."""
    _setup_and_ship_feature(tmp_repo_with_release, fixed_owner)
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    receipt = tmp_repo_with_release.parent / "custom-deploy.txt"
    (rel_wt / "ci").mkdir(parents=True, exist_ok=True)
    sh = rel_wt / "ci" / "deploy.sh"
    sh.write_text(f'#!/bin/sh\necho "$PWD" >> "{receipt}"\nexit 0\n')
    sh.chmod(0o755)
    _poison_or_point_hooks(rel_wt, {"deploy_local": "ci/deploy.sh"}, "custom deploy hook")

    promote_release(tmp_repo_with_release, run_gate2=False, run_deploy=True,
                    push=False, use_pr=False)
    assert receipt.exists(), "the hooks.deploy_local script never ran"
    assert Path(receipt.read_text().strip().splitlines()[0]).resolve() == rel_wt.resolve(), (
        "the custom deploy hook must still run from the _release worktree"
    )
