# F-003 Share one git test helper — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three private copies of the `_git` test helper in the engine test-suite with one shared `tests/_helpers.py:git`, keeping every call site byte-identical.

**Architecture:** Add a new module `engine/ps-release-workflow/tests/_helpers.py` exporting a single
function `git(cwd, *args) -> str` whose semantics are the `test_promote_finalize_sync.py` version
(assert `returncode == 0`, assertion message includes git's stderr). Each of the three test modules
deletes its private `def _git` and gains `from tests._helpers import git as _git`. The `as _git`
alias is deliberate — it keeps all ~60 call sites untouched so the diff stays ~32 lines. The existing
test-suite is the safety net; this slice adds no new tests.

**Tech Stack:** Python 3.13, pytest (`[tool.pytest.ini_options]`: `testpaths = ["tests"]`,
`addopts = "-v --strict-markers"`), run from `engine/ps-release-workflow`. `tests/__init__.py`
already exists, so `from tests._helpers import ...` resolves under pytest's rootdir.

**Spec:** `.claude/refined_backlog/F-003-share-one-git-test-helper/spec.md` (read it; this plan argues from it)

## Global Constraints

- **Worktree:** all work happens in `/Users/pasitnusso/ps-skills/.claude/worktrees/F-003-share-one-git-test-helper`, branch `feat/F-003`. Never edit outside it.
- **Sync base for this slice's diff:** `1a2edaa98cfc296f47f64ee797f87ad1e5e5ae20`.
- **Files this slice may touch — nothing else.** Under `engine/ps-release-workflow/`:
  - NEW `tests/_helpers.py`
  - EDIT `tests/test_epic_run.py`, `tests/test_epic_run_e2e.py`, `tests/test_promote_finalize_sync.py`
  - plus `plan.md` / `handoff.md` under `.claude/refined_backlog/F-003-share-one-git-test-helper/`.
- **Explicitly forbidden to touch:** `scripts/`, `lib/`, `tests/conftest.py`, `install.sh`, `_catalog.json` (hand-editing `_catalog.json` is forbidden outright), and any other test file.
- **Do NOT rename call sites.** `_git(` stays `_git(` everywhere. Do not change any assertion, test name, or test count.
- **Do NOT convert** the inline `subprocess.run(["git", ...])` calls in `conftest.py` or other test files to the helper. Out of scope.
- **Exactly ONE commit** on `feat/F-003`. Never `git commit --amend`. Commit message must end with the line `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- **Forbidden commands:** `psrw ship`, `psrw promote`, `--deploy`, `git push`, opening a PR, merging to main, `rm -rf`.
- **Expected final counts (verbatim from spec):** three-module run = `41 passed`; full suite = `465 passed, 2 skipped`.
- **Bash timeouts cap at 600000 ms.** The full suite measures ~7m25s, which fits. Do NOT write `timeout: 900000` — the tool rejects it.
- **Approved deviation from spec AC5.** Spec AC5 (`spec.md:65`) and the DoD say the diff lists *only*
  `tests/_helpers.py` plus the three test files, and "No other file changed". This slice's planning doc
  `.claude/refined_backlog/F-003-share-one-git-test-helper/plan.md` is ALSO modified and **is committed**,
  because the slice's scope explicitly permits `plan.md` / `research.md` in that folder and the commit must
  leave `git status --porcelain` empty (AC6). Read AC5's "only" as *only, among files under
  `engine/ps-release-workflow/`*. Nothing else may appear in the diff. This deviation is explicit and approved;
  it is not licence to add any further file.
- **Handback contract — the spec's DoD tail is deliberately NOT owned by this plan.** The spec's Definition of
  Done also requires `psrw ship --no-deploy` exit 0 with its `{"ok"` line captured, the ledger paste, and the
  catalog entry flipped to `shipped` on `release/1.1`. Those steps belong to the **caller**, not this plan —
  `psrw ship` is on this slice's forbidden list. This plan ends at: one commit on `feat/F-003`, a clean tree,
  and AC1-AC6 output pasted. Hand that back; do not attempt the ship.

---

### Task 1: Extract the shared `git` helper and rewire the three modules

**Files:**
- Create: `engine/ps-release-workflow/tests/_helpers.py`
- Modify: `engine/ps-release-workflow/tests/test_epic_run.py` (import block ends line 21; delete `def _git` at lines 24-27)
- Modify: `engine/ps-release-workflow/tests/test_epic_run_e2e.py` (delete `import subprocess` line 8; import block ends line 19; delete `def _git` at lines 22-25)
- Modify: `engine/ps-release-workflow/tests/test_promote_finalize_sync.py` (import block ends line 16; delete `def _git` at lines 24-27)
- Test: no new test file. The existing three modules ARE the test.

**Interfaces:**
- Consumes: nothing from earlier tasks (this is the first task).
- Produces: `tests/_helpers.py` exporting exactly one public name:
  `git(cwd: Path, *args: str) -> str` — runs `git <args>` in `cwd`, returns stripped stdout,
  raises `AssertionError` (message contains git's stderr) on non-zero exit.
  Task 2 and the follow-on epic slices depend on this exact name and signature.

- [ ] **Step 1: Record the baseline — run the three modules BEFORE any edit**

All commands in this task run from the engine directory:

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-003-share-one-git-test-helper/engine/ps-release-workflow
python3 -m pytest tests/test_epic_run.py tests/test_epic_run_e2e.py tests/test_promote_finalize_sync.py -q 2>&1 | tail -n 3
```

Expected: a line reporting `41 passed` (34 + 1 + 6). If the baseline is NOT 41 passed, STOP and
report — the tree is not in the state the spec was written against, and nothing below is valid.

- [ ] **Step 2: Create `tests/_helpers.py`**

Create `engine/ps-release-workflow/tests/_helpers.py` with exactly this content:

```python
"""Shared helpers for the engine test-suite. Not a test module."""
import subprocess
from pathlib import Path


def git(cwd: Path, *args: str) -> str:
    """Run `git <args>` in cwd; return stripped stdout; fail loudly with git's stderr."""
    cp = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert cp.returncode == 0, f"git {' '.join(args)} failed: {cp.stderr}"
    return cp.stdout.strip()
```

This body is the `test_promote_finalize_sync.py` version verbatim — the one that surfaces stderr.
Do not add extra arguments, a `check=` parameter, retries, or logging. One function, nothing else.

The filename must be `_helpers.py` as the spec mandates. Note for accuracy: pytest skips this module
because it does not match the default `python_files = test_*.py` glob, not because of the underscore —
so do not "fix" the name, and do not repeat the underscore claim in the shipped docstring.

- [ ] **Step 3: Rewire `tests/test_epic_run.py`**

Replace this exact text (lines 21-29, the last import plus the private helper and the two blank lines after it):

```python
from scripts.ship_current_work_to_release import DirtyTreeError, NotInFeatureWorktreeError


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


```

with:

```python
from scripts.ship_current_work_to_release import DirtyTreeError, NotInFeatureWorktreeError
from tests._helpers import git as _git


```

`tests` sorts after `scripts`, so the new import belongs at the end of the import block and stays
isort-clean. **Keep `import subprocess` (line 4)** — it is still used at lines 282 and 351.

- [ ] **Step 4: Rewire `tests/test_epic_run_e2e.py`**

First, delete the now-unused `import subprocess`. Replace:

```python
import subprocess
from pathlib import Path
```

with:

```python
from pathlib import Path
```

`Path` stays — it is still used in `_run_slice(repo: Path, ...)`.

Then replace this exact text (lines 19-27 in the original numbering, including the two trailing blank lines):

```python
from scripts.ship_current_work_to_release import ship_current_work


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


```

with:

```python
from scripts.ship_current_work_to_release import ship_current_work
from tests._helpers import git as _git


```

- [ ] **Step 5: Rewire `tests/test_promote_finalize_sync.py`**

Replace this exact text (the last import; line 16):

```python
from scripts.promote_release import cleanup, _finalize_release_state
```

with:

```python
from scripts.promote_release import cleanup, _finalize_release_state
from tests._helpers import git as _git
```

Then delete the private helper — replace:

```python
def _git(cwd: Path, *args: str) -> str:
    cp = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert cp.returncode == 0, f"git {' '.join(args)} failed: {cp.stderr}"
    return cp.stdout.strip()


def _release_json(in_progress: bool) -> str:
```

with:

```python
def _release_json(in_progress: bool) -> str:
```

**Keep `import subprocess` (line 11)** — still used by `_gh_no_pr` at line 21. **Keep
`from pathlib import Path`** — `Path` appears on 10 lines in this file, so it remains used after the
helper's signature goes away. Verify with Step 7's grep rather than assuming.

- [ ] **Step 6: Run the three modules — expect the same 41 passed**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-003-share-one-git-test-helper/engine/ps-release-workflow
python3 -m pytest tests/test_epic_run.py tests/test_epic_run_e2e.py tests/test_promote_finalize_sync.py -q 2>&1 | tail -n 3
```

Expected: `41 passed` — identical to the Step 1 baseline. Any failure means the rewire is wrong;
fix the rewire, never the test being run.

- [ ] **Step 7: Unused-import check (no flake8/pyflakes is installed in this environment)**

Confirm that every import left behind is still referenced, and that no import was dropped that is
still needed:

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-003-share-one-git-test-helper/engine/ps-release-workflow
for f in tests/test_epic_run.py tests/test_epic_run_e2e.py tests/test_promote_finalize_sync.py; do
  echo "--- $f"
  echo -n "  subprocess refs: "; grep -c "subprocess" "$f"
  echo -n "  Path refs:       "; grep -c "Path" "$f"
done
```

Expected:
- `test_epic_run.py` — `subprocess` ≥ 2 (import + real uses), `Path` ≥ 2.
- `test_epic_run_e2e.py` — `subprocess` **0** (the import was deleted and the only other use was the
  deleted helper), `Path` ≥ 2.
- `test_promote_finalize_sync.py` — `subprocess` ≥ 2, `Path` ≥ 2.

A count of exactly 1 for either name means that import is now unused — delete it. A count of 0 for
`subprocess` in a file that still calls `subprocess.` means the import was wrongly deleted — restore it.

- [ ] **Step 8: Acceptance criteria 1 and 2**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-003-share-one-git-test-helper/engine/ps-release-workflow
echo "--- AC1: expect NO output"; grep -rn "def _git" tests/ ; echo "(exit $?)"
echo "--- AC2: expect exactly 3 lines"; grep -rn "from tests._helpers import git" tests/
echo "--- spec risk check: expect NO output"; grep -n CalledProcessError tests/test_epic_run.py tests/test_epic_run_e2e.py
```

Expected: AC1 prints nothing (grep exits 1). AC2 prints exactly 3 lines — one each for
`test_epic_run.py`, `test_epic_run_e2e.py`, `test_promote_finalize_sync.py`.

The third grep is the spec's own risk verification (`spec.md:69-71`): the helper's failure mode changes
from `CalledProcessError` to `AssertionError`, which would only matter if a test wrapped `_git` in
`pytest.raises(subprocess.CalledProcessError)`. It must print nothing. If it prints anything, STOP —
the spec's risk analysis no longer holds.

- [ ] **Step 9: Acceptance criterion 5 — the diff touches only the four files**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-003-share-one-git-test-helper
git status --porcelain
```

Expected exactly (order may vary; the `.claude/refined_backlog/F-003-share-one-git-test-helper/plan.md`
entry from this planning step is expected too and is committed together with the change):

```
 M .claude/refined_backlog/F-003-share-one-git-test-helper/plan.md
 M engine/ps-release-workflow/tests/test_epic_run.py
 M engine/ps-release-workflow/tests/test_epic_run_e2e.py
 M engine/ps-release-workflow/tests/test_promote_finalize_sync.py
?? engine/ps-release-workflow/tests/_helpers.py
```

The `plan.md` line is expected — it is already modified in the worktree by the planning step (verified
with `git status --porcelain` before execution began) and is committed alongside the change, per the
"Approved deviation from spec AC5" constraint above.

If ANY other path appears under `engine/ps-release-workflow/` — especially `scripts/`, `lib/`,
`conftest.py`, `install.sh`, or `_catalog.json` — STOP and report. Do not revert it silently and do
not commit it.

- [ ] **Step 10: Commit — ONE commit, never `--amend`**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-003-share-one-git-test-helper
git add engine/ps-release-workflow/tests/_helpers.py \
        engine/ps-release-workflow/tests/test_epic_run.py \
        engine/ps-release-workflow/tests/test_epic_run_e2e.py \
        engine/ps-release-workflow/tests/test_promote_finalize_sync.py \
        .claude/refined_backlog/F-003-share-one-git-test-helper/
git commit -m "$(cat <<'EOF'
refactor(tests): share one git helper across the engine test-suite

Three test modules each carried a private `_git` copy; two of them used
check=True with capture_output, so a failing git call raised a bare
CalledProcessError with git's stderr swallowed. Extract one
tests/_helpers.py:git with the loud semantics (assert rc == 0, stderr in
the message) and import it as `_git` in all three, leaving every call
site byte-identical.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
git log --oneline -1
```

Expected: one new commit on `feat/F-003`. Do NOT run `git push`, `psrw ship`, or `psrw promote`.

- [ ] **Step 11: Phase gate** (rule 7): the diff is ~32 lines in one subsystem, so a single gate
covers the whole task. Verify (Steps 6-9 already run) → independent review by `code-reviewer` plus
`python-reviewer` (`model: sonnet`) on `git diff 1a2edaa98cfc296f47f64ee797f87ad1e5e5ae20 HEAD` →
act on blocking findings **inside the Scope above only** (if a finding requires touching `scripts/`,
`lib/`, or `conftest.py`, record it and do NOT act) → re-verify with Step 6 if anything changed.
Because only one commit is allowed, prefer running the reviewers on the staged diff *before* Step 10
so any fix lands in the same commit.

---

### Task 2: Full-suite verification and the acceptance gate

**Files:** none — this task changes no file. It only runs commands and reports output.

**Interfaces:**
- Consumes: `tests/_helpers.py:git` and the committed rewire from Task 1.
- Produces: the pasted command output that satisfies the spec's Definition of Done.

- [ ] **Step 1: Run the full suite (takes 4-8 minutes — pass `timeout: 600000`, the Bash tool's maximum; measured 7m25s fits)**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-003-share-one-git-test-helper/engine/ps-release-workflow
python3 -m pytest tests -q 2>&1 | tail -n 5
```

Expected: `465 passed, 2 skipped` — the count is **unchanged** from before the slice. A different
total means a test was added, removed, or renamed, which the spec forbids: STOP and report.
If any test fails, invoke `systematic-debugging`; do not paper over it and do not change an assertion.

- [ ] **Step 2: Acceptance criterion 3 — the three modules**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-003-share-one-git-test-helper/engine/ps-release-workflow
python3 -m pytest tests/test_epic_run.py tests/test_epic_run_e2e.py tests/test_promote_finalize_sync.py -q 2>&1 | tail -n 3
```

Expected: `41 passed`.

- [ ] **Step 3: Acceptance criteria 1, 2, 5, 6 — re-run against the committed tree**

```bash
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-003-share-one-git-test-helper/engine/ps-release-workflow
echo "--- AC1 (expect no output)"; grep -rn "def _git" tests/
echo "--- AC2 (expect 3 lines)";   grep -rn "from tests._helpers import git" tests/
cd /Users/pasitnusso/ps-skills/.claude/worktrees/F-003-share-one-git-test-helper
echo "--- AC5 (diff stat vs sync base)"; git diff --stat 1a2edaa98cfc296f47f64ee797f87ad1e5e5ae20 HEAD
echo "--- AC6 (expect empty)"; git status --porcelain; echo "(end)"
```

Expected:
- AC1: nothing.
- AC2: exactly 3 lines.
- AC5: only `engine/ps-release-workflow/tests/_helpers.py` (new) and the three test files, plus the
  `.claude/refined_backlog/F-003-share-one-git-test-helper/` planning docs.
- AC6: empty output — the tree is clean.

- [ ] **Step 4: Report**

Report: status, the commit sha, files changed, the last 3 lines of the full-suite output, and the
literal output of the acceptance greps. Do not run `psrw ship`, `psrw promote`, or `git push` —
those belong to the caller.

---

## Appendix — audit trail

- 2026-09-19 `self-grill-audit` (one independent adversarial auditor, told to refute, file:line evidence).
  Verdict **safe-with-fixes**. 9 findings: 2 HIGH, 3 MEDIUM, 4 LOW. All claims re-verified on disk before
  editing. Corrected in this plan:
  - HIGH 1 — Task 2 Step 1 said "≥900000 ms timeout"; the Bash tool caps `timeout` at 600000 ms, making the
    call uninvokable. Now `timeout: 600000` (measured 7m25s fits), plus a Global Constraint.
  - HIGH 2 — the plan silently redefined spec AC5 by committing `plan.md`. Now an explicit, stated deviation
    ("only" = only among files under `engine/ps-release-workflow/`), justified by AC6's clean-tree requirement.
  - MEDIUM 3 — the Step 9 "Expected exactly" block omitted the already-modified
    ` M .claude/refined_backlog/F-003-share-one-git-test-helper/plan.md`. Added.
  - MEDIUM 4 — the spec's own risk check (`grep -n CalledProcessError ...`, `spec.md:69-71`) appeared nowhere.
    Folded into Task 1 Step 8. Pre-verified: zero hits anywhere under `tests/`.
  - MEDIUM 5 — the spec's DoD tail (`psrw ship --no-deploy`, ledger paste, catalog `shipped`) was unowned.
    Now stated as an explicit handback contract to the caller.
  - LOW 6 — off-by-one line-range labels (21-28 → 21-29, 19-26 → 19-27). Fixed; text-match remains authoritative.
  - LOW 7 — the shipped docstring baked in a wrong causal claim (underscore ⇒ not collected). Collection is
    governed by `python_files = test_*.py` (verified: no override in `pyproject.toml`). Docstring shortened;
    the correct reason is noted in the plan, not in the shipped file.
  - Auditor also confirmed, and this plan relies on: all three replace-blocks match byte-for-byte at
    `1a2edaa`; `--collect-only -q` gives 41 and 467 (= 465 passed + 2 skipped); `tests._helpers` resolves;
    no lint/pre-commit gate exists (CI runs only `pytest -q`); downstream slice I-004 needs exactly
    `tests._helpers.git`. It also found the *spec* stale at one point — `spec.md:46` cites
    `test_epic_run.py:276,345` for the surviving `subprocess` uses; the real lines are 282 and 351. The spec
    is approved and is NOT edited; this plan carries the correct numbers.
- **Not applied, deliberately:**
  - LOW 8 — auditor flagged the `Co-Authored-By: Claude Sonnet 5` trailer as possibly wrong. It is the
    trailer this slice's instructions mandate verbatim, so it stands. Do NOT "correct" it during execution.
  - LOW 9 — the spec's call-site counts (14/6/40) include the `def _git(` line; true call sites are 13/5/39.
    Cosmetic; this plan says "~60" and the spec is not edited.
