# Task 2 Report: Hub (A8, A12, A13, A24)

**Target Branch:** `feat/F-025`  
**Working Directory:** `/Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin`  
**Date:** 2026-10-13  
**Status:** PASS / VERIFIED  

---

## 1. Summary of Changes Per Item

### A13: hubGit takes a working-folder argument
- **Code:**
  - In `tools/vault-engine/pkg/vaultsync/hub.go`, updated `hubGit(stdin string, args ...string)` to `hubGit(dir, stdin string, args ...string)`, setting `cmd.Dir = dir` without modifying `cmd.Env`.
  - Updated `batchCheck(input, format, ...)` to `batchCheck(dir, input, format, ...)`.
  - Updated `PreReceive(stdin io.Reader, ...)` to `PreReceive(dir string, stdin io.Reader, ...)`.
  - Forwarded `dir` at all 6 call sites inside `PreReceive` (`merge-base`, `rev-list`, `diff-tree`, `batchCheck` for files, `rev-list --objects`, `batchCheck` for send allowance).
  - In `tools/vault-engine/cmd/vault-engine/main.go` line 42, passed `""` as `dir` to `PreReceive`, preserving hook behavior (running git in current working directory with inherited environment untouched).
- **Tests:**
  - In `tools/vault-engine/pkg/vaultsync/hub_test.go`, added helper `hubRepo(t *testing.T) string` which clears `gitLocationVars` for test isolation and initializes an empty bare git repository in a temp directory.
  - Updated 7 calls in `hub_test.go`: `TestPreReceive_RefusesInputItCannotRead` uses `hubRepo(t)`, `TestPreReceive_OwnFaultsAreEngineErrors` (4 calls to `PreReceive` and 1 to `batchCheck`) uses `hubRepo(t)`, and `TestPreReceive_AncestorCheckThatCannotRunIsAnEngineError` passes `hubRepo(t)`.
- **Commit:** `76df471 refactor(vault-engine): A13 hubGit takes a working folder; hub tests use a temp repository`

### A12: Ancestor check test pins exit code 1
- **Tests:** In `tools/vault-engine/pkg/vaultsync/hub_test.go` (`TestPreReceive_AncestorCheckThatCannotRunIsAnEngineError`), tightened the check from `code == 0` to `code != 1`, asserting that when the hub cannot run the ancestor check due to missing objects, it exits with exit code 1 and prefix `vault-hub: REFUSED engine-error: cannot check that refs/heads/main only moves forward`.
- **Commit:** `6b47f10 test(vault-engine): A12 the ancestor-check test asserts exit code 1`

### A8: A tree or blob as the new tip is refused as type-not-allowed (place exits 6)
- **Check for message readers:** Verified with `grep` that only `pkg/vaultsync/hub.go` and `hub_test.go` read the refusal reason string, and `syncer.go:312-315` parses only the label (`too-large`, `type-not-allowed`, `engine-error`), mapping `type-not-allowed` to exit code 6 (`ExitTypeNotAllowed`).
- **Tests (RED):** Added `TestPreReceive_ATreeOrBlobAsTheNewTipIsTypeNotAllowed` and `TestSave_ATreeOrBlobRefusalFromTheHubEndsWithExitSix` to `hub_test.go`. Ran tests and verified failure (hub returned `REFUSED engine-error` with exit 1).
- **Code (GREEN):** In `tools/vault-engine/pkg/vaultsync/hub.go` inside `PreReceive`, when `merge-base` fails and is not exit code 1, added a check with `cat-file -t newSHA`. If `terr == nil` and object type is not `"commit"`, returns `refuse("type-not-allowed", "%s may only point at a commit; this send points it at a %s", ref, strings.TrimSpace(typ))`. Unresolved objects fail `cat-file -t` and remain `engine-error`.
- **Commit:** `6516fa1 fix(vault-engine): A8 a tree or blob as the new tip is refused as type-not-allowed (the place exits 6)`

