"""Lint: mechanics live in docs/lifecycle.md; skills link to it and stay short."""
from pathlib import Path

import pytest

TOOLKIT = Path(__file__).resolve().parent.parent
LIFECYCLE = TOOLKIT / "docs" / "lifecycle.md"
README = TOOLKIT / "README.md"
SKILLS_DIR = Path.home() / ".claude" / "skills"

ANCHORS = ["d11-backlog-routing", "gates", "promote-sequence",
           "state-layout", "guard-guarantees"]

# full-promote is exempt: it is an R0 chain whose command sequence stays inline.
EXEMPT = {"ps-release-workflow-full-promote"}
LINE_BUDGET = 40


def skill_dirs():
    """Parametrize source. MUST NOT call pytest.skip(): this runs at COLLECTION
    time inside the decorator, where skip() is an error, not a skip
    ("Using pytest.skip outside of a test is not allowed"). Return [] instead and
    let test_skills_repo_is_present report the absence."""
    if not SKILLS_DIR.is_dir():
        return []
    return sorted(d for d in SKILLS_DIR.glob("ps-release-workflow-*") if (d / "SKILL.md").is_file())


def test_skills_repo_is_present():
    if not SKILLS_DIR.is_dir():
        pytest.skip(f"{SKILLS_DIR} not present on this machine")
    assert skill_dirs(), "skills repo present but no ps-release-workflow-* skills found"


def body_lines(text: str) -> list[str]:
    """Everything after the closing frontmatter delimiter."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip().splitlines()
    return text.splitlines()


def test_lifecycle_doc_has_every_anchor():
    content = LIFECYCLE.read_text()
    for a in ANCHORS:
        assert f'id="{a}"' in content, f"docs/lifecycle.md is missing anchor {a}"


def test_readme_links_instead_of_restating():
    readme = README.read_text()
    for anchor in ("promote-sequence", "state-layout", "d11-backlog-routing"):
        assert f"lifecycle.md#{anchor}" in readme, (
            f"README.md should link lifecycle.md#{anchor} rather than restate it"
        )
    assert "$CLAUDE_SESSION_ID" not in readme, (
        "README.md still claims per-session owner resolution; see lifecycle.md#guard-guarantees"
    )


@pytest.mark.parametrize("skill_dir", skill_dirs(), ids=lambda d: d.name)
def test_skill_body_is_within_budget(skill_dir):
    if skill_dir.name in EXEMPT:
        pytest.skip(f"{skill_dir.name} is exempt from thinning")
    lines = [l for l in body_lines((skill_dir / "SKILL.md").read_text()) if l.strip()]
    assert len(lines) <= LINE_BUDGET, (
        f"{skill_dir.name} body is {len(lines)} non-blank lines (budget {LINE_BUDGET}); "
        f"move explanatory mechanics into docs/lifecycle.md"
    )


@pytest.mark.parametrize("skill_dir", skill_dirs(), ids=lambda d: d.name)
def test_skill_links_to_lifecycle_or_needs_no_mechanics(skill_dir):
    """A skill either links to lifecycle.md or is short enough to need no pointer."""
    if skill_dir.name in EXEMPT:
        pytest.skip(f"{skill_dir.name} is exempt: its command sequence stays inline by design")
    text = (skill_dir / "SKILL.md").read_text()
    lines = [l for l in body_lines(text) if l.strip()]
    if len(lines) <= 12:
        return  # trivially short; a pointer would be noise
    import re
    fragments = re.findall(r"lifecycle\.md#([a-z0-9-]+)", text)
    assert fragments, (
        f"{skill_dir.name} has {len(lines)} body lines but no lifecycle.md#<anchor> link"
    )
    unknown = [f for f in fragments if f not in ANCHORS]
    assert not unknown, (
        f"{skill_dir.name} links to non-existent anchor(s) {unknown}; known: {ANCHORS}"
    )


@pytest.mark.parametrize("skill_dir", skill_dirs(), ids=lambda d: d.name)
def test_frontmatter_description_is_present_and_untouched_in_shape(skill_dir):
    """The description block is the auto-trigger surface — it must survive thinning."""
    text = (skill_dir / "SKILL.md").read_text()
    assert text.startswith("---"), f"{skill_dir.name} lost its frontmatter"
    delimiter_lines = [l for l in text.splitlines() if l == "---"]
    assert len(delimiter_lines) == 2, (
        f"{skill_dir.name} has {len(delimiter_lines)} '---' delimiter lines, expected exactly 2; "
        f"body_lines() splits on '---' with maxsplit=2 and silently mis-splits otherwise"
    )
    fm = text.split("---", 2)[1]
    assert "description:" in fm, f"{skill_dir.name} lost its description:"
    assert f"name: {skill_dir.name}" in fm, f"{skill_dir.name} name: does not match its directory"
