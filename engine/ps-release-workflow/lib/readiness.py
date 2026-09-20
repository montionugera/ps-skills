"""Spec and plan readiness validation for ps-release-workflow.

Enforces that features claimed and shipped in the release lifecycle
are not empty templates or unrefined skeletons.
"""
from pathlib import Path
import re
from typing import NamedTuple

SKELETON_PHRASES = [
    "(one sentence)",
    "(2-3 sentences)",
    "(list — each with one responsibility)",
    "Fill via `/superpowers:writing-plans` once the spec is final.",
    "Empty until promoted to F-NNN",
]

REQUIRED_SPEC_SECTIONS = [
    "## Goal",
    "## Architecture",
]

REQUIRED_PLAN_SECTIONS = [
    "## ",  # Must have at least one phase or task header
]


class ReadinessResult(NamedTuple):
    is_ready: bool
    reasons: list[str]


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def check_spec_readiness(spec_path: Path) -> ReadinessResult:
    """Validate that spec.md exists and is not an unrefined skeleton."""
    reasons = []
    if not spec_path.exists():
        return ReadinessResult(False, [f"Spec file missing: {spec_path}"])

    content = _read_file(spec_path)
    if not content.strip():
        return ReadinessResult(False, [f"Spec file is empty: {spec_path}"])

    # Check for placeholder phrases
    for phrase in SKELETON_PHRASES:
        if phrase in content:
            reasons.append(f"Spec contains skeleton placeholder: '{phrase}'")

    # Check for required sections
    for section in REQUIRED_SPEC_SECTIONS:
        if section not in content:
            reasons.append(f"Spec missing required section: '{section}'")

    # Check length / density
    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("---")]
    if len(lines) < 8:
        reasons.append("Spec is too short (< 8 non-empty lines of substance)")

    return ReadinessResult(len(reasons) == 0, reasons)


def check_plan_readiness(plan_path: Path) -> ReadinessResult:
    """Validate that plan.md exists and contains actionable implementation tasks."""
    reasons = []
    if not plan_path.exists():
        return ReadinessResult(False, [f"Plan file missing: {plan_path}"])

    content = _read_file(plan_path)
    if not content.strip():
        return ReadinessResult(False, [f"Plan file is empty: {plan_path}"])

    # Check for placeholder phrases
    for phrase in SKELETON_PHRASES:
        if phrase in content:
            reasons.append(f"Plan contains skeleton placeholder: '{phrase}'")

    # Check for task checkboxes or numbered phases
    has_tasks = "- [ ]" in content or "- [x]" in content or re.search(r"Phase\s+\d+", content, re.IGNORECASE)
    if not has_tasks:
        reasons.append("Plan contains no task checkboxes (- [ ] / - [x]) or phase definitions")

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if len(lines) < 5:
        reasons.append("Plan is too short (< 5 non-empty lines)")

    return ReadinessResult(len(reasons) == 0, reasons)


def check_feature_readiness(feature_dir: Path, check_plan: bool = True) -> ReadinessResult:
    """Validate both spec.md and plan.md for a feature folder."""
    all_reasons = []
    spec_path = feature_dir / "spec.md"
    spec_res = check_spec_readiness(spec_path)
    if not spec_res.is_ready:
        all_reasons.extend(spec_res.reasons)

    if check_plan:
        plan_path = feature_dir / "plan.md"
        plan_res = check_plan_readiness(plan_path)
        if not plan_res.is_ready:
            all_reasons.extend(plan_res.reasons)

    return ReadinessResult(len(all_reasons) == 0, all_reasons)
