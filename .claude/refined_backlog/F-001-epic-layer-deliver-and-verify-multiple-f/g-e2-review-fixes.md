# G-E2 ship-time gate — review-fix spec, plan, and outcome

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development to
> execute the tasks below task-by-task if re-run from a plan. This document
> already carries its own completed execution + verification (see
> "Outcome" at the bottom of each task) — treat it as both the spec/plan and
> the closure record for this batch.

**Goal:** Close every CONFIRMED finding from the independent adversarial
review of Task 3 (G-E2, the ship-time epic-verification gate) in
`engine/ps-release-workflow`, with the minimal correct fix per finding, no
unrelated refactors, and the full `pytest` suite green afterward.

**Architecture:** No new components. All fixes tighten existing
concurrency/locking, error-handling, and data-flow contracts in
`lib/epic.py`, `lib/epic_gate.py`, `scripts/ship_current_work_to_release.py`,
and `scripts/epic.py` — the same four files Task 3 introduced.

**Spec:** `.claude/refined_backlog/F-001-epic-layer-deliver-and-verify-multiple-f/spec.md`
(canonical F-001 spec, in the `_release` worktree) — this doc is a
review-response addendum to Task 3 of that feature's plan, not a new spec.

**Review input:** 15 findings from an independent adversarial review,
deduped below to 10 distinct defects (several findings described the same
mechanism from different angles — see "Dup of" column).

## Global Constraints

- No refactor beyond what each finding requires; unrelated code untouched.
- Every fix keeps the existing 41 tests in
  `tests/test_epic_gate.py tests/test_epic_cli.py tests/test_ship_current_work_to_release.py`
  green, plus the full suite.
- Locking discipline unchanged: the multi-minute `epic-check` hook still runs
  OUTSIDE `file_lock(rel_wt)` (stalling every concurrent ship to hold that
  lock across it was an explicit, documented design rejection in Task 3) —
  only catalog writes and quick copies are ever done under the lock.

---

## Task list (10 defects, 15 findings)

### Task 1 — CAS win left uncommitted (findings #1, #7 — high, dup)

**Files:** `scripts/ship_current_work_to_release.py:149-170`

**Problem:** `try_begin_verification` writes `status="verifying"` via a plain
filesystem replace (`lib/state.py mutate_state` — no git). Ship read/CAS'd
this under `file_lock(rel_wt)` but never committed it before releasing the
lock. A concurrent ship whose own Gate 1 fails runs
`git reset --hard HEAD~1` in the same shared `_release` worktree, wiping the
uncommitted write and reverting the epic to `"open"` while the winner's
multi-minute check is still running — the exact double-run the CAS exists to
prevent, and the eventual `mark_epic_verified`/`mark_epic_failed` then no-ops
against a wrong `from_status`.

**Fix:** `commit_all(rel_wt, ...)` immediately after a won
`try_begin_verification`, still inside `with file_lock(rel_wt):`.

**Outcome:** Fixed. `scripts/ship_current_work_to_release.py:170`. Verified
by direct repro (`scenario_1_commit_survives_reset` in
`repro_fixes.py` — see Verification below): the CAS write now survives a
concurrent `reset --hard`. Full suite green.

### Task 2 — mark_* not scoped to the winning sha (findings #2, #8 — high, dup)

**Files:** `lib/epic.py:148-176`, `lib/epic_gate.py` (call sites)

