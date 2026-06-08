"""promote_idea_to_refined: I-NNN → F-NNN on the _release worktree (D11/SR-1)."""
import json
from pathlib import Path

import pytest

from lib.backlog_paths import NoReleaseInProgressError
from scripts.init_work_new_release import new_release
from scripts.new_idea import new_idea
from scripts.promote_idea_to_refined import (
    promote_idea_to_refined,
    IdeaNotFoundError,
    AlreadyPromotedError,
)


def test_creates_refined_folder(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"])
    folder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"
    assert folder.is_dir()
    assert (folder / "spec.md").exists()


def test_marks_idea_promoted(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="X")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"])
    cat = json.loads((wt / ".claude" / "idea_backlog" / "_catalog.json").read_text())
    assert cat[0]["promoted_to"] == feat["id"]


def test_refined_status_is_open(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="X")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"])
    refined_cat = json.loads(
        (wt / ".claude" / "refined_backlog" / "_catalog.json").read_text()
    )
    assert refined_cat[0]["status"] == "open"
    assert refined_cat[0]["from_idea"] == idea["id"]


def test_unknown_idea_raises(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    with pytest.raises(IdeaNotFoundError):
        promote_idea_to_refined(tmp_repo_with_release, idea_id="I-999")


def test_already_promoted_raises(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="X")
    promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"])
    with pytest.raises(AlreadyPromotedError):
        promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"])


def test_refuses_when_no_release_in_progress(tmp_repo_with_release: Path):
    with pytest.raises(NoReleaseInProgressError):
        promote_idea_to_refined(tmp_repo_with_release, idea_id="I-001")
