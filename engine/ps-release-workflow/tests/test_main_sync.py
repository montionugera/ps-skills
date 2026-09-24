"""A hotfix merged to main must reach the in-progress release/<v> before any
ship, deploy or promote runs from it (joy-companion 2026-09-24: release/1.6
was deployed locally without hotfix #7, silently dropping its UI)."""
import subprocess
import sys
from pathlib import Path

import pytest

from tests._helpers import git
from scripts.init_work_new_release import new_release
from scripts.new_idea import new_idea
from scripts.promote_idea_to_refined import promote_idea_to_refined
from scripts.init_work_refined_backlog import claim_feature
from scripts.ship_current_work_to_release import ship_current_work, GateFailedError
from lib.main_sync import MainSyncConflictError, sync_main_into_release


def _land_on_origin_main(repo: Path, path: str, content: str, msg: str = "hotfix") -> str:
    """Simulate a GitHub squash-merge: origin/main advances, the local main
    checkout does NOT (exactly what a PR merge does). Returns the new sha."""
    clone = repo.parent / f"clone-{abs(hash((path, content))) % 10**8}"
    if not clone.exists():
        subprocess.run(["git", "clone", "-q", str(repo.parent / "origin.git"), str(clone)],
                       check=True, capture_output=True)
        git(clone, "config", "user.email", "t@t")
        git(clone, "config", "user.name", "T")
    git(clone, "pull", "-q", "origin", "main")
    (clone / path).parent.mkdir(parents=True, exist_ok=True)
    (clone / path).write_text(content)
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", msg)
    git(clone, "push", "-q", "origin", "HEAD:main")
    return git(clone, "rev-parse", "HEAD")


def _scaffold_precheck(repo: Path, body: str = "#!/bin/sh\nexit 0\n") -> None:
    d = repo / "scripts"
    d.mkdir(exist_ok=True)
    (d / "precheck.sh").write_text(body)
    (d / "precheck.sh").chmod(0o755)
    git(repo, "add", "scripts/precheck.sh")
    git(repo, "commit", "-q", "-m", "precheck")
    git(repo, "push", "-q", "origin", "main")


def _claimed_feature_with_commit(repo: Path, owner: str) -> Path:
    new_release(repo, version="1.1")
    idea = new_idea(repo, title="Feature")
    feat = promote_idea_to_refined(repo, idea["id"], allow_empty_spec=True)
    wt = Path(claim_feature(repo, feat["id"], owner=owner)["worktree"])
    (wt / "feature.txt").write_text("feature\n")
    git(wt, "add", ".")
    git(wt, "commit", "-q", "-m", "feat")
    return wt


def _rel_wt(repo: Path) -> Path:
    return repo / ".claude" / "worktrees" / "_release"


def test_ship_merges_a_hotfix_from_main_into_the_release_first(
    tmp_repo_with_release: Path, fixed_owner: str
):
    repo = tmp_repo_with_release
    _scaffold_precheck(repo)
    wt = _claimed_feature_with_commit(repo, fixed_owner)
    hotfix_sha = _land_on_origin_main(repo, "hotfix.txt", "urgent\n")

    result = ship_current_work(wt)

    rel = _rel_wt(repo)
    assert (rel / "hotfix.txt").exists(), "the hotfix on main never reached release/1.1"
    assert (rel / "feature.txt").exists()
    subprocess.run(["git", "merge-base", "--is-ancestor", hotfix_sha, "HEAD"], cwd=rel, check=True)
    assert result["main_synced"] == 1


def test_ship_refuses_loudly_with_the_exact_command_on_a_sync_conflict(
    tmp_repo_with_release: Path, fixed_owner: str
):
    repo = tmp_repo_with_release
    _scaffold_precheck(repo)
    wt = _claimed_feature_with_commit(repo, fixed_owner)
    rel = _rel_wt(repo)
    (rel / "README.md").write_text("release side\n")
    git(rel, "commit", "-q", "-am", "release edits README")
    _land_on_origin_main(repo, "README.md", "hotfix side\n")
    pre = git(rel, "rev-parse", "HEAD")

    with pytest.raises(MainSyncConflictError) as ei:
        ship_current_work(wt)

    msg = str(ei.value)
    assert "README.md" in msg
    assert f"cd {rel}" in msg and "git merge origin/main" in msg
    assert git(rel, "rev-parse", "HEAD") == pre, "a conflicted sync must leave release untouched"
    assert git(rel, "status", "--porcelain") == ""
    assert not (rel / "feature.txt").exists(), "the feature must not merge over a failed sync"


