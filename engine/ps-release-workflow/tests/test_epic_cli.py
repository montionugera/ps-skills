import json

import pytest

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

    # Patch the NARROW call, not Path.mkdir globally: file_lock's lockdir.mkdir
    # (state.py:28) and mutate_state's parent.mkdir (state.py:69) both fire first,
    # so a global patch raises before a single id is minted and the rollback this
    # test exists for is never exercised.
    import scripts.epic as epic_mod
    real_write = epic_mod.Path.write_text
    calls = {"n": 0}

    def exploding_write(self, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 3:          # partway through slice 2
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
    assert '"risk"' not in spec.split("---")[1]
