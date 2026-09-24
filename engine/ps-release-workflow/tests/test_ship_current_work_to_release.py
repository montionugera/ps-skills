"""ship_current_work_to_release: Gate 1 + merge feat → release."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.epic import epic_fanout, epic_open
from scripts.init_work_new_release import new_release
from scripts.new_idea import new_idea
from scripts.promote_idea_to_refined import promote_idea_to_refined
from scripts.init_work_refined_backlog import claim_feature
from scripts.ship_current_work_to_release import (
    ship_current_work, DirtyTreeError, GateFailedError, NotInFeatureWorktreeError,
)


def _scaffold_precheck(repo: Path, body: str = "#!/bin/sh\nexit 0\n") -> None:
    """Commit scripts/precheck.sh on main (call BEFORE cutting release/feature branches
    so both the feature worktree and the _release worktree carry it)."""
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    pre = scripts_dir / "precheck.sh"
    pre.write_text(body)
    pre.chmod(0o755)
    subprocess.run(["git", "add", "scripts/precheck.sh"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "scaffold precheck"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True, capture_output=True)


def _make_repo_with_open_release_and_claim(tmp_repo_with_release: Path, fixed_owner: str,
                                           with_precheck: bool = True):
    # Gate 1 stub is committed on main FIRST so the feature worktree (cut from
    # main at claim) and the _release worktree (cut at new_release) both have it.
    if with_precheck:
        _scaffold_precheck(tmp_repo_with_release)
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea["id"], allow_empty_spec=True)
    claim = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    return feat, claim


def test_ship_merges_feat_into_release(tmp_repo_with_release: Path, fixed_owner: str):
    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    # Make a commit in the feature worktree.
    (wt / "feature.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "feat: add feature.txt"], cwd=wt, check=True, capture_output=True)
    ship_current_work(wt)
    # Verify feature.txt is on release/1.1 (the _release worktree is checked out on it).
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    assert (rel_wt / "feature.txt").exists()


def test_ship_refuses_dirty_tree(tmp_repo_with_release: Path, fixed_owner: str):
    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    (wt / "uncommitted.txt").write_text("x")
    with pytest.raises(DirtyTreeError):
        ship_current_work(wt)


def test_ship_marks_catalog_shipped(tmp_repo_with_release: Path, fixed_owner: str):
    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    (wt / "x.txt").write_text("y")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "x"], cwd=wt, check=True, capture_output=True)
    ship_current_work(wt)
    # Read the _RELEASE worktree catalog (NOT main) — that's where the populated catalog lives (D11).
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    cat = json.loads((rel_wt / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    f = next(e for e in cat if e["id"] == feat["id"])
    assert f["status"] == "shipped"
    assert f["release_version"] == "1.1"
    # MAIN's catalog must remain empty — no leakage to main (D11).
    main_cat = json.loads((tmp_repo_with_release / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    assert main_cat == []


def test_ship_failing_precheck_in_worktree_aborts_before_merge(tmp_repo_with_release: Path, fixed_owner: str):
    """Gate 1 failure in the FEATURE worktree must abort the ship before any
    merge touches the _release worktree."""
    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    # Break precheck IN THE WORKTREE — Gate 1 verifies the code being shipped.
    (wt / "scripts" / "precheck.sh").write_text("#!/bin/sh\nexit 1\n")
    (wt / "x.txt").write_text("y")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "x"], cwd=wt, check=True, capture_output=True)

    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    head_before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rel_wt,
                                 capture_output=True, text=True, check=True).stdout.strip()
    with pytest.raises(GateFailedError):
        ship_current_work(wt)
    # No merge happened: release HEAD unchanged, feature file absent.
    head_after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rel_wt,
                                capture_output=True, text=True, check=True).stdout.strip()
    assert head_after == head_before
    assert not (rel_wt / "x.txt").exists()


def test_ship_runs_precheck_from_feature_worktree_then_release_worktree(tmp_repo_with_release: Path, fixed_owner: str, tmp_path: Path):
    """Gate 1 must execute the FEATURE WORKTREE's scripts/precheck.sh (cwd=worktree),
    and the post-merge re-verify must execute it from the _release worktree
    (cwd=rel_wt). The MAIN checkout's precheck.sh is made to exit 1, so the old
    behavior (resolving from the main checkout) would abort the ship."""
    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    marker = tmp_path / "precheck-cwds.txt"

    # Worktree precheck records its cwd; committed on the feature branch.
    (wt / "scripts" / "precheck.sh").write_text(f"#!/bin/sh\npwd >> {marker}\nexit 0\n")
    (wt / "feature.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "feat: record precheck cwd"], cwd=wt, check=True, capture_output=True)

    # MAIN checkout's precheck now fails — if ship resolved precheck from the
    # main checkout (the A5 bug), the ship would raise GateFailedError.
    (tmp_repo_with_release / "scripts" / "precheck.sh").write_text("#!/bin/sh\nexit 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_repo_with_release, check=True)
    subprocess.run(["git", "commit", "-m", "break main precheck"], cwd=tmp_repo_with_release, check=True, capture_output=True)

    ship_current_work(wt)

    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    assert (rel_wt / "feature.txt").exists()
    cwds = [os.path.realpath(line) for line in marker.read_text().splitlines() if line.strip()]
    assert len(cwds) == 2, f"expected Gate 1 + post-merge re-verify runs, got {cwds}"
    assert cwds[0] == os.path.realpath(wt), "Gate 1 must run with cwd = feature worktree"
    assert cwds[1] == os.path.realpath(rel_wt), "post-merge re-verify must run with cwd = _release worktree"


def test_ship_warns_but_ships_when_precheck_absent(tmp_repo_with_release: Path, fixed_owner: str, capsys):
    """No scripts/precheck.sh in the relevant trees: ship must still work, but
    print a loud Gate 1 SKIPPED warning on stderr (not silently skip)."""
    feat, claim = _make_repo_with_open_release_and_claim(
        tmp_repo_with_release, fixed_owner, with_precheck=False)
    wt = Path(claim["worktree"])
    (wt / "feature.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "feat"], cwd=wt, check=True, capture_output=True)

    result = ship_current_work(wt)

    assert result["ok"] is True
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    assert (rel_wt / "feature.txt").exists()
    err = capsys.readouterr().err
    assert "Gate 1 SKIPPED" in err
    assert "scripts/precheck.sh not found" in err
    assert str(wt) in err  # names the tree it looked in


def test_two_features_ship_into_same_release(tmp_repo_with_release: Path, fixed_owner: str):
    """Sequential ship of two features into one release — proves the file_lock
    doesn't break the normal path: both end up status=shipped and both feature
    files land on release/<v> in the _release worktree."""
    # Stub a passing Gate 1 script on main BEFORE cutting any branches.
    _scaffold_precheck(tmp_repo_with_release)
    new_release(tmp_repo_with_release, version="1.1")

    # Feature A.
    idea_a = new_idea(tmp_repo_with_release, title="Feature A")
    feat_a = promote_idea_to_refined(tmp_repo_with_release, idea_a["id"], allow_empty_spec=True)
    claim_a = claim_feature(tmp_repo_with_release, feat_a["id"], owner=fixed_owner)
    wt_a = Path(claim_a["worktree"])
    (wt_a / "feature_a.txt").write_text("A")
    subprocess.run(["git", "add", "."], cwd=wt_a, check=True)
    subprocess.run(["git", "commit", "-m", "feat: A"], cwd=wt_a, check=True, capture_output=True)
    ship_current_work(wt_a)

    # Feature B.
    idea_b = new_idea(tmp_repo_with_release, title="Feature B")
    feat_b = promote_idea_to_refined(tmp_repo_with_release, idea_b["id"], allow_empty_spec=True)
    claim_b = claim_feature(tmp_repo_with_release, feat_b["id"], owner=fixed_owner)
    wt_b = Path(claim_b["worktree"])
    (wt_b / "feature_b.txt").write_text("B")
    subprocess.run(["git", "add", "."], cwd=wt_b, check=True)
    subprocess.run(["git", "commit", "-m", "feat: B"], cwd=wt_b, check=True, capture_output=True)
    ship_current_work(wt_b)

    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    # Both feature files on release/1.1.
    assert (rel_wt / "feature_a.txt").exists()
    assert (rel_wt / "feature_b.txt").exists()
    # Both shipped in the _release catalog.
    cat = json.loads((rel_wt / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    by_id = {e["id"]: e for e in cat}
    assert by_id[feat_a["id"]]["status"] == "shipped"
    assert by_id[feat_b["id"]]["status"] == "shipped"


def test_ship_refuses_when_not_in_feature_worktree(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    with pytest.raises(NotInFeatureWorktreeError):
        ship_current_work(tmp_repo_with_release)  # main checkout, not a feat worktree


# ── A6: a drifted/typo'd feature id must fail loudly, not silently no-op ───────


def _commit_feature_file(wt: Path) -> None:
    (wt / "feature.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "feat: add feature.txt"], cwd=wt, check=True, capture_output=True)


def test_ship_unknown_catalog_entry_raises(tmp_repo_with_release: Path, fixed_owner: str):
    """If the worktree's marker feature id is missing from the release catalog
    (drift), ship must raise — not rewrite the catalog unchanged and 'succeed'."""
    from lib.catalog import CatalogEntryNotFoundError
    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    _commit_feature_file(wt)
    cat = (tmp_repo_with_release / ".claude" / "worktrees" / "_release"
           / ".claude" / "refined_backlog" / "_catalog.json")
    cat.write_text("[]\n")  # simulate the entry drifting away
    with pytest.raises(CatalogEntryNotFoundError, match=feat["id"]):
        ship_current_work(wt)


def test_ship_main_reports_unknown_catalog_entry_cleanly(
    tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys
):
    """CLI surface: exit 1 + one ERROR line naming the id — no traceback."""
    import sys as _sys
    from scripts.ship_current_work_to_release import main as ship_main
    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    _commit_feature_file(wt)
    cat = (tmp_repo_with_release / ".claude" / "worktrees" / "_release"
           / ".claude" / "refined_backlog" / "_catalog.json")
    cat.write_text("[]\n")
    monkeypatch.chdir(wt)
    monkeypatch.setattr(_sys, "argv", ["ship_current_work_to_release.py", "--no-deploy"])
    assert ship_main() == 1
    err = capsys.readouterr().err
    assert "ERROR: CatalogEntryNotFoundError" in err
    assert feat["id"] in err
    assert "Traceback" not in err


def test_ship_commits_crashed_catalog_mutation(tmp_repo_with_release: Path, fixed_owner: str):
    """M-2: a previous ship crashed between mark_shipped and commit_all — the
    catalog already says shipped but the change is uncommitted. Re-running ship
    sees 'no change' from mark_shipped; it must still commit the dirty tree."""
    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    _commit_feature_file(wt)

    # Crash simulation: mutate the _release catalog ON DISK, no commit.
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    cat_path = rel_wt / ".claude" / "refined_backlog" / "_catalog.json"
    cat = json.loads(cat_path.read_text())
    entry = next(e for e in cat if e["id"] == feat["id"])
    entry.update({"status": "shipped", "release_version": "1.1",
                  "shipped_at": "2026-01-01T00:00:00+00:00"})
    cat_path.write_text(json.dumps(cat, indent=2) + "\n")
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=rel_wt,
                           capture_output=True, text=True).stdout.strip()
    assert dirty, "precondition: the _release worktree must be dirty"

    result = ship_current_work(wt)
    assert result["ok"] is True

    porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=rel_wt,
                               capture_output=True, text=True).stdout.strip()
    assert porcelain == "", "ship must commit the crashed catalog mutation"
    cat = json.loads(cat_path.read_text())
    assert next(e for e in cat if e["id"] == feat["id"])["status"] == "shipped"


def test_ship_main_reports_git_error_cleanly(
    tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys
):
    """M-2: a GitError inside ship must exit 1 with one ERROR line — no raw
    traceback (GitError was missing from main()'s except tuple)."""
    import sys as _sys
    import scripts.ship_current_work_to_release as ship_mod
    from lib.git_ops import GitError

    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    _commit_feature_file(wt)

    def boom(*args, **kwargs):
        raise GitError("simulated: git commit failed")

    monkeypatch.setattr(ship_mod, "commit_all", boom)
    monkeypatch.chdir(wt)
    monkeypatch.setattr(_sys, "argv", ["ship_current_work_to_release.py", "--no-deploy"])
    assert ship_mod.main() == 1
    err = capsys.readouterr().err
    assert "ERROR: GitError" in err
    assert "Traceback" not in err


def test_ship_twice_is_idempotent_no_empty_recommit(tmp_repo_with_release: Path, fixed_owner: str):
    """Re-shipping an already-shipped feature stays OK: the catalog entry is
    already in the target state, so no rewrite/commit happens the second time."""
    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    _commit_feature_file(wt)
    ship_current_work(wt)
    result = ship_current_work(wt)  # merge is 'Already up to date'; mark is a no-op
    assert result["ok"] is True
    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    cat = json.loads((rel_wt / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    assert next(e for e in cat if e["id"] == feat["id"])["status"] == "shipped"


def test_help_does_not_ship(tmp_path):
    """--help must print usage and never reach ship_current_work()."""
    import subprocess, sys
    from pathlib import Path
    script = Path(__file__).resolve().parent.parent / "scripts" / "ship_current_work_to_release.py"
    proc = subprocess.run([sys.executable, str(script), "--help"], cwd=tmp_path,
                          env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
                          capture_output=True, text=True)
    assert proc.returncode == 0
    out = proc.stdout.lower()
    assert "usage:" in out
    assert "--no-deploy" in proc.stdout, "the deploy flags must be documented in usage"


def test_deploy_and_no_deploy_are_mutually_exclusive(tmp_path):
    import subprocess, sys
    from pathlib import Path
    script = Path(__file__).resolve().parent.parent / "scripts" / "ship_current_work_to_release.py"
    proc = subprocess.run([sys.executable, str(script), "--deploy", "--no-deploy"],
                          cwd=tmp_path, env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
                          capture_output=True, text=True)
    assert proc.returncode == 2
    assert "not allowed with" in proc.stderr


def test_unrecognized_flag_exits_2_before_the_merge(tmp_path):
    """An unrecognised flag used to be silently ignored (sniffed via `in
    sys.argv`) and the ship still happened. Now argparse rejects it and exits
    2 before ship_current_work() — and therefore the merge — ever runs."""
    import subprocess, sys
    from pathlib import Path
    script = Path(__file__).resolve().parent.parent / "scripts" / "ship_current_work_to_release.py"
    proc = subprocess.run([sys.executable, str(script), "--frobnicate"],
                          cwd=tmp_path, env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
                          capture_output=True, text=True)
    assert proc.returncode == 2
    assert "unrecognized argument" in proc.stderr


# ── Task 14: Gate 1 resolves precheck through the .release.json hooks block ────


def test_precheck_honours_a_custom_hooks_path(tmp_path):
    """Gate 1 resolves precheck from the hooks block, still from the FEATURE tree."""
    from scripts import ship_current_work_to_release as ship

    tree = tmp_path / "feature"
    (tree / "ci").mkdir(parents=True)
    (tree / ".release.json").write_text(json.dumps(
        {"version": "1.1", "in_progress": True, "hooks": {"precheck": "ci/check.sh"}}))
    sh = tree / "ci" / "check.sh"
    sh.write_text("#!/bin/sh\nexit 7\n")
    sh.chmod(0o755)

    assert ship._run_precheck(tree) == 7, "custom precheck path was not used"


def test_precheck_falls_back_to_scripts_precheck_sh(tmp_path):
    from scripts import ship_current_work_to_release as ship
    tree = tmp_path / "plain"
    (tree / "scripts").mkdir(parents=True)
    sh = tree / "scripts" / "precheck.sh"
    sh.write_text("#!/bin/sh\nexit 3\n")
    sh.chmod(0o755)
    assert ship._run_precheck(tree) == 3


def test_precheck_missing_still_returns_none(tmp_path):
    from scripts import ship_current_work_to_release as ship
    tree = tmp_path / "empty"
    tree.mkdir()
    assert ship._run_precheck(tree) is None


def test_precheck_refuses_a_hooks_path_outside_the_tree(tmp_path):
    """Unit: an unusable hooks.precheck makes Gate 1 RAISE, never silently skip."""
    from scripts import ship_current_work_to_release as ship

    tree = tmp_path / "rel"
    tree.mkdir()
    (tree / ".release.json").write_text(json.dumps(
        {"version": "1.1", "in_progress": True, "hooks": {"precheck": "../../evil.sh"}}))

    with pytest.raises(GateFailedError):
        ship._run_precheck(tree)


def test_bad_hooks_path_post_merge_rolls_back_the_merge(
    tmp_repo_with_release: Path, fixed_owner: str
):
    """End-to-end: a Gate 1 refusal AFTER the merge must reset release/<v>.

    Reachable for real: the RELEASE branch's .release.json carries a bad
    hooks.precheck while the feature branch's (cut from main) does not — so the
    pre-merge Gate 1 passes, `git merge --no-ff` commits, and only then does
    Gate 1 refuse. Without the rollback at the post-merge call site the feature
    stays merged on release/<v> while ship reports failure.
    """
    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    _commit_feature_file(wt)

    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    rj = rel_wt / ".release.json"
    state = json.loads(rj.read_text())
    state["hooks"] = {"precheck": "/etc/passwd"}  # absolute → refused
    rj.write_text(json.dumps(state, indent=2) + "\n")
    subprocess.run(["git", "commit", "-am", "poison hooks.precheck on the release branch"],
                   cwd=rel_wt, check=True, capture_output=True)

    # Precondition: the FEATURE tree has no hooks block, so pre-merge Gate 1
    # passes and the failure can only happen post-merge.
    assert json.loads((wt / ".release.json").read_text()).get("hooks") is None
    head_before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rel_wt,
                                 capture_output=True, text=True, check=True).stdout.strip()

    with pytest.raises(GateFailedError):
        ship_current_work(wt)

    head_after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rel_wt,
                                capture_output=True, text=True, check=True).stdout.strip()
    assert head_after == head_before, "the merge was left standing on release/<v>"
    assert not (rel_wt / "feature.txt").exists(), "the feature file is still on release/<v>"
    porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=rel_wt,
                               capture_output=True, text=True).stdout.strip()
    assert porcelain == "", f"the _release worktree was left dirty: {porcelain}"


