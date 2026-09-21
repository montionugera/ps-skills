"""promote_idea_to_refined: I-NNN → F-NNN on the _release worktree (D11/SR-1)."""
import json
from pathlib import Path

import pytest

from lib.backlog_paths import NoReleaseInProgressError, get_backlog_catalog_path
from lib.catalog import add_idea_entry
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
    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    folder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"
    assert folder.is_dir()
    assert (folder / "spec.md").exists()
    assert (folder / "plan.md").exists()
    # Defect 2: research happens at idea stage; refine must not lay down an
    # empty research skeleton nobody fills.
    assert not (folder / "research.md").exists()
    assert sorted(f.name for f in folder.iterdir()) == ["plan.md", "spec.md"]


def test_marks_idea_promoted(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="X")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    cat = json.loads((wt / ".claude" / "idea_backlog" / "_catalog.json").read_text())
    assert cat[0]["promoted_to"] == feat["id"]


def test_refined_status_is_open(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="X")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    refined_cat = json.loads(
        (wt / ".claude" / "refined_backlog" / "_catalog.json").read_text()
    )
    assert refined_cat[0]["status"] == "open"
    assert refined_cat[0]["from_idea"] == idea["id"]


def test_unknown_idea_raises(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    with pytest.raises(IdeaNotFoundError):
        promote_idea_to_refined(tmp_repo_with_release, idea_id="I-999", allow_empty_spec=True)


def test_already_promoted_raises(tmp_repo_with_release: Path):
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="X")
    promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    with pytest.raises(AlreadyPromotedError):
        promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)


def test_refuses_when_no_release_in_progress(tmp_repo_with_release: Path):
    with pytest.raises(NoReleaseInProgressError):
        promote_idea_to_refined(tmp_repo_with_release, idea_id="I-001", allow_empty_spec=True)


def test_mark_promoted_failure_leaves_no_orphan_refined_entry(
    tmp_repo_with_release: Path, monkeypatch
):
    """m-4: F-NNN is minted BEFORE mark_promoted. If mark_promoted raises, the
    minted refined entry + folder must be rolled back — otherwise the retry
    mints F-002 and F-001 is orphaned forever."""
    import scripts.promote_idea_to_refined as promote_mod
    from lib.catalog import CatalogEntryNotFoundError

    repo = tmp_repo_with_release
    new_release(repo, version="1.1")
    wt = repo / ".claude" / "worktrees" / "_release"
    idea = new_idea(repo, title="X")

    def boom(*args, **kwargs):
        raise CatalogEntryNotFoundError(idea["id"], Path("catalog"))

    monkeypatch.setattr(promote_mod, "mark_promoted", boom)
    with pytest.raises(CatalogEntryNotFoundError):
        promote_idea_to_refined(repo, idea_id=idea["id"], allow_empty_spec=True)
    monkeypatch.undo()

    refined_cat = json.loads(
        (wt / ".claude" / "refined_backlog" / "_catalog.json").read_text()
    )
    assert refined_cat == [], "the minted refined entry must be rolled back"
    assert not list((wt / ".claude" / "refined_backlog").glob("F-*")), \
        "the refined folder must be rolled back"

    # Retry must mint F-001 again — not an orphan-skipping F-002.
    feat = promote_idea_to_refined(repo, idea_id=idea["id"], allow_empty_spec=True)
    assert feat["id"] == "F-001"


def test_main_reports_unknown_idea_cleanly(tmp_repo_with_release: Path, monkeypatch, capsys):
    """CLI surface (A6): a typo'd idea id exits 1 with an ERROR line, no traceback."""
    import sys as _sys
    from scripts.promote_idea_to_refined import main as refine_main
    new_release(tmp_repo_with_release, version="1.1")
    monkeypatch.chdir(tmp_repo_with_release)
    monkeypatch.setattr(_sys, "argv", ["promote_idea_to_refined.py", "I-999"])
    assert refine_main() == 1
    err = capsys.readouterr().err
    assert "I-999" in err
    assert "Traceback" not in err


