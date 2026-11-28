# Final whole-branch review — F-025 (fix the 32 open vault sync review findings)

Range 3204b99..8c277b8, limited to `tools/vault-engine/` (18 files, +936/-99).
Reviewed from `final-review.diff` in four passes (whole file read once), plus
read-only look-ups in the worktree for call sites. No tests or harness run by
me (the controller runs both); nothing in the tree, index or branches changed.

Paths below are relative to `tools/vault-engine/`; `pv/` = `pkg/vaultsync/`.

## Strengths

- **All 32 items have a hunk and none is half done.** Checked item by item
  against `open-findings.md` and the plan's per-item table. The 21 commit
  subjects name all of A1 to A32.
- **Scope held.** Every changed file is under `tools/vault-engine/`. The three
  changes outside an item's named lines are each explained: `main.go:42`
  (A13's new `dir` argument), the `chargeDaily` sentinel in `hub.go` (ledger
  ruling, caused by A7), and the rewritten undo comment in `recover.go`
  (same ruling). No drive-by refactor found.
- **The five behaviour changes each have a test that fails without the fix**
  (A1: three fetches instead of one; A4: the listed file would be removed;
  A5: the file would be quarantined; A7: no folder sync call; A8: the label
  would be engine-error).
- **Cross-task seams line up** (details under "Cross-task checks").

## Cross-task checks (what the task reviews could not see)

1. **Task 1's `errFolderSync` and Task 2's hub work in `chargeDaily`.** Fine.
   The sentinel is raised only after a successful rename (`pv/recover.go:574`);
   Task 2's "usage file cannot be written" tests fail before the rename (a
   folder sits on the `.tmp` name), so they take the plain error path and
   charge nothing. The two branches cannot be confused. The third caller of
   `writeFileAtomic`, the quarantine copy in `setAside` (`pv/recover.go:614`),
   also behaves safely on the sentinel: the copy is in place, the caller stops,
   and the retry finds the copy through `hasCopy` and writes the report line.
2. **Task 5's `gitIn` environment against tests from Tasks 1 to 4.** Fine.
   `gitIn` now uses `placeEnv(dir)`, which is the same environment production
   `Repo.run` already uses, so the ceiling variable reaching the hub hook
   through a local push is not new behaviour. No Task 1 to 4 test calls `gitIn`
   on a sub-folder of a repository (which the ceiling would break). `hubRepo`
   (Task 2) clears the same variable set in the process for in-process
   `PreReceive` calls. The one gap is the already-logged one (see triage, group 3).
3. **Task 2's exit code 6 against the README (Task 6) and `syncer.go`.**
   Consistent. `pv/syncer.go:317-320` cuts the label out of the hub's line and
   `violationOutcome` maps `type-not-allowed` to exit 6; the README table row
   and the new sentence at `README.md:82` say the same. Real-push parsing of a
   hook refusal is already covered by `TestHub_HookItselfRefusesAHistoryRewrite`,
   so the seam-based exit-6 test is enough.
4. **`Undo` now refusing with no marker (A4) against its two production
   callers** (`pv/syncer.go:222`, `pv/syncer.go:425`). Neither can reach `Undo`
   after the marker is removed: both call `End` only after `Undo` returns.
5. **A5's wrapped `ErrStopped` from `Update`** still satisfies `errors.Is`, so
   the daemon keeps treating it as a stop, not a refusal.
6. **Tests that cannot fail:** none found. `TestUndo_RefusesAMarkerThatBelongsToAnotherSave`
   and the two A24 tests pass before and after by design (A16 and A24 are
   test-only items that pin existing behaviour).

## Issues

### Critical (Must Fix)

None.

### Important (Should Fix)

None.

### Minor (Nice to Have)

1. **`README.md:82` says more than the code does.** "A send that points
   `refs/heads/main` at something other than a commit (a tree or a blob) is
   also refused as `type-not-allowed`" is unconditional, but the type check at
   `pv/hub.go:117-119` only runs when the hub already has a main line and the
   ancestor check has failed. On an empty hub the same send is answered
   `engine-error` ("cannot list incoming commits"), and an annotated tag passes
   the hook. Why it matters: the README is the contract an operator reads.
   Fix: add "when the hub already has a main line", or leave it and let the
   filed idea (an up-front type check on the new tip) make the sentence true.
2. **`pv/syncer.go:55-57` comment example.** It illustrates "one error can
   match more than one case" with `ErrStopped`, `ErrTimedOut` and
   `*exec.ExitError`, none of which is a case of the switch. The rule it states
   (order decides) is right. Fix: use a real pair, or drop the parenthesis.
