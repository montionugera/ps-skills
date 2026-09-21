"""refine refuses an idea whose spec.md is still a template or has no acceptance criteria.

Measured in one consumer repo: 36 of 44 shipped features carried an unfilled
template spec. The gate lives inside promote_idea_to_refined() so every caller
(the CLI, and epic-run which shells out to `psrw refine`) passes through it.
"""
import json
from pathlib import Path

import pytest

from lib.backlog_paths import get_backlog_catalog_path
from scripts import new_idea as new_idea_mod
from scripts import promote_idea_to_refined as refine_mod
from scripts.init_work_new_release import new_release
from scripts.new_idea import idea_spec_placeholders, new_idea
from scripts.promote_idea_to_refined import (
    SpecNotReadyError,
    promote_idea_to_refined,
    spec_readiness_problems,
)

FILLED_SPEC = """\
---
title: "Add fee cap"
id: I-001
status: idea
---

# Add fee cap

## Problem

Fees above 2% silently eat the position.

## Acceptance criteria

- [ ] An order with a fee above the cap is rejected with a 422.
"""


def _idea_spec(repo: Path, idea: dict, slug: str) -> Path:
    wt = repo / ".claude" / "worktrees" / "_release"
    return wt / ".claude" / "idea_backlog" / f"{idea['id']}-{slug}" / "spec.md"


def _refined_catalog(repo: Path) -> list:
    return json.loads(get_backlog_catalog_path(repo, "refined").read_text())


# --- placeholders are derived from the template, not a second hardcoded copy ---

def test_placeholders_are_derived_from_the_idea_template():
    found = idea_spec_placeholders()
    assert "(what hurts; concrete examples)" in found
    assert "(opportunity; deadline; constraint)" in found
    assert "(rough shape; not a design yet)" in found
    for placeholder in found:
        assert placeholder in new_idea_mod.SPEC_TEMPLATE


def test_a_placeholder_added_to_the_template_is_picked_up(monkeypatch):
    monkeypatch.setattr(
        new_idea_mod, "SPEC_TEMPLATE",
        new_idea_mod.SPEC_TEMPLATE + "\n## Risks\n\n(what could go wrong)\n",
    )
    assert "(what could go wrong)" in idea_spec_placeholders()


def test_idea_skeleton_prompts_for_acceptance_criteria():
    assert "## Acceptance criteria" in new_idea_mod.SPEC_TEMPLATE
    # ...and the skeleton itself must never satisfy the gate.
    skeleton = new_idea_mod.SPEC_TEMPLATE.format(title="X", id="I-001")
    assert spec_readiness_problems(skeleton)


# --- spec_readiness_problems: the pure check ---

def test_filled_spec_has_no_problems():
    assert spec_readiness_problems(FILLED_SPEC) == []


def test_leftover_placeholder_is_named():
    text = FILLED_SPEC.replace(
        "Fees above 2% silently eat the position.", "(what hurts; concrete examples)"
    )
    problems = spec_readiness_problems(text)
    assert len(problems) == 1
    assert "(what hurts; concrete examples)" in problems[0]


def test_missing_acceptance_heading_is_named():
    text = FILLED_SPEC.split("## Acceptance criteria")[0]
    problems = spec_readiness_problems(text)
    assert any("Acceptance criteria" in p for p in problems)


def test_acceptance_heading_without_checklist_item_is_refused():
    text = FILLED_SPEC.replace(
        "- [ ] An order with a fee above the cap is rejected with a 422.",
        "It should work.",
    )
    problems = spec_readiness_problems(text)
    assert any("- [ ]" in p for p in problems)


def test_checklist_item_outside_the_acceptance_section_does_not_count():
    text = FILLED_SPEC.replace(
        "- [ ] An order with a fee above the cap is rejected with a 422.", "tbd"
    ) + "\n## Follow-ups\n\n- [ ] rename the module\n"
    assert any("- [ ]" in p for p in spec_readiness_problems(text))


def test_empty_checklist_item_does_not_count():
    text = FILLED_SPEC.replace(
        "- [ ] An order with a fee above the cap is rejected with a 422.", "- [ ]"
    )
    assert any("- [ ]" in p for p in spec_readiness_problems(text))


@pytest.mark.parametrize("heading", [
    "## Acceptance criteria",
    "### acceptance criteria",
    "## Tests / acceptance criteria",
])
def test_acceptance_heading_variants_are_accepted(heading):
    assert spec_readiness_problems(
        FILLED_SPEC.replace("## Acceptance criteria", heading)) == []


