"""psrw epic plan / psrw epic sync — the deterministic half of `epic run`."""
import json
import subprocess

import pytest

from lib.backlog_paths import (
    NoReleaseInProgressError, get_backlog_catalog_path, get_release_worktree,
)
from lib.catalog import CatalogEntryNotFoundError, mark_promoted_to_main, mark_shipped
from lib.epic import mark_epic_failed, mark_epic_promoted, try_begin_verification
from lib.git_ops import commit_all
from scripts.epic import EpicPlanError, epic_plan, epic_verify
from scripts.init_work_refined_backlog import claim_feature
from scripts.new_idea import SPEC_TEMPLATE as IDEA_SPEC_TEMPLATE
from scripts.promote_idea_to_refined import promote_idea_to_refined


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def _plan_error(repo, *args, **kwargs) -> str:
    with pytest.raises(EpicPlanError) as excinfo:
        epic_plan(repo, *args, **kwargs)
    return str(excinfo.value)


# ── epic plan: the output ────────────────────────────────────────────────────

def test_plan_lists_slices_in_fanout_order_not_allowlist_order(epic_repo):
    out = epic_plan(epic_repo, "E-001", "I-002,I-001")
    assert out["allowlist"] == ["I-002", "I-001"]
    assert out["slices"] == [
        {"idea": "I-001", "feature": None, "state": "idea",
         "claimed_by": None, "action": "refine"},
        {"idea": "I-002", "feature": None, "state": "idea",
         "claimed_by": None, "action": "refine"},
    ]
    assert out["epic"] == "E-001"
    assert out["epic_status"] == "open"
    assert out["release"] == "1.1"
    assert out["precheck"].endswith("scripts/precheck.sh")
    assert out["notes"] == []


def test_plan_only_lists_allowlisted_slices(epic_repo):
    out = epic_plan(epic_repo, "E-001", "I-002")
    assert [s["idea"] for s in out["slices"]] == ["I-002"]


def test_plan_reports_every_state_and_action(epic_repo):
    repo = epic_repo
    feature = promote_idea_to_refined(repo, "I-001")["id"]
    out = epic_plan(repo, "E-001", "I-001,I-002")
    assert [(s["state"], s["action"]) for s in out["slices"]] == [
        ("refined", "claim"), ("idea", "refine")]
    assert out["slices"][0]["feature"] == feature

    claim_feature(repo, feature, owner="chain-owner")
    first = epic_plan(repo, "E-001", "I-001,I-002")["slices"][0]
    assert (first["state"], first["action"]) == ("claimed", "resume")
    assert first["claimed_by"] == "chain-owner"

    mark_shipped(get_backlog_catalog_path(repo, "refined"), feature, "1.1")
    first = epic_plan(repo, "E-001", "I-001,I-002")["slices"][0]
    assert (first["state"], first["action"]) == ("shipped", "skip")


def test_plan_names_failed_verification_without_refusing(epic_repo):
    epic_cat = get_backlog_catalog_path(epic_repo, "epic")
    assert try_begin_verification(epic_cat, "E-001", "abc123")
    mark_epic_failed(epic_cat, "E-001", "1.1", sha="abc123")
    out = epic_plan(epic_repo, "E-001", "I-001")
    assert out["epic_status"] == "failed_verification"
    assert any("psrw epic verify E-001" in note for note in out["notes"])


# ── epic plan: refusals ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["", "  ", " , ,"])
def test_plan_refuses_a_missing_or_empty_allowlist(epic_repo, raw):
    assert "--slices" in _plan_error(epic_repo, "E-001", raw)


def test_plan_refuses_when_no_release_is_in_progress(tmp_repo_with_release):
    with pytest.raises(NoReleaseInProgressError):
        epic_plan(tmp_repo_with_release, "E-001", "I-001")


def test_plan_refuses_an_unknown_epic(epic_repo):
    with pytest.raises(CatalogEntryNotFoundError):
        epic_plan(epic_repo, "E-009", "I-001")


def test_plan_refuses_a_slice_that_is_not_a_child_of_the_epic(epic_repo):
    assert "I-009" in _plan_error(epic_repo, "E-001", "I-001,I-009")


@pytest.mark.parametrize("state", ["verified", "promoted", "verifying"])
def test_plan_refuses_a_settled_or_in_flight_epic(epic_repo, state):
    epic_cat = get_backlog_catalog_path(epic_repo, "epic")
    if state == "verified":
        epic_verify(epic_repo, "E-001")
    elif state == "promoted":
        mark_epic_promoted(epic_cat, "E-001")
    else:
        assert try_begin_verification(epic_cat, "E-001", "abc123")
    assert state in _plan_error(epic_repo, "E-001", "I-001")


