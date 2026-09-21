"""init_work_refined_backlog: atomic claim of F-NNN + per-feature worktree (D11/SR-1/D12)."""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from lib.git_ops import GitError
from scripts.init_work_new_release import new_release
from scripts.new_idea import new_idea
from scripts.promote_idea_to_refined import promote_idea_to_refined
import scripts.init_work_refined_backlog as claim_mod
from scripts.init_work_refined_backlog import (
    claim_feature,
    resume_feature,
    AlreadyClaimedError,
    NoFreeFeatureError,
    NotClaimedError,
    NoReleaseInProgressError,
)


def _setup_feature(repo: Path, title: str = "X") -> dict:
    """Open a release (so the _release worktree exists), capture+promote one idea."""
    idea = new_idea(repo, title=title)
    return promote_idea_to_refined(repo, idea["id"], allow_empty_spec=True)


def test_claim_creates_worktree_with_marker(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)
    result = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    assert Path(result["worktree"]).is_dir()
    assert result["feature"] == feat["id"]
    assert result["branch"] == f"feat/{feat['id']}"


def test_claim_writes_marker_in_git_worktree_metadata(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)
    result = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    wt_dir = Path(result["worktree"]).name  # <F-id>-<slug>
    marker = tmp_repo_with_release / ".git" / "worktrees" / wt_dir / "working-feature.json"
    assert marker.exists()
    marker_data = json.loads(marker.read_text())
    assert marker_data["feature"] == feat["id"]
    assert marker_data["owner"] == fixed_owner


def test_claim_updates_claims_json(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)
    claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    claims = json.loads(
        (tmp_repo_with_release / ".claude" / "state" / "claims.json").read_text()
    )
    assert feat["id"] in claims
    assert claims[feat["id"]]["owner"] == fixed_owner


def test_claim_marks_feature_status_claimed(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)
    claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    # Read the catalog in the _RELEASE worktree (not the main checkout).
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    cat = json.loads((wt / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    entry = next(e for e in cat if e["id"] == feat["id"])
    assert entry["status"] == "claimed"
    assert entry["claimed_by"] == fixed_owner

    # _release worktree must be clean (no stray .lock / .tmp, commit landed).
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"], cwd=wt, capture_output=True, text=True
    )
    assert porcelain.stdout.strip() == ""


def test_claim_collision_raises_already_claimed(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)
    claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    with pytest.raises(AlreadyClaimedError):
        claim_feature(tmp_repo_with_release, feat["id"], owner="another-owner")


def test_claim_next_picks_first_unclaimed(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    for t in ["A", "B", "C"]:
        idea = new_idea(tmp_repo_with_release, title=t)
        promote_idea_to_refined(tmp_repo_with_release, idea["id"], allow_empty_spec=True)
    claim_feature(tmp_repo_with_release, "F-001", owner=fixed_owner)
    result = claim_feature(tmp_repo_with_release, None, owner="other", select_next=True)
    assert result["feature"] == "F-002"


def test_claim_next_with_no_unclaimed_raises(tmp_repo_with_release: Path, fixed_owner: str):
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)
    claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    with pytest.raises(NoFreeFeatureError):
        claim_feature(tmp_repo_with_release, None, owner="other", select_next=True)


def test_claim_refuses_when_no_release_in_progress(tmp_repo_with_release: Path, fixed_owner: str):
    # No new_release() -> .release.json.in_progress is False (fixture default).
    # Release check happens before feature lookup, so no feature need exist.
    with pytest.raises(NoReleaseInProgressError):
        claim_feature(tmp_repo_with_release, "F-001", owner=fixed_owner)


# --- Transactional claim (audit A4) ------------------------------------------


def test_worktree_creation_failure_rolls_back_claim(
    tmp_repo_with_release: Path, fixed_owner: str, monkeypatch
):
    """A failed worktree creation must leave NO half-state: no claims.json entry,
    catalog untouched — and a subsequent claim of the same feature succeeds."""
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)

    def boom(*args, **kwargs):
        raise GitError("simulated: git worktree add failed")

    monkeypatch.setattr(claim_mod, "add_worktree_new_branch", boom)
    with pytest.raises(GitError):
        claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)

    claims = json.loads(
        (tmp_repo_with_release / ".claude" / "state" / "claims.json").read_text()
    )
    assert feat["id"] not in claims, "claims.json entry must be rolled back"

    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    cat = json.loads((wt / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    entry = next(e for e in cat if e["id"] == feat["id"])
    assert entry["status"] == "open", "catalog must be unchanged after a failed claim"

    # No half-state left behind: retrying (with the real git op) must succeed.
    monkeypatch.undo()
    result = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    assert Path(result["worktree"]).is_dir()


def test_concurrent_double_claim_yields_exactly_one_winner(
    tmp_repo_with_release: Path,
):
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)

    results: list[dict] = []
    losers: list[Exception] = []

    def attempt(owner: str) -> None:
        try:
            results.append(claim_feature(tmp_repo_with_release, feat["id"], owner=owner))
        except AlreadyClaimedError as e:
            losers.append(e)

    with ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(attempt, ["owner-a", "owner-b"]))

    assert len(results) == 1, f"exactly one claim must win, got {len(results)}"
    assert len(losers) == 1
    claims = json.loads(
        (tmp_repo_with_release / ".claude" / "state" / "claims.json").read_text()
    )
    assert claims[feat["id"]]["owner"] == results[0]["owner"]


