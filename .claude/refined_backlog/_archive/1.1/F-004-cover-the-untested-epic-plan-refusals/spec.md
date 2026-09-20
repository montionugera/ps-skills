---
title: "Cover the untested epic plan refusals"
id: F-004
status: refined
from_idea: I-004
---

# Cover the untested epic plan refusals

Epic: E-001 "Test and doc hygiene deferred from the epic-run review". Chain position: 2 of 3. Depends on slice 1 (imports `tests._helpers.git`).
Human-approved as drafted.

## Problem

`engine/ps-release-workflow/docs/known-issues.md:36` (the "Deferred from the epic-run final review" list) says
three `_plan_slice` refusal branches in `scripts/epic.py` are untested (`~270`, `~280`, `~283`). Read against
`tests/test_epic_run.py` at head `750f52d`, only TWO of the three are actually untested, and the line numbers are
slightly off:

| Branch in `scripts/epic.py` `_plan_slice` | Line | Covered? |
|---|---|---|
| idea's `promoted_to` feature missing from the refined catalog: `"{idea} points at {F}, which is missing from the refined catalog"` | 269-271 | NO test |
| feature already `promoted` | 277 | yes, `test_epic_run.py:119` |
| feature `shipped` on another release | 279-281 | YES, `test_epic_run.py:126` (asserts `"0.9" in message`; weak but it does reach the branch) |
| feature with an unexpected status: `"{F} has unexpected status {status!r}"` | 283 | NO test |
| spec.md not found | 254 | yes, `test_epic_run.py:156` |

So the known-issues line is partly stale: "shipped on another release" is covered. This slice covers the two real gaps
and corrects that bullet.

## Scope (files this slice may touch, nothing else)

1. NEW `engine/ps-release-workflow/tests/test_epic_plan_refusals.py` (~34 lines) with two tests, using the existing
   `epic_repo` fixture (`tests/conftest.py`) and `lib.catalog.update_entry` (lib/catalog.py:84) to put the catalog in
   the impossible states without any new fixture:
   - `test_plan_refuses_a_slice_whose_feature_is_missing_from_the_refined_catalog`: `update_entry(<idea catalog>,
     "I-001", lambda e: e.update(promoted_to="F-099"))`; assert the refusal message contains `I-001`, `F-099`, `missing`.
   - `test_plan_refuses_a_feature_with_an_unexpected_status`: `promote_idea_to_refined(epic_repo, "I-001")`, then
     `update_entry(<refined catalog>, F, lambda e: e.update(status="weird"))`; assert the message contains the F id,
     `unexpected status`, `'weird'`.
   Both commit the corruption on release/<v> (`commit_all`), then also assert the refusal writes nothing: release
   HEAD unchanged and `git status --porcelain` empty, using `git` imported from `tests._helpers`
   (`from tests._helpers import git`). Fixtures/imports as `test_epic_run.py` uses them.
2. EDIT `engine/ps-release-workflow/docs/known-issues.md`: rewrite the one bullet at line 36 ("Three refusal branches are
   untested ...") to say the two branches are now covered by `tests/test_epic_plan_refusals.py` and the
   shipped-on-another-release branch was already covered by `test_epic_run.py`. Do not touch any other line.

Prototype (drafter, in a scratch COPY, not the repo): the test file as described passes, `2 passed` in ~3 s.

## Why a new file, and the honest dependency statement

New tests could sit in `test_epic_run.py`, but that file already has its own `_git` name both before and after
slice 1, so nothing would prove slice 1's work reached this slice. Putting them in a NEW file that imports
`tests._helpers.git` (which exists only after slice 1) makes the dependency observable: if `epic sync` failed to bring
slice 1's commit into this slice's worktree, this file fails at import (`ModuleNotFoundError: tests._helpers`) and the
slice cannot ship green.

This is an ENGINEERED dependency, not a semantic one. Using `git` to assert "refusal writes nothing" is a legitimate
assertion (mirrors `test_plan_writes_nothing`), but the tests would be fine without it. It exercises `epic sync` and the
order of the chain; it does not test a deep coupling. The cost of the new file: it does not reuse `_plan_error` (private to
`test_epic_run.py`), so the refusal is captured inline with `pytest.raises`.

## Out of scope

- `scripts/epic.py` and anything under `lib/` or `scripts/` (tests only; if a test exposes a bug, file it, do not fix it).
- Strengthening `test_epic_run.py:126`'s weak `"0.9"` assertion; the "refusal ordering" and "presence-only skill assertions"
  bullets in known-issues.
- Editing `test_epic_run.py`, `conftest.py`, or slice 1's helper.

## Acceptance criteria (from `engine/ps-release-workflow` in the slice worktree)

1. `python3 -m pytest tests/test_epic_plan_refusals.py -q` reports `2 passed`.
2. Each new test fails when its target branch is removed (mutation check by the reviewer, in a scratch copy only:
   deleting the `raise` at `epic.py:269` or `:283` makes the corresponding test fail).
3. `python3 -m pytest tests -q` reports `467 passed, 2 skipped` (465 + 2; slice 1 kept the count at 465).
4. `git diff --stat <sync base> HEAD` lists only `tests/test_epic_plan_refusals.py` (new) and `docs/known-issues.md`
   under `engine/ps-release-workflow/`.
5. `git diff <base> HEAD -- docs/known-issues.md` changes exactly one bullet.
6. `git status --porcelain` empty after the commit; `tests/_helpers.py` present in the worktree (proves sync).

## Risks

- Corrupting catalog state through `update_entry` bypasses the CLI: if `update_entry` semantics change the tests would
  break, but they only use the public function.
- `epic_repo` commits fixture content on release/<v>; the tests add one more commit. The `git status` assertion runs
  after that commit on purpose.
- If slice 1 is not synced in, the import error is the intended tripwire, so the implementer must not "fix" it by
  inlining a copy of the helper (call this out in the implementer brief).

## Definition of done

Criteria 1-6 pass with output pasted into the ledger; independent whole-slice review done; one commit, no amend;
`psrw ship --no-deploy` exit 0 with the `{"ok"` line; the ledger records that `epic sync` output showed `base` and that
`tests/_helpers.py` arrived via sync (not re-created by the slice).
