"""Test git subprocess wrappers."""
import subprocess
from pathlib import Path

import pytest

from lib.git_ops import (
    add_worktree_new_branch, current_branch, branch_exists, is_dirty,
    commit_all, commit_paths, create_branch, GitError,
)


def test_current_branch(tmp_repo: Path):
    assert current_branch(tmp_repo) == "main"


def test_branch_exists(tmp_repo: Path):
    assert branch_exists(tmp_repo, "main")
    assert not branch_exists(tmp_repo, "nonexistent")


def test_is_dirty_clean(tmp_repo: Path):
    assert not is_dirty(tmp_repo)


def test_is_dirty_with_untracked(tmp_repo: Path):
    (tmp_repo / "newfile.txt").write_text("x")
    assert is_dirty(tmp_repo)


def test_is_dirty_with_staged(tmp_repo: Path):
    (tmp_repo / "newfile.txt").write_text("x")
    subprocess.run(["git", "add", "newfile.txt"], cwd=tmp_repo, check=True)
    assert is_dirty(tmp_repo)


def test_commit_all_creates_commit(tmp_repo: Path):
    (tmp_repo / "x.txt").write_text("y")
    commit_all(tmp_repo, "test commit")
    log = subprocess.run(["git", "log", "--oneline"], cwd=tmp_repo, capture_output=True, text=True)
    assert "test commit" in log.stdout


def test_create_branch(tmp_repo: Path):
    create_branch(tmp_repo, "feat/foo")
    assert branch_exists(tmp_repo, "feat/foo")


def _committed_files(repo: Path) -> list[str]:
    out = subprocess.run(["git", "show", "--name-status", "--format=", "HEAD"], cwd=repo,
                         check=True, capture_output=True, text=True).stdout
    return sorted(out.split("\n")[:-1])


def test_commit_paths_ignores_everything_else(tmp_repo: Path):
    (tmp_repo / "keep").mkdir()
    (tmp_repo / "keep" / "a.txt").write_text("a")
    (tmp_repo / "junk.txt").write_text("junk")
    assert commit_paths(tmp_repo, "msg", ["keep", "missing-path"]) is True
    assert _committed_files(tmp_repo) == ["A\tkeep/a.txt"]
    assert is_dirty(tmp_repo)


def test_commit_paths_leaves_prestaged_files_out(tmp_repo: Path):
    (tmp_repo / "keep.txt").write_text("a")
    (tmp_repo / "staged.txt").write_text("b")
    subprocess.run(["git", "add", "staged.txt"], cwd=tmp_repo, check=True)
    assert commit_paths(tmp_repo, "msg", ["keep.txt"]) is True
    assert _committed_files(tmp_repo) == ["A\tkeep.txt"]


def test_commit_paths_records_deletions(tmp_repo: Path):
    (tmp_repo / "README.md").unlink()
    assert commit_paths(tmp_repo, "msg", ["README.md"]) is True
    assert _committed_files(tmp_repo) == ["D\tREADME.md"]


def test_commit_paths_nothing_to_commit_returns_false(tmp_repo: Path):
    (tmp_repo / "junk.txt").write_text("junk")
    assert commit_paths(tmp_repo, "msg", ["keep"]) is False


def test_add_worktree_copies_ignored_caches_and_excludes_claude_state(tmp_repo: Path):
    import shutil
    if not shutil.which("wt"):
        pytest.skip("wt (worktrunk) not installed")

    (tmp_repo / ".gitignore").write_text("node_modules/\ngraft/\n.claude/state/\n")
    commit_all(tmp_repo, "chore: add gitignore")

    nm = tmp_repo / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("module.exports = 42;\n")

    graft_dir = tmp_repo / "graft"
    graft_dir.mkdir(parents=True)
    (graft_dir / "graph.json").write_text("{}\n")

    state_dir = tmp_repo / ".claude" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "claims.json").write_text('{"F-001": "main"}\n')

    wt_path = tmp_repo.parent / "wt-warm-cache"
    add_worktree_new_branch(tmp_repo, wt_path, "feat/warm-cache", "main")

    assert (wt_path / "node_modules" / "pkg" / "index.js").read_text() == "module.exports = 42;\n"
    assert (wt_path / "graft" / "graph.json").is_file()
    assert not (wt_path / ".claude" / "state" / "claims.json").exists()
    assert not is_dirty(wt_path)