def test_gate1_failure_after_sync_rolls_back_both_the_sync_and_the_merge(
    tmp_repo_with_release: Path, fixed_owner: str
):
    """HEAD~1 rollback would leave the untested sync standing — reset to the
    pre-ship head instead."""
    repo = tmp_repo_with_release
    # Passes in the feature worktree (no hotfix.txt), fails on the synced release.
    _scaffold_precheck(repo, "#!/bin/sh\ntest ! -e hotfix.txt\n")
    wt = _claimed_feature_with_commit(repo, fixed_owner)
    rel = _rel_wt(repo)
    pre = git(rel, "rev-parse", "HEAD")
    _land_on_origin_main(repo, "hotfix.txt", "urgent\n")

    with pytest.raises(GateFailedError):
        ship_current_work(wt)
    assert git(rel, "rev-parse", "HEAD") == pre


def test_ship_main_refuses_to_deploy_a_release_that_is_behind_main(
    tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys
):
    """Defense in depth: a hotfix landing between the merge and the deploy must
    block the deploy, never deploy a release missing main's commits."""
    import scripts.ship_current_work_to_release as ship_mod
    repo = tmp_repo_with_release
    _scaffold_precheck(repo)
    marker = repo.parent / "deploy.ran"
    (repo / "scripts" / "deploy-local.sh").write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    (repo / "scripts" / "deploy-local.sh").chmod(0o755)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "deploy script")
    git(repo, "push", "-q", "origin", "main")
    wt = _claimed_feature_with_commit(repo, fixed_owner)

    real = ship_mod.ship_current_work

    def ship_then_hotfix_lands(*a, **kw):
        out = real(*a, **kw)
        _land_on_origin_main(repo, "late-hotfix.txt", "late\n")
        return out

    monkeypatch.setattr(ship_mod, "ship_current_work", ship_then_hotfix_lands)
    monkeypatch.chdir(wt)
    monkeypatch.setattr(sys, "argv", ["ship_current_work_to_release.py", "--deploy"])
    assert ship_mod.main() == 0, "the merge landed; only the deploy is refused"
    assert not marker.exists(), "deployed a release that is missing a commit on main"
    err = capsys.readouterr().err
    assert "behind main" in err and "psrw hotfix --sync-release" in err


def test_promote_syncs_main_before_gate2_and_push(tmp_repo_with_release: Path, fixed_owner: str):
    from scripts.promote_release import promote_release

    class Gh:
        def __call__(self, cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, stdout="https://x/pull/1", stderr="")

    repo = tmp_repo_with_release
    _scaffold_precheck(repo)
    wt = _claimed_feature_with_commit(repo, fixed_owner)
    ship_current_work(wt)
    _land_on_origin_main(repo, "hotfix.txt", "urgent\n")

    promote_release(repo, run_gate2=False, run_deploy=False, gh_runner=Gh())
    origin = repo.parent / "origin.git"
    assert git(origin, "show", "release/1.1:hotfix.txt") == "urgent"


def test_hotfix_sync_release_merges_main_into_the_open_release(
    tmp_repo_with_release: Path, fixed_owner: str
):
    from scripts.hotfix import sync_release
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    _land_on_origin_main(repo, "hotfix.txt", "urgent\n")

    result = sync_release(repo)
    assert result["synced"] == 1
    assert (_rel_wt(repo) / "hotfix.txt").exists()
    assert sync_release(repo)["synced"] == 0, "second run must be a no-op"


def test_sync_refuses_when_main_touched_release_bookkeeping(tmp_repo_with_release: Path):
    """main's .release.json / backlog catalogs differ from release/<v> by design;
    an auto-merge that silently rewrote them could end the release."""
    from lib.state import file_lock
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    _land_on_origin_main(repo, ".claude/refined_backlog/_catalog.json", "[]\n\n")
    rel = _rel_wt(repo)
    pre = git(rel, "rev-parse", "HEAD")
    with file_lock(rel):
        with pytest.raises(MainSyncConflictError, match="_catalog.json"):
            sync_main_into_release(repo, rel, "release/1.1")
    assert git(rel, "rev-parse", "HEAD") == pre


def test_bookkeeping_refusal_offers_a_merge_that_keeps_the_release_copy(tmp_repo_with_release: Path):
    from lib.state import file_lock
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    _land_on_origin_main(repo, ".release.json", "{}\n")
    rel = _rel_wt(repo)
    with file_lock(rel):
        with pytest.raises(MainSyncConflictError) as ei:
            sync_main_into_release(repo, rel, "release/1.1")
    assert "git checkout HEAD -- .release.json" in str(ei.value)


def test_hotfix_sync_release_refuses_while_the_release_is_being_promoted(
    tmp_repo_with_release: Path,
):
    """promote runs Gate 2 and the push outside the _release lock; a sync under
    it would ship a tree Gate 2 never verified."""
    from lib.release_freeze import freeze_release
    from scripts.hotfix import sync_release
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    freeze_release(repo, "1.1")
    _land_on_origin_main(repo, "hotfix.txt", "urgent\n")
    with pytest.raises(MainSyncConflictError, match="being promoted"):
        sync_release(repo)
    assert not (_rel_wt(repo) / "hotfix.txt").exists()
