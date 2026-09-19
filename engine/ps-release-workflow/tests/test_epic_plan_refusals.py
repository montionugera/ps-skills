"""`epic plan` refusals that no other test reaches (see docs/known-issues.md)."""
import pytest

from lib.backlog_paths import get_backlog_catalog_path, get_release_worktree
from lib.catalog import update_entry
from lib.git_ops import commit_all
from scripts.epic import EpicPlanError, epic_plan
from scripts.promote_idea_to_refined import promote_idea_to_refined
from tests._helpers import git


def _refusal_writing_nothing(repo) -> str:
    """Plan E-001/I-001, expect a refusal, and prove it left release/<v> alone.

    Mirrors test_epic_run.py::test_plan_writes_nothing: a refusal is still a
    read-only path, so HEAD must not move and the tree must stay clean.
    """
    rel = get_release_worktree(repo)
    head = git(rel, "rev-parse", "HEAD")
    with pytest.raises(EpicPlanError) as excinfo:
        epic_plan(repo, "E-001", "I-001")
    assert git(rel, "status", "--porcelain") == ""
    assert git(rel, "rev-parse", "HEAD") == head
    return str(excinfo.value)


def test_plan_refuses_a_slice_whose_feature_is_missing_from_the_refined_catalog(epic_repo):
    update_entry(get_backlog_catalog_path(epic_repo, "idea"), "I-001",
                 lambda entry: entry.update(promoted_to="F-099"))
    commit_all(get_release_worktree(epic_repo), "test: point I-001 at a missing feature")
    message = _refusal_writing_nothing(epic_repo)
    assert "I-001" in message and "F-099" in message and "missing" in message


def test_plan_refuses_a_feature_with_an_unexpected_status(epic_repo):
    feature = promote_idea_to_refined(epic_repo, "I-001")["id"]
    update_entry(get_backlog_catalog_path(epic_repo, "refined"), feature,
                 lambda entry: entry.update(status="weird"))
    commit_all(get_release_worktree(epic_repo), "test: give the feature an unexpected status")
    message = _refusal_writing_nothing(epic_repo)
    assert feature in message and "unexpected status" in message and "'weird'" in message
