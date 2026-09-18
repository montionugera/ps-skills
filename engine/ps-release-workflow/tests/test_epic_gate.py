"""lib.epic_gate: the epic_check hook runs on an immutable snapshot, never _release."""
import subprocess

from lib.epic_gate import run_epic_check


def _scaffold_epic_check(repo, body="#!/bin/sh\nexit 0\n"):
    """Commit scripts/epic-check.sh on main BEFORE branches are cut, so the
    release tree carries it — same pattern as _scaffold_precheck."""
    d = repo / "scripts"
    d.mkdir(exist_ok=True)
    f = d / "epic-check.sh"
    f.write_text(body)
    f.chmod(0o755)
    subprocess.run(["git", "add", "scripts/epic-check.sh"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "scaffold epic-check"], cwd=repo,
                   check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True, capture_output=True)


def test_missing_script_returns_none_and_does_not_fail(tmp_repo_in_release, capsys):
    repo = tmp_repo_in_release
    rel_wt = repo / ".claude" / "worktrees" / "_release"
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rel_wt,
                         capture_output=True, text=True, check=True).stdout.strip()
    rc = run_epic_check(repo, rel_wt, "E-001", ["F-001"], sha)
    assert rc is None
    assert "epic_check" in capsys.readouterr().err


def test_hook_runs_in_a_detached_snapshot_not_the_shared_tree(tmp_repo_in_release):
    """The suite must not run in _release, which concurrent ships mutate."""
    repo = tmp_repo_in_release
    _scaffold_epic_check(repo, "#!/bin/sh\npwd > \"$PSRW_EPIC_DIR/where\"\nexit 0\n")
    rel_wt = repo / ".claude" / "worktrees" / "_release"
    subprocess.run(["git", "merge", "origin/main", "--no-edit"], cwd=rel_wt,
                   check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rel_wt,
                         capture_output=True, text=True, check=True).stdout.strip()
    epic_dir = repo / ".claude" / "epic_tmp"
    epic_dir.mkdir()
    rc = run_epic_check(repo, rel_wt, "E-001", ["F-001"], sha, epic_dir=epic_dir)
    assert rc == 0
    where = (epic_dir / "where").read_text().strip()
    assert str(rel_wt) not in where


def test_snapshot_worktree_is_removed_afterwards(tmp_repo_in_release):
    repo = tmp_repo_in_release
    _scaffold_epic_check(repo)
    rel_wt = repo / ".claude" / "worktrees" / "_release"
    subprocess.run(["git", "merge", "origin/main", "--no-edit"], cwd=rel_wt,
                   check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rel_wt,
                         capture_output=True, text=True, check=True).stdout.strip()
    before = subprocess.run(["git", "worktree", "list"], cwd=repo,
                            capture_output=True, text=True).stdout
    run_epic_check(repo, rel_wt, "E-001", ["F-001"], sha)
    after = subprocess.run(["git", "worktree", "list"], cwd=repo,
                           capture_output=True, text=True).stdout
    assert before.count("\n") == after.count("\n")


def test_failing_hook_returns_nonzero(tmp_repo_in_release):
    repo = tmp_repo_in_release
    _scaffold_epic_check(repo, "#!/bin/sh\nexit 3\n")
    rel_wt = repo / ".claude" / "worktrees" / "_release"
    subprocess.run(["git", "merge", "origin/main", "--no-edit"], cwd=rel_wt,
                   check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rel_wt,
                         capture_output=True, text=True, check=True).stdout.strip()
    assert run_epic_check(repo, rel_wt, "E-001", ["F-001"], sha) == 3
