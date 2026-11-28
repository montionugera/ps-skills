# Task 4 Review: Daemon tests (A19, A20, A22)

Range 9bb0da1..96589d0. Reviewed from the review package only, plus three focused checks named below. No tests were run by the reviewer.

### Spec Compliance
- ✅ Spec compliant. Every step of the brief has its hunk, and the added code matches the brief's text.
  - Step 1 (helpers `closedWhen`, `waitingForFolderLock`, `runtime` import): daemon_test.go:13, 528-551.
  - Step 2 (200 ms settle sleep removed from `runAndCancel`): daemon_test.go:573-574, the sleep line is gone.
  - Step 3 (pid poller waits for a pid in the file; `strconv.Atoi` error checked): daemon_test.go:605-622.
  - Step 4 (lock test waits on its own goroutine stacks, per the owner decision on A22): daemon_test.go:644-646.
  - Step 7 (`cancelledAt` and the new two-case test): daemon_test.go:654-741.
  - Scope: one file changed, `tools/vault-engine/pkg/vaultsync/daemon_test.go`. No production file touched. No HOME redirect in the diff.
  - Both commit messages name their items (A19 A22; A20).
- ⚠️ Acceptance item 1, read literally ("no goroutine started by daemon_test.go can outlive its test"), is not fully met on one failure path: see Minor 1. The parenthetical the acceptance names (the pid-file poller) is met.
- ⚠️ Cannot verify from the diff: that no commit was amended (two plain commits are listed, nothing suggests otherwise); and the reported test runs themselves. The report's final gate ran `verify-4.sh`, not the brief's command typed out. I read that script: it is the brief's verify-cmd word for word, plus one gofmt check.

### Strengths
- `closedWhen` is small and correct: one stop channel closed by `t.Cleanup`, `ready` is closed by exactly one goroutine, and it is registered before `runAndCancel`'s cleanup, so it is torn down after Run has been waited for (daemon_test.go:530-545).
- The pid condition waits for content, not for the file. With the sleep gone this closes a real gap: a cancel between file creation and the pid write (daemon_test.go:607-610).
- The lock test now waits for the real event. Checked (risk: the stack match could be true for some other goroutine): the package has no `t.Parallel()`, the only production caller of `AcquireFolderLockContext` is syncer.go:132, the test's own `AcquireFolderLock` call at daemon_test.go:633 has already returned, and the function is a loop with a select (lock.go:34-63) so its frame stays on the stack for the whole wait.
- No data race on `hit`. Checked (risk: gate called from another goroutine): daemon.go:33-35 states passes run on the calling goroutine, and the test reads `hit` only after receiving from `done` (daemon_test.go:673-685).
- The gate word cannot hit the wrong git command. Checked (risk: "merge" or "commit" appearing as an argument elsewhere): in production code "merge" is passed only at recover.go:702 and "commit" only at repo.go:282; the match is on a whole argument.
- The new test asserts real state after each stage: marker left, update not applied or drop staged-not-committed, then marker settled, content on the other side, hub commit count exactly 2, folder clean, no `_quarantine`.

### Issues
#### Critical (Must Fix)
None.

#### Important (Should Fix)
None.

#### Minor (Nice to Have)
1. daemon_test.go:674-682 (`cancelledAt`), plan-mandated code. If Run does not stop within 30 s the helper calls `t.Fatalf` without waiting for the Run goroutine. That goroutine then outlives the test while the temp folders are removed, and it still holds `d.S.Repo`. `runAndCancel` guards against exactly this with a cleanup that waits on `done` (daemon_test.go:559-565); `cancelledAt` does not. Only reachable when the test is already failing, so it cannot produce a false pass, but it is the one place acceptance item 1 does not hold as written. Fix: register the same cleanup (`cancel(); <-done` unless already received).
2. daemon_test.go:530-545 (`closedWhen`), plan-mandated code. The cleanup closes `stop` but does not wait for the poller, so on a failing test the poller can run up to one more `cond()` call plus 5 ms after the test ends. Harmless here (it only reads a file or stacks and closes its own channel). A `done` channel waited on in the cleanup would make "ends when the test ends" exact.
3. daemon_test.go:549-550 (`waitingForFolderLock`). The stack dump is cut at 1 MiB. If the binary ever held enough goroutines to push the daemon's stack past that, the check would stay false and the test would fail at the 20 s limit with a misleading message. It fails loudly, never passes falsely. Also allocates 1 MiB and stops the world every 5 ms while polling; fine at this scale.
4. Report wording only: it says `_quarantine` is "left empty"; the test asserts the folder does not exist (daemon_test.go:717, 739). The code is the stricter and correct one.

### Assessment
**Task quality:** Approved
**Reasoning:** The diff is the brief, verbatim, in the one allowed file, and the three risks the brief asked reviewers to look hardest at (goroutine lifetime, a false stack match, a race on `hit`) all check out on the passing path. The remaining gaps are confined to already-failing paths.