### A24: A usage file that cannot be written charges nothing
- **Tests:** In `tools/vault-engine/pkg/vaultsync/hub_test.go`, added:
  - `TestChargeDaily_AUsageFileThatCannotBeWrittenChargesNothing`: tests `chargeDaily` when `file+".tmp"` is an unwritable path (directory collision), verifying `chargeDaily` returns `(0, false, err)` with no charge to existing ledger data.
  - `TestHub_UsageFileThatCannotBeWrittenRefusesTheSendAndChargesNothing`: performs a real push into a hub with blocked usage files, asserting refusal with `vault-hub: REFUSED engine-error: daily allowance cannot be recorded: writing usage file`, no refs updated on the hub, and no usage file created.
- **Commit:** `1cc6c45 test(vault-engine): A24 a usage file that cannot be written refuses the send and charges nothing`

---

## 2. Test Commands & Last Output Lines

### Step 3 (A13 verification):
- **Command:** `cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestPreReceive_|TestHub'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	30.983s
```

### Step 6 (A12 verification):
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestPreReceive_AncestorCheck'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	2.252s
```

### Step 9 (A8 RED test run):
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestPreReceive_ATreeOrBlob|TestSave_ATreeOrBlobRefusal'`
- **Output:**
```
--- FAIL: TestPreReceive_ATreeOrBlobAsTheNewTipIsTypeNotAllowed (1.16s)
    --- FAIL: TestPreReceive_ATreeOrBlobAsTheNewTipIsTypeNotAllowed/tree (0.01s)
        hub_test.go:489: code=1 stderr="vault-hub: REFUSED engine-error: cannot check that refs/heads/main only moves forward: git merge-base: exit status 128: error: object 2d2805be0106da973023879415a3ba82b35018ab is a tree, not a commit\nfatal: Not a valid commit name 2d2805be0106da973023879415a3ba82b35018ab\n", want code 1 and "vault-hub: REFUSED type-not-allowed: refs/heads/main may only point at a commit; this send points it at a tree"
    --- FAIL: TestPreReceive_ATreeOrBlobAsTheNewTipIsTypeNotAllowed/blob (0.01s)
        hub_test.go:489: code=1 stderr="vault-hub: REFUSED engine-error: cannot check that refs/heads/main only moves forward: git merge-base: exit status 128: error: object e31de1f3a235fd5e8f97207b8e43cd2aa06a6417 is a blob, not a commit\nfatal: Not a valid commit name e31de1f3a235fd5e8f97207b8e43cd2aa06a6417\n", want code 1 and "vault-hub: REFUSED type-not-allowed: refs/heads/main may only point at a commit; this send points it at a blob"
--- FAIL: TestSave_ATreeOrBlobRefusalFromTheHubEndsWithExitSix (2.63s)
    hub_test.go:514: outcome = {Line:REFUSED engine-error Exit:1 Detail:cannot check that refs/heads/main only moves forward: git merge-base: exit status 128: error: object 2d2805be0106da973023879415a3ba82b35018ab is a tree, not a commit}, want REFUSED type-not-allowed with exit 6
FAIL
FAIL	obsidian-vault-engine/pkg/vaultsync	4.972s
FAIL
```

### Step 11 (A8 GREEN test run):
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestPreReceive_|TestHub|TestSave_ATreeOrBlobRefusal'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	41.636s
```

### Step 14 (A24 verification):
- **Command:** `cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestChargeDaily_|TestHub_Usage|TestHub_Unwritable'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	7.846s
```

### Final Phase Gate Verification:
- **Command:** `bash .superpowers/sdd/plan/verify-2.sh`
- **Exit Code:** 0
- **Final Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	49.349s
```

---

## 3. Off-Scope Findings

- Finding 1: An annotated tag object sent as the new tip of `refs/heads/main` yields type `tag` via `cat-file -t`, and is appropriately refused with `type-not-allowed: refs/heads/main may only point at a commit; this send points it at a tag`.
- Finding 2: `gofmt -l .` reports two legacy files under `pkg/vault/` (`pkg/vault/vault.go`, `pkg/vault/vault_test.go`) which remain unformatted in the repository baseline but are outside our scope per global constraints.
