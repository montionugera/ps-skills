# Task 4 review (Go): daemon tests A19, A20, A22

Range 9bb0da1..96589d0, one file: `tools/vault-engine/pkg/vaultsync/daemon_test.go`.
Method: read the brief, the report and the review package once. Not re-run: any test (the
implementer's `-race -count=3` runs are in the report). Run by me: `go vet ./...` in
`tools/vault-engine` (no output), and four focused reads outside the diff, each for a named risk
(listed under "Checks outside the diff").

### Spec Compliance
- ✅ Spec compliant. Every step of the brief has its hunk, and the code matches the brief's text:
  - A19: `closedWhen` (daemon_test.go:528) replaces the endless pid-file poller; the poller now
    waits for a pid in the file, not just the file (daemon_test.go:604-607); `strconv.Atoi` error
    is checked (daemon_test.go:615-618).
  - A22: the 200 ms settle sleep is gone from `runAndCancel` (daemon_test.go:557-586);
    the lock test waits on `closedWhen(t, waitingForFolderLock)` (daemon_test.go:645).
  - A20: `cancelledAt` (daemon_test.go:654) and
    `TestDaemon_CancelWithoutASignalAtMergeOrCommitIsSettledByTheNextPass` (daemon_test.go:689)
    with both subtests.
  - Constraints: only `daemon_test.go` changed; both commit messages name their items; no
    `--amend` visible (two separate commits); no `HOME`/`Setenv` in the file; no `time.Sleep`
    left anywhere in the file; `"sync"` import kept.
- ⚠️ Cannot verify from diff: acceptance 1 says "no goroutine started by daemon_test.go can
  outlive its test". Three `go func() { done <- X.Run(...) }()` starts at daemon_test.go:255,
  408 and 506 are outside this diff, and two of them use `context.Background()`. The brief only
  names the pid-file poller, so I did not judge them. The controller should confirm those tests
  always stop and wait for `Run` (or that they belong to another item).

### Strengths
- A rename of the lock function cannot pass silently: the string would never match, the poller
  would never close `ready`, and `runAndCancel` fails after 20 s (daemon_test.go:571-572).
- The match string ends in `(`, so it matches both a normal frame (`...Context(0x...`) and an
  inlined frame (`...Context(...)`), and it cannot match a "created by" line (no bracket there).
- The matched function contains the whole wait loop itself (lock.go:34-64, no helper, no closure,
  no second goroutine), so its frame is on the daemon's stack for the whole wait.
- Cancelling "too early" (inside the function but before the first lock attempt) still takes the
  cancel branch: the attempt fails with would-block, then `ctx.Done()` is already ready
  (lock.go:57-60). So the outcome does not depend on timing.
- `hit` (daemon_test.go:658) is race-free: the gate runs on the `Run` goroutine ("Passes run on
  this goroutine only", daemon.go), and the test reads it only after receiving from `done`.
- Cleanup order is right: `closedWhen` registers before `runAndCancel`, so `Run` is waited for
  first, the poller is stopped second, and the temp folders go last.
- The pid condition avoids the empty-file window that removing the sleep would have opened.
- The A20 assertions check real state (marker on disk, staged-not-committed status, commit count
  on the hub, no `_quarantine`), not mocks.

### Issues
#### Critical (Must Fix)
None.

#### Important (Should Fix)
None.

#### Minor (Nice to Have)
1. daemon_test.go:531-541, `closedWhen` stops its goroutine but does not wait for it. After the
   cleanup closes `stop`, the goroutine can still be inside one `cond()` call (a file read, or a
   stop-the-world stack dump) while the next test starts. It is bounded to one poll, and harmless
   here, but it is not strictly "ends when the test ends". Fix: add a `done` channel closed by
   the goroutine (`defer close(done)`) and make the cleanup `close(stop); <-done`.
   (Plan-mandated text; kept Minor because the overrun is one bounded poll with no shared state.)
2. daemon_test.go:548-551, `waitingForFolderLock` matches ANY goroutine of the binary. No test in
   the package is parallel and the test's own `AcquireFolderLock` call (daemon_test.go:633) has
   returned, so today only the daemon can match. But a goroutine leaked by an earlier failed test
   while waiting for a lock would give a false "ready"; the cancel would then land before the
   daemon reaches the lock and the test would pass without testing the wait. Fix: split the dump
   on blank lines and require one goroutine block to contain both `(*Daemon).Run(` and the lock
   function name.
3. daemon_test.go:549, the 1 MiB buffer is silently truncated by `runtime.Stack` when the dump is
   larger. The result is a loud 20 s failure, not a false pass, but the message ("the daemon never
   reached the step under test", daemon_test.go:572) would point the wrong way. Fix: grow the
   buffer in a loop until `n < len(buf)`. It also allocates 1 MiB every 5 ms; reuse is optional.
4. daemon_test.go:550, the function name is a hand-typed string. Fix (optional): build it from
   the function itself, `runtime.FuncForPC(reflect.ValueOf(AcquireFolderLockContext).Pointer()).Name() + "("`,
   so a rename is followed by the compiler instead of found by a 20 s timeout.
5. daemon_test.go:670-677, `cancelledAt` does not wait for `Run` on its 30 s time-out path. The
   deferred `cancel()` makes `Run` end soon, but it is not joined, so on that failure path it can
   overlap temp-folder removal and the restore of the package-level `exitOnSignal`. `runAndCancel`
   already has the right pattern (daemon_test.go:563-569). Failure path only.
6. daemon_test.go:676 and 679-681, if the pass never reaches git `<word>`, `Run` never returns
   (only the gate cancels), so the test fails with "Run did not stop" and the clearer
   "the pass never reached git ..." check cannot be reached. Fix: make the time-out message name
   the word, for example "Run did not stop: git %s was never reached or the cancel was ignored".

### Checks outside the diff (one per named risk)
- Risk: another goroutine could be inside the lock function. Checked `lock.go:28-64` and all
  callers (`syncer.go:132` is the only production caller in the package), and grepped for
  `t.Parallel()` in the package tests: none.
- Risk: `hit` is written on a different goroutine than the one that ends `Run`. Checked
  `daemon.go` `Run`/`tick`: passes run on the calling goroutine.
- Risk: `Tick` after a cancelled `Run` reuses a cancelled context. Checked: `Run` restores
  `r.stop` and `r.gate` on return, and `Tick` uses `context.Background()`.
- Risk: older goroutine starts in the same file. Grepped `go func` in `daemon_test.go` (see ⚠️).

### Assessment
**Task quality:** Approved
**Reasoning:** The diff does what the brief asks, with no production change, and the three
focus risks (leaks, false stack matches, a race on `hit`) do not hold in the code as it stands.
The six Minor items are hardening against failure paths and future changes, not present defects.
