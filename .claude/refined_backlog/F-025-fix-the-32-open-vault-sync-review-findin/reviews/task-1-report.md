# Task 1 Report: Recovery and undo (A4, A5, A6, A7, A15, A16, A17, A18)

**Target Branch:** `feat/F-025`  
**Working Directory:** `/Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin`  
**Date:** 2026-10-13  
**Status:** PASS / VERIFIED  

---

## 1. Summary of Changes Per Item

### A4 & A16: Undo refuses when the marker file is missing
- **Code:** In `tools/vault-engine/pkg/vaultsync/recover.go` (`Undo`), checked if `disk == nil` from `r.readMarker()`. If missing, return an error stating `there is no save marker on disk for the %s by %s (started %s): that save was already settled; nothing was changed`.
- **Tests:** Added `TestUndo_RefusesWhenTheMarkerFileIsGone` in `recover_test.go`.
- **Commit:** `22b1bda fix(vault-engine): A4 A16 Undo refuses when the marker file is missing`

### A16 (other half): Foreign-marker refusal
- **Tests:** Added `TestUndo_RefusesAMarkerThatBelongsToAnotherSave` in `recover_test.go` checking all mismatched marker attributes (`Op`, `Actor`, `Base`, `StartedAt`, `PID`).
- **Commit:** `a354c1d test(vault-engine): A16 Undo refuses a marker that belongs to another save`

### A6 & A15: Name the step in marker-write errors & test unrecordable undo start
- **Code:** In `tools/vault-engine/pkg/vaultsync/recover.go`, updated `writeMarker` to wrap errors with `fmt.Errorf("write save marker %s: %w", markerRel, err)`, and wrapped marker write failure in `undo` with `fmt.Errorf("record undo start: %w", err)`.
- **Tests:** Added `TestUndo_WhenTheUndoStartCannotBeRecordedNothingIsChanged` in `recover_test.go`.
- **Commit:** `2df4fe0 fix(vault-engine): A6 A15 marker-write errors name their step; test the undo start that cannot be recorded`

### A5: File comparison cut by stop is treated as unknown
- **Code:** In `tools/vault-engine/pkg/vaultsync/recover.go` (`Update`), imported `errors` and checked `errors.Is(err, ErrStopped)` for `hash-object` and `rev-parse`. If interrupted, returns `(false, fmt.Errorf("compare %s with the incoming file of the same name: %w", p, err))` leaving the file untouched with no report line. Other errors continue to set aside to quarantine.
- **Tests:** Added `TestUpdate_AnInterruptedCompareLeavesTheClashingFileWhereItIs` and guarded today's behavior with `TestUpdate_AClashingFileThatCannotBeHashedIsStillSetAside`.
- **Commit:** `a013a23 fix(vault-engine): A5 a compare cut by a stop leaves the file in place and reports nothing`

### A7: writeFileAtomic syncs parent folder and states lock rule
- **Code:** In `tools/vault-engine/pkg/vaultsync/recover.go`, added `var syncDir = func(dir string) error` that opens and syncs the directory. Updated `writeFileAtomic` to call `syncDir(filepath.Dir(path))` after a successful rename, returning any directory sync error.
- **Tests:** Added `TestWriteFileAtomic_SyncsTheFolderAfterTheRenameAndReturnsItsError` in `recover_test.go`.
- **Commit:** `b7a41de fix(vault-engine): A7 writeFileAtomic syncs the parent folder and states its lock rule`

### A17 & A18: Recover tests check read errors and assert premise
- **Tests:** In `tools/vault-engine/pkg/vaultsync/recover_test.go`, replaced dropped `os.ReadFile` errors with explicit `err != nil` assertions in 6 designated locations across `TestRecover_InterruptedSaveMovesUnprovenFilesToQuarantineAndNeverTouchesAnInboxFile`, `TestUndo_RemovesExactlyTheListedFilesAndLeavesAHandMadeFileAlone`, and `undoAfterFailedPass`. Added premise assertion `if head, err := r.Head(); err != nil || head != m.Base` in `undoAfterFailedPass`.
- **Commit:** `596e9f0 test(vault-engine): A17 A18 recover tests check read errors and assert the folder was moved back`