def test_help_does_not_promote_anything(tmp_repo_in_release, tmp_path):
    import subprocess, sys, json
    from pathlib import Path
    script = Path(__file__).resolve().parent.parent / "scripts" / "promote_idea_to_refined.py"
    wt = tmp_repo_in_release / ".claude" / "worktrees" / "_release"
    catalog = wt / ".claude" / "refined_backlog" / "_catalog.json"
    before = catalog.read_text()

    proc = subprocess.run([sys.executable, str(script), "--help"], cwd=tmp_repo_in_release,
                          env={"HOME": str(tmp_path / "h"), "PATH": "/usr/bin:/bin"},
                          capture_output=True, text=True)

    assert proc.returncode == 0
    assert "usage:" in proc.stdout.lower()
    assert catalog.read_text() == before, "--help created a refined catalog entry"
    assert json.loads(catalog.read_text()) == [] or "--help" not in catalog.read_text()


# ---------------------------------------------------------------------------
# Defect 1: refine must CARRY idea content forward, never overwrite it.
# ---------------------------------------------------------------------------

FILLED_RESEARCH = """\
# Add fee cap — research notes

## Prior art

Measured across 7 live repos: the MT5 bridge caps at 0.8% but the
UI shows 1.2%. See ticket QUANT-441 and the 2026-05 incident review.

- option A: cap in the adapter (cheap, wrong layer)
- option B: cap in the domain service (correct, touches 3 call sites)

## Open questions

1. Does the cap apply per-order or per-day?
2. Who owns the rounding rule — us or the broker?

## Numbers

| repo | filled research.md | bytes |
|---|---|---|
| quant | yes | 21014 |
| user-svc | yes | 10233 |
"""

FILLED_SPEC_BODY = """\
# Add fee cap — design notes from the idea stage

## Problem

Fees compound past the advertised cap on multi-leg orders.

## Sketch

Cap in the domain service, clamp at serialization, log the delta.
"""


def _idea_folder(wt: Path, idea_id: str, slug: str) -> Path:
    return wt / ".claude" / "idea_backlog" / f"{idea_id}-{slug}"


def test_carries_filled_research_forward_byte_for_byte(tmp_repo_with_release: Path):
    """The measured data loss: 7/13 live idea folders have a filled research.md."""
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    ifolder = _idea_folder(wt, idea["id"], "add-fee-cap")
    (ifolder / "research.md").write_text(FILLED_RESEARCH)

    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    ffolder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"

    assert (ffolder / "research.md").read_text() == FILLED_RESEARCH
    # The idea folder is the historical record — it keeps its copy too.
    assert (ifolder / "research.md").read_text() == FILLED_RESEARCH


def test_carries_filled_spec_body_and_rewrites_frontmatter(tmp_repo_with_release: Path):
    """A filled idea spec keeps its body; only the identity frontmatter is rewritten."""
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    ifolder = _idea_folder(wt, idea["id"], "add-fee-cap")
    (ifolder / "spec.md").write_text(
        f'---\ntitle: "Add fee cap"\nid: {idea["id"]}\nstatus: idea\nowner: pasit\n---\n\n'
        + FILLED_SPEC_BODY
    )

    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    ffolder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"
    text = (ffolder / "spec.md").read_text()

    # Body survives byte-for-byte.
    assert text.endswith(FILLED_SPEC_BODY)
    # Frontmatter now carries the F-NNN identity.
    fm = text.split("---")[1]
    assert f"id: {feat['id']}" in fm
    assert f"from_idea: {idea['id']}" in fm
    assert "status: refined" in fm
    assert "status: idea" not in fm
    assert 'title: "Add fee cap"' in fm
    # Unrelated frontmatter keys are not dropped.
    assert "owner: pasit" in fm
    # And it is NOT the empty F skeleton.
    assert "(one sentence)" not in text


def test_untouched_idea_spec_is_replaced_by_the_f_skeleton(tmp_repo_with_release: Path):
    """Still a skeleton → the F-NNN skeleton wins (existing behaviour, kept)."""
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")

    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    ffolder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"
    spec = (ffolder / "spec.md").read_text()
    assert "— design" in spec
    assert f"from_idea: {idea['id']}" in spec
    assert "## Tests / acceptance criteria" in spec
    assert "(rough shape; not a design yet)" not in spec


def test_legacy_idea_plan_with_content_is_preserved(tmp_repo_with_release: Path):
    """Ideas captured before the skeleton fix may carry a plan.md."""
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    ifolder = _idea_folder(wt, idea["id"], "add-fee-cap")
    body = "# Add fee cap Implementation Plan\n\n## Task 1\n\nClamp in the service.\n"
    (ifolder / "plan.md").write_text(body)

    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    ffolder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"
    assert (ffolder / "plan.md").read_text() == body