def test_ticked_checklist_item_counts():
    assert spec_readiness_problems(FILLED_SPEC.replace("- [ ]", "- [x]")) == []


# --- promote_idea_to_refined: the gate is inside the function every caller uses ---

def test_refine_refuses_the_untouched_skeleton(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    with pytest.raises(SpecNotReadyError) as exc:
        promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"])
    msg = str(exc.value)
    assert "(what hurts; concrete examples)" in msg
    assert "--allow-empty-spec" in msg
    # Refused BEFORE minting: nothing to roll back, nothing orphaned.
    assert _refined_catalog(tmp_repo_with_release) == []
    idea_cat = json.loads(get_backlog_catalog_path(tmp_repo_with_release, "idea").read_text())
    assert not idea_cat[0].get("promoted_to")


def test_refine_refuses_when_spec_is_missing(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    _idea_spec(tmp_repo_with_release, idea, "add-fee-cap").unlink()
    with pytest.raises(SpecNotReadyError, match="spec.md"):
        promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"])


def test_refine_accepts_a_filled_spec(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    _idea_spec(tmp_repo_with_release, idea, "add-fee-cap").write_text(FILLED_SPEC)
    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"])
    assert feat["id"] == "F-001"


def test_allow_empty_spec_bypasses_the_gate(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    feat = promote_idea_to_refined(
        tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    assert feat["id"] == "F-001"


# --- CLI ---

def _run_main(monkeypatch, repo: Path, *argv: str) -> int:
    monkeypatch.chdir(repo)
    monkeypatch.setattr("sys.argv", ["promote_idea_to_refined.py", *argv])
    return refine_mod.main()


def test_main_exits_nonzero_and_names_what_is_missing(
        tmp_repo_with_release: Path, monkeypatch, capsys):
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    assert _run_main(monkeypatch, tmp_repo_with_release, idea["id"]) == 1
    err = capsys.readouterr().err
    assert "(what hurts; concrete examples)" in err
    assert "Acceptance criteria" in err
    assert "Traceback" not in err


def test_main_allow_empty_spec_flag_warns_and_promotes(
        tmp_repo_with_release: Path, monkeypatch, capsys):
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    assert _run_main(
        monkeypatch, tmp_repo_with_release, idea["id"], "--allow-empty-spec") == 0
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "(what hurts; concrete examples)" in captured.err
    assert _refined_catalog(tmp_repo_with_release)[0]["id"] == "F-001"


def test_allow_empty_spec_is_silent_when_the_spec_is_fine(
        tmp_repo_with_release: Path, monkeypatch, capsys):
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    _idea_spec(tmp_repo_with_release, idea, "add-fee-cap").write_text(FILLED_SPEC)
    assert _run_main(
        monkeypatch, tmp_repo_with_release, idea["id"], "--allow-empty-spec") == 0
    assert "WARNING" not in capsys.readouterr().err


# --- epic-run path: it shells out to `psrw refine`, so it meets the same gate ---

def test_fanout_slice_skeleton_is_refused_by_the_same_check():
    from scripts.epic import _fanout_idea_spec
    assert spec_readiness_problems(_fanout_idea_spec("Slice one", "I-001"))


def test_epic_run_skill_refines_through_psrw_and_never_uses_the_escape_hatch():
    skill = (Path(__file__).resolve().parents[3]
             / "skills" / "ps-release-workflow-epic-run" / "SKILL.md").read_text()
    assert "psrw refine I-NNN" in skill
    assert skill.count("--allow-empty-spec") == 1
    assert "never `--allow-empty-spec`" in skill


# --- review fix: markdown inside a code fence is an example, not the spec ---

def test_acceptance_section_inside_a_code_fence_does_not_count():
    text = FILLED_SPEC.split("## Acceptance criteria")[0] + (
        "## Sketch\n\n```markdown\n## Acceptance criteria\n\n- [ ] an example item\n```\n")
    assert any("Acceptance criteria" in p for p in spec_readiness_problems(text))


def test_checklist_item_inside_a_code_fence_does_not_count():
    text = FILLED_SPEC.replace(
        "- [ ] An order with a fee above the cap is rejected with a 422.",
        "~~~\n- [ ] an example item\n~~~",
    )
    assert any("- [ ]" in p for p in spec_readiness_problems(text))