3. **`pv/recover.go:107` (`Begin`) on a folder-sync failure.** `Begin` returns
   an error while the marker is already on disk. The next command's `Recover`
   then treats it as a crashed save and moves untracked files outside `_inbox/`
   to quarantine. Nothing is lost and it matches the rule stated on
   `writeFileAtomic`, but it is not said at `Begin` and has no test. Worth one
   comment line. Related note, not a finding: on a filesystem that refuses to
   sync a folder, every save would now be refused. I have no evidence any place
   or hub lives on such a filesystem; keep it in mind when the hub moves to a
   server.
4. **`pv/hub.go:248-252`** swallows the folder-sync error with no log line.
   `chargeDaily` has no writer to log to; the caller does. Acceptable as is.
5. The remaining minors are the ledger's deferred items; see the triage.

## Deferred / Parked Triage

Deferred minors, by group:

- **Task 1 — `chargeDaily` swallows the folder-sync error unlogged; undo's and
  `Begin`'s folder-sync branches have no test:** ships as-is. Both branches are
  safe by reading (the next pass reads the marker from disk; the usage file is
  in place). The failure needs a disk error at one exact moment.
- **Task 2 — new A8 tests do not clear git location variables
  (`pv/hub_test.go:476`, `:498`); exit-6 test uses the seam:** ships as-is.
  Under an exported `GIT_DIR` they fail loudly and write nothing; the suite is
  not clean in that situation anyway (the plan's own follow-up for `newWorld`
  and `newHub`). Fold into that follow-up.
- **Task 3 — the signal helper's stderr message is discarded
  (`pv/repo_test.go:148`):** ships as-is, and it does **not** defeat A27. A27
  asked for the helper to stop printing "started" when the pid file never
  appears and for the parent's `Atoi` error to be checked. Both are done, and
  the parent now fails at once on the missing "started" line and kills the
  helper. Only the extra reason text is lost; `holder.Stderr = os.Stderr` is a
  one-line nicety for later.
- **Task 3 — two unclear test failure messages:** ships as-is.
- **Task 4 — `cancelledAt` does not wait for `Run` on its 30 s failure path
  (`pv/daemon_test.go:654`); `closedWhen` does not wait for its poller
  (`:528`); `waitingForFolderLock` matches any goroutine (`:548`):** ships
  as-is. The first two only matter after a test has already failed or ended;
  the third is safe while no test in the package is parallel (none is).
- **Task 5 — A9 has no regression test; the 15-minute build limit is never
  exercised:** ships as-is. Both reviewers proved A9 by experiment on bash 3.2;
  the assignment is at top level, so `set -e` applies.
- **Task 6 — `README.md:61`, `README.md:82`, `pv/syncer.go:55-57` slightly
  wider than the code:** ships as-is. `README.md:61` is the wording A1 asked
  for word for word. The other two are Minor 1 and 2 above; fix them in the
  same commit if any other fix round happens, otherwise with the filed idea.

Rulings:

- **Verify commands run as script files:** stands.
- **Task 5's verify script runs the whole package:** stands; it is what makes
  cross-task check 2 above trustworthy.
- **Fix the `chargeDaily` finding inside Task 1 (widening to `hub.go`):**
  stands. It is the right call and the stated worst case (one under-counted
  send after a power cut) is accurate.
- **No extra plan audit for Task 2:** stands; no cost showed up.
- **One reviewer for Task 6:** stands; this review found only the same three
  wording points.

Pointers and off-goal:

- **Pointer (A7 folder-sync branch):** resolved by the sentinel.
- **Pointer (`pv/syncer.go:339-342`, stop before `r.Head()`):** the README
  sentence does not promise an outcome for that case; nothing to fix.
- **OFF-GOAL (annotated tag as the new tip passes the hook and is charged):**
  correct to leave. File the idea at Finish; it also covers Minor 1.

## Recommendations

- File the off-goal idea (type check on the new tip, up front) and attach
  Minor 1 to it.
- Add the two A8 tests and the `Begin` comment to the existing git-location
  follow-up or a small clean-up item; none needs to hold the merge.

## Assessment

**Ready to merge?** Yes

**Reasoning:** All 32 items are present and complete, the seams between the six
tasks line up, and I found no Critical or Important issue. This verdict rests
on reading only: it assumes the controller's full test run and harness run
come back green.
