"""The psrw verbs an `epic run` calls, composed for a two-slice epic.

Only the LLM steps are stubbed (a commit stands in for "implement"); every psrw
call the chain makes is the real one, so this pins the mechanics the skill relies
on: slice 2 sees slice 1, sync's `base` isolates a slice's own diff, ship works on
a synced branch, the last ship records the epic outcome, and main never moves.
"""
import subprocess
from pathlib import Path

import pytest

from lib.backlog_paths import get_backlog_catalog_path, get_release_worktree
from lib.catalog import find_entry
from lib.git_ops import commit_all
from scripts.epic import EpicPlanError, epic_plan, epic_sync
from scripts.init_work_refined_backlog import claim_feature
from scripts.promote_idea_to_refined import promote_idea_to_refined
from scripts.ship_current_work_to_release import ship_current_work


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def _run_slice(repo: Path, idea_id: str, filename: str) -> dict:
    """Refine, claim, sync, 'implement' (one commit), ship: the chain minus the LLM."""
    feature = promote_idea_to_refined(repo, idea_id)["id"]
    wt = Path(claim_feature(repo, feature, owner="chain-owner")["worktree"])
    synced = epic_sync(wt)
    (wt / filename).write_text(f"{idea_id}\n")
    commit_all(wt, f"feat: {idea_id}")
    return {"feature": feature, "wt": wt, "synced": synced, "shipped": ship_current_work(wt)}


def test_two_slice_chain_ships_in_order_and_verifies_the_epic(epic_repo):
    repo = epic_repo
    rel = get_release_worktree(repo)
    main_before = _git(repo, "rev-parse", "main")
    origin_main_before = _git(repo, "rev-parse", "origin/main")

    first = _run_slice(repo, "I-001", "one.txt")
    assert first["shipped"]["epic_outcome"] is None, "epic is not complete after slice 1"
    assert [s["action"] for s in epic_plan(repo, "E-001", "I-001,I-002")["slices"]] == [
        "skip", "refine"]

    second = _run_slice(repo, "I-002", "two.txt")
    # slice 2 was cut from main, yet it saw slice 1's shipped work after sync
    assert (second["wt"] / "one.txt").read_text() == "I-001\n"
    # and `base` still isolates slice 2's own diff for review
    assert _git(second["wt"], "diff", "--name-only", second["synced"]["base"], "HEAD") == "two.txt"

    outcome = second["shipped"]["epic_outcome"]
    assert outcome["epic"] == "E-001"
    assert outcome["rc"] is None, "no epic-check.sh here: skipped, not passed"
    epic = find_entry(get_backlog_catalog_path(repo, "epic"), "E-001")
    assert epic["status"] == "verified"

    refined = get_backlog_catalog_path(repo, "refined")
    assert [find_entry(refined, f["feature"])["status"] for f in (first, second)] == [
        "shipped", "shipped"]
    assert (rel / "one.txt").is_file() and (rel / "two.txt").is_file()
    assert _git(repo, "rev-parse", "main") == main_before, "the chain never touches main"
    assert _git(repo, "rev-parse", "origin/main") == origin_main_before, "nor pushes main"

    with pytest.raises(EpicPlanError, match="verified"):
        epic_plan(repo, "E-001", "I-001,I-002")
