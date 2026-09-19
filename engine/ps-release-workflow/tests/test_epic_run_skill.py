"""Repo-relative lint for the epic-run skill and the auto-chain bans.

tests/test_docs_single_source.py reads ~/.claude/skills and skips wherever the
skills are not installed (CI). This file reads the skills straight from the repo
checkout, so it always runs.
"""
import re
from pathlib import Path

import pytest

TOOLKIT = Path(__file__).resolve().parent.parent
SKILLS = TOOLKIT.parent.parent / "skills"
ANCHORS = ["d11-backlog-routing", "gates", "promote-sequence",
           "state-layout", "guard-guarantees"]
LINE_BUDGET = 40
BAN = "- **NEVER run `psrw promote`, `psrw ship --deploy`, or merge anything to main.**"

pytestmark = pytest.mark.skipif(not SKILLS.is_dir(), reason=f"{SKILLS} not present")


def _skill(name: str) -> tuple[str, str, str]:
    """(full text, frontmatter, body) of skills/ps-release-workflow-<name>/SKILL.md."""
    text = (SKILLS / f"ps-release-workflow-{name}" / "SKILL.md").read_text()
    _, frontmatter, body = text.split("---", 2)
    return text, frontmatter, body


def test_epic_run_body_is_within_the_line_budget():
    _, _, body = _skill("epic-run")
    lines = [line for line in body.strip().splitlines() if line.strip()]
    assert len(lines) <= LINE_BUDGET, f"{len(lines)} non-blank body lines (budget {LINE_BUDGET})"


def test_epic_run_frontmatter_has_name_and_description():
    text, frontmatter, _ = _skill("epic-run")
    assert [line for line in text.splitlines() if line == "---"] == ["---", "---"]
    assert "name: ps-release-workflow-epic-run" in frontmatter
    assert "description:" in frontmatter


def test_epic_run_links_only_known_lifecycle_anchors():
    text, _, _ = _skill("epic-run")
    fragments = re.findall(r"lifecycle\.md#([a-z0-9-]+)", text)
    assert "gates" in fragments
    assert set(fragments) <= set(ANCHORS)


def test_epic_run_never_promotes():
    _, _, body = _skill("epic-run")
    assert "NEVER run `psrw promote`" in body
    assert "`psrw ship --deploy`" in body and "merge anything to main" in body


# Clause 1+2 of the ban: never legitimate outside the BAN line itself.
STRICT_HAZARD = re.compile(r"psrw\s+promote|(?<!-)--deploy")
# Clause 3 (merge to main): legitimate only inside a "never ..." prohibition.
MERGE_HAZARD = re.compile(r"merge\s+(?:\S+\s+){0,3}(?:to|into)\s+main\b|git\s+merge\s+main\b"
                          r"|push\s+(?:\S+\s+){0,2}main\b", re.IGNORECASE)


def _is_prohibited(body: str, start: int) -> bool:
    """True when a `never` opens the same sentence as the match at body[start]."""
    sentence = re.split(r"[.;!?]", body[:start])[-1]
    return re.search(r"\bnever\b", sentence, re.IGNORECASE) is not None


def test_epic_run_body_never_instructs_promote_or_deploy():
    _, _, body = _skill("epic-run")
    offenders = [ln for ln in body.splitlines()
                 if ln.strip() != BAN and STRICT_HAZARD.search(ln)]
    offenders += [m.group(0) for m in MERGE_HAZARD.finditer(body)
                  if not _is_prohibited(body, m.start())]
    assert offenders == [], offenders


def test_epic_run_uses_every_verb_the_chain_needs():
    _, _, text = _skill("epic-run")
    for token in ("psrw epic plan", "--allow-no-precheck", "psrw refine", "psrw claim",
                  "--resume", "psrw epic sync", "psrw ship --no-deploy", '{"ok"',
                  "git diff --quiet", "git log release/", "/self-grill-audit",
                  "Never blind-retry"):
        assert token in text, f"epic-run skill never mentions {token!r}"


def test_no_skill_uses_the_slash_form_of_the_namespace():
    for skill in sorted(SKILLS.glob("ps-release-workflow-*/SKILL.md")):
        assert "/ps-release-workflow:" not in skill.read_text(), skill.parent.name
