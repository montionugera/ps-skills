"""new_idea: append to idea_backlog + create folder skeleton on the _release worktree (D11/SR-1)."""
import json
import subprocess
from pathlib import Path

import pytest

from lib.backlog_paths import NoReleaseInProgressError
from scripts.init_work_new_release import new_release
from scripts.new_idea import new_idea


def test_creates_folder_with_skeleton(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    entry = new_idea(tmp_repo_with_release, title="Add fee cap")
    folder = wt / ".claude" / "idea_backlog" / f"{entry['id']}-add-fee-cap"
    assert folder.is_dir()
    assert (folder / "spec.md").exists()
    assert (folder / "plan.md").exists()
    assert (folder / "research.md").exists()
    # Spec skeleton mentions the title
    assert "Add fee cap" in (folder / "spec.md").read_text()


def test_appends_to_catalog(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    new_idea(tmp_repo_with_release, title="First")
    new_idea(tmp_repo_with_release, title="Second")
    cat = json.loads((wt / ".claude" / "idea_backlog" / "_catalog.json").read_text())
    assert [e["id"] for e in cat] == ["I-001", "I-002"]
    assert [e["title"] for e in cat] == ["First", "Second"]


def test_commits_on_release(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    new_idea(tmp_repo_with_release, title="X")

    log = subprocess.run(
        ["git", "-C", str(wt), "log", "--oneline"],
        capture_output=True, text=True,
    )
    assert "I-001" in log.stdout

    branch = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    )
    assert branch.stdout.strip() == "release/1.1"

    # D11: metadata did NOT land on main — main checkout's idea catalog stays empty.
    main_cat = json.loads(
        (tmp_repo_with_release / ".claude" / "idea_backlog" / "_catalog.json").read_text()
    )
    assert main_cat == []

    # No stray / lock files left uncommitted in the worktree.
    status = subprocess.run(
        ["git", "-C", str(wt), "status", "--porcelain"],
        capture_output=True, text=True,
    )
    assert status.stdout.strip() == ""


def test_refuses_if_not_initialized(tmp_repo: Path):
    with pytest.raises(Exception, match="ps-release-workflow"):
        new_idea(tmp_repo, title="X")


def test_refuses_when_no_release_in_progress(tmp_repo_with_release: Path):
    # No new_release call → .release.json in_progress is False.
    with pytest.raises(NoReleaseInProgressError):
        new_idea(tmp_repo_with_release, title="X")