**Problem:** `_transition`'s guard checked only `status == "verifying"`, not
that `verifying_sha` still belongs to the caller's run. `psrw epic verify
--force` can re-enter `"verifying"` with a new sha while a stale run for the
old sha is still finishing; whichever lands second can silently clobber or
be silently dropped by the other.

**Fix:** `_transition` takes an optional `sha` and additionally requires
`entry['verifying_sha'] == sha`; `mark_epic_verified` always passes it,
`mark_epic_failed` gained an optional `sha` parameter that `run_and_record`
now supplies (it already had `sha` in scope).

**Outcome:** Fixed. `lib/epic.py:148-179`. Verified by direct repro
(`scenario_2_stale_run_cannot_clobber_fresh_claim`): the stale run's
`mark_epic_verified` now no-ops, and the fresh run's `failed_verification`
verdict is recorded instead of being dropped. All existing `test_epic.py`
calls pass an unchanged sha end-to-end, so none needed updating. Full suite
green.

### Task 3 — commit_all raises on a no-op record (finding #3 — medium)

**Files:** `lib/epic_gate.py:run_and_record`

**Problem:** `commit_all` was unconditional after the `mark_*` call; when
`_transition` (Task 2's guard, or the pre-existing status guard) no-ops, the
tree is clean and `git commit` exits non-zero → `GitError` escapes
`run_and_record` even though the merge and Gate 1 already succeeded.

**Fix:** Guard with `is_dirty(rel_wt)`, mirroring the exact idiom ship
already uses for its own catalog commit
(`ship_current_work_to_release.py:146`).

**Outcome:** Fixed. `lib/epic_gate.py` (both the normal and the
exception-recovery `commit_all` calls in `run_and_record`). Full suite
green.

### Task 4 — no try/except around the hook run (findings #4, #9 — medium, dup)

**Files:** `lib/epic_gate.py:run_and_record`

**Problem:** Any exception between the won CAS and the record (a hook
committed without its exec bit → `PermissionError`, a `git worktree add`
failure, ...) left the epic pinned in `"verifying"` forever — no timeout,
recoverable only via `psrw epic verify --force`.

**Fix:** Wrap the `run_epic_check` call in `try/except Exception`; on
failure, print a warning and record `failed_verification` (with the
winning `sha`, per Task 2) under the same short lock, then return instead of
propagating.

**Outcome:** Fixed. `lib/epic_gate.py:run_and_record`. Verified by direct
repro (`repro_crash.py`): a non-executable `epic-check.sh` now raises
`PermissionError` internally but `run_and_record` catches it, prints a
warning, and leaves the catalog at `failed_verification` instead of
`verifying`. Full suite green.

### Task 5 — features list can contain None (findings #5, #13 — medium/low, dup)

**Files:** `scripts/ship_current_work_to_release.py:167-184`

**Problem:** `add_idea_entry` seeds `promoted_to=None`; the feature list was
built without the `if i.get("promoted_to")` filter that the equivalent line
in `scripts/epic.py:191` already had. A concurrent `epic fanout` landing
between the lock release and this (unlocked) re-read could poison the list
with `None`, crashing `",".join(sorted(features))` with a `TypeError`.

**Fix:** Add the same filter used in `scripts/epic.py`.

**Outcome:** Fixed. `scripts/ship_current_work_to_release.py:183-184`. Full
suite green (no existing test exercised the mixed list, so this is a
defensive parity fix, not a regression fix).

### Task 6 — epic_verify's HEAD read + CAS unlocked (findings #6, #14 — low, dup)

**Files:** `scripts/epic.py:epic_verify`

**Problem:** Ship reads HEAD and CASes under `file_lock(rel_wt)` precisely
because HEAD is only stable there; `epic_verify` (the `psrw epic verify`
CLI path) did the same rev-parse + CAS with no lock, so it could capture a
sha a concurrent ship's Gate-1 rollback then discards.

**Fix:** Wrap the rev-parse + `try_begin_verification` call in
`with file_lock(rel_wt):`, matching ship's own pattern exactly.

**Outcome:** Fixed. `scripts/epic.py` (inside `epic_verify`). Full suite
green, including `tests/test_epic_cli.py::test_verify_manually_reruns_the_check`.

### Task 7 — PSRW_EPIC_DIR="" when no epic folder exists (finding #10 — medium)

**Files:** `lib/epic_gate.py:run_epic_check`

**Problem:** When `epic_folder_path` returns `None` (folder renamed/removed
off `release/<v>`), the env var was set to the empty string. A hook
following the documented `"$PSRW_EPIC_DIR/marker"` pattern resolves to
`/marker` at the filesystem root and fails for a reason unrelated to the
actual outcome check.

**Fix:** Omit the `PSRW_EPIC_DIR` key entirely when `epic_dir is None`,
rather than setting it to `""`. (The hook must still run in this case — two
existing tests scaffold a real hook and call `run_epic_check` without an
`epic_dir` at all — so "warn and skip" was rejected in favor of "omit the
var" to avoid a behavior change unrelated to this finding.)

**Outcome:** Fixed. `lib/epic_gate.py:run_epic_check`. Full suite green,
including the two tests that call `run_epic_check` without `epic_dir`.

### Task 8 — PSRW_EPIC_DIR points into the shared, mutable tree (finding #11 — medium)

**Files:** `lib/epic_gate.py:run_epic_check`

**Problem:** `epic_dir` (from `epic_folder_path`) resolves inside the same
shared `_release` worktree every concurrent ship mutates
(`git add -A`, `reset --hard HEAD~1`). The hook can stream output there for
minutes while unrelated ships commit or roll back the same tree underneath
it.

**Fix:** The hook now writes to a scratch directory inside this run's own
throwaway temp dir (`Path(tmp) / "epic_output"`), isolated from `rel_wt` for
the entire run. Once the hook returns (success or failure), the `finally`
block copies the scratch dir's final contents onto the real `epic_dir` — a
single fast copy at the very end, not a multi-minute stream into the shared
tree. This copy is the point where `run_and_record`'s later `commit_all`
(under `file_lock(rel_wt)`) picks the files up via `git add -A`.

**Note (documented deviation):** the finding's suggested fix said "copy
results back under the lock in `run_and_record`." I copy back inside
`run_epic_check`'s own `finally` instead, one level down, because
`tests/test_epic_gate.py` calls `run_epic_check` directly (not through
`run_and_record`) and asserts the file is readable at `epic_dir` immediately
after it returns — moving the copy into `run_and_record` would have broken
that test's contract. The residual risk is narrower than what the finding
described (a single `shutil.copytree` at the very end, not the whole
multi-minute hook run) but is not literally zero; flagging this here rather
than silently claiming full closure, per verification discipline.

**Outcome:** Fixed (with the documented deviation above).
`lib/epic_gate.py:run_epic_check`. Full suite green, including
`tests/test_ship_current_work_to_release.py::test_second_ship_does_not_run_a_second_check`,
which specifically reads the hook's marker file back from `rel_wt` after
`ship_current_work` — proving the copy-back still lands the file where
downstream code expects it.

### Task 9 — worktree-remove GitError masks the real outcome (finding #15 — low)

**Files:** `lib/epic_gate.py:run_epic_check`

**Problem:** The `finally`'s `git worktree remove --force` used
`check=True`; if it failed, the resulting `GitError` replaced the `try`
block's return value (or any in-flight exception) per normal Python
`finally` semantics, turning a legitimately passing (or failing) check into
an opaque `GitError`.

**Fix:** Catch `GitError` around that call, print a warning naming the
snapshot path and suggesting `git worktree prune`, and continue — the
function's real return value (or exception, from Task 4's new
try/except) is preserved.

**Outcome:** Fixed. `lib/epic_gate.py:run_epic_check`. Full suite green,
including `tests/test_epic_gate.py::test_snapshot_worktree_is_removed_afterwards`.

### Task 10 — ship silently reports success on a failed epic check (finding #12 — medium)

**Files:** `scripts/ship_current_work_to_release.py` (`ship_current_work`
and `main`)

**Problem:** `run_and_record`'s `(rc, entry)` return was discarded; `main()`
always printed `✅ Shipped ...` and exited 0, even when the epic check the
same ship just triggered failed and was recorded `failed_verification`. The
only place this would surface was `G-E3` at promote time — a release cycle
later.

**Fix:** `ship_current_work` now returns an `epic_outcome` dict
(`{epic, rc, sha}` or `None`) alongside the existing fields; `main()` prints
a loud `stderr` warning (naming the epic, exit code, and the
`--force` re-check command) whenever `epic_outcome["rc"]` is not `None`/`0`.
Exit code and the `✅ Shipped` line are unchanged — the merge itself did
succeed — matching the existing precedent for a failing local-deploy script
just below it in the same function.

**Outcome:** Fixed. `scripts/ship_current_work_to_release.py`. Full suite
green, including `test_failing_epic_check_leaves_the_merge_standing` (which
did not previously assert on stdout/stderr and needed no changes to keep
passing).

---

## Verification

```
$ python3 -m pytest tests/test_epic_gate.py tests/test_epic_cli.py tests/test_ship_current_work_to_release.py -q
41 passed in 32.98s

