---
title: "Share one git test helper"
id: I-003
status: idea
---

# Share one git test helper

Epic: E-001 "Test and doc hygiene deferred from the epic-run review". Chain position: 1 of 3.
Human-approved as drafted.

## Problem

Three engine test modules each carry a private copy of a `_git` helper. Verified at release/1.1 head `750f52d`:

| File | Line | Body | Failure behaviour |
|---|---|---|---|
| `engine/ps-release-workflow/tests/test_epic_run.py` | 24-27 | `subprocess.run(..., check=True).stdout.strip()` | `CalledProcessError`, stderr NOT in the message (capture_output swallows it) |
| `engine/ps-release-workflow/tests/test_epic_run_e2e.py` | 22-25 | identical to the above | same |
| `engine/ps-release-workflow/tests/test_promote_finalize_sync.py` | 24-27 | `assert cp.returncode == 0, f"git ... failed: {cp.stderr}"` | `AssertionError` that includes stderr |

Call sites: 14 in `test_epic_run.py` (lines 187-341), 6 in `test_epic_run_e2e.py` (lines 41-66), 40 in
`test_promote_finalize_sync.py`. `tests/conftest.py` has no shared git helper (its fixtures inline
`subprocess.run(["git", ...])`). No other test file defines a `_git`/`git` helper (grep of `tests/*.py`
for `def _?git` returns exactly these three). `tests/__init__.py` exists, so `from tests._helpers import ...`
resolves (verified by prototype, see below).

Two copies fail opaquely (a bare `CalledProcessError` hides git's stderr); one fails with the reason.
Copy-paste drift is the defect. Source: `engine/ps-release-workflow/docs/known-issues.md`, epic-run review.

## Scope (files this slice may touch, nothing else)

1. NEW `engine/ps-release-workflow/tests/_helpers.py` with one function:

       def git(cwd: Path, *args: str) -> str:
           """Run `git <args>` in cwd; return stripped stdout; fail loudly with git's stderr."""

   Semantics = the `test_promote_finalize_sync.py` version (assert rc == 0, message includes stderr).
   The leading underscore keeps pytest from collecting it.
2. EDIT `tests/test_epic_run.py`, `tests/test_epic_run_e2e.py`, `tests/test_promote_finalize_sync.py`:
   delete the private `_git` def; add `from tests._helpers import git as _git`.
   The `as _git` alias is deliberate: call sites stay byte-identical, which keeps the diff to ~30 lines.
   (Renaming the ~60 call sites to `git(` is mechanical and would push the diff to ~130 lines; do not do it here.)
   In `test_epic_run_e2e.py` also delete the now-unused `import subprocess`. Keep `import subprocess` in the
   other two: `test_epic_run.py:276,345` and `test_promote_finalize_sync.py:21` still use it.

Prototype (done by the drafter in a scratch COPY of the engine, never in the repo): exactly the above gives
`_helpers.py` 10 lines + 22 changed lines in the three files, and the three modules run 41 passed
(34 + 1 + 6), same as before the change.

## Out of scope

- Any file not listed in Scope. In particular NOT `scripts/epic.py`, `lib/*`, `conftest.py`, `install.sh`.
- Converting the inline `subprocess.run(["git", ...])` calls in `conftest.py` or other test files to the helper.
- Renaming call sites; changing any assertion; touching test names or count.
- `_plan_error` and the other private helpers.

## Acceptance criteria (runnable, from `engine/ps-release-workflow` in the slice worktree)

1. `grep -rn "def _git" tests/` prints nothing.
2. `grep -rn "from tests._helpers import git" tests/` prints exactly 3 lines (the three files above).
3. `python3 -m pytest tests/test_epic_run.py tests/test_epic_run_e2e.py tests/test_promote_finalize_sync.py -q` reports `41 passed`.
4. `python3 -m pytest tests -q` reports `465 passed, 2 skipped` (unchanged count; wall-clock 4-8 min; 7m25s measured in a scratch copy).
5. `git diff --stat <sync base> HEAD` lists only: `tests/_helpers.py` (new) and the three test files, under `engine/ps-release-workflow/`.
6. `git status --porcelain` is empty after the commit.

## Risks

- Behaviour change for two of the three copies: a failing git call now raises `AssertionError` with stderr, not
  `CalledProcessError`. Only matters if a test does `pytest.raises(subprocess.CalledProcessError)` around `_git`;
  none does today (verify: `grep -n CalledProcessError tests/test_epic_run.py tests/test_epic_run_e2e.py`).
- Import path: `tests._helpers` relies on `tests/__init__.py` plus pytest rootdir on `sys.path`. Works with the
  repo's `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, run from `engine/ps-release-workflow`). Would not
  work if a test file is executed outside pytest; none is.
- Both `test_epic_run.py` and slice 2 (`tests/test_epic_plan_refusals.py`, new file) depend on this helper existing.
  S1 must ship first; that is the pilot's `epic sync` exercise.

## Definition of done

Acceptance criteria 1-6 pass with the command output pasted into the ledger; independent whole-slice review of
`git diff <base> HEAD` done (rounds recorded); one commit, no amend; `psrw ship --no-deploy` exit 0 with the
`{"ok"` line captured; the F-NNN catalog entry is `shipped` on release/1.1. No other file changed.