---

## 2. Test Commands & Last Output Lines

### Step 3 (Red Test - A4/A16):
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestUndo_RefusesWhenTheMarkerFileIsGone'`
- **Output:**
```
--- FAIL: TestUndo_RefusesWhenTheMarkerFileIsGone (2.43s)
    recover_test.go:923: undo with no marker on disk must refuse and say nothing was changed, got <nil>
FAIL
FAIL	obsidian-vault-engine/pkg/vaultsync	3.543s
FAIL
```

### Step 5 (Green Test - A4/A16):
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestUndo_|TestSave_'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	101.856s
```

### Step 8 (Green Test - A16 foreign marker):
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m -v ./pkg/vaultsync/ -run 'TestUndo_RefusesAMarkerThatBelongsToAnotherSave'`
- **Output:**
```
--- PASS: TestUndo_RefusesAMarkerThatBelongsToAnotherSave (2.09s)
    --- PASS: TestUndo_RefusesAMarkerThatBelongsToAnotherSave/other_start_time (0.00s)
    --- PASS: TestUndo_RefusesAMarkerThatBelongsToAnotherSave/other_process (0.00s)
    --- PASS: TestUndo_RefusesAMarkerThatBelongsToAnotherSave/other_operation (0.00s)
    --- PASS: TestUndo_RefusesAMarkerThatBelongsToAnotherSave/other_actor (0.00s)
    --- PASS: TestUndo_RefusesAMarkerThatBelongsToAnotherSave/other_base (0.00s)
PASS
ok  	obsidian-vault-engine/pkg/vaultsync	3.795s
```

### Step 11 (Red Test - A6/A15):
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestUndo_WhenTheUndoStartCannotBeRecordedNothingIsChanged'`
- **Output:**
```
--- FAIL: TestUndo_WhenTheUndoStartCannotBeRecordedNothingIsChanged (2.59s)
    recover_test.go:996: undo must fail and name the step that failed, got open /var/folders/5c/tyw0hp6d4pgdl7j8hkpggltr0000gp/T/TestUndo_WhenTheUndoStartCannotBeRecordedNothingIsChanged3196635410/001/mac-test/_meta/guards/save-in-progress.json.tmp: is a directory
FAIL
FAIL	obsidian-vault-engine/pkg/vaultsync	4.015s
FAIL
```

### Step 13 (Green Test - A6/A15):
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestUndo_|TestBegin_'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	54.931s
```

### Step 16 (Red Test - A5):
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestUpdate_AnInterruptedCompare|TestUpdate_AClashingFileThatCannotBeHashed' -v 2>&1 | grep -E '^(--- |ok|FAIL)|_test.go'`
- **Output:**
```
    recover_test.go:1039: update = (true, <nil>), want (false, an error that wraps ErrStopped)
--- FAIL: TestUpdate_AnInterruptedCompareLeavesTheClashingFileWhereItIs (3.57s)
--- PASS: TestUpdate_AClashingFileThatCannotBeHashedIsStillSetAside (3.01s)
FAIL
FAIL	obsidian-vault-engine/pkg/vaultsync	8.440s
FAIL
```

### Step 18 (Green Test - A5):
- **Command:** `cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestUpdate_'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	13.401s
```

### Step 21 (Red Test - A7):
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestWriteFileAtomic_'`
- **Output:**
```
# obsidian-vault-engine/pkg/vaultsync [obsidian-vault-engine/pkg/vaultsync.test]
pkg/vaultsync/recover_test.go:1105:10: undefined: syncDir
pkg/vaultsync/recover_test.go:1106:21: undefined: syncDir
pkg/vaultsync/recover_test.go:1110:2: undefined: syncDir
pkg/vaultsync/recover_test.go:1125:2: undefined: syncDir
pkg/vaultsync/recover_test.go:1137:2: undefined: syncDir
FAIL	obsidian-vault-engine/pkg/vaultsync [build failed]
FAIL
```

