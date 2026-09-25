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
from lib.main_sync import (
    MainSyncConflictError, MainUnreachableError, resolve_main_ref, sync_main_into_release,
)


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
    assert "behind main" in err and "psrw sync-main" in err


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


# ── Primitive-level behaviour (ported from the release/1.6 unit tests) ─────────


def test_resolve_main_ref_prefers_a_fetched_origin_main(tmp_repo_with_release: Path):
    assert resolve_main_ref(tmp_repo_with_release) == "origin/main"


def test_resolve_main_ref_falls_back_to_local_main_without_an_origin(tmp_path: Path):
    repo = tmp_path / "solo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "T")
    (repo / "README.md").write_text("solo\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "init")
    assert resolve_main_ref(repo) == "main"


def test_resolve_main_ref_strict_refuses_when_origin_main_cannot_be_fetched(
    tmp_repo_with_release: Path, capsys
):
    """Default: a failed fetch warns and uses the last-fetched origin/main (it
    may miss a just-merged hotfix). --strict turns that into a refusal."""
    repo = tmp_repo_with_release
    git(repo, "remote", "set-url", "origin", str(repo.parent / "gone.git"))
    with pytest.raises(MainUnreachableError, match="cannot fetch origin/main"):
        resolve_main_ref(repo, strict=True)
    assert resolve_main_ref(repo) == "origin/main"
    assert "git fetch origin main failed" in capsys.readouterr().err


def test_sync_main_into_release_absorbs_main_and_is_idempotent(tmp_repo_with_release: Path):
    from lib.state import file_lock
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    rel = _rel_wt(repo)
    hotfix_sha = _land_on_origin_main(repo, "hotfix.txt", "urgent\n")
    assert not (rel / "hotfix.txt").exists()

    with file_lock(rel):
        assert sync_main_into_release(repo, rel, "release/1.1") == 1
    assert (rel / "hotfix.txt").read_text() == "urgent\n"
    assert git(rel, "status", "--porcelain") == "", "the sync must be committed"
    subprocess.run(["git", "merge-base", "--is-ancestor", hotfix_sha, "HEAD"], cwd=rel, check=True)

    with file_lock(rel):
        assert sync_main_into_release(repo, rel, "release/1.1") == 0, "second sync is a no-op"


def test_sync_main_into_release_conflict_aborts_and_restores_the_tree(tmp_repo_with_release: Path):
    from lib.state import file_lock
    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    rel = _rel_wt(repo)
    (rel / "README.md").write_text("release side\n")
    git(rel, "commit", "-q", "-am", "release edits README")
    _land_on_origin_main(repo, "README.md", "hotfix side\n")
    pre = git(rel, "rev-parse", "HEAD")

    with file_lock(rel):
        with pytest.raises(MainSyncConflictError, match="README.md"):
            sync_main_into_release(repo, rel, "release/1.1")

    assert git(rel, "rev-parse", "HEAD") == pre
    assert git(rel, "status", "--porcelain") == ""
    in_merge = subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                              cwd=rel, capture_output=True)
    assert in_merge.returncode != 0, "the conflicted merge must have been aborted"
