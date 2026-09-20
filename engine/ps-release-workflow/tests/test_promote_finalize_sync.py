"""Guard: cleanup() must finalize .release.json onto origin/main even when the
PR squash-merge has advanced origin under a diverged local main.

Regression target: cleanup() used to commit the finalize on the local (diverged)
main and `git push origin main` in a try/except that SWALLOWED the non-ff
failure — leaving origin's .release.json stale (in_progress: true) and local main
diverged, with no error. These tests build a real `origin` remote, reproduce the
divergence, and assert the finalize lands on origin + local main is synced.
"""
import json
import subprocess
from pathlib import Path

import pytest

from scripts.promote_release import cleanup, _finalize_release_state
from tests._helpers import git as _git


def _gh_no_pr(cmd, **kwargs):
    """Stub gh runner: no PR exists for any branch (B3 check passes)."""
    return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no pull requests found")


def _release_json(in_progress: bool) -> str:
    return json.dumps({
        "version": "1.1",
        "in_progress": in_progress,
        "started_at": "2026-01-01T00:00:00+00:00",
        "started_by": "tester",
        "last_promoted_at": "2026-01-01T00:00:00+00:00",
        "last_promoted_version": "1.0",
    }, indent=2) + "\n"


def _opt_in_repo(repo: Path, in_progress: bool = True) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "checkout", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "T")
    (repo / ".release.json").write_text(_release_json(in_progress))
    claude = repo / ".claude"
    (claude / "refined_backlog").mkdir(parents=True)
    (claude / "refined_backlog" / "_catalog.json").write_text("[]")
    (claude / "state").mkdir(parents=True)
    (claude / "state" / "claims.json").write_text("{}")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "opt in")


def test_cleanup_finalizes_onto_origin_after_pr_squash_divergence(tmp_path: Path):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", str(origin))

    repo = tmp_path / "repo"
    _opt_in_repo(repo, in_progress=True)
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")

    # Simulate the GitHub squash-merge: a second clone adds a commit (the released
    # code) and pushes it to origin/main. .release.json stays in_progress:true,
    # exactly as the release branch carried it.
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(origin), str(clone))
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "T")
    _git(clone, "checkout", "main")  # bare's default HEAD may not be 'main'
    (clone / "released.txt").write_text("shipped\n")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "release 1.1 (#99)")
    _git(clone, "push", "origin", "main")

    # Simulate the disposable local bookkeeping commit on main → local main now
    # DIVERGES from origin/main (different child of the opt-in commit).
    (repo / "localnote.txt").write_text("start bookkeeping\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "chore(release): start 1.1")

    cleanup(repo, version="1.1", gh_runner=_gh_no_pr)

    # 1. origin/main .release.json is finalized (the bug left it stale).
    origin_rj = json.loads(_git(origin, "show", "main:.release.json"))
    assert origin_rj["in_progress"] is False
    assert origin_rj["last_promoted_version"] == "1.1"

    # 2. Local main is synced to origin/main (not diverged) and carries the squash.
    assert _git(repo, "rev-parse", "main") == _git(origin, "rev-parse", "main")
    assert (repo / "released.txt").exists()
    # the disposable local bookkeeping commit was correctly discarded
    assert not (repo / "localnote.txt").exists()


def test_cleanup_refuses_to_reset_over_uncommitted_tracked_changes(tmp_path: Path):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", str(origin))
    repo = tmp_path / "repo"
    _opt_in_repo(repo, in_progress=True)
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")

    # Advance origin/main (the squash) so cleanup would want to reset to it.
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(origin), str(clone))
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "T")
    _git(clone, "checkout", "main")
    (clone / "released.txt").write_text("shipped\n")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "release 1.1 (#99)")
    _git(clone, "push", "origin", "main")

    # Uncommitted tracked edit in the main checkout must NOT be silently nuked.
    (repo / ".release.json").write_text(_release_json(in_progress=True).replace("tester", "EDITED"))
    with pytest.raises(RuntimeError, match="uncommitted tracked changes"):
        cleanup(repo, version="1.1", gh_runner=_gh_no_pr)


def test_cleanup_local_only_repo_still_finalizes(tmp_path: Path):
    # No origin remote (the local-only / test case): cleanup finalizes locally
    # and must not crash trying to fetch/push.
    repo = tmp_path / "repo"
    _opt_in_repo(repo, in_progress=True)

    cleanup(repo, version="1.1")

    rj = json.loads((repo / ".release.json").read_text())
    assert rj["in_progress"] is False
    assert rj["last_promoted_version"] == "1.1"


# ── Fix #2: finalize on the release branch so the PR squash carries it ──────────

def _release_worktree(path: Path, in_progress: bool = True) -> None:
    """A git repo standing in for the _release worktree, on a release branch."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "checkout", "-b", "release/1.1")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "T")
    (path / ".release.json").write_text(_release_json(in_progress))
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "release wip")


def test_finalize_release_state_commits_finalized_json(tmp_path: Path):
    wt = tmp_path / "_release"
    _release_worktree(wt, in_progress=True)

    assert _finalize_release_state(wt, "1.1") is True

    rj = json.loads((wt / ".release.json").read_text())
    assert rj["in_progress"] is False
    assert rj["last_promoted_version"] == "1.1"
    # committed (clean tree) with the expected message
    assert _git(wt, "status", "--porcelain") == ""
    assert "finalize 1.1 in .release.json" in _git(wt, "log", "-1", "--pretty=%s")


def test_finalize_release_state_noop_when_already_final(tmp_path: Path):
    wt = tmp_path / "_release"
    _release_worktree(wt, in_progress=False)
    assert _finalize_release_state(wt, "1.1") is False


def test_finalize_release_state_noop_when_no_release_json(tmp_path: Path):
    wt = tmp_path / "_release"
    wt.mkdir()
    _git(wt, "init")
    assert _finalize_release_state(wt, "1.1") is False
