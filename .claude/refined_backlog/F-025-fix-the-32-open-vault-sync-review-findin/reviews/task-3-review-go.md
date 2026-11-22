# Task 3 review (Go): sync engine and repo (A1 code, A21, A25, A27, A32)

Range 01dd268..2da5ecb. Reviewed from the review package in one pass. Outside the diff I read
two unchanged ranges, each for a named risk (listed under "Checks outside the diff").
I ran `go vet ./...` in tools/vault-engine (no output). I did not run any test.

### Spec Compliance
- ✅ Spec compliant. Every listed file has its hunk and every item matches the brief's text:
  - A1: tools/vault-engine/pkg/vaultsync/syncer.go:344-350, test at syncer_test.go:849-885.
  - A21: repo_test.go:452-479 (cancel during a running command) and :481-501 (ended well, stop already cancelled).
  - A25: repo_test.go:446-447.
  - A27: testkit_test.go:54-65 (helper exits 4), A32 and the Atoi half: repo_test.go:158-160 and :168-173.
- Constraints: three new commits, each message names its items, no amend visible. The diff touches only
  tools/vault-engine/ (stat outside that path is empty). repo.go is not in the diff and the working tree is
  clean at 2da5ecb, so no "prove the test bites" edit remains. No HOME redirect in the new tests.
- ⚠️ Cannot verify from diff: the A1 sentence "the outcome is still REFUSED no-connection" holds only when the
  stop lands on the fetch itself. If stop is already cancelled when record reaches the unchanged `r.Head()` at
  syncer.go:339-342, Head fails with ErrStopped and the function returns `errorOutcome(err)` before the loop.
  That code predates this batch and the constraint is worded about the fetch, so this is not a finding here;
  the controller should check what errorOutcome answers for ErrStopped and whether the README sentence in
  Task 6 promises more than the code gives.

### Checks outside the diff (one named risk each)
1. Risk: the new A1 branch never fires because the stop error loses its identity on the way out of Fetch.
   Checked repo.go:147-152 and :225-231. A gate error is returned as it is, and Fetch wraps with
   `%w: fetch: %w`, so `errors.Is(err, ErrStopped)` is true for both the gate path (the test) and a real
   kill (run maps it at repo.go:188-189).
2. Risk: the new Repo.run tests leave a `sleep 30` behind, or the "ended well" test is killed by its own
   fake context. Checked repo.go:153-194. git runs in its own process group (Setpgid), cmd.Cancel sends
   SIGKILL to the whole group, WaitDelay is 2 s, so the `exec sleep 30` dies with the cancel. For
   stoppedButSilent, `context.WithTimeout` sees a parent whose Done() is nil and never propagates a cancel,
   so only `stop.Err()` at repo.go:188 reports "cancelled", which is the state the test wants.

### Strengths
- The A1 change is the smallest possible one: `break` falls into the same code that built the unconfirmed
  answer before (syncer.go:367-375), so the outcome and the marker are unchanged apart from the missing wait.
  The non-stop path keeps its sleep and retry.
- The A1 test proves the second half too: it clears the hooks and shows the next command settles the marker
  (syncer_test.go:873-884). The reported RED run (3 fetches, want 1) shows it fails without the fix.
- Both A21 tests bite, and the reported proof matches the code: `case false` gives "signal: killed",
  `case stop.Err() != nil` gives `(".git\n", stopped)`.
- The cancel test waits for the pid file instead of a fixed time and asserts the command really ran
  (repo_test.go:476-478), so it cannot pass by cancelling too early. The 15 s bound is far from both the
  expected few milliseconds and the 30 s sleep, so it is not timing-sensitive under -race.
- The hook closures in the A1 test run on the calling goroutine, so the plain `stopping` and `fetches`
  variables are not a data race.

### Issues
#### Critical (Must Fix)
None.

#### Important (Should Fix)
None.

#### Minor (Nice to Have)
1. repo_test.go:148 with testkit_test.go:62-63 (plan-mandated shape). The helper's new message
   "the git child never wrote its pid file" goes to stderr, but the parent starts the helper without
   setting `holder.Stderr`, so it goes to the null device. The parent also drops the exit status
   (`_ = holder.Wait()` at repo_test.go:160). A failed run shows only `said ""`. The item's aim was to
   fail clearly. Fix: set `holder.Stderr = os.Stderr` (or a buffer added to the Fatalf), or put the Wait
   error into the message.
2. repo_test.go:170-171. In the Atoi branch the helper is alive and its git child is running. SIGKILL
   cannot be handled, so the helper cannot kill the git group: `sleep 30` stays for up to 30 s and keeps the
   inherited lock descriptor. Bounded and nearly unreachable (the helper already saw a non-empty pid file),
   so it is only polish. Fix: send SIGTERM, which the helper's Repo.run turns into a group kill, then Wait.
   The same holds for testkit_test.go:63: `os.Exit(4)` leaves a git child, if one started, to its 30 s.
3. repo_test.go:461-467. If git ends early for another reason, the test fails at once, but the polling
   goroutine keeps reading a removed temp path every millisecond for up to 20 s. It ends by itself and
   never touches `t`, so it is harmless. Fix: give it a `done` channel closed by a defer, or poll in
   `waitFor` against `ctx.Done()`.

### Assessment
**Task quality:** Approved
**Reasoning:** The one behaviour change is correct and minimal, each new test pins real behaviour and is shown
to fail without its fix, and no child process or goroutine can outlive a passing run. The three Minor items
concern only failure paths of the tests.
