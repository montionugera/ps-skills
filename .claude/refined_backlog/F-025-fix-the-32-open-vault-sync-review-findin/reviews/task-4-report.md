# Task 4 Report: Daemon Tests (A19, A20, A22)

**Target Branch:** `feat/F-025`  
**Working Directory:** `/Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin`  
**Date:** 2026-10-13  
**Status:** PASS / VERIFIED  

---

## 1. Summary of Changes Per Item

### A19: The pid-file poller ends with the test and validates pid content
- **Changes in `tools/vault-engine/pkg/vaultsync/daemon_test.go`:**
  - Added helper `closedWhen(t *testing.T, cond func() bool) <-chan struct{}`: registers `t.Cleanup` to close a `stop` channel ensuring the polling goroutine always terminates when the test ends or when condition is met.
  - In `TestDaemon_CancelCutsARunningGitCommandShort`, replaced the unmanaged polling goroutine with `closedWhen`, waiting until `os.ReadFile(pidFile)` succeeds and contains non-empty trimmed data.
  - Added error handling when converting pid (`strconv.Atoi` checked with `t.Fatalf`).
- **Commit:** `30ac02e test(vault-engine): A19 A22 daemon test pollers end with the test; the lock test waits for the real lock wait`

### A22: Remove fixed settle sleep and wait for real lock acquisition
- **Changes in `tools/vault-engine/pkg/vaultsync/daemon_test.go`:**
  - Added `"runtime"` import.
  - Added helper `waitingForFolderLock() bool`: inspects runtime stack traces via `runtime.Stack` to detect if a goroutine in the test binary is inside `vaultsync.AcquireFolderLockContext(`.
  - In `runAndCancel`, removed `time.Sleep(200 * time.Millisecond) // let it settle into the wait`. Cancellation happens immediately upon the `ready` signal.
  - In `TestDaemon_CancelEndsTheWaitForTheFolderLock`, replaced the speculative gate on `--show-toplevel` and sleep with `closedWhen(t, waitingForFolderLock)`.
- **Commit:** `30ac02e test(vault-engine): A19 A22 daemon test pollers end with the test; the lock test waits for the real lock wait`

### A20: Cancel without a signal at merge or commit is settled by next pass
- **Changes in `tools/vault-engine/pkg/vaultsync/daemon_test.go`:**
  - Added helper `cancelledAt(t *testing.T, d *Daemon, word string)`: intercepts the target git command via `Repo.gate`, cancels the context directly without sending an OS signal, verifies `Run` exits cleanly without error, ensures the command was hit, and confirms the save marker remains on disk.
  - Added test `TestDaemon_CancelWithoutASignalAtMergeOrCommitIsSettledByTheNextPass`:
    - Subtest `"merge of an incoming update"`: verifies a cancel at `git merge` halts the incoming update while leaving the marker, and a subsequent `Tick()` settles the marker, applies the update, and leaves `_quarantine` empty.
    - Subtest `"commit of an inbox drop"`: verifies a cancel at `git commit` leaves the inbox drop staged with marker intact, and a subsequent `Tick()` settles the marker, commits and pushes to hub, and leaves `_quarantine` empty.
- **Commit:** `96589d0 test(vault-engine): A20 a cancel without a signal at merge or commit is settled by the next pass`

---

## 2. Test Commands & Output Lines

### Step 5: A19 and A22 Verification Run
- **Command:** `cd tools/vault-engine && go vet ./... && go test -count=3 -race -timeout 40m ./pkg/vaultsync/ -run 'TestDaemon_CancelCutsARunningGitCommandShort|TestDaemon_CancelEndsTheWaitForTheFolderLock' -v 2>&1 | grep -E '^(--- |ok|FAIL|panic)|Run returned'`
- **Output:**
```
    daemon_test.go:611: Run returned 703.667µs after the cancel
--- PASS: TestDaemon_CancelCutsARunningGitCommandShort (2.29s)
    daemon_test.go:644: Run returned 65.125µs after the cancel
--- PASS: TestDaemon_CancelEndsTheWaitForTheFolderLock (2.05s)
    daemon_test.go:611: Run returned 1.197ms after the cancel
--- PASS: TestDaemon_CancelCutsARunningGitCommandShort (2.08s)
    daemon_test.go:644: Run returned 39.5µs after the cancel
--- PASS: TestDaemon_CancelEndsTheWaitForTheFolderLock (1.96s)
    daemon_test.go:611: Run returned 1.900708ms after the cancel
--- PASS: TestDaemon_CancelCutsARunningGitCommandShort (2.75s)
    daemon_test.go:644: Run returned 47.208µs after the cancel
--- PASS: TestDaemon_CancelEndsTheWaitForTheFolderLock (2.36s)
ok  	obsidian-vault-engine/pkg/vaultsync	15.382s
```

### Step 8: A20 Verification Run
- **Command:** `cd tools/vault-engine && go vet ./... && go test -count=3 -race -timeout 40m ./pkg/vaultsync/ -run 'TestDaemon_CancelWithoutASignal'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	15.585s
```

### Final Phase Gate Verification
- **Command:** `bash .superpowers/sdd/plan/verify-4.sh`
- **Exit Code:** 0
- **Final Output Lines:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	33.732s
ok  	obsidian-vault-engine/pkg/vaultsync	58.048s
```

---

## 3. Acceptance Criteria Checklist

1. **No goroutine started by `daemon_test.go` can outlive its test:** Verified. `closedWhen` attaches a `t.Cleanup` that closes the stop channel, causing the polling goroutine to exit promptly when the test completes or when condition is satisfied.
2. **`runAndCancel` has no fixed sleep; lock test cancels only once inside `AcquireFolderLockContext`:** Verified. Removed 200ms sleep in `runAndCancel`. `waitingForFolderLock` checks runtime stack for `vaultsync.AcquireFolderLockContext(`.
3. **New test cancels context at `git merge` and `git commit`, checks marker left, checks next pass settles:** Verified. `TestDaemon_CancelWithoutASignalAtMergeOrCommitIsSettledByTheNextPass` tests both cases and asserts marker presence and subsequent pass resolution.
4. **The three cancel tests pass three times in a row under `-race`:** Verified. Ran `-count=3 -race -timeout 40m` on `TestDaemon_Cancel` passing 3 iterations cleanly.

---

## 4. Off-Scope Findings

None.
