"""Unit and integration tests for lib/main_sync.py."""
import json
import subprocess
from pathlib import Path

import pytest

from lib.git_ops import _run as git_run
from lib.main_sync import (
    MainSyncConflictError,
    MainUnreachableError,
    ProtectedPathSyncError,
    _is_protected,
    resolve_main_sha,
    sync_main_into_release,
)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    (path / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=path, check=True)
    return path


def test_is_protected_paths():
    assert _is_protected(".release.json")
    assert _is_protected("./.release.json")
    assert _is_protected(".claude/idea_backlog/_catalog.json")
    assert _is_protected(".claude/refined_backlog/F-001/spec.md")
    assert _is_protected(".claude/epic_backlog/E-001/spec.md")
    assert _is_protected(".claude/state/claims.json")
    assert not _is_protected("src/main.py")
    assert not _is_protected("README.md")
    assert not _is_protected("scripts/precheck.sh")


def test_resolve_main_sha_no_origin(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    main_sha = git_run(repo, "rev-parse", "main").stdout.strip()
    sha, label = resolve_main_sha(repo, strict=True)
    assert sha == main_sha
    assert label == "main (no origin)"


def test_resolve_main_sha_with_origin_success(tmp_path: Path):
    bare = tmp_path / "origin.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", "-b", "main"], cwd=bare, check=True, capture_output=True)

    repo = _init_repo(tmp_path / "repo")
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True, capture_output=True)

    main_sha = git_run(repo, "rev-parse", "main").stdout.strip()
    sha, label = resolve_main_sha(repo, strict=True)
    assert sha == main_sha
    assert label == "origin/main"


def test_resolve_main_sha_fetch_failure(tmp_path: Path, monkeypatch):
    bare = tmp_path / "origin.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", "-b", "main"], cwd=bare, check=True, capture_output=True)

    repo = _init_repo(tmp_path / "repo")
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True, capture_output=True)

    # Corrupt remote URL so fetch fails
    subprocess.run(["git", "remote", "set-url", "origin", "/nonexistent/path.git"], cwd=repo, check=True)

    with pytest.raises(MainUnreachableError):
        resolve_main_sha(repo, strict=True)

    # Non-strict should fall back with warning
    sha, label = resolve_main_sha(repo, strict=False)
    assert len(sha) == 40
    assert "stale: fetch failed" in label


def test_sync_main_noop_when_already_ancestor(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    # Cut release/1.0 from main
    subprocess.run(["git", "branch", "release/1.0", "main"], cwd=repo, check=True)
    main_sha = git_run(repo, "rev-parse", "main").stdout.strip()

    # Create worktree for release/1.0
    rel_wt = tmp_path / "rel_wt"
    subprocess.run(["git", "worktree", "add", str(rel_wt), "release/1.0"], cwd=repo, check=True)

    res = sync_main_into_release(repo, rel_wt, "release/1.0", main_sha, "origin/main")
    assert not res.synced
    assert res.behind == 0
    assert res.files == []


def test_sync_main_absorbs_squash_hotfix(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    # Cut release/1.0 from main commit M0
    subprocess.run(["git", "branch", "release/1.0", "main"], cwd=repo, check=True)
    rel_wt = tmp_path / "rel_wt"
    subprocess.run(["git", "worktree", "add", str(rel_wt), "release/1.0"], cwd=repo, check=True)

    # On main, simulate a squash-merged hotfix H'
    hotfix_file = repo / "hotfix.txt"
    hotfix_file.write_text("critical security fix\n")
    subprocess.run(["git", "add", "hotfix.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "fix: critical security bug (#42)"], cwd=repo, check=True)
    main_sha = git_run(repo, "rev-parse", "main").stdout.strip()

    # Pre-condition: release worktree does not have hotfix.txt
    assert not (rel_wt / "hotfix.txt").exists()

    res = sync_main_into_release(repo, rel_wt, "release/1.0", main_sha, "origin/main")
    assert res.synced
    assert res.behind == 1
    assert "hotfix.txt" in res.files

    # Post-condition: hotfix.txt is present and committed in release worktree
    assert (rel_wt / "hotfix.txt").exists()
    assert (rel_wt / "hotfix.txt").read_text() == "critical security fix\n"
    assert not bool(git_run(rel_wt, "status", "--porcelain").stdout.strip())

    # Idempotent: second sync does nothing
    res2 = sync_main_into_release(repo, rel_wt, "release/1.0", main_sha, "origin/main")
    assert not res2.synced


def test_sync_main_conflict_aborts_cleanly(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "shared.txt").write_text("line 1\nline 2\n")
    subprocess.run(["git", "add", "shared.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add shared.txt"], cwd=repo, check=True)

    # Cut release/1.0
    subprocess.run(["git", "branch", "release/1.0", "main"], cwd=repo, check=True)
    rel_wt = tmp_path / "rel_wt"
    subprocess.run(["git", "worktree", "add", str(rel_wt), "release/1.0"], cwd=repo, check=True)

    # Modify shared.txt on release
    (rel_wt / "shared.txt").write_text("line 1\nrelease modification\n")
    subprocess.run(["git", "commit", "-am", "release edit"], cwd=rel_wt, check=True)
    pre_sha = git_run(rel_wt, "rev-parse", "HEAD").stdout.strip()

    # Modify shared.txt on main differently (conflict)
    (repo / "shared.txt").write_text("line 1\nhotfix modification\n")
    subprocess.run(["git", "commit", "-am", "hotfix edit"], cwd=repo, check=True)
    main_sha = git_run(repo, "rev-parse", "main").stdout.strip()

    with pytest.raises(MainSyncConflictError) as exc_info:
        sync_main_into_release(repo, rel_wt, "release/1.0", main_sha, "origin/main")

    assert "shared.txt" in exc_info.value.conflicted_files
    # Tree must be clean and reset back to pre_sha
    assert git_run(rel_wt, "rev-parse", "HEAD").stdout.strip() == pre_sha
    assert not (rel_wt / ".git" / "MERGE_HEAD").exists()
    assert not bool(git_run(rel_wt, "status", "--porcelain").stdout.strip())


def test_sync_main_refuses_protected_d11_paths(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    # Cut release/1.0
    subprocess.run(["git", "branch", "release/1.0", "main"], cwd=repo, check=True)
    rel_wt = tmp_path / "rel_wt"
    subprocess.run(["git", "worktree", "add", str(rel_wt), "release/1.0"], cwd=repo, check=True)
    pre_sha = git_run(rel_wt, "rev-parse", "HEAD").stdout.strip()

    # Commit a change to .release.json on main
    (repo / ".release.json").write_text('{"version": "9.9", "in_progress": false}\n')
    subprocess.run(["git", "add", ".release.json"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "rogue edit to .release.json on main"], cwd=repo, check=True)
    main_sha = git_run(repo, "rev-parse", "main").stdout.strip()

    with pytest.raises(ProtectedPathSyncError) as exc_info:
        sync_main_into_release(repo, rel_wt, "release/1.0", main_sha, "origin/main")

    assert ".release.json" in exc_info.value.protected_files
    # Tree must be untouched
    assert git_run(rel_wt, "rev-parse", "HEAD").stdout.strip() == pre_sha
    assert not (rel_wt / ".release.json").exists()