# ── Final review #3: ship's post-merge deploy also resolves through hooks ──────


def test_ship_main_runs_a_custom_hooks_deploy_local(
    tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys
):
    """ship hardcoded rel_wt/scripts/deploy-local.sh while promote resolved the
    same key through resolve_hook, so a repo with a custom hooks.deploy_local got
    a deploy from promote and a SILENT no-op from ship (the .exists() gate just
    failed) — despite ship/SKILL.md advertising "the repo's own local deploy
    script (default scripts/deploy-local.sh)"."""
    import sys as _sys
    import scripts.ship_current_work_to_release as ship_mod

    repo = tmp_repo_with_release
    _scaffold_precheck(repo)
    # Custom deploy script + hooks block committed on main BEFORE the branches are
    # cut, so both the feature worktree and the _release worktree carry them.
    (repo / "ci").mkdir()
    dep = repo / "ci" / "deploy.sh"
    dep.write_text("#!/bin/sh\ntouch custom-deploy.ran\nexit 0\n")
    dep.chmod(0o755)
    rj = repo / ".release.json"
    state = json.loads(rj.read_text())
    state["hooks"] = {"deploy_local": "ci/deploy.sh"}
    rj.write_text(json.dumps(state, indent=2) + "\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "custom deploy hook"], cwd=repo,
                   check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True, capture_output=True)

    feat, claim = _make_repo_with_open_release_and_claim(repo, fixed_owner,
                                                        with_precheck=False)
    wt = Path(claim["worktree"])
    _commit_feature_file(wt)

    monkeypatch.chdir(wt)
    monkeypatch.setattr(_sys, "argv", ["ship_current_work_to_release.py", "--deploy"])
    assert ship_mod.main() == 0

    rel_wt = repo / ".claude" / "worktrees" / "_release"
    assert (rel_wt / "custom-deploy.ran").exists(), (
        "ship skipped the custom hooks.deploy_local script"
    )
    out = capsys.readouterr().out
    assert "Running local deployment" in out


