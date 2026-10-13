# Task 1 re-review, fix round 1 (596e9f0..0c39bb4)

Method: read the brief findings (task-1-review.md, task-1-review-go.md), the
"Fix round 1" section of task-1-report.md and the review package diff once.
No test was run. Outside the diff I read only what the named risks needed:
the two other `writeFileAtomic` callers (`recover.go:122`, `recover.go:614`),
the `chargeDaily` call site (`hub.go:193-200`), the existing
`TestWriteFileAtomic_` sync case (`recover_test.go:1138-1142`), `go.mod`
(Go version) and `verify-1b.sh`. HEAD is 0c39bb4 and the tree is clean.
Paths are relative to tools/vault-engine/pkg/vaultsync/.

### Finding Verdicts

- **1. Important: chargeDaily refused a send it had already charged when only the post-rename folder sync failed; no TestChargeDaily_ case covered it** — ADDRESSED.
  - `recover.go:542` adds the sentinel `errFolderSync`; `recover.go:574-576` wraps only the `syncDir` failure after a successful rename (`fmt.Errorf("%w: %w", errFolderSync, err)`). Every earlier failure (open, write, fsync, close, rename) still returns the bare `werr` at `recover.go:569-572`, unchanged.
  - `hub.go:238-242`: `errors.Is(err, errFolderSync)` returns `(usage[place], true, nil)`; every other error still returns `(0, false, wrapped err)` at `hub.go:243`. This is the controller's ruling exactly.
  - The call site (`hub.go:193-200`) therefore no longer refuses, so there is no retry that charges a second time.
  - Test: `hub_test.go:282` `TestChargeDaily_AFolderSyncFailureAfterTheRenameStillCountsAsCharged`. It asserts ok=true, err=nil, the returned total equals the total on disk, and a second charge grows the total by exactly the added amount.
  - The test does not pass without the hub.go change: with `syncDir` failing, the old `chargeDaily` returns `(0, false, err)` and the first assertion (`hub_test.go:292-294`) fails. The report's red run shows that exact failure, with the message "folder sync: simulated folder sync failure".
  - The seam is restored: `prev := syncDir` plus `t.Cleanup` at `hub_test.go:283-284`, set before the override. No `t.Parallel` in the package, so no race.

- **2. Minor: the undo comment claimed the marker "in memory and on disk stays as it was"** — ADDRESSED.
  - `recover.go:327-332` now tells the two cases apart: a failure before the rename changes nothing; a folder-sync-only failure leaves the disk record saying the undo started, safe because the next Undo or Recover reads the disk marker. That matches the code: `recover.go:220` merges `disk.UndoStarted` into the caller's marker.

### New Breakage in the Fix Diff

None.

Checks made for the risks the controller named:
- Other `writeFileAtomic` callers changed by accident: no. `writeMarker` (`recover.go:122-124`) and the `setAside` copy branch (`recover.go:614-615`) only wrap or return the error and never test its identity, so they still fail on a folder-sync failure as before. Only the error text gains the prefix "folder sync: ". A grep found no code or test that matches that text.
- Sentinel hiding the underlying error: no. Two `%w` verbs keep both in the chain (the module is on Go 1.22.4; this needs 1.20). The text reads "folder sync: sync folder <dir>: <cause>". The existing assertion `errors.Is(err, failed)` at `recover_test.go:1140` still holds.
- Gate: `verify-1b.sh` runs `TestChargeDaily_`, `TestWriteFileAtomic_`, `TestUndo_` and `TestRecover_` with `-race`, checks gofmt, and checks that the sentinel is present in both files and the new test exists. The report shows exit code 0.

### Out-of-Scope Observations

1. Minor, `hub.go:238-242`: the folder-sync error is now dropped with no log line. That follows the ruling, but on a filesystem where the folder sync always fails the hub gives no sign of it. A one-line warning to the hub's log would make it visible.
2. Minor, `recover.go:333-338`: the folder-sync branch of `undo` (disk says UndoStarted, memory copy set back to false) still has no test. Only the comment was taken into this round, as decided.
3. Minor, carried over unchanged from the first review: `Begin` leaving a marker after a failed folder sync (review Minor 2) and filesystems that do not support a folder sync making every marker write fail (Go review Minor 2).

### Verdict

**Fix round:** All findings addressed, no new Critical/Important breakage.
