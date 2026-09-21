"""psrw epic plan / psrw epic sync — the deterministic half of `epic run`."""
import contextlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from lib.backlog_paths import (
    NoReleaseInProgressError, get_backlog_catalog_path, get_release_worktree,
)
from lib.catalog import CatalogEntryNotFoundError, mark_promoted_to_main, mark_shipped
from lib.epic import mark_epic_failed, mark_epic_promoted, try_begin_verification
from lib.git_ops import commit_all
from lib.slug import slugify
from scripts.epic import EpicPlanError, EpicSyncError, epic_plan, epic_sync, epic_verify
from scripts.init_work_refined_backlog import claim_feature
from scripts.new_idea import SPEC_TEMPLATE as IDEA_SPEC_TEMPLATE
from scripts.promote_idea_to_refined import promote_idea_to_refined
from scripts.ship_current_work_to_release import DirtyTreeError, NotInFeatureWorktreeError
from tests._helpers import git as _git


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
    feature = promote_idea_to_refined(repo, "I-001", allow_empty_spec=True)["id"]
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
    feature = promote_idea_to_refined(epic_repo, "I-001", allow_empty_spec=True)["id"]
    mark_promoted_to_main(get_backlog_catalog_path(epic_repo, "refined"), feature)
    message = _plan_error(epic_repo, "E-001", "I-001")
    assert "I-001" in message and "already promoted" in message


def test_plan_refuses_a_slice_shipped_on_another_release(epic_repo):
    feature = promote_idea_to_refined(epic_repo, "I-001", allow_empty_spec=True)["id"]
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
    feature = promote_idea_to_refined(epic_repo, "I-001", allow_empty_spec=True)["id"]
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


# ── epic sync ────────────────────────────────────────────────────────────────

@pytest.fixture
def slice_worktree(epic_repo):
    """(repo, feature worktree, F-id) for slice I-001, refined then claimed."""
    feature = promote_idea_to_refined(epic_repo, "I-001", allow_empty_spec=True)["id"]
    claimed = claim_feature(epic_repo, feature, owner="chain-owner")
    return epic_repo, Path(claimed["worktree"]), feature


def test_sync_makes_the_slice_spec_and_plan_visible(slice_worktree):
    repo, wt, feature = slice_worktree
    folder = wt / ".claude" / "refined_backlog" / f"{feature}-{slugify('alpha')}"
    assert not folder.exists(), "a worktree cut from main must not see it yet"

    result = epic_sync(wt)

    assert (folder / "spec.md").is_file() and (folder / "plan.md").is_file()
    assert result["feature"] == feature
    assert result["branch"] == f"feat/{feature}"
    assert result["release"] == "1.1"
    assert result["base"] == _git(get_release_worktree(repo), "rev-parse", "HEAD")
    assert result["sha"] == _git(wt, "rev-parse", "HEAD")


def test_sync_fast_forward_puts_the_feature_on_the_release_head(slice_worktree):
    _, wt, _ = slice_worktree
    result = epic_sync(wt)
    assert result["sha"] == result["base"]


def test_sync_merges_when_the_feature_already_has_commits(slice_worktree):
    _, wt, _ = slice_worktree
    (wt / "feature.txt").write_text("work\n")
    commit_all(wt, "feat: work before the sync")

    result = epic_sync(wt)

    assert result["sha"] != result["base"], "a real merge commit expected"
    assert _git(wt, "status", "--porcelain") == ""
    # the review anchor: `base` isolates exactly the slice's own work
    assert _git(wt, "diff", "--name-only", result["base"], "HEAD") == "feature.txt"


def test_sync_twice_is_a_no_op(slice_worktree):
    _, wt, _ = slice_worktree
    first = epic_sync(wt)
    second = epic_sync(wt)
    assert second == first


def test_sync_conflict_aborts_cleanly_and_leaves_the_feature_claimed(slice_worktree):
    repo, wt, feature = slice_worktree
    rel = get_release_worktree(repo)
    (rel / "shared.txt").write_text("release side\n")
    commit_all(rel, "test: release adds shared.txt")
    (wt / "shared.txt").write_text("feature side\n")
    commit_all(wt, "test: feature adds shared.txt")
    head = _git(wt, "rev-parse", "HEAD")

    with pytest.raises(EpicSyncError, match="shared.txt"):
        epic_sync(wt)

    assert _git(wt, "rev-parse", "HEAD") == head
    assert _git(wt, "status", "--porcelain") == ""
    assert subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                          cwd=wt, capture_output=True).returncode != 0
    catalog = json.loads(get_backlog_catalog_path(repo, "refined").read_text())
    assert next(f for f in catalog if f["id"] == feature)["status"] == "claimed"


def test_sync_refuses_outside_a_feature_worktree(slice_worktree):
    repo, _, _ = slice_worktree
    with pytest.raises(NotInFeatureWorktreeError):
        epic_sync(repo)                                  # the main checkout
    with pytest.raises(NotInFeatureWorktreeError):
        epic_sync(get_release_worktree(repo))            # the _release worktree


def test_sync_refuses_a_dirty_tree_and_keeps_the_edit(slice_worktree):
    _, wt, _ = slice_worktree
    head = _git(wt, "rev-parse", "HEAD")
    (wt / "scratch.txt").write_text("uncommitted\n")
    with pytest.raises(DirtyTreeError):
        epic_sync(wt)
    assert _git(wt, "rev-parse", "HEAD") == head
    assert (wt / "scratch.txt").read_text() == "uncommitted\n"


def test_sync_holds_the_release_lock_around_the_merge_only(slice_worktree, monkeypatch):
    repo, wt, _ = slice_worktree
    import scripts.epic as epic_mod
    events = []
    real_lock, real_run = epic_mod.file_lock, epic_mod.git_run

    @contextlib.contextmanager
    def spy_lock(target):
        events.append(("lock", Path(target).resolve()))
        with real_lock(target):
            yield
        events.append(("unlock", Path(target).resolve()))

    def spy_run(cwd, *args, **kwargs):
        if args and args[0] == "merge":
            events.append(("merge", None))
        return real_run(cwd, *args, **kwargs)

    monkeypatch.setattr(epic_mod, "file_lock", spy_lock)
    monkeypatch.setattr(epic_mod, "git_run", spy_run)

    epic_sync(wt)

    rel = get_release_worktree(repo).resolve()
    assert events == [("lock", rel), ("merge", None), ("unlock", rel)]


def test_cli_sync_prints_the_sha_and_fails_cleanly_outside_a_worktree(
        slice_worktree, monkeypatch, capsys):
    from scripts.epic import main
    repo, wt, _ = slice_worktree
    monkeypatch.setattr("sys.argv", ["epic.py", "sync"])

    monkeypatch.chdir(wt)
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["sha"] == _git(wt, "rev-parse", "HEAD")

    monkeypatch.chdir(repo)
    assert main() == 1
    err = capsys.readouterr().err
    assert err.startswith("ERROR: ") and "Traceback" not in err


def test_epic_help_lists_plan_and_sync():
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    proc = subprocess.run([sys.executable, str(scripts_dir / "epic.py"), "--help"],
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert "{open,fanout,verify,plan,sync}" in proc.stdout
