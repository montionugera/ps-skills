# Task 3 Review: sync engine and repo (A1 code, A21, A25, A27, A32)

Range: 01dd268..2da5ecb (3 commits, 4 files, +110/-3). Reviewed from the review package in one pass.
Tests were not re-run (per the method); the implementer's reported runs are taken as the test evidence.

### Spec Compliance
- ✅ Spec compliant. Every item and every listed file has its hunk, and each hunk matches the brief's text.
  - A1: tools/vault-engine/pkg/vaultsync/syncer.go:344-350. A fetch that ends with ErrStopped breaks out of the loop; any other fetch error still sleeps and retries. Test at syncer_test.go:848-885.
  - A21: repo_test.go:453-502, both tests present, `context` import placed between `bufio` and `errors`.
  - A25: repo_test.go:447-448 adds the positive `has no refs/heads/` check.
  - A27: testkit_test.go:54-64 (helper exits 4 when the pid file never appears); repo_test.go:167-172 (Atoi error handled, helper killed and reaped).
  - A32: repo_test.go:158-159 (helper killed and reaped before the fatal).
- Global constraints: only files under tools/vault-engine/ changed; all three commit messages name their items; three new commits, no amend; no HOME redirect in the new tests; no extra changes beyond the named items.
- "Prove the test bites" edits: repo.go is not in the diff and `git status --short` on the worktree is empty, so no temporary edit remains.
- ⚠️ Cannot verify from diff: none.

### Named risks checked outside the diff (one focused read each)
1. Risk: the `break` at syncer.go:346 could land on a different answer than before. Checked syncer.go:367-375: the code after the loop is the unchanged `pushUnconfirmed` + `refused("no-connection", ExitNoConnection, ...)` return, so outcome and marker handling are the same as a loop that ran out of tries. Only the two 500 ms waits and two fetches are gone.
2. Risk: `errors.Is(err, ErrStopped)` could be false because Fetch wraps its cause. Checked repo.go:225-231: Fetch uses `%w` for both ErrNoConnection and the cause, so the match holds. The gate path (repo.go:148-151) returns the gate's error as `res.Err`, which is what the new test drives.
3. Risk: the new Repo.run cancel test could leave a `sleep 30` running. Checked repo.go:156-161: git runs in its own process group (`Setpgid`), and `cmd.Cancel` sends SIGKILL to the whole group, with a 2 s WaitDelay. The `exec sleep 30` is in that group, so the cancel kills it. The test's `defer cancel()` and the 20 s cap on the waiting goroutine cover the path where the command never starts.
4. Risk: `Repo{stop: ctx}` with nil lock and nil gate could panic in run. Checked repo.go:148 and :162: both are nil-guarded.

### Strengths
- The production change is five lines, exactly at the named spot, with the signature and every other branch untouched.
- The A1 test pins all three parts of the requirement (outcome line and exit code, exactly one fetch, marker stays) and then proves the marker is settled by the next command.
- The A21 tests exercise the real git child, not a mock, and the reported bite proofs show each test fails for the right mutation of repo.go:188.
- `stoppedButSilent` is a small, well-commented way to reach a state that is otherwise a race.
- The A32 and A27 parent paths both kill and reap the helper before failing, so no one-hour idle helper is left.

### Issues
#### Critical (Must Fix)
None.

#### Important (Should Fix)
None.

#### Minor (Nice to Have)
1. tools/vault-engine/pkg/vaultsync/testkit_test.go:62 with repo_test.go:148-150 (plan-mandated wording). The helper prints "the git child never wrote its pid file" to stderr, but the parent never sets `holder.Stderr`, so the text goes to the null device and nobody sees it. The parent only reports `said ""`, and the exit status 4 is thrown away by `_ = holder.Wait()`. The acceptance text (exit non-zero, kill before failing) is met; the failure is just less clear than the item's name promises. Fix: set `holder.Stderr = os.Stderr` in the parent, or include the result of `holder.Wait()` in the fatal message.
2. tools/vault-engine/pkg/vaultsync/repo_test.go:462-470. If git never starts the alias, the waiting goroutine cancels after 20 s and the test fails on the "took more than 15 s" check (or passes the ErrStopped check first) before it reaches the clearer "the command was never running" check. The test still fails, only with a less helpful message. Fix: do the pid-file check first.

### Assessment
**Task quality:** Approved
**Reasoning:** The diff is a faithful, minimal implementation of the five items, the one behaviour change keeps the outcome and the marker as required, and the new tests check real behaviour. The two Minor points are about how clear a failure message is, not about correctness.
