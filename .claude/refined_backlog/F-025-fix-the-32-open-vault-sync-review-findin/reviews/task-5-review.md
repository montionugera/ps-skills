# Task 5 Review: Build script and its tests (A9, A10, A14, A26, A28, A29, A30, A31)

Range 20e41c7..a59069e (3 commits, 5 files, +133/-16). Reviewed against task-5-brief.md and acceptance criteria.

### Spec Compliance
- ✅ Spec compliant. Every item and file named in the brief has its exact hunk matching the brief:
  - Step 1 (A9, A10): `build-release.sh` assigns `changes="$(git status --porcelain -- .)"` first, halting on error under `set -e`; per-target echo outputs `built $name`.
  - Step 3 & 4 (A14 tests): `harness_test.go` has `TestHarness_FixtureGitDropsEveryGitLocationVariable` and `TestGitIn_IgnoresAnExportedGitDir`. Both failed on RED run as expected.
  - Step 5 (A14 `gitIn`): `testkit_test.go` uses `cmd.Env = append(placeEnv(dir), env...)`.
  - Step 6 (A14 `fixture_git`): `sync-harness.sh` unsets all 13 git location variables and sets `GIT_CEILING_DIRECTORIES`. Only `fixture_git` and its three calls in `setup` were changed.
  - Step 9 (A28, A14 `runBuild`): `build_release_test.go` has `buildTimeout = 15 * time.Minute`, `CommandContext`, `placeEnv`, `Setpgid: true`, process group `SIGKILL` on cancel, and `WaitDelay = 10 * time.Second`.
  - Step 10 (A31): `releaseSet` checks `os.ReadFile` error with `t.Fatalf`.
  - Step 11 (A26): Step 4 of `TestBuildRelease_StampsChecksAndKeepsTheOldSetOnFailure` asserts `build-release: vault-engine-darwin-amd64 does not carry version` and confirms `it says:` is absent.
  - Step 12 (A29, A30): `TestBuildRelease_TheRealEngineStillHasTheStampedVariable` and `TestBuildRelease_AnExplicitVersionIsUsedAsGiven` added.
- All 3 commits are fresh, no amend, and name their addressed items.
- Scope: Only files under `tools/vault-engine/` touched. No home redirection, no prohibited file touched.

### Focus Invariants
1. **`fixture_git` drops every name in `gitLocationVars` except ceiling:**
   Checked: `repo.go:95-100` defines 14 keys in `gitLocationVars`. `sync-harness.sh:22-26` unsets all 13 variables (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_COMMON_DIR`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_QUARANTINE_PATH`, `GIT_NAMESPACE`, `GIT_PREFIX`, `GIT_IMPLICIT_WORK_TREE`, `GIT_SHALLOW_FILE`, `GIT_GRAFT_FILE`, `GIT_REPLACE_REF_BASE`) and sets `GIT_CEILING_DIRECTORIES`. Validated by `TestHarness_FixtureGitDropsEveryGitLocationVariable`.
2. **Nothing in `sync-harness.sh` changed outside `fixture_git` and its 3 calls:**
   Checked git diff: `sync-harness.sh` diff contains only the replacement of `fixture_git()` and the 3 call invocations in `setup`.
3. **Timed-out build leaves no `go build` running:**
   Checked: `runBuild` creates a new process group with `Setpgid: true` and defines `cmd.Cancel = func() error { return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) }` with `WaitDelay = 10 * time.Second`. Killing `-cmd.Process.Pid` kills the group containing `bash` and any spawned `go build` compiler processes.

### Strengths
- Precise TDD with RED failure captured before implementation.
- Error handling in `releaseSet` prevents silent false-passes if checksum file cannot be read.
- `placeEnv(dir)` and `fixture_git` prevent test pollution when run by CI or developers with global `GIT_DIR` exported.

### Issues
#### Critical (Must Fix)
None.

#### Important (Should Fix)
None.

#### Minor (Nice to Have)
None.

### Assessment
**Task quality:** Approved
**Reasoning:** All acceptance criteria and brief specifications are verified with 0 defects and clean test execution.