def test_legacy_idea_plan_skeleton_is_replaced(tmp_repo_with_release: Path):
    """A legacy idea plan.md skeleton must not shadow the F plan skeleton."""
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    ifolder = _idea_folder(wt, idea["id"], "add-fee-cap")
    (ifolder / "plan.md").write_text(
        "# Add fee cap — plan placeholder\n\n"
        "Empty until promoted to F-NNN and filled via `/superpowers:writing-plans`.\n"
    )

    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    ffolder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"
    assert "Implementation Plan" in (ffolder / "plan.md").read_text()


def test_carried_files_are_committed(tmp_repo_with_release: Path):
    """Carry-forward lands in the promote commit, not as a dirty worktree."""
    import subprocess
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    ifolder = _idea_folder(wt, idea["id"], "add-fee-cap")
    (ifolder / "research.md").write_text(FILLED_RESEARCH)
    promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    status = subprocess.run(["git", "-C", str(wt), "status", "--porcelain"],
                            capture_output=True, text=True)
    assert status.stdout.strip() == ""


def test_promote_works_when_idea_folder_is_missing(tmp_repo_with_release: Path):
    """Nothing to carry → plain F skeletons, no crash."""
    import shutil as _shutil
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    _shutil.rmtree(_idea_folder(wt, idea["id"], "add-fee-cap"))

    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    ffolder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"
    assert sorted(f.name for f in ffolder.iterdir()) == ["plan.md", "spec.md"]


def test_undecodable_spec_and_plan_are_never_overwritten(tmp_repo_with_release: Path):
    """Prefer false-preserve: a file we cannot decode is content we cannot judge."""
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    ifolder = _idea_folder(wt, idea["id"], "add-fee-cap")
    # cp1252 smart quotes — real content, not valid UTF-8.
    blob = b"# Add fee cap\n\nThe broker\x92s cap is 0.8%.\n"  # cp1252 smart quote
    (ifolder / "spec.md").write_bytes(blob)
    (ifolder / "plan.md").write_bytes(blob)

    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    ffolder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"
    assert (ffolder / "spec.md").read_bytes() == blob
    assert (ffolder / "plan.md").read_bytes() == blob


def test_multiline_frontmatter_values_survive_the_identity_rewrite(tmp_repo_with_release: Path):
    """Non-identity keys with list / block-scalar values must not be flattened."""
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    ifolder = _idea_folder(wt, idea["id"], "add-fee-cap")
    (ifolder / "spec.md").write_text(
        "---\n"
        'title: "Add fee cap"\n'
        f'id: {idea["id"]}\n'
        "status: idea\n"
        "tags:\n"
        "  - fees\n"
        "  - mt5\n"
        "description: >\n"
        "  Long folded description\n"
        "  spanning two lines\n"
        "---\n\n" + FILLED_SPEC_BODY
    )

    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    ffolder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"
    fm = (ffolder / "spec.md").read_text().split("---")[1]
    assert "  - fees" in fm
    assert "  - mt5" in fm
    assert "  Long folded description" in fm
    assert "  spanning two lines" in fm
    assert f"id: {feat['id']}" in fm
    assert "status: refined" in fm


def test_frontmatter_closing_at_eof_without_newline_does_not_crash(tmp_repo_with_release: Path):
    """A frontmatter-only spec with no trailing newline used to raise IndexError."""
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    ifolder = _idea_folder(wt, idea["id"], "add-fee-cap")
    (ifolder / "spec.md").write_text(
        f'---\ntitle: "Add fee cap"\nid: {idea["id"]}\nstatus: idea\nowner: pasit\n---'
    )

    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    ffolder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"
    text = (ffolder / "spec.md").read_text()
    assert f"id: {feat['id']}" in text
    assert f"from_idea: {idea['id']}" in text
    assert "owner: pasit" in text