def test_plan_refuses_a_slice_that_is_already_promoted(epic_repo):
    feature = promote_idea_to_refined(epic_repo, "I-001")["id"]
    mark_promoted_to_main(get_backlog_catalog_path(epic_repo, "refined"), feature)
    message = _plan_error(epic_repo, "E-001", "I-001")
    assert "I-001" in message and "already promoted" in message


def test_plan_refuses_a_slice_shipped_on_another_release(epic_repo):
    feature = promote_idea_to_refined(epic_repo, "I-001")["id"]
    mark_shipped(get_backlog_catalog_path(epic_repo, "refined"), feature, "0.9")
    assert "0.9" in _plan_error(epic_repo, "E-001", "I-001")


def test_plan_refuses_an_untouched_fanout_skeleton_spec(epic_repo_raw):
    """epic_repo_raw's specs are exactly what `epic fanout` wrote, so this pins
    the skeleton comparison to fanout's real output, not to a copy of it."""
    message = _plan_error(epic_repo_raw, "E-001", "I-001", allow_no_precheck=True)
    assert "I-001" in message and "skeleton" in message


def test_plan_refuses_an_untouched_new_idea_skeleton_spec(epic_repo, idea_spec):
    spec = idea_spec(epic_repo, "I-002")
    spec.write_text(IDEA_SPEC_TEMPLATE.format(title="beta", id="I-002"))
    commit_all(get_release_worktree(epic_repo), "test: reset I-002 spec")
    message = _plan_error(epic_repo, "E-001", "I-001,I-002")
    assert "I-002" in message and "skeleton" in message


def test_plan_ignores_the_spec_of_an_already_shipped_slice(epic_repo, idea_spec):
    feature = promote_idea_to_refined(epic_repo, "I-001")["id"]
    mark_shipped(get_backlog_catalog_path(epic_repo, "refined"), feature, "1.1")
    idea_spec(epic_repo, "I-001").write_text(
        IDEA_SPEC_TEMPLATE.format(title="alpha", id="I-001"))   # skeleton again
    out = epic_plan(epic_repo, "E-001", "I-001")
    assert out["slices"][0]["action"] == "skip"


def test_plan_refuses_a_missing_idea_spec(epic_repo, idea_spec):
    idea_spec(epic_repo, "I-001").unlink()
    assert "spec.md" in _plan_error(epic_repo, "E-001", "I-001")


def test_plan_refuses_a_missing_precheck_unless_allowed(epic_repo):
    rel = get_release_worktree(epic_repo)
    (rel / "scripts" / "precheck.sh").unlink()
    commit_all(rel, "test: drop precheck")
    assert "--allow-no-precheck" in _plan_error(epic_repo, "E-001", "I-001")
    out = epic_plan(epic_repo, "E-001", "I-001", allow_no_precheck=True)
    assert out["precheck"] is None


def test_plan_refuses_an_unusable_precheck_hook_even_when_allowed(epic_repo):
    rel = get_release_worktree(epic_repo)
    release_json = json.loads((rel / ".release.json").read_text())
    release_json["hooks"] = {"precheck": "/etc/passwd"}
    (rel / ".release.json").write_text(json.dumps(release_json))
    commit_all(rel, "test: absolute precheck hook")
    assert "hooks.precheck" in _plan_error(
        epic_repo, "E-001", "I-001", allow_no_precheck=True)


# ── epic plan: read-only ─────────────────────────────────────────────────────

def test_plan_writes_nothing(epic_repo):
    rel = get_release_worktree(epic_repo)
    catalogs = [get_backlog_catalog_path(epic_repo, kind)
                for kind in ("idea", "refined", "epic")]
    before = {p: p.read_bytes() for p in catalogs if p.exists()}
    head = _git(rel, "rev-parse", "HEAD")

    epic_plan(epic_repo, "E-001", "I-001,I-002")

    assert {p: p.read_bytes() for p in catalogs if p.exists()} == before
    assert _git(rel, "status", "--porcelain") == ""
    assert _git(rel, "rev-parse", "HEAD") == head


# ── epic plan: the CLI ───────────────────────────────────────────────────────

def test_cli_plan_prints_the_json_plan(epic_repo, monkeypatch, capsys):
    from scripts.epic import main
    monkeypatch.chdir(epic_repo)
    monkeypatch.setattr("sys.argv", ["epic.py", "plan", "E-001", "--slices", "I-001,I-002"])
    assert main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["allowlist"] == ["I-001", "I-002"]
    assert [s["action"] for s in out["slices"]] == ["refine", "refine"]


def test_cli_plan_refusal_is_one_error_line_not_a_traceback(epic_repo, monkeypatch, capsys):
    from scripts.epic import main
    monkeypatch.chdir(epic_repo)
    monkeypatch.setattr("sys.argv", ["epic.py", "plan", "E-001"])
    assert main() == 1
    err = capsys.readouterr().err
    assert err.startswith("ERROR: ") and "--slices" in err and "Traceback" not in err