def test_main_reports_git_error_cleanly(
    tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys
):
    """A GitError inside claim must exit 1 with an ERROR line, not a traceback."""
    new_release(tmp_repo_with_release, version="1.1")
    feat = _setup_feature(tmp_repo_with_release)

    def boom(*args, **kwargs):
        raise GitError("simulated: git worktree add failed")

    monkeypatch.setattr(claim_mod, "add_worktree_new_branch", boom)
    monkeypatch.chdir(tmp_repo_with_release)
    monkeypatch.setattr("sys.argv", ["init_work_refined_backlog.py", feat["id"]])
    assert claim_mod.main() == 1
    err = capsys.readouterr().err
    assert "ERROR: GitError" in err


# --- --resume F-NNN (audit B2) ------------------------------------------------


def _read_marker(repo: Path, worktree: Path) -> dict:
    return json.loads(
        (repo / ".git" / "worktrees" / Path(worktree).name / "working-feature.json").read_text()
    )


def _read_claims(repo: Path) -> dict:
    return json.loads((repo / ".claude" / "state" / "claims.json").read_text())


def _release_catalog_entry(repo: Path, feature_id: str) -> dict:
    wt = repo / ".claude" / "worktrees" / "_release"
    cat = json.loads((wt / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    return next(e for e in cat if e["id"] == feature_id)


def test_resume_rewrites_owner_in_marker_and_claims(tmp_repo_with_release: Path):
    """Case (a): worktree + marker intact — resume re-owns to the current session."""
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    feat = _setup_feature(repo)
    claimed = claim_feature(repo, feat["id"], owner="old-session")

    result = resume_feature(repo, feat["id"], owner="new-session")
    assert result["worktree"] == claimed["worktree"]
    assert result["recreated"] is False

    assert _read_marker(repo, Path(result["worktree"]))["owner"] == "new-session"
    assert _read_claims(repo)[feat["id"]]["owner"] == "new-session"
    entry = _release_catalog_entry(repo, feat["id"])
    assert entry["status"] == "claimed"
    assert entry["claimed_by"] == "new-session"


def test_resume_heals_missing_claims_entry(tmp_repo_with_release: Path):
    """Catalog-only drift: claimed in the catalog but absent from claims.json."""
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    feat = _setup_feature(repo)
    claim_feature(repo, feat["id"], owner="old-session")
    # Simulate the observed drift: ledger lost the entry entirely.
    (repo / ".claude" / "state" / "claims.json").write_text("{}")

    result = resume_feature(repo, feat["id"], owner="new-session")
    claims = _read_claims(repo)
    assert feat["id"] in claims, "resume must recreate the missing ledger entry"
    assert claims[feat["id"]]["owner"] == "new-session"
    assert claims[feat["id"]]["worktree"] == result["worktree"]


def test_resume_recreates_deleted_worktree_keeping_commits(tmp_repo_with_release: Path):
    """Case (b): worktree dir deleted out-of-band, branch survives — recreate the
    worktree ON that branch with prior commits intact."""
    import shutil

    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    feat = _setup_feature(repo)
    claimed = claim_feature(repo, feat["id"], owner="old-session")
    wt_path = Path(claimed["worktree"])

    # Commit real work on the feature branch, then lose the worktree (drift).
    (wt_path / "work.txt").write_text("in-flight work\n")
    subprocess.run(["git", "add", "."], cwd=wt_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "wip"], cwd=wt_path, check=True, capture_output=True
    )
    shutil.rmtree(wt_path)

    result = resume_feature(repo, feat["id"], owner="new-session")
    assert result["recreated"] is True
    new_wt = Path(result["worktree"])
    assert new_wt.is_dir()
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=new_wt, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert branch == f"feat/{feat['id']}"
    assert (new_wt / "work.txt").read_text() == "in-flight work\n", "prior commits must survive"
    assert _read_marker(repo, new_wt)["owner"] == "new-session"
    assert _read_claims(repo)[feat["id"]]["owner"] == "new-session"
    assert _release_catalog_entry(repo, feat["id"])["status"] == "claimed"


def test_resume_recreates_branch_and_worktree_when_both_gone(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    feat = _setup_feature(repo)
    claimed = claim_feature(repo, feat["id"], owner="old-session")

    subprocess.run(
        ["git", "worktree", "remove", "--force", claimed["worktree"]],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "branch", "-D", claimed["branch"]], cwd=repo, check=True, capture_output=True
    )

    result = resume_feature(repo, feat["id"], owner="new-session")
    assert result["recreated"] is True
    new_wt = Path(result["worktree"])
    assert new_wt.is_dir()
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=new_wt, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert branch == claimed["branch"]
    assert _read_claims(repo)[feat["id"]]["owner"] == "new-session"


def test_resume_refuses_feature_not_claimed(tmp_repo_with_release: Path):
    """Case (c): status != claimed — clear error pointing at plain claim."""
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    feat = _setup_feature(repo)  # status: open, never claimed
    with pytest.raises(NotClaimedError) as exc:
        resume_feature(repo, feat["id"], owner="new-session")
    assert "claim" in str(exc.value).lower()


# --- B-1: unclaim → re-claim re-attaches the surviving branch -----------------


def _commit_work(worktree: Path, name: str = "work.txt") -> None:
    (worktree / name).write_text("in-flight work\n")
    subprocess.run(["git", "add", "."], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "wip"], cwd=worktree, check=True, capture_output=True)