def test_ship_main_refuses_a_bad_hooks_deploy_local_loudly(
    tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys
):
    """An unusable hooks.deploy_local must not silently skip the deploy. It is
    raised AFTER the merge landed, so the message must say the ship succeeded and
    hand over the manual command — and the exit code stays 0, matching the
    existing precedent that a deploy script which runs and fails also leaves ship
    successful."""
    import sys as _sys
    import scripts.ship_current_work_to_release as ship_mod

    feat, claim = _make_repo_with_open_release_and_claim(tmp_repo_with_release, fixed_owner)
    wt = Path(claim["worktree"])
    _commit_feature_file(wt)

    rel_wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    rj = rel_wt / ".release.json"
    state = json.loads(rj.read_text())
    state["hooks"] = {"deploy_local": "/usr/bin/true"}  # absolute → refused
    rj.write_text(json.dumps(state, indent=2) + "\n")
    subprocess.run(["git", "commit", "-am", "poison hooks.deploy_local"],
                   cwd=rel_wt, check=True, capture_output=True)
    # Precondition: the FEATURE tree has no hooks block, so Gate 1 is unaffected.
    assert json.loads((wt / ".release.json").read_text()).get("hooks") is None

    monkeypatch.chdir(wt)
    monkeypatch.setattr(_sys, "argv", ["ship_current_work_to_release.py", "--deploy"])
    assert ship_mod.main() == 0, "the merge landed; ship must not report failure"

    captured = capsys.readouterr()
    assert "REFUSED" in captured.err
    assert "deploy_local" in captured.err
    assert "SUCCEEDED" in captured.err, "the message must say the merge landed"
    assert "deploy by hand" in captured.err, "the manual command must be offered"
    assert "Traceback" not in captured.err
    # The merge really did stand — this is not the rollback path.
    assert (rel_wt / "feature.txt").exists()