### Step 23 (Green Test - A7):
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestWriteFileAtomic_|TestBegin_|TestUndo_|TestChargeDaily_'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	47.935s
```

### Step 27 (Green Test - A17/A18):
- **Command:** `cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestRecover_|TestUndo_'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	64.924s
```

### Final Phase Gate Verification:
- **Command:** `bash .superpowers/sdd/plan/verify-1.sh`
- **Exit Code:** 0
- **Final Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	145.214s
```

---

## 3. Off-Scope Findings

- Finding 1: Unchecked `os.ReadFile` calls remain in non-targeted test suites (`scenario_test.go`, `repo_test.go`, `daemon_test.go`, `syncer_test.go`) and the 3 explicitly un-targeted lines in `recover_test.go` outside the scope of A17.
- Finding 2: `gofmt -l .` reports two legacy files under `pkg/vault/` (`pkg/vault/vault.go`, `pkg/vault/vault_test.go`) which are outside our permitted scope per global constraints.

## Fix round 1

### Changes Made:
- **`tools/vault-engine/pkg/vaultsync/recover.go`**:
  - Added unexported sentinel `var errFolderSync = errors.New("folder sync")`.
  - In `writeFileAtomic`, wrapped only the parent-folder sync error occurring after the rename using `%w: %w` so `errors.Is(err, errFolderSync)` and `errors.Is(err, failed)` both match while keeping other errors unmodified.
  - In `undo`, updated the comment to truthfully state that if the write fails before the rename nothing is changed and the marker stays as it was, whereas if only the folder sync failed the record on disk already says the undo started, which is safe because the next `Undo` or `Recover` reads the disk marker.
- **`tools/vault-engine/pkg/vaultsync/hub.go`**:
  - In `chargeDaily`, when `writeFileAtomic` returns an error matching `errors.Is(err, errFolderSync)`, treated the send as charged by returning `(usage[place], true, nil)` with a note explaining that the usage file is already in place and the worst case after a power cut is an under-count. All other write errors still return `(0, false, err)`.
- **`tools/vault-engine/pkg/vaultsync/hub_test.go`**:
  - Added `TestChargeDaily_AFolderSyncFailureAfterTheRenameStillCountsAsCharged` swapping `syncDir` test seam to simulate folder sync error, asserting `chargeDaily` returns charged (`ok=true`, `err=nil`), the file on disk matches the returned total, and a second charge increments the total by the added amount once.
- **Commit**: `0c39bb4 fix(vault-engine): A7 a folder-sync failure after the rename no longer refuses a send it charged`

### Red Test (hub.go unchanged):
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m -v ./pkg/vaultsync/ -run 'TestChargeDaily_AFolderSyncFailureAfterTheRenameStillCountsAsCharged'`
- **Last Output Lines:**
```
=== RUN   TestChargeDaily_AFolderSyncFailureAfterTheRenameStillCountsAsCharged
    hub_test.go:293: first chargeDaily: ok=false err=writing usage file /var/folders/5c/tyw0hp6d4pgdl7j8hkpggltr0000gp/T/TestChargeDaily_AFolderSyncFailureAfterTheRenameStillCountsAsCha3093216986/001/2026-10-10.json: folder sync: simulated folder sync failure, want ok=true err=nil
--- FAIL: TestChargeDaily_AFolderSyncFailureAfterTheRenameStillCountsAsCharged (0.01s)
FAIL
FAIL	obsidian-vault-engine/pkg/vaultsync	0.783s
FAIL
```

### Green Test (hub.go fix applied):
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m -v ./pkg/vaultsync/ -run 'TestChargeDaily_AFolderSyncFailureAfterTheRenameStillCountsAsCharged'`
- **Last Output Lines:**
```
=== RUN   TestChargeDaily_AFolderSyncFailureAfterTheRenameStillCountsAsCharged
--- PASS: TestChargeDaily_AFolderSyncFailureAfterTheRenameStillCountsAsCharged (0.01s)
PASS
ok  	obsidian-vault-engine/pkg/vaultsync	2.177s
```

### Gate Verification:
- **Command:** `bash .superpowers/sdd/plan/verify-1b.sh`
- **Exit Code:** 0
- **Final Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	129.257s
```
