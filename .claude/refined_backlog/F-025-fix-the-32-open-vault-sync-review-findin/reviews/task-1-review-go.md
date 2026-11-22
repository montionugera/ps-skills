# Task 1 review (Go): recovery and undo (A4, A5, A6, A7, A15, A16, A17, A18)

Range 3204b99..596e9f0, six commits, two files (recover.go, recover_test.go).
Method: read the brief, the report and the review package once; no test suite run.
Checks outside the diff (one per named risk) are listed under "Named-risk checks".
Paths are relative to tools/vault-engine/pkg/vaultsync/.

### Spec Compliance
- ✅ Spec compliant. Every item has its hunk and each hunk matches the brief's text:
  - A4 / A16: Undo returns "no save marker on disk ... nothing was changed" when readMarker gives nil (recover.go:203-206); foreign-marker refusal kept as it was (recover.go:207-211). Tests: TestUndo_RefusesWhenTheMarkerFileIsGone, TestUndo_RefusesAMarkerThatBelongsToAnotherSave (five sub-tests).
  - A6 / A15: writeMarker wraps all three failure points with %w (recover.go:116-124); undo wraps with "record undo start: %w" (recover.go:335). Test: TestUndo_WhenTheUndoStartCannotBeRecordedNothingIsChanged.
  - A5: only errors.Is(err, ErrStopped) on either compare call returns early with (false, wrapped stop) (recover.go:678-682); every other failure still falls through to setAside. This matches the owner decision exactly. Tests: one for the stop, one guarding the non-stop path with a dangling link.
  - A7: syncDir seam added (recover.go:523), called after a successful rename and its error returned (recover.go:568); lock rule stated in the doc comment.
  - A17: exactly six places changed; the three `original, _ := os.ReadFile` lines left on purpose are still there (recover_test.go:230, 588, 641).
  - A18: premise assertion (head == m.Base) added in undoAfterFailedPass.
- Constraints: only tools/vault-engine files touched; each commit subject names its items; no t.Setenv("HOME") in the diff; nothing outside the named items was refactored.
- ⚠️ Cannot verify from diff: "no git commit --amend". Six separate commits exist in the expected order, which is consistent with it, but the diff cannot prove it. The controller can check the reflog if it matters.

### Named-risk checks (outside the diff)
1. Risk: a production path reaches Undo after the marker was removed, so A4 turns a working undo into a refusal. Checked syncer.go:185-232 and 407-423 plus every End / Recover / Update call in the package. Both production Undo calls run on the marker that s.begin wrote in the same step; every End() comes after the undo; Update (which overwrites the marker) is only called at syncer.go:154 before begin, and from the daemon. No such path found.
2. Risk: the new folder-sync error after a completed rename leaves a caller in a wrong state. Checked the three callers:
   - setAside copy branch (recover.go:605): copy is in place, error returned, the note is not overwritten. A retry finds the copy through hasCopy and only adds a report line. Safe.
   - chargeDaily (hub.go:237): the usage is charged on disk but the request is refused. Fails closed. See Minor 3.
   - writeMarker from Begin and from undo: see Minor 1.
3. Risk: the package-level syncDir variable races with parallel tests. Checked: no t.Parallel() anywhere in pkg/vaultsync, and production code never writes the variable. No race today.
4. `go vet ./...` in tools/vault-engine printed nothing. gofmt reports neither changed file.

### Strengths
- Error wrapping is correct throughout: %w everywhere, and the stop is detected with errors.Is, not string matching, so the wrap added by Repo.local does not hide it.
- The A5 change is as narrow as the owner asked; the second test pins the behaviour that must not change, with a real unhashable file instead of a fake.
- Tests assert on real disk state (file text, head, marker on disk, quarantine folder, report line count), not on mocks. No sleeps, no timing, no HOME redirect.
- Red evidence in the report matches what the code would do before each fix (nil error for A4, bare open error for A6, (true, nil) for A5, build failure for A7).
- syncDir handles Close correctly (keeps the first error) and is restored with t.Cleanup.

### Issues
#### Critical (Must Fix)
None.

#### Important (Should Fix)
None.

#### Minor (Nice to Have)
1. recover.go:327-336 (undo, the "record undo start" block). The comment says that when the record cannot be written "nothing is changed and the marker (in memory and on disk) stays as it was". After A7 that is no longer always true: if the rename succeeded and only the folder sync failed, the disk marker now says UndoStarted while the code sets the in-memory flag back to false. The outcome is safe (Undo re-reads the disk marker and then sweeps, which keeps more, never less), but the comment and the writeFileAtomic doc ("treat that like a crash right after the rename") now disagree with the code. Fix: correct the comment, or leave m.UndoStarted true when the error wraps a folder-sync failure. No test covers this path.
2. recover.go:523-536 (syncDir) and :568. A folder sync that the file system does not support (some network and FUSE mounts return EINVAL) now fails every marker write. Because the rename already happened, Begin leaves a marker behind, and the next Recover fails at the same step, so the folder would stay stuck. Not a problem on APFS or ext4, and returning the error is what the brief asks for. Worth a line in the README or a follow-up item, not a change in this task.
3. hub.go:237 (unchanged caller, new behaviour). chargeDaily now does one extra folder sync per charge, and a sync failure refuses the request after the usage was already written. Fails closed, so acceptable; note it for the hub latency budget.
4. recover_test.go, TestUpdate_AnInterruptedCompareLeavesTheClashingFileWhereItIs (about line 1018). Only the hash-object stop is tested. The second half of the loop at recover.go:678 (a stop on rev-parse) has no test, so removing err2 from the slice would not turn any test red. A second gate case would close it.
5. recover_test.go, TestUndo_RefusesWhenTheMarkerFileIsGone (about line 923). It matches only "nothing was changed", which the foreign-marker error also contains. Matching "no save marker on disk" would pin the right branch.
6. recover_test.go, TestWriteFileAtomic_SyncsTheFolderAfterTheRenameAndReturnsItsError (about line 1104). It swaps a package-level variable, so it (and any test that writes a marker) can never be made parallel without a data race. Fine today (no t.Parallel in the package); a one-line comment on syncDir would warn the next person.

### Assessment
**Task quality:** Approved
**Reasoning:** The diff implements all eight items as written, with correct %w wrapping, a real post-rename folder sync, and tests that fail without their fixes and check real disk state. The six Minor items are a stale comment, two notes on the new sync error, and three test-coverage gaps; none makes the batch untrustworthy.
