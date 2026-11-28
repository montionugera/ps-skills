# Task 5 Report: Build script and its tests (A9, A10, A14, A26, A28, A29, A30, A31)

**Target Branch:** `feat/F-025`  
**Working Directory:** `/Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin`  
**Date:** 2026-10-13  
**Status:** PASS / VERIFIED  

---

## 1. Summary of Changes Per Item

### A9: Build script stops on failing git status
- **Changes in `tools/vault-engine/scripts/build-release.sh`:**
  - Assigned `changes="$(git status --porcelain -- .)"` as a standalone command before testing `[ -z "$changes" ]`.
  - Under `set -e`, a failing `git status` command immediately halts the script with a non-zero exit code instead of silently evaluating to empty string and treating the tree as clean.
- **Commit:** `112a13c fix(vault-engine): A9 A10 build script stops on a failing git status and names only the binary it built`

### A10: Build script names only the binary it built
- **Changes in `tools/vault-engine/scripts/build-release.sh`:**
  - Changed `echo "built $OUT/$name"` to `echo "built $name"`.
  - At this stage, the binary is in the temporary staging directory `$STAGE`, not in `$OUT` (`bin/release/`).
- **Commit:** `112a13c fix(vault-engine): A9 A10 build script stops on a failing git status and names only the binary it built`

### A14: Fixtures and test helpers drop git location variables
- **Changes in `tools/vault-engine/pkg/vaultsync/testkit_test.go`:**
  - Updated `gitIn` to use `cmd.Env = append(placeEnv(dir), env...)`, preventing any caller-exported `GIT_DIR` or related variables from leaking into fixture commands.
- **Changes in `tools/vault-engine/scripts/sync-harness.sh`:**
  - Redefined `fixture_git()` to take `<dir>` as its first argument and use `env -u` to unset all 13 git location variables defined in `gitLocationVars` (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_COMMON_DIR`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_QUARANTINE_PATH`, `GIT_NAMESPACE`, `GIT_PREFIX`, `GIT_IMPLICIT_WORK_TREE`, `GIT_SHALLOW_FILE`, `GIT_GRAFT_FILE`, `GIT_REPLACE_REF_BASE`), while setting `GIT_CEILING_DIRECTORIES="$(dirname "$dir")"`.
  - Updated the three invocations in `setup` to call `fixture_git "$root/seed" ...`.
- **Changes in `tools/vault-engine/pkg/vaultsync/harness_test.go`:**
  - Added `TestHarness_FixtureGitDropsEveryGitLocationVariable`: dynamically iterates over `gitLocationVars` to ensure `scripts/sync-harness.sh` drops every variable except the ceiling directory, and verifies the ceiling directory configuration.
  - Added `TestGitIn_IgnoresAnExportedGitDir`: exports `GIT_DIR` and `GIT_WORK_TREE` pointing to another repository and verifies `gitIn` acts exclusively on the target fixture folder without altering the exported repo.
- **Commit:** `811c9c0 test(vault-engine): A14 gitIn and fixture_git drop git's location variables`

### A28: `runBuild` bounded by a time limit and process group kill
- **Changes in `tools/vault-engine/pkg/vaultsync/build_release_test.go`:**
  - Defined `const buildTimeout = 15 * time.Minute`.
  - Updated `runBuild` signature to `func runBuild(t *testing.T, dir string, extra ...string) (string, error)` using `exec.CommandContext(ctx, ...)`.
  - Configured process group isolation via `cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}`, `cmd.Cancel = func() error { return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) }`, and `cmd.WaitDelay = 10 * time.Second`.
  - Scrubbed git location variables using `cmd.Env = placeEnv(dir)` and cleared `VERSION`, `GOOS`, `GOARCH`, `GOFLAGS`.
- **Commit:** `a59069e test(vault-engine): A14 A26 A28 A29 A30 A31 build test: time limit, clean git environment, explicit VERSION, real main.go, named check`

### A31: Check error when reading checksums in `releaseSet`
- **Changes in `tools/vault-engine/pkg/vaultsync/build_release_test.go`:**
  - Replaced unchecked `sums, _ := os.ReadFile(...)` in `releaseSet` with error check and `t.Fatalf("read the checksum file: %v", err)`.
- **Commit:** `a59069e test(vault-engine): A14 A26 A28 A29 A30 A31 build test: time limit, clean git environment, explicit VERSION, real main.go, named check`

### A26: Step 4 verifies in-file check on first target
- **Changes in `tools/vault-engine/pkg/vaultsync/build_release_test.go`:**
  - In `TestBuildRelease_StampsChecksAndKeepsTheOldSetOnFailure` step 4, asserted output contains `"build-release: vault-engine-darwin-amd64 does not carry version"` and does NOT contain `"it says:"`, verifying the script failed on the in-file check of the first target rather than proceeding to run the host binary.
