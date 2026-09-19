# Cover the Untested Epic Plan Refusals — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two tests covering the two genuinely-untested `_plan_slice` refusal branches in `scripts/epic.py`, and correct the stale known-issues bullet that claims three branches are untested.

**Architecture:** A single new test module, `engine/ps-release-workflow/tests/test_epic_plan_refusals.py`, drives `epic_plan` against a catalog corrupted through the public `lib.catalog.update_entry`, using the existing `epic_repo` fixture — no new fixture, no production-code change. The module reuses `git` from `tests._helpers` (slice 1's shared helper) for its "the refusal wrote nothing" assertions. One documentation bullet in `docs/known-issues.md` is rewritten to match reality.

**Correction from the audit (do not restate the old rationale):** the spec's "Why a new file" section argues the new module makes slice 1's arrival observable because `test_epic_run.py` "binds `_git` both before and after slice 1". That is **false** — slice 1 rewrote `test_epic_run.py`, `test_epic_run_e2e.py` and `test_promote_finalize_sync.py` to `from tests._helpers import git as _git`, so all three already fail at import without `tests/_helpers.py`. The new file's real justification is narrower and still valid: `_plan_error` is private to `test_epic_run.py`, so these refusals are captured inline with `pytest.raises` in their own module. The `from tests._helpers import git` import stays (legitimate reuse, and the implementer brief requires it) — it is simply not an extra chain proof.

**Tech Stack:** Python 3, pytest, the repo's own `lib/` + `scripts/` modules, real `git` subprocesses via `tests._helpers.git`.

**Spec:** `.claude/refined_backlog/F-004-cover-the-untested-epic-plan-refusals/spec.md`

## Global Constraints

- **Files this slice may touch, nothing else.** Under `engine/ps-release-workflow/`: NEW `tests/test_epic_plan_refusals.py` and EDIT `docs/known-issues.md` (exactly ONE bullet). Plus `plan.md` / `research.md` under `.claude/refined_backlog/F-004-cover-the-untested-epic-plan-refusals/`.
- **Must NOT touch:** `scripts/` (especially `scripts/epic.py`), `lib/`, `tests/conftest.py`, `tests/test_epic_run.py`, `tests/_helpers.py`, `install.sh`, `_catalog.json`. Hand-editing `_catalog.json` is forbidden outright.
- **If a new test exposes a real bug in `scripts/epic.py`: FILE IT in the final report. Do not fix it.**
- **TRIPWIRE — do not defeat it.** The new test file must do `from tests._helpers import git`. That module arrived from slice 1 via `psrw epic sync` and is already present. A `ModuleNotFoundError: tests._helpers` is a REAL FAILURE of the chain — STOP and report. Never "fix" it by inlining a local copy of the helper or importing from elsewhere.
- **ONE commit** on `feat/F-004` for the whole slice. New commit only; **never** `git commit --amend`.
- **Forbidden:** `psrw ship`, `psrw promote`, `--deploy`, `git push`, opening a PR, merging to main, `rm -rf`, leaving the worktree.
- **Worktree (never leave it):** `/Users/pasitnusso/ps-skills/.claude/worktrees/F-004-cover-the-untested-epic-plan-refusals`. All `pytest` commands run from `<worktree>/engine/ps-release-workflow`.
- **Slice base commit:** `b45fc770bae341927b9a1bfea44ec37460c95c67`.

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/ps-release-workflow/tests/test_epic_plan_refusals.py` (NEW, ~40 lines) | The two refusal tests plus one small local assertion helper that runs `epic_plan`, captures the `EpicPlanError`, and proves the refusal wrote nothing. |
| `engine/ps-release-workflow/docs/known-issues.md` (MODIFY, one bullet) | Correct the stale "three refusal branches are untested" claim. |

A new module (rather than appending to `test_epic_run.py`) is deliberate: `test_epic_run.py`'s `_plan_error` helper is private to that module, so this module captures the refusal inline with `pytest.raises`. (See the Architecture correction above: the "engineered dependency" argument in the spec is factually wrong and must not be repeated.)

## Facts established by reading the code (do not re-derive)

- `_plan_slice` in `scripts/epic.py`:
  - line 269-271 — `raise EpicPlanError(f"{idea['id']} points at {idea['promoted_to']}, which is missing from the refined catalog")` when `find_entry(refined_cat, idea["promoted_to"])` returns `None`. **No test.**
  - line 283 — `raise EpicPlanError(f"{feature['id']} has unexpected status {status!r}")` when `status not in _SLICE_STATE`. **No test.**
  - line 279-281 — "shipped on another release" is **already covered** by `test_epic_run.py::test_plan_refuses_a_slice_shipped_on_another_release`.
- `lib.catalog.update_entry(catalog: Path, entry_id: str, updater: Callable[[dict], None]) -> bool` mutates the matched entry in place under the state flock; an updater that changes nothing returns `False` without rewriting; a missing id raises `CatalogEntryNotFoundError`.
- `lib.backlog_paths.get_backlog_catalog_path(repo, kind)` with `kind` in `("idea", "refined", "epic")`; `get_release_worktree(repo)` is the tree the catalogs live in.
- `epic_repo` fixture (`tests/conftest.py:117`) gives release/1.1 open, epic `E-001` fanned out into ideas `I-001` "alpha" and `I-002` "beta", both specs filled with real content, a passing `scripts/precheck.sh`, all committed on `release/1.1`. `epic plan` accepts it as-is.
- `promote_idea_to_refined(repo, "I-001")["id"]` returns the minted `F-NNN` id.
- `lib.git_ops.commit_all(rel_wt, message)` commits the release worktree.
- `tests/_helpers.py` exports `git(cwd: Path, *args: str) -> str` (stripped stdout, asserts returncode 0).
- The read-only assertion pattern to mirror is `test_epic_run.py::test_plan_writes_nothing`: capture `rev-parse HEAD` before, then assert `status --porcelain == ""` and HEAD unchanged after.

---

### Task 1: The two refusal tests

**Files:**
- Create: `engine/ps-release-workflow/tests/test_epic_plan_refusals.py`
- Test: the file itself is the test.

**Interfaces:**
- Consumes: `epic_repo` fixture (conftest), `lib.backlog_paths.get_backlog_catalog_path` / `get_release_worktree`, `lib.catalog.update_entry`, `lib.git_ops.commit_all`, `scripts.epic.EpicPlanError` / `epic_plan`, `scripts.promote_idea_to_refined.promote_idea_to_refined`, `tests._helpers.git`.
- Produces: nothing other tasks import. Task 2 references this file's path in prose.

- [ ] **Step 1: Confirm the tripwire module is present before writing anything**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-004-cover-the-untested-epic-plan-refusals/engine/ps-release-workflow
ls -l tests/_helpers.py && sed -n '1,12p' tests/_helpers.py
```

Expected: the file exists and defines `def git(cwd: Path, *args: str) -> str`. If it is MISSING, STOP and report the chain failure — do not create it.

- [ ] **Step 2: Write the test file**

Create `engine/ps-release-workflow/tests/test_epic_plan_refusals.py` with exactly this content:

```python
"""`epic plan` refusals that no other test reaches (see docs/known-issues.md)."""
import pytest

from lib.backlog_paths import get_backlog_catalog_path, get_release_worktree
from lib.catalog import update_entry
from lib.git_ops import commit_all
from scripts.epic import EpicPlanError, epic_plan
from scripts.promote_idea_to_refined import promote_idea_to_refined
from tests._helpers import git


def _refusal_writing_nothing(repo) -> str:
    """Plan E-001/I-001, expect a refusal, and prove it left release/<v> alone.

    Mirrors test_epic_run.py::test_plan_writes_nothing: a refusal is still a
    read-only path, so HEAD must not move and the tree must stay clean.
    """
    rel = get_release_worktree(repo)
    head = git(rel, "rev-parse", "HEAD")
    with pytest.raises(EpicPlanError) as excinfo:
        epic_plan(repo, "E-001", "I-001")
    assert git(rel, "status", "--porcelain") == ""
    assert git(rel, "rev-parse", "HEAD") == head
    return str(excinfo.value)


def test_plan_refuses_a_slice_whose_feature_is_missing_from_the_refined_catalog(epic_repo):
    update_entry(get_backlog_catalog_path(epic_repo, "idea"), "I-001",
                 lambda entry: entry.update(promoted_to="F-099"))
    commit_all(get_release_worktree(epic_repo), "test: point I-001 at a missing feature")
    message = _refusal_writing_nothing(epic_repo)
    assert "I-001" in message and "F-099" in message and "missing" in message


def test_plan_refuses_a_feature_with_an_unexpected_status(epic_repo):
    feature = promote_idea_to_refined(epic_repo, "I-001")["id"]
    update_entry(get_backlog_catalog_path(epic_repo, "refined"), feature,
                 lambda entry: entry.update(status="weird"))
    commit_all(get_release_worktree(epic_repo), "test: give the feature an unexpected status")
    message = _refusal_writing_nothing(epic_repo)
    assert feature in message and "unexpected status" in message and "'weird'" in message
```

Notes for the implementer:
- `dict.update` returns `None`; `update_entry` ignores the updater's return value and mutates in place, so the lambda form is correct.
- `commit_all` runs BEFORE the plan call on purpose: the corruption must be committed so the later `status --porcelain == ""` assertion is meaningful rather than trivially failing on the dirty catalog.
- If `commit_all` raises "nothing to commit", that means the catalog is gitignored in this fixture — STOP and report; do not silently drop the assertion.

- [ ] **Step 3: Run the new tests**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-004-cover-the-untested-epic-plan-refusals/engine/ps-release-workflow
python3 -m pytest tests/test_epic_plan_refusals.py -q
```

Expected: `2 passed`. A `ModuleNotFoundError: tests._helpers` here is the tripwire firing — STOP and report, do not work around it.

- [ ] **Step 4: Mutation check — prove each test actually bites (scratch copy ONLY)**

Copy the engine to a scratch directory, neutralize the `raise` at `epic.py:269-271`, run the first test, and confirm it FAILS; restore, neutralize the `raise` at `epic.py:283`, run the second test, confirm it FAILS. The repo worktree's `scripts/epic.py` must never be modified — verify with `git status --porcelain` after, which must not list `scripts/epic.py`.

```bash
SCRATCH="$(mktemp -d)"
cp -R /Users/pasitnusso/ps-skills/.claude/worktrees/F-004-cover-the-untested-epic-plan-refusals/engine/ps-release-workflow "$SCRATCH/eng"
# in "$SCRATCH/eng": neutralize the first raise, then:
cd "$SCRATCH/eng" && python3 -m pytest tests/test_epic_plan_refusals.py -q
```

Expected: with branch 269 neutralized, `test_plan_refuses_a_slice_whose_feature_is_missing_from_the_refined_catalog` fails; with branch 283 neutralized, `test_plan_refuses_a_feature_with_an_unexpected_status` fails. Record both outcomes. Do not `rm -rf` the scratch dir (denied here) — just leave it.

- [ ] **Step 5: No commit yet**

This slice ships ONE commit; it is made in Task 3. Do not commit here.

- [ ] **Step 6: Phase gate** (rule 7): verify (Step 3 output) → independent review of the new file by `code-reviewer` + `python-reviewer` (`model: sonnet`, diff is < 50 lines) → act on blocking findings → re-run Step 3. Reviewers must be told the Global Constraints above, especially the tripwire and the do-not-touch list.

---

### Task 2: Correct the stale known-issues bullet

**Files:**
- Modify: `engine/ps-release-workflow/docs/known-issues.md` (the single bullet under "Deferred from the epic-run final review" beginning "Three refusal branches are untested")

**Interfaces:**
- Consumes: the file path created in Task 1, quoted in prose.
- Produces: nothing.

- [ ] **Step 1: Locate the exact bullet**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-004-cover-the-untested-epic-plan-refusals/engine/ps-release-workflow
grep -n "Three refusal branches are untested" docs/known-issues.md
```

Expected: exactly one hit, at **line 36** (measured during execution; an audit pass had claimed 37 — the grep output is authoritative and said 36, matching the spec).

- [ ] **Step 2: Replace that one line**

Old line (verbatim):

```markdown
- Three refusal branches are untested (`scripts/epic.py`: the idea whose `promoted_to` feature is missing from the refined catalog, ~line 270; a slice shipped on another release, ~280; an unexpected feature status, ~283).
```

New line (verbatim):

```markdown
- Two `_plan_slice` refusal branches in `scripts/epic.py` are now covered by `tests/test_epic_plan_refusals.py` (the idea whose `promoted_to` feature is missing from the refined catalog; a feature with an unexpected status). The third branch this entry once counted — a slice shipped on another release — was already covered by `tests/test_epic_run.py::test_plan_refuses_a_slice_shipped_on_another_release`, so the original "three untested" count was wrong.
```

Deliberately **no raw line numbers** in the replacement (audit MEDIUM): the original bullet went stale precisely because it hardcoded `~270`/`~280`/`~283`. Branch descriptions plus covering test names survive edits to `scripts/epic.py`.

Change **nothing else** in the file: no reflow, no neighbouring bullets, no heading edits.

- [ ] **Step 3: Verify exactly one bullet changed**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-004-cover-the-untested-epic-plan-refusals
git --no-pager diff --numstat -- engine/ps-release-workflow/docs/known-issues.md
```

Expected: `1	1	engine/ps-release-workflow/docs/known-issues.md` — one line added, one removed.

(Do NOT use `grep -c '^[+-][^+-]'` for this file: markdown bullets already begin with `- `, so the diff lines read `--` / `+-` and that pattern counts 0. Found during execution.)

- [ ] **Step 4: No commit yet** — see Task 3.

- [ ] **Step 5: Phase gate**: docs-only, < 5-line diff — folded into Task 3's gate.

---

### Task 3: Full-suite verification and the single commit

**Files:**
- Modify: none beyond Tasks 1-2. This task only verifies and commits.

**Interfaces:**
- Consumes: the working tree left by Tasks 1-2.
- Produces: one commit on `feat/F-004`.

- [ ] **Step 1: Run the full suite**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-004-cover-the-untested-epic-plan-refusals/engine/ps-release-workflow
python3 -m pytest tests -q 2>&1 | tail -n 15
```

Expected: `467 passed, 2 skipped` (465 before this slice + 2 new). Takes 7-8 minutes — use a Bash timeout of 600000 ms. **The passed count and zero failures are the gate**; the skip count is machine-dependent (audit LOW: both skips come from `tests/test_docs_single_source.py`, conditioned on `SKILLS_DIR` being present), so a different skip number is worth reporting but is not by itself a failure. Any failure: STOP and report the failing test names; if a failure points at a real bug in `scripts/epic.py`, FILE it, do not fix it.

- [ ] **Step 2: Confirm the diff surface**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-004-cover-the-untested-epic-plan-refusals
git status --porcelain
```

Expected: only `?? engine/ps-release-workflow/tests/test_epic_plan_refusals.py`, ` M engine/ps-release-workflow/docs/known-issues.md`, and the backlog `plan.md` / `research.md`. Anything else listed — especially `scripts/`, `lib/`, `tests/conftest.py`, `tests/test_epic_run.py`, `tests/_helpers.py`, `_catalog.json` — means scope was breached: STOP and report.

- [ ] **Step 3: Commit (ONE commit, never `--amend`)**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-004-cover-the-untested-epic-plan-refusals
git add engine/ps-release-workflow/tests/test_epic_plan_refusals.py \
        engine/ps-release-workflow/docs/known-issues.md \
        .claude/refined_backlog/F-004-cover-the-untested-epic-plan-refusals/
git commit -m "$(cat <<'EOF'
test(epic): cover the two untested _plan_slice refusal branches

Adds tests/test_epic_plan_refusals.py covering the idea whose promoted_to
feature is missing from the refined catalog (epic.py:269) and the feature
with an unexpected status (epic.py:283). Both assert the refusal writes
nothing (release HEAD unchanged, tree clean), via tests._helpers.git.

Corrects the known-issues bullet: only two of the three listed branches
were untested; "shipped on another release" was already covered by
test_epic_run.py.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Post-commit evidence**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-004-cover-the-untested-epic-plan-refusals
git --no-pager diff --stat b45fc770 HEAD
git --no-pager diff b45fc770 HEAD -- engine/ps-release-workflow/docs/known-issues.md
git status --porcelain
```

Expected: the stat lists only the two engine files plus the backlog docs; the known-issues diff shows exactly one removed and one added bullet; `git status --porcelain` is empty. (A denied cleanup of the gitignored `.superpowers/sdd/plan` scratch path is NOT a gate — skip it and continue.)

- [ ] **Step 5: Phase gate** (covers Tasks 2 and 3): the full-suite run in Step 1 is the verification; the independent review from Task 1's gate plus a read of the one-bullet diff is the review; there is nothing to refactor in a 2-line docs change; Step 4's evidence is the re-verify.

---

## Acceptance criteria (from the spec — all must be evidenced with pasted output)

1. `python3 -m pytest tests/test_epic_plan_refusals.py -q` reports `2 passed`.
2. Each new test fails when its target branch is removed (mutation check, scratch copy only).
3. `python3 -m pytest tests -q` reports `467 passed, 2 skipped`.
4. `git diff --stat b45fc770 HEAD` lists only `tests/test_epic_plan_refusals.py` (new) and `docs/known-issues.md` under `engine/ps-release-workflow/`.
5. `git diff b45fc770 HEAD -- docs/known-issues.md` changes exactly one bullet.
6. `git status --porcelain` empty after the commit; `tests/_helpers.py` present in the worktree (proves sync).

## Appendix — audit trail

- 2026-09-19 `self-grill-audit` (independent `general-purpose` auditor, ran the plan's test file verbatim in a scratch copy): verdict **safe-with-fixes**. 1 HIGH, 2 MEDIUM, 2 LOW.
  - Confirmed true: the 269 / 277 / 279 / 283 raises; 279-281 already covered by `test_epic_run.py::test_plan_refuses_a_slice_shipped_on_another_release`; every symbol and signature the plan cites; refusal ORDER is safe (the status check at `epic.py:282-283` fires BEFORE the skeleton-spec check at `:285-287`, so nothing masks the branch under test); catalogs are not gitignored so `commit_all` succeeds; `docs/known-issues.md` has exactly one matching bullet and the plan's "old line" is byte-exact; baseline `--collect-only` = 467 collected. Auditor ran the plan's test file: `2 passed in 3.20s`, and the mutation check bites both ways (neutralizing 269 → test 1 `DID NOT RAISE EpicPlanError`; neutralizing 283 → test 2 `KeyError: 'weird'`).
  - **Corrected (HIGH):** the spec's "engineered dependency" rationale is false — slice 1 already rewrote `test_epic_run.py`, `test_epic_run_e2e.py` and `test_promote_finalize_sync.py` to import `tests._helpers`, so those modules already fail at import without it. Plan's Architecture and File Structure now say so; the import stays as legitimate reuse.
  - **Corrected (MEDIUM):** replacement known-issues bullet drops raw line numbers (they are what made the original stale) and cites branch descriptions + test names instead.
  - **Corrected (MEDIUM):** the target bullet is at `docs/known-issues.md:37`, not 36.
  - **Corrected (LOW):** the full-suite gate is the passed count + zero failures; the skip count is machine-dependent.
  - **Open / filed, not fixed (spec-only, out of this slice's scope):** the spec's coverage table cites `test_epic_run.py:119 / :126 / :156`; the actual defs are at 114 / 121 / 151, and line 156 is a different test. The spec also asserts `known-issues.md:36` (actually 37). Per the implementer brief, the spec is not edited by this slice.
  - Blast radius: R2 for both files; one additive test module (+~3 s suite time) and a one-line doc swap; no hook, CI job or release gate reads either path; undo is `git revert` of the single commit. No R0 item.
