from pathlib import Path
import pytest
from lib.readiness import check_spec_readiness, check_plan_readiness, check_feature_readiness


def test_skeleton_spec_fails(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("""---
title: "Test Feature"
---
# Test Feature — design
## Goal
(one sentence)
## Architecture
(2-3 sentences)
""")
    res = check_spec_readiness(spec)
    assert not res.is_ready
    assert any("skeleton placeholder" in r for r in res.reasons)


def test_complete_spec_passes(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("""---
title: "Real Feature"
---
# Real Feature — design
## Goal
This feature adds robust hash routing and view persistence to the component portal.
## Architecture
The client-side router listens on window hashchange events and updates the DOM view.
It syncs active view state to localStorage for offline reload tolerance.
## Acceptance Criteria
- Clicking view sets hash
- Refreshing restores view
""")
    res = check_spec_readiness(spec)
    assert res.is_ready
    assert len(res.reasons) == 0


def test_skeleton_plan_fails(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("""# Real Feature Implementation Plan
> Fill via `/superpowers:writing-plans` once the spec is final.
""")
    res = check_plan_readiness(plan)
    assert not res.is_ready
    assert any("skeleton placeholder" in r for r in res.reasons)


def test_actionable_plan_passes(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("""# Real Feature Implementation Plan
## Phase 1: Router Engine
- [x] Create router.ts
- [ ] Bind hashchange listener
- [ ] Add unit test suite
""")
    res = check_plan_readiness(plan)
    assert res.is_ready
    assert len(res.reasons) == 0
