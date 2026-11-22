# Task 2 Review: Hub (A8, A12, A13, A24) — 630019e..1cc6c45

Method: read the brief, the implementer's report and the review package once. Two focused checks
outside the diff, each for a named risk (see "Checks outside the diff"). No tests run, nothing changed.

### Spec Compliance
- ✅ Spec compliant. Every listed file has its hunk, and every item has its change:
  - A13: `hubGit(dir, stdin, ...)` sets `cmd.Dir = dir` (hub.go:65-67); `batchCheck(dir, ...)` (hub.go:83-84);
    `PreReceive(dir, ...)` (hub.go:111); `dir` passed at all six inner call sites (hub.go:134, 149, 155, 178,
    195, 206); `main.go:42` passes `""`. All seven existing test calls updated; `hubRepo` added above
    `hubLimitsCopy` (hub_test.go:270-281) as written in the brief.
  - Owner decision on A13 (no machine check): verified in the diff. `hubGit` has no `cmd.Env` assignment, and
    a grep of hub.go for `cmd.Env` returns nothing. With `dir == ""`, `cmd.Dir = ""` is Go's "use the calling
    process's folder", so the hook runs git exactly as before, quarantine variables included.
  - A12: `code != 1` (hub_test.go:369).
  - A8: the `cat-file -t` branch (hub.go:139-143) matches the brief; label `type-not-allowed`; the place-side
    test asserts `out.Exit != 6` (hub_test.go:432). The empty-hub path (rev-list) is untouched, as decided.
  - A24: both tests present (hub_test.go:437, 458). `chargeDaily` is not in the diff, so the Task 1 branch
    `errors.Is(err, errFolderSync)` and its test are left alone.
  - Scope: three files, all under tools/vault-engine/. No drive-by changes. Four commits, each names its item.
- ⚠️ Cannot verify from diff: "no git commit --amend" (history shows four separate commits, which is
  consistent, but an amend leaves no trace in a diff). The verify-cmd result (exit 0) is the implementer's
  claim; I did not re-run it, as instructed.
- ⚠️ Report claim that is wrong in one case (not a defect of this batch): the report's off-scope "Finding 1"
  says an annotated tag as the new tip is refused as `type-not-allowed ... points it at a tag`. That holds
  only when `merge-base` fails, i.e. when the tag points at a tree or blob. A tag that points at a commit
  ahead of the current tip is peeled by `merge-base --is-ancestor`, which succeeds, so the new branch at
  hub.go:139 is never reached and the hook goes on to measure and charge the send. This is the behaviour
  from before this batch and outside item A8. I did not test whether git's own ref update then refuses the
  tag on a branch; the controller should file it as a follow-up question rather than trust the report's line.

### Strengths
- The A8 change cannot turn a hub fault into a sender fault. It runs only after `merge-base` failed with
  something other than exit 1, and it relabels only when `cat-file -t` SUCCEEDS and names a non-commit type.
  A missing object, a corrupt repository or a git that cannot start all make `cat-file -t` fail, so they stay
  `engine-error` (hub.go:141, 144). The A12 test pins exactly that case with exit code 1.
- The check uses the same inherited environment as the rest of the hook, so it sees quarantined objects.
- RED evidence in the report is real and specific: both A8 tests failed with the old label before the fix.
- A24's end-to-end test checks three things that matter for a fail-closed control: the refusal label, that no
  ref was taken, and that no usage file appeared.
- `hubRepo` restores the cleared variables through `t.Setenv`'s cleanup, so it does not leak into other tests.

### Issues
#### Critical (Must Fix)
None.

#### Important (Should Fix)
None.

#### Minor (Nice to Have)
1. hub_test.go:405 and hub_test.go:423 — the two new A8 tests call `PreReceive(hub, ...)` in-process without
   clearing git's location variables (they use `newHub`, not `hubRepo`). `hubGit` inherits the environment by
   design, so when the test runner exports `GIT_DIR` (a git hook, `git rebase --exec`), `merge-base` and
   `cat-file -t` run against that other repository, not the temp hub. Effect: the tests fail with
   `engine-error` (objects not found); the commands on this path are read-only, so nothing is harmed.
   This is the very situation `hubRepo`'s comment describes, left uncovered for the new tests. Fix: move the
   variable-clearing loop into a small helper and call it in these two tests as well. The code is as the
   brief wrote it, so this is a gap in the brief, not a deviation.
2. hub_test.go:417-435 — `TestSave_ATreeOrBlobRefusalFromTheHubEndsWithExitSix` proves the place maps the
   hub's real refusal line to exit 6, but through the `PushResult` seam, not through a real push. It does not
   show that a real `git push` of a tree reaches the hook at all. Acceptable for the owner's decision ("a
   test asserts 6"); worth one line in the test comment so nobody reads it as an end-to-end proof.

### Checks outside the diff (named risk, one check each)
- Risk: the A24 end-to-end test blocks the usage file by UTC date; if `chargeDaily` named the file by local
  date it would fail for hours each day in a non-UTC zone. Checked hub.go:228: `now.UTC().Format(...)`. No issue.
- Risk: whether the test helpers strip git's location variables (bears on Minor 1). Checked
  testkit_test.go:87-120: `newHub` runs create-hub.sh and returns a temp path; it does not clear the
  process environment, which is what makes Minor 1 real for in-process `PreReceive` calls.

### Assessment
**Task quality:** Approved
**Reasoning:** The diff matches the brief and both owner decisions line by line, and the one behaviour change
(A8) is narrow: it relabels only on a positive, successful type answer, so no hub fault can read as a broken
rule. Two Minor notes on test robustness; neither blocks.
