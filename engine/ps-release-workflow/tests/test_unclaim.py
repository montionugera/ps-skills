"""unclaim: release a claimed feature — remove worktree, clear ledger+catalog, keep branch (B2)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.init_work_new_release import new_release
from scripts.new_idea import new_idea
from scripts.promote_idea_to_refined import promote_idea_to_refined
from scripts.init_work_refined_backlog import claim_feature
from scripts.unclaim import (
    DirtyWorktreeError,
    FeatureNotFoundError,
    NotClaimedError,
    unclaim_feature,
)


def _setup_claimed_feature(repo: Path, owner: str = "session-a") -> tuple[dict, dict]:
    new_release(repo, version="1.1")
    idea = new_idea(repo, title="X")
    feat = promote_idea_to_refined(repo, idea["id"])
    claimed = claim_feature(repo, feat["id"], owner=owner)
    return feat, claimed


def _read_claims(repo: Path) -> dict:
    return json.loads((repo / ".claude" / "state" / "claims.json").read_text())


def _release_catalog_entry(repo: Path, feature_id: str) -> dict:
    wt = repo / ".claude" / "worktrees" / "_release"
    cat = json.loads((wt / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    return next(e for e in cat if e["id"] == feature_id)


def _branch_exists(repo: Path, name: str) -> bool:
    cp = subprocess.run(
        ["git", "rev-parse", "--verify", name], cwd=repo, capture_output=True
    )
    return cp.returncode == 0


def test_unclaim_happy_path(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    feat, claimed = _setup_claimed_feature(repo)

    result = unclaim_feature(repo, feat["id"])
    assert result["worktree_removed"] is True
    assert not Path(claimed["worktree"]).exists()
    assert feat["id"] not in _read_claims(repo)

    entry = _release_catalog_entry(repo, feat["id"])
    assert entry["status"] == "open"
    assert entry["claimed_by"] is None

    # The feature BRANCH is always kept — committed work is preserved.
    assert result["branch_kept"] is True
    assert _branch_exists(repo, claimed["branch"])

    # _release worktree clean: the catalog commit landed, no stray files.
    wt = repo / ".claude" / "worktrees" / "_release"
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"], cwd=wt, capture_output=True, text=True
    )
    assert porcelain.stdout.strip() == ""


def test_unclaim_refuses_dirty_worktree(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    feat, claimed = _setup_claimed_feature(repo)
    (Path(claimed["worktree"]) / "uncommitted.txt").write_text("precious\n")

    with pytest.raises(DirtyWorktreeError):
        unclaim_feature(repo, feat["id"])

    # Nothing was mutated: worktree, ledger, catalog all intact.
    assert Path(claimed["worktree"]).is_dir()
    assert feat["id"] in _read_claims(repo)
    assert _release_catalog_entry(repo, feat["id"])["status"] == "claimed"


def test_unclaim_force_discards_dirty_worktree(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    feat, claimed = _setup_claimed_feature(repo)
    (Path(claimed["worktree"]) / "uncommitted.txt").write_text("disposable\n")

    result = unclaim_feature(repo, feat["id"], force=True)
    assert result["worktree_removed"] is True
    assert not Path(claimed["worktree"]).exists()
    assert feat["id"] not in _read_claims(repo)
    assert _release_catalog_entry(repo, feat["id"])["status"] == "open"
    assert _branch_exists(repo, claimed["branch"])


def test_unclaim_worktree_already_gone_still_cleans_state(tmp_repo_with_release: Path):
    """Drift case: worktree deleted out-of-band — ledger + catalog still cleaned."""
    repo = tmp_repo_with_release
    feat, claimed = _setup_claimed_feature(repo)
    shutil.rmtree(claimed["worktree"])

    result = unclaim_feature(repo, feat["id"])
    assert result["worktree_removed"] is False
    assert feat["id"] not in _read_claims(repo)
    entry = _release_catalog_entry(repo, feat["id"])
    assert entry["status"] == "open"
    assert entry["claimed_by"] is None
    assert _branch_exists(repo, claimed["branch"])


def test_unclaim_refuses_feature_not_claimed(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    idea = new_idea(repo, title="X")
    feat = promote_idea_to_refined(repo, idea["id"])  # status: open

    with pytest.raises(NotClaimedError):
        unclaim_feature(repo, feat["id"])


def test_unclaim_unknown_feature_raises(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    with pytest.raises(FeatureNotFoundError):
        unclaim_feature(repo, "F-999")


def test_unclaim_heals_ledger_only_orphan(tmp_repo_with_release: Path, capsys):
    """M-1 drift: a claims.json row whose id is ABSENT from the catalog (e.g. a
    claim that crashed mid-rollback). unclaim is the healing tool — it must drop
    the ledger row (and remove the worktree, if any) with a warning, not die
    with FeatureNotFoundError."""
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    orphan_wt = repo / ".claude" / "worktrees" / "F-001-orphan"
    (repo / ".claude" / "state" / "claims.json").write_text(json.dumps({
        "F-001": {"owner": "ghost-session", "worktree": str(orphan_wt),
                  "claimed_at": "2026-01-01T00:00:00+00:00"},
    }))

    result = unclaim_feature(repo, "F-001")
    assert result["catalog_entry_missing"] is True
    assert "F-001" not in _read_claims(repo), "the orphan ledger row must be dropped"
    err = capsys.readouterr().err
    assert "catalog" in err.lower(), "must warn that the catalog had no such entry"

    # The catalog itself is untouched (there was nothing to reopen).
    wt = repo / ".claude" / "worktrees" / "_release"
    cat = json.loads((wt / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    assert cat == []


def test_unclaim_heals_ledger_only_orphan_with_real_worktree(tmp_repo_with_release: Path):
    """Same drift, but the orphan row points at a REAL worktree — unclaim must
    remove it too."""
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    orphan_wt = repo / ".claude" / "worktrees" / "F-001-orphan"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feat/F-001", str(orphan_wt), "main"],
        cwd=repo, check=True, capture_output=True,
    )
    (repo / ".claude" / "state" / "claims.json").write_text(json.dumps({
        "F-001": {"owner": "ghost-session", "worktree": str(orphan_wt),
                  "claimed_at": "2026-01-01T00:00:00+00:00"},
    }))

    result = unclaim_feature(repo, "F-001")
    assert result["catalog_entry_missing"] is True
    assert result["worktree_removed"] is True
    assert not orphan_wt.exists()
    assert "F-001" not in _read_claims(repo)
    assert _branch_exists(repo, "feat/F-001"), "the branch is still always kept"


def test_unclaim_main_reports_unknown_feature_cleanly(
    tmp_repo_with_release: Path, monkeypatch, capsys
):
    """CLI surface (A6): a typo'd id exits 1 with an ERROR line, no traceback."""
    import sys as _sys
    from scripts.unclaim import main as unclaim_main
    new_release(tmp_repo_with_release, version="1.1")
    monkeypatch.chdir(tmp_repo_with_release)
    monkeypatch.setattr(_sys, "argv", ["unclaim.py", "F-999"])
    assert unclaim_main() == 1
    err = capsys.readouterr().err
    assert "F-999" in err
    assert "Traceback" not in err
