# Task 1 review: recovery and undo (A4, A5, A6, A7, A15, A16, A17, A18)

Range 3204b99..596e9f0. Method: read the brief, the report and the review
package once. No tests were run. Code outside the diff was read only for the
one named risk (callers of `writeFileAtomic` when the folder sync fails):
`hub.go:192-241`, `recover.go:78-125` and `582-620`, `syncer.go:145-236` and
`403-426`, `hub_test.go:244-275`, plus a grep for `t.Parallel` (none in the
package, so the package-level `syncDir` test seam cannot race).

### Spec Compliance
- ✅ Spec compliant. Every item has its hunk and the code matches the brief line for line:
  - A4 / A16: `recover.go:209-217` refuses a missing marker and a foreign marker; tests at `recover_test.go:920` and `:950` (five sub-cases).
  - A6 / A15: `recover.go:116-124` and `:335` name the step; test at `recover_test.go:988`.
  - A5: `recover.go:680-684` returns only for `ErrStopped`; any other compare failure still reaches `setAside` (`recover.go:689`). Owner decision honoured. Tests at `recover_test.go:1031` and `:1084`.
  - A7: `syncDir` at `recover.go:523`, called after the rename at `:568`; test at `recover_test.go:1117`.
  - A17: exactly six places changed (three `original, err :=`, three `now, err :=`). A18: premise check added in `undoAfterFailedPass`.
  - Constraints: only two files under `tools/vault-engine/`, no drive-by edits, six commits each naming its items, no HOME redirect in the new tests.
- ⚠️ Cannot verify from diff: that exactly three `original, _ := os.ReadFile` lines remain (the diff shows only the three that were changed; the report's verify command claims the count). Also no amend can be proven from a diff.

### Strengths
- The new tests assert real outcomes on disk (file text, HEAD, marker on disk and in memory), not mocks.
- The A5 pair pins both sides of the owner decision: a stop leaves the file, a file git cannot hash is still moved aside.
- TDD evidence in the report is complete: each red run shows the expected failure text.
- The lock rule for the fixed temp name is now written on `writeFileAtomic`.

### Named risk: folder sync fails after the rename (A7)

What each caller does with the new error:

| Caller | Outcome | Coherent? |
|---|---|---|
| `chargeDaily` (`hub.go:237`) | Usage file already holds the added bytes; returns an error; `hub.go:194-195` refuses the send as `engine-error`. | No. See Important 1. |
| `writeMarker` from `undo` (`recover.go:333`) | Marker on disk now says `UndoStarted: true`; memory copy is set back to `false`; folder not moved back. | Safe, but the comment is now false. See Minor 1. |
| `writeMarker` from `Begin` (`recover.go:107`) | `Begin` returns `(nil, err)` with a marker on disk. `syncer.go:186` and `:407` return without `End`; `Syncer.begin` (`syncer.go:146`) then refuses until `Recover` settles it. | Yes. Same as a crash right after `Begin`, which `Recover` already handles. |
| `setAside` copy branch (`recover.go:605`) | Copy is in quarantine, no REPORT line, error returned so the caller does not overwrite the note. Next pass `hasCopy` finds it and writes the line. | Yes. |

Test coverage of that branch: only the unit test of `writeFileAtomic` itself (`recover_test.go:1139-1148`). No caller is tested with a failing `syncDir`.

### Issues

#### Critical (Must Fix)
None.

#### Important (Should Fix)

1. **`hub.go:237` with `recover.go:568`: a send is refused after its bytes were already charged (plan-mandated).**
   - What: `writeFileAtomic` now returns an error when the rename succeeded but the folder sync failed. `chargeDaily` treats every error as "not recorded" and returns `(0, false, err)`; the hub then refuses with "daily allowance cannot be recorded". The usage file on disk already has `usage[place] += add`.
   - Failure: folder sync on the `vault-usage` folder fails (I/O error, or a filesystem that does not support syncing a folder). The send is refused but counted. Each retry counts again, so a place can use up its daily allowance without one send landing. On a filesystem where the folder sync always fails, every send to the hub is refused, where before this change it was accepted.
   - Why existing guards do not catch it: before this batch the function had no "written but error" result; `chargeDaily` (unchanged) was written for the old contract. No `TestChargeDaily_` case sets `syncDir` to fail (`hub_test.go:244-275`).
   - The trigger is rare. The wrong accounting when it happens is certain from the code.
   - Fix: make the two results tell apart. For example have `writeFileAtomic` wrap the post-rename failure in a sentinel (`errFolderSync`), and in `chargeDaily` treat it as charged: return `(usage[place], true, nil)` (the worst case after a power cut is an under-count). Add a `TestChargeDaily_` case with a failing `syncDir` that asserts the charge and the answer agree. This touches `hub.go`, which is outside the two files the brief names but inside `tools/vault-engine/`; the controller should decide whether to widen this batch or carry it as its own item.

#### Minor (Nice to Have)

1. **`recover.go:327-337`: comment is false on the folder-sync branch, and the branch has no test.** The comment says that when the record cannot be written "the marker (in memory and on disk) stays as it was". After a failed folder sync the marker on disk has `UndoStarted: true` and the copy in memory is reset to `false`. The result is safe: the next `Undo` or `Recover` reads the disk marker (`recover.go:217`) and takes the careful path that keeps copies and deletes nothing. The same overstatement is in the doc comment of the new test (`recover_test.go:985-987`), which only exercises the temp-file-open failure. Fix: reword the comment ("if the write fails before the rename nothing is changed; if only the folder sync fails the disk marker already records the undo start, which is the safe side"), and add a case with a failing `syncDir`.
2. **`recover.go:107` (`Begin`): a failed folder sync leaves a marker for a save that never ran.** Coherent (see table), but the next `Recover` will move files that were untracked before the save into quarantine, as after a real crash. Worth one sentence in the `Begin` or `writeMarker` comment, and a test, so the "treat it like a crash" rule on `writeFileAtomic` is shown to hold for this caller.

### Assessment
**Task quality:** Needs fixes
**Reasoning:** The batch implements the brief exactly and its tests are sound. The one open point is the A7 contract change: the hub's usage charge now can be recorded and refused at the same time, and no test covers any caller on that branch.
