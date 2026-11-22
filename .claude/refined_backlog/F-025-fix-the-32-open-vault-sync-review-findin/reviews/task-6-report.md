# Task 6 Report: Wording (A2, A3, A11, A23, and the README text for A1 and A8)

**Target Branch:** `feat/F-025`  
**Working Directory:** `/Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin`  
**Date:** 2026-10-13  
**Status:** PASS / VERIFIED  

---

## 1. Summary of Changes Per Item

### A2: Goroutine safety documentation for `Repo` and `stop`
- **Changes in `tools/vault-engine/pkg/vaultsync/repo.go` (comments only):**
  - Documented on `type Repo` that it is not safe for use from more than one goroutine because `lock`, `gate`, and `stop` are plain fields without synchronisation.
  - Documented on the `stop` field that it is set and read on the one goroutine that uses `Repo`, never from another one.
- **Commit:** `ba4a91b docs(vault-engine): A2 A3 A23 comments say what Repo, errorOutcome and the lock test really promise`

### A3: Case-ordering dependency documentation on `errorOutcome`
- **Changes in `tools/vault-engine/pkg/vaultsync/syncer.go` (comment only):**
  - Added doc comment to `func errorOutcome(err error) Outcome` explaining that the order of the switch cases decides the outcome, because a single error (e.g. `ErrNoConnection` wrapping `ErrStopped`) can match multiple cases, and the first match wins.
- **Commit:** `ba4a91b docs(vault-engine): A2 A3 A23 comments say what Repo, errorOutcome and the lock test really promise`

### A23: Clarification of guarantees in lock test
- **Changes in `tools/vault-engine/pkg/vaultsync/lock_test.go` (comment only):**
  - Replaced imprecise comment with detailed explanation in `TestFolderLock_WaitEndsAtOnceWhenTheContextIsCancelled` explaining that re-acquiring the lock verifies the cancelled wait did not leave the lock taken, but does not prove descriptor closure (which is handled in `ctx.Done` of `AcquireFolderLockContext`).
- **Commit:** `ba4a91b docs(vault-engine): A2 A3 A23 comments say what Repo, errorOutcome and the lock test really promise`

### A11: Rule 5 case b wording and test assertion update
- **Changes in `tools/vault-engine/templates/vault-rules/AGENTS.section.md`:**
  - Updated Rule 5 case b to read "Your input is probably fine. Change nothing, wait one minute, and run the same command again, up to 3 times."
- **Changes in `tools/vault-engine/pkg/vaultsync/harness_test.go`:**
  - Updated `TestHarness_InstallsTheRulesFiles` assertion list from `"Your input is fine"` to `"Your input is probably fine"`.
- **Commit:** `e3b6908 docs(vault-engine): A11 A1 A8 rules text says 'probably fine'; README: daemon ends within a couple of seconds, tree or blob tip is type-not-allowed`

### A1 (README sentence): Daemon shutdown timing
- **Changes in `tools/vault-engine/README.md`:**
  - Replaced `"The stop does not wait for a time limit: a git command that is running is killed, and a wait for the folder lock ends at once."` with `"The stop does not wait for a time limit: a git command that is running is killed and a wait for the folder lock is given up, so \`sync-daemon\` ends within a couple of seconds."`
- **Commit:** `e3b6908 docs(vault-engine): A11 A1 A8 rules text says 'probably fine'; README: daemon ends within a couple of seconds, tree or blob tip is type-not-allowed`

### A8 (README sentence): Tree or blob tip refused as `type-not-allowed` (exit 6)
- **Changes in `tools/vault-engine/README.md`:**
  - Updated hub paragraph to specify: `"\`too-large\` and \`type-not-allowed\` mean the send broke a rule in the table above. A send that points \`refs/heads/main\` at something other than a commit (a tree or a blob) is also refused as \`type-not-allowed\`, so the place answers \`REFUSED type-not-allowed\` (exit 6)."`
- **Commit:** `e3b6908 docs(vault-engine): A11 A1 A8 rules text says 'probably fine'; README: daemon ends within a couple of seconds, tree or blob tip is type-not-allowed`

---

## 2. Test Commands & Output Lines

### Step 4 (TDD RED): `TestHarness_InstallsTheRulesFiles`
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestHarness_InstallsTheRulesFiles'`
- **Output:**
```
--- FAIL: TestHarness_InstallsTheRulesFiles (1.86s)
    harness_test.go:50: AGENTS.md does not mention "Your input is probably fine"
FAIL
FAIL	obsidian-vault-engine/pkg/vaultsync	2.881s
FAIL
```

### Step 4 (TDD GREEN): `TestHarness_InstallsTheRulesFiles`
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestHarness_InstallsTheRulesFiles'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	3.906s
```

### Step 7: Lint, Vet, and Targeted Tests
- **Command:** `cd tools/vault-engine && go vet ./... && gofmt -l pkg/vaultsync cmd && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestHarness_InstallsTheRulesFiles|TestFolderLock_'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	3.681s
```

### Gate Verification Command
- **Command:** `bash .superpowers/sdd/plan/verify-6.sh`
- **Exit Code:** 0
- **Final Output Lines:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	4.472s
```

---

## 3. Acceptance Criteria Checklist

1. **The `Repo` type says it is not safe for use from more than one goroutine, and `errorOutcome` says its answer depends on the order of its cases:**  
   Checked via grep and code inspection in `repo.go` (line 40) and `syncer.go` (line 54).
2. **Rule 5 case b reads "Your input is probably fine." and the rules-file test quotes the new sentence:**  
   Checked via grep in `templates/vault-rules/AGENTS.section.md` and verified passing in `harness_test.go` (`TestHarness_InstallsTheRulesFiles`).
3. **`tools/vault-engine/README.md` says the daemon ends "within a couple of seconds" and no longer says "ends at once"; its hub paragraph says a tree or blob as the new tip is `type-not-allowed`, exit 6:**  
   Checked via grep on `README.md` (lines 61 and 82) and negative grep confirming `"ends at once"` is absent.
4. **No line of executable code changed in `repo.go`, `syncer.go` or `lock_test.go` (comments only):**  
   Checked via `git diff ba4a91b^! -- '*.go'`. Only comment lines were added or modified.

---

## 4. Off-Scope Findings

None.