def _scaffold_epic_check(repo: Path, body: str = "#!/bin/sh\nexit 0\n") -> None:
    """Commit scripts/epic-check.sh on main BEFORE cutting release/feature
    branches, same pattern as _scaffold_precheck, so the release tree snapshot
    G-E2 runs against carries it."""
    d = repo / "scripts"
    d.mkdir(exist_ok=True)
    f = d / "epic-check.sh"
    f.write_text(body)
    f.chmod(0o755)
    subprocess.run(["git", "add", "scripts/epic-check.sh"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "scaffold epic-check"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True, capture_output=True)


def _ship_single_slice_epic_feature(repo: Path, fixed_owner: str, epic_check_body: str):
    """Scaffold precheck + epic-check on main, open a 1-slice epic, promote that
    slice into a feature, claim + ship it. Completeness is true the moment this
    single slice ships, so this ship is the one that wins the G-E2 CAS.
    Returns (epic_id, feature_id, rel_wt)."""
    _scaffold_precheck(repo)
    _scaffold_epic_check(repo, epic_check_body)
    new_release(repo, version="1.1")
    epic = epic_open(repo, "Cap the risk")
    epic_id = epic["epic"]["id"]
    fan = epic_fanout(repo, epic_id, ["cap it"])
    idea_id = fan["ideas"][0]["id"]
    feat = promote_idea_to_refined(repo, idea_id, allow_empty_spec=True)
    claim = claim_feature(repo, feat["id"], owner=fixed_owner)
    wt = Path(claim["worktree"])
    _commit_feature_file(wt)
    ship_current_work(wt)
    rel_wt = repo / ".claude" / "worktrees" / "_release"
    return epic_id, feat["id"], rel_wt, wt


def test_failing_epic_check_leaves_the_merge_standing(tmp_repo_with_release: Path, fixed_owner: str):
    """v1 rolled the merge back on ANY post-merge gate failure; that erased the
    failure record ship_current_work_to_release.py:earlier wrote and made a
    re-run land on an emptied tree. The epic outcome check is NOT that gate —
    G-E3 (Task 4) guards the way to main, so a failing epic must leave
    release/<v> exactly as shipped."""
    repo = tmp_repo_with_release
    epic_id, feature_id, rel_wt, _wt = _ship_single_slice_epic_feature(
        repo, fixed_owner, "#!/bin/sh\nexit 3\n"
    )
    epic_cat = json.loads((rel_wt / ".claude" / "epic_backlog" / "_catalog.json").read_text())
    epic_entry = next(e for e in epic_cat if e["id"] == epic_id)
    assert epic_entry["status"] == "failed_verification"

    refined_cat = json.loads((rel_wt / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    feature_entry = next(e for e in refined_cat if e["id"] == feature_id)
    assert feature_entry["status"] == "shipped"  # merge still standing

    log = subprocess.run(["git", "log", "--oneline", "-5"], cwd=rel_wt,
                         capture_output=True, text=True, check=True).stdout
    assert feature_id in log


def test_second_ship_does_not_run_a_second_check(tmp_repo_with_release: Path, fixed_owner: str):
    """The CAS must let exactly one caller through. try_begin_verification's own
    lost-CAS behavior is unit-tested in tests/test_epic.py — this proves the
    SHIP WIRING actually honors it: a re-ship of an already-verified epic's
    feature (worktree clean, merge a no-op, HEAD unchanged) must not re-run
    epic-check.sh, because try_begin_verification refuses a non-idle status
    without --force."""
    repo = tmp_repo_with_release
    epic_id, feature_id, rel_wt, wt = _ship_single_slice_epic_feature(
        repo, fixed_owner, '#!/bin/sh\necho ran >> "$PSRW_EPIC_DIR/marker"\nexit 0\n'
    )
    epic_dir = rel_wt / ".claude" / "epic_backlog"
    marker = next(epic_dir.glob(f"{epic_id}-*")) / "marker"
    assert marker.read_text().count("\n") == 1

    epic_cat = json.loads((rel_wt / ".claude" / "epic_backlog" / "_catalog.json").read_text())
    assert next(e for e in epic_cat if e["id"] == epic_id)["status"] == "verified"

    # Re-ship the same, already-merged feature worktree — a no-op merge, so HEAD
    # does not move and the feature stays "shipped" (mark_shipped is idempotent).
    ship_current_work(wt)

    assert marker.read_text().count("\n") == 1, "epic-check.sh must not have run again"
    epic_cat = json.loads((rel_wt / ".claude" / "epic_backlog" / "_catalog.json").read_text())
    assert next(e for e in epic_cat if e["id"] == epic_id)["status"] == "verified"


# ── Silent deploy skip: a missing deploy script must be announced ──────────────


def _ship_main(repo: Path, fixed_owner: str, monkeypatch, *flags: str) -> int:
    import sys as _sys
    import scripts.ship_current_work_to_release as ship_mod
    feat, claim = _make_repo_with_open_release_and_claim(repo, fixed_owner)
    wt = Path(claim["worktree"])
    _commit_feature_file(wt)
    monkeypatch.chdir(wt)
    monkeypatch.setattr(_sys, "argv", ["ship_current_work_to_release.py", *flags])
    return ship_mod.main()


def test_ship_main_announces_when_no_local_deploy_is_configured(
    tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys
):
    """No scripts/deploy-local.sh and no hooks.deploy_local: ship used to print
    NOTHING about the deploy, so a stale local cluster went unnoticed."""
    assert _ship_main(tmp_repo_with_release, fixed_owner, monkeypatch) == 0
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "no local deploy configured" in text
    assert "scripts/deploy-local.sh" in text and "hooks.deploy_local" in text


def test_ship_main_no_deploy_flag_is_not_reported_as_unconfigured(
    tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys
):
    """--no-deploy is an explicit choice: it must not print the 'not configured'
    notice (the two reasons for skipping stay distinguishable)."""
    assert _ship_main(tmp_repo_with_release, fixed_owner, monkeypatch, "--no-deploy") == 0
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "no local deploy configured" not in text
    assert "--no-deploy" in text