$ python3 -m pytest tests/test_epic.py -q
13 passed in 0.05s

$ python3 -m pytest -q          # full repo suite
386 passed, 2 skipped in 158.31s
```

Plus two standalone repro scripts (not part of the committed test suite —
scratch verification only) exercising the two highest-severity races
directly against the real functions in a throwaway git worktree:

- `scenario_1_commit_survives_reset` (Task 1): CAS write now survives a
  concurrent `reset --hard` → PASS.
- `scenario_2_stale_run_cannot_clobber_fresh_claim` (Task 2): stale run
  no-ops, fresh failing verdict is recorded → PASS.
- Non-executable-hook crash repro (Task 4): `run_and_record` catches the
  `PermissionError` and records `failed_verification` instead of raising or
  stranding the epic in `verifying` → PASS.

## Phase gate (rule 7)

- **Implement:** all 10 tasks above, batched as one commit (small, same
  subsystem, same review round — per the "batch small related phases"
  guidance).
- **Verify:** pytest output above (fresh run, this session).
- **Review:** this batch IS the response to an already-independent
  adversarial review; no further self-review round was run before this
  commit given the findings were already externally verified line-by-line.
  A follow-up `code-reviewer` pass on the diff is recommended before
  promoting this release, given two of the ten defects (Tasks 1 and 2) are
  concurrency-sensitive and only exercised here by hand-rolled repros, not
  by the committed test suite.
- **Refactor:** none needed — every change is additive/corrective within
  the existing four files; no duplication or dead code introduced.
- **Re-verify:** full suite re-run after every file edit (see Verification).

## Known gaps / follow-ups (filed, not chased — rule 4)

- Tasks 1, 2, and 4's exact race conditions have no permanent regression
  test in the committed suite (only the manual repro scripts). Consider a
  follow-up task to port `scenario_1`/`scenario_2`/the crash repro into
  `tests/test_epic.py` / `tests/test_epic_gate.py`.
- Task 8's documented deviation (copy-back one level down from where the
  finding suggested) leaves a narrow residual race during the final
  `shutil.copytree` itself. Closing it fully would need `run_epic_check` to
  either take `rel_wt`'s lock for just that copy, or have `run_and_record`
  do the copy instead of `run_epic_check` — which would require updating
  `tests/test_epic_gate.py`'s direct-call tests to go through
  `run_and_record`. Not done here as out of scope for a "minimal fix."