- **Commit:** `a59069e test(vault-engine): A14 A26 A28 A29 A30 A31 build test: time limit, clean git environment, explicit VERSION, real main.go, named check`

### A29: Check real engine's `main.go` has stamped variable
- **Changes in `tools/vault-engine/pkg/vaultsync/build_release_test.go`:**
  - Added `TestBuildRelease_TheRealEngineStillHasTheStampedVariable`: verifies `cmd/vault-engine/main.go` contains `\nvar version = "\"`.
- **Commit:** `a59069e test(vault-engine): A14 A26 A28 A29 A30 A31 build test: time limit, clean git environment, explicit VERSION, real main.go, named check`

### A30: Test explicit `VERSION` override in build script
- **Changes in `tools/vault-engine/pkg/vaultsync/build_release_test.go`:**
  - Added `TestBuildRelease_AnExplicitVersionIsUsedAsGiven`: invokes `runBuild(t, dir, "VERSION=9.9.9-explicit")` on a dirty tree, verifies built version equals `"9.9.9-explicit"` without `.dirty` appended, and verifies running the host binary reports `vault-engine 9.9.9-explicit`.
- **Commit:** `a59069e test(vault-engine): A14 A26 A28 A29 A30 A31 build test: time limit, clean git environment, explicit VERSION, real main.go, named check`

---

## 2. Test Commands & Output Lines

### Step 2: A9 & A10 Test Run
- **Command:** `cd tools/vault-engine && bash -n scripts/build-release.sh && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestBuildRelease_'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	7.304s
```

### Step 4: A14 RED Run (Expected Failure)
- **Command:** `cd tools/vault-engine && go test -count=1 -timeout 40m ./pkg/vaultsync/ -run 'TestHarness_FixtureGit|TestGitIn_'`
- **Output:**
```
--- FAIL: TestHarness_FixtureGitDropsEveryGitLocationVariable (0.00s)
    harness_test.go:135: fixture_git in scripts/sync-harness.sh does not drop GIT_DIR
    ...
    harness_test.go:139: fixture_git does not stop git from looking above the fixture folder
--- FAIL: TestGitIn_IgnoresAnExportedGitDir (0.12s)
    harness_test.go:157: the helper worked on .../other, not on the fixture folder
FAIL
FAIL	obsidian-vault-engine/pkg/vaultsync	0.873s
```

### Step 7: A14 GREEN Run
- **Command:** `cd tools/vault-engine && bash -n scripts/sync-harness.sh && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestHarness_|TestGitIn_|TestHub_|TestRepo_'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	75.285s
```

### Step 13: Build Tests (A14, A26, A28, A29, A30, A31) Run
- **Command:** `cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestBuildRelease_'`
- **Output:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	26.587s
```

### Step 15: Full Phase Gate Verification
- **Command:** `bash .superpowers/sdd/plan/verify-5.sh`
- **Exit Code:** 0
- **Final Output Lines:**
```
ok  	obsidian-vault-engine/pkg/vaultsync	103.300s
ok  	obsidian-vault-engine/pkg/vaultsync	583.211s
```

---

## 3. Acceptance Criteria Checklist

1. **`build-release.sh` stops when `git status` fails, and its per-target line reads `built <name>` with no folder:**  
   Verified. `changes="$(git status --porcelain -- .)"` ensures exit code 1 stops the script with `set -e`. `echo "built $name"` outputs only the binary name.
2. **With `GIT_DIR` exported, `gitIn` works on the folder it is given and leaves the exported repository untouched; `runBuild` and `fixture_git` drop the same variables:**  
   Verified. `gitIn` and `runBuild` use `placeEnv(dir)`. `fixture_git` unsets all 13 location variables and sets `GIT_CEILING_DIRECTORIES`. Verified by `TestGitIn_IgnoresAnExportedGitDir` and `TestHarness_FixtureGitDropsEveryGitLocationVariable`.
3. **`runBuild` cannot hang past its time limit; an explicit `VERSION` is used as given; the real `main.go` is checked for `var version`:**  
   Verified. `runBuild` uses `context.WithTimeout` with `buildTimeout = 15 * time.Minute` and group `SIGKILL`. `TestBuildRelease_AnExplicitVersionIsUsedAsGiven` passes an explicit `VERSION` and validates binary and output. `TestBuildRelease_TheRealEngineStillHasTheStampedVariable` checks `cmd/vault-engine/main.go`.
4. **Build test step 4 can tell the in-file check from the host-run check:**  
   Verified. Step 4 asserts presence of `"build-release: vault-engine-darwin-amd64 does not carry version"` and absence of `"it says:"`.

---

## 4. Off-Scope Findings

None.