def test_leading_rule_that_is_not_frontmatter_is_never_rewritten(tmp_repo_with_release: Path):
    """A leading `---` used as a horizontal rule must not be eaten as frontmatter.

    The tell is YAML that cannot parse: an indented line continuing a key that
    already has an inline scalar value. Preserve the whole file verbatim instead.
    """
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    ifolder = _idea_folder(wt, idea["id"], "add-fee-cap")
    original = (
        "---\n"
        "status: we are unsure\n"
        "  about the cap on multi-leg orders\n"
        "---\n\n" + FILLED_SPEC_BODY
    )
    (ifolder / "spec.md").write_text(original)

    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    ffolder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"
    text = (ffolder / "spec.md").read_text()
    # Not one character of the original is lost.
    assert original in text
    assert "status: we are unsure" in text
    assert "  about the cap on multi-leg orders" in text
    # Identity still lands, prepended.
    assert text.startswith("---\n")
    assert f"id: {feat['id']}" in text
    assert f"from_idea: {idea['id']}" in text


def test_leading_rule_over_prose_is_preserved(tmp_repo_with_release: Path):
    """The plainer shape: a rule followed by prose that is not key: value at all."""
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    ifolder = _idea_folder(wt, idea["id"], "add-fee-cap")
    original = "---\nWe are still unsure about the cap.\n---\n\n" + FILLED_SPEC_BODY
    (ifolder / "spec.md").write_text(original)

    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    ffolder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"
    text = (ffolder / "spec.md").read_text()
    assert original in text
    assert f"id: {feat['id']}" in text


def test_skeleton_plus_one_appended_line_counts_as_content(tmp_repo_with_release: Path):
    """Negative skeleton test: a fuzzy 'near enough' predicate must not pass this."""
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    ifolder = _idea_folder(wt, idea["id"], "add-fee-cap")

    spec_plus = (ifolder / "spec.md").read_text() + "\nThe broker caps at 0.8%.\n"
    (ifolder / "spec.md").write_text(spec_plus)
    research_plus = (ifolder / "research.md").read_text() + "\nSee QUANT-441.\n"
    (ifolder / "research.md").write_text(research_plus)

    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    ffolder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"

    spec = (ffolder / "spec.md").read_text()
    assert "The broker caps at 0.8%." in spec
    assert "(what hurts; concrete examples)" in spec, "idea body was replaced by the F skeleton"
    assert "## Tests / acceptance criteria" not in spec
    # research.md is one line off its skeleton — it must survive, not be deleted.
    assert (ffolder / "research.md").read_text() == research_plus


def test_spec_with_only_frontmatter_edited_counts_as_content(tmp_repo_with_release: Path):
    """Negative skeleton test: an untouched body but an edited header is content."""
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    ifolder = _idea_folder(wt, idea["id"], "add-fee-cap")
    edited = (ifolder / "spec.md").read_text().replace(
        "status: idea\n", "status: idea\nowner: pasit\n"
    )
    (ifolder / "spec.md").write_text(edited)

    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    ffolder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"
    spec = (ffolder / "spec.md").read_text()
    assert "owner: pasit" in spec
    assert "(rough shape; not a design yet)" in spec, "idea body was replaced by the F skeleton"
    assert "## Tests / acceptance criteria" not in spec
    assert f"id: {feat['id']}" in spec


def test_undecodable_research_is_never_deleted(tmp_repo_with_release: Path):
    """Symmetry with spec/plan: a research.md we cannot decode must still arrive."""
    new_release(tmp_repo_with_release, version="1.1")
    wt = tmp_repo_with_release / ".claude" / "worktrees" / "_release"
    idea = new_idea(tmp_repo_with_release, title="Add fee cap")
    ifolder = _idea_folder(wt, idea["id"], "add-fee-cap")
    blob = b"# Add fee cap \x92 research\n\nThe broker\x92s cap.\n"
    (ifolder / "research.md").write_bytes(blob)

    feat = promote_idea_to_refined(tmp_repo_with_release, idea_id=idea["id"], allow_empty_spec=True)
    ffolder = wt / ".claude" / "refined_backlog" / f"{feat['id']}-add-fee-cap"
    assert (ffolder / "research.md").read_bytes() == blob


def test_refine_carries_the_epic_tag_forward(tmp_repo_in_release, fixed_owner):
    repo = tmp_repo_in_release
    idea_cat = get_backlog_catalog_path(repo, "idea")
    add_idea_entry(idea_cat, "slice a", epic="E-001")
    result = promote_idea_to_refined(repo, "I-001", allow_empty_spec=True)
    refined = json.loads(get_backlog_catalog_path(repo, "refined").read_text())
    assert refined[0]["epic"] == "E-001"
    assert refined[0]["id"] == result["id"]
