import json

import pytest
import yaml

from lib.backlog_paths import get_backlog_catalog_path
from scripts.epic import epic_open, epic_fanout


def test_open_mints_epic_with_spec_and_verification(tmp_repo_in_release, fixed_owner):
    repo = tmp_repo_in_release
    result = epic_open(repo, "Multi-account risk limits")
    assert result["epic"]["id"] == "E-001"
    folder = result["folder"]
    assert (folder / "spec.md").exists()
    assert (folder / "verification.md").exists()
    assert "status: epic" in (folder / "spec.md").read_text()


def test_fanout_mints_one_idea_per_slice_all_tagged(tmp_repo_in_release, fixed_owner):
    repo = tmp_repo_in_release
    epic_open(repo, "Multi-account risk limits")
    result = epic_fanout(repo, "E-001", ["per-account cap", "aggregate cap", "breach alert"])
    ideas = json.loads(get_backlog_catalog_path(repo, "idea").read_text())
    assert [i["id"] for i in ideas] == ["I-001", "I-002", "I-003"]
    assert {i["epic"] for i in ideas} == {"E-001"}
    assert len(result["ideas"]) == 3


def test_fanout_is_all_or_nothing(tmp_repo_in_release, fixed_owner, monkeypatch):
    """A failure partway must mint nothing — the FileExistsError-on-retry bug in
    docs/known-issues.md multiplies by N here."""
    repo = tmp_repo_in_release
    epic_open(repo, "Multi-account risk limits")

    # This patches pathlib.Path.write_text on the class itself (epic_mod.Path IS
    # pathlib.Path, not a copy), so it is NOT narrow — it also catches
    # mutate_state's internal tmp-file write (state.py) inside add_idea_entry.
    # Call #1 is that mutate_state write for slice "a", #2 is its spec.md, #3
    # (its research.md) is where this explodes — i.e. partway through the FIRST
    # slice, before any second slice is even minted.
    import scripts.epic as epic_mod
    real_write = epic_mod.Path.write_text
    calls = {"n": 0}

    def exploding_write(self, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 3:          # slice "a"'s research.md
            raise OSError("disk full")
        return real_write(self, *a, **kw)

    monkeypatch.setattr(epic_mod.Path, "write_text", exploding_write)
    with pytest.raises(OSError):
        epic_fanout(repo, "E-001", ["a", "b", "c"])

    ideas = json.loads(get_backlog_catalog_path(repo, "idea").read_text())
    assert ideas == [], "a partial fan-out must mint nothing"
    assert not list((repo / ".claude" / "worktrees" / "_release"
                     / ".claude" / "idea_backlog").glob("I-*"))


def test_fanout_twice_appends_slices(tmp_repo_in_release, fixed_owner):
    """No stored slice_count, so a later fanout simply adds more tagged ideas."""
    repo = tmp_repo_in_release
    epic_open(repo, "E")
    epic_fanout(repo, "E-001", ["a"])
    epic_fanout(repo, "E-001", ["b"])
    ideas = json.loads(get_backlog_catalog_path(repo, "idea").read_text())
    assert len(ideas) == 2


def test_title_with_double_quotes_is_sanitized(tmp_repo_in_release, fixed_owner):
    """known-issues.md: quotes in titles produce broken YAML in skeletons."""
    repo = tmp_repo_in_release
    result = epic_open(repo, 'Cap the "risk" number')
    spec = (result["folder"] / "spec.md").read_text()
    front_matter = spec.split("---")[1]
    assert yaml.safe_load(front_matter)["title"] == 'Cap the "risk" number'


def test_title_with_colon_is_valid_yaml(tmp_repo_in_release, fixed_owner):
    """An unquoted `title: {title}` plain scalar breaks on a colon (a very
    plausible real title, e.g. "Epic: Payment gateway migration") even though
    it has no quotes to sanitize — the bug _sanitize() alone didn't close."""
    repo = tmp_repo_in_release
    result = epic_open(repo, "Epic: Payment gateway migration")
    spec = (result["folder"] / "spec.md").read_text()
    front_matter = spec.split("---")[1]
    assert yaml.safe_load(front_matter)["title"] == "Epic: Payment gateway migration"


def test_open_rolls_back_on_commit_failure(tmp_repo_in_release, fixed_owner, monkeypatch):
    """A GitError from commit_all must roll back the mint too, not just a
    write_text failure — commit_all used to run outside the rollback guard."""
    import scripts.epic as epic_mod
    from lib.git_ops import GitError

    def exploding_commit(*a, **kw):
        raise GitError("simulated commit failure")

    monkeypatch.setattr(epic_mod, "commit_all", exploding_commit)
    repo = tmp_repo_in_release
    with pytest.raises(GitError):
        epic_open(repo, "Multi-account risk limits")

    epics = json.loads(get_backlog_catalog_path(repo, "epic").read_text())
    assert epics == [], "a commit failure must roll back the minted epic"
    assert not list((repo / ".claude" / "worktrees" / "_release"
                     / ".claude" / "epic_backlog").glob("E-*"))


def test_fanout_rolls_back_on_commit_failure(tmp_repo_in_release, fixed_owner, monkeypatch):
    """Same commit-failure-rollback gap as epic_open, on the fanout path."""
    repo = tmp_repo_in_release
    epic_open(repo, "Multi-account risk limits")

    import scripts.epic as epic_mod
    from lib.git_ops import GitError

    def exploding_commit(*a, **kw):
        raise GitError("simulated commit failure")

    monkeypatch.setattr(epic_mod, "commit_all", exploding_commit)
    with pytest.raises(GitError):
        epic_fanout(repo, "E-001", ["a", "b"])

    ideas = json.loads(get_backlog_catalog_path(repo, "idea").read_text())
    assert ideas == [], "a commit failure must roll back every minted idea"
    assert not list((repo / ".claude" / "worktrees" / "_release"
                     / ".claude" / "idea_backlog").glob("I-*"))