def _branch_exists(repo: Path, name: str) -> bool:
    cp = subprocess.run(["git", "rev-parse", "--verify", name], cwd=repo, capture_output=True)
    return cp.returncode == 0


def test_reclaim_after_unclaim_reattaches_existing_branch(
    tmp_repo_with_release: Path, fixed_owner: str, capsys
):
    """claim → commit → unclaim keeps feat/F-NNN; the NEXT claim must re-attach
    to that branch (prior commits intact) instead of dying on 'already exists'."""
    from scripts.unclaim import unclaim_feature

    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    feat = _setup_feature(repo)
    claimed = claim_feature(repo, feat["id"], owner=fixed_owner)
    _commit_work(Path(claimed["worktree"]))
    unclaim_feature(repo, feat["id"])
    assert _branch_exists(repo, claimed["branch"])  # unclaim keeps the branch

    result = claim_feature(repo, feat["id"], owner="second-session")
    assert result["reattached"] is True
    new_wt = Path(result["worktree"])
    assert new_wt.is_dir()
    assert (new_wt / "work.txt").read_text() == "in-flight work\n", "prior commits must survive"
    assert "re-attached" in capsys.readouterr().err
    claims = _read_claims(repo)
    assert claims[feat["id"]]["owner"] == "second-session"


def test_rollback_after_reattach_keeps_preexisting_branch(
    tmp_repo_with_release: Path, fixed_owner: str, monkeypatch
):
    """A failure AFTER re-attaching must remove the worktree but NOT delete the
    pre-existing branch — the claim didn't create it, so it must not destroy it."""
    from scripts.unclaim import unclaim_feature

    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    feat = _setup_feature(repo)
    claimed = claim_feature(repo, feat["id"], owner=fixed_owner)
    _commit_work(Path(claimed["worktree"]))
    unclaim_feature(repo, feat["id"])

    orig_write_text = Path.write_text

    def boom(self, *args, **kwargs):
        if self.name == "working-feature.json":
            raise OSError("simulated: marker write failed")
        return orig_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", boom)
    with pytest.raises(OSError):
        claim_feature(repo, feat["id"], owner="second-session")
    monkeypatch.undo()

    assert not Path(claimed["worktree"]).exists(), "worktree must be torn down"
    assert _branch_exists(repo, claimed["branch"]), "pre-existing branch must be KEPT"
    assert feat["id"] not in _read_claims(repo), "ledger row must be rolled back"


# --- M-1: rollback covers the catalog step ------------------------------------


def test_catalog_step_failure_rolls_back_everything(
    tmp_repo_with_release: Path, fixed_owner: str, monkeypatch
):
    """A CatalogEntryNotFoundError in the catalog mutate/commit step must tear
    down the worktree, the self-created branch, and the ledger row — no
    half-state that wedges the feature."""
    from lib.catalog import CatalogEntryNotFoundError

    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    feat = _setup_feature(repo)
    slug_wt = repo / ".claude" / "worktrees"

    def boom(*args, **kwargs):
        raise CatalogEntryNotFoundError(feat["id"], Path("catalog"))

    monkeypatch.setattr(claim_mod, "update_entry", boom)
    with pytest.raises(CatalogEntryNotFoundError):
        claim_feature(repo, feat["id"], owner=fixed_owner)

    assert not list(slug_wt.glob(f"{feat['id']}-*")), "worktree must be torn down"
    assert not _branch_exists(repo, f"feat/{feat['id']}"), "self-created branch must be deleted"
    assert feat["id"] not in _read_claims(repo), "ledger row must be rolled back"

    # No half-state left: retrying with the real catalog step must succeed.
    monkeypatch.undo()
    result = claim_feature(repo, feat["id"], owner=fixed_owner)
    assert Path(result["worktree"]).is_dir()


# --- m-3: marker-write failure exercises the teardown branch -------------------


def test_marker_write_failure_tears_down_worktree_and_branch(
    tmp_repo_with_release: Path, fixed_owner: str, monkeypatch
):
    """Fail at the MARKER WRITE step (after the worktree/branch exist): the
    rollback must remove the worktree AND the self-created branch, and the
    ledger must have no row."""
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    feat = _setup_feature(repo)

    orig_write_text = Path.write_text

    def boom(self, *args, **kwargs):
        if self.name == "working-feature.json":
            raise OSError("simulated: marker write failed")
        return orig_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", boom)
    with pytest.raises(OSError):
        claim_feature(repo, feat["id"], owner=fixed_owner)
    monkeypatch.undo()

    wt_root = repo / ".claude" / "worktrees"
    assert not list(wt_root.glob(f"{feat['id']}-*")), "worktree must be torn down"
    assert not _branch_exists(repo, f"feat/{feat['id']}"), "self-created branch must be deleted"
    assert feat["id"] not in _read_claims(repo), "ledger row must be rolled back"


# --- M-2: dirty _release worktree still gets committed (crashed-commit heal) ---


def test_resume_commits_crashed_catalog_mutation(tmp_repo_with_release: Path):
    """Simulate a previous resume that crashed between the catalog mutation and
    the commit: the entry already says claimed_by=<owner> but the _release
    worktree is dirty. Re-running resume must commit the dangling change."""
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    feat = _setup_feature(repo)
    claim_feature(repo, feat["id"], owner="old-session")

    # Crash simulation: mutate the catalog ON DISK (no commit) — exactly the
    # state a kill between update_entry and commit_all leaves behind.
    wt = repo / ".claude" / "worktrees" / "_release"
    cat_path = wt / ".claude" / "refined_backlog" / "_catalog.json"
    cat = json.loads(cat_path.read_text())
    next(e for e in cat if e["id"] == feat["id"])["claimed_by"] = "new-session"
    cat_path.write_text(json.dumps(cat, indent=2) + "\n")
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=wt,
                           capture_output=True, text=True).stdout.strip()
    assert dirty, "precondition: the _release worktree must be dirty"

    resume_feature(repo, feat["id"], owner="new-session")

    porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=wt,
                               capture_output=True, text=True).stdout.strip()
    assert porcelain == "", "resume must commit the crashed catalog mutation"
    assert _release_catalog_entry(repo, feat["id"])["claimed_by"] == "new-session"


# --- m-2: dirty resume warns loudly ---------------------------------------------


def test_dirty_resume_warns_about_previous_owners_changes(
    tmp_repo_with_release: Path, capsys
):
    """Resuming a worktree that has uncommitted changes from the previous owner
    must print a loud warning naming them (no --force required — just warn)."""
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    feat = _setup_feature(repo)
    claimed = claim_feature(repo, feat["id"], owner="old-session")
    (Path(claimed["worktree"]) / "half-done.txt").write_text("uncommitted\n")

    result = resume_feature(repo, feat["id"], owner="new-session")
    assert result["owner"] == "new-session"  # resume still succeeds

    err = capsys.readouterr().err
    assert "uncommitted" in err.lower()
    assert "half-done.txt" in err, "the warning must list the dirty files"


def test_claim_main_reports_unknown_feature_cleanly(
    tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys
):
    """CLI surface (A6): a typo'd feature id exits 1 with an ERROR line, no traceback."""
    import sys as _sys
    new_release(tmp_repo_with_release, version="1.1")
    monkeypatch.chdir(tmp_repo_with_release)
    monkeypatch.setattr(_sys, "argv", ["init_work_refined_backlog.py", "F-999"])
    assert claim_mod.main() == 1
    err = capsys.readouterr().err
    assert "F-999" in err
    assert "Traceback" not in err
