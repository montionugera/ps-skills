# Task 5 review: build script and its tests (A9, A10, A14, A26, A28, A29, A30, A31)

Independent review of 20e41c7..a59069e, formed from the brief and the diff only.
The earlier file at this path (written by the implementer) was not read and is replaced.

### Spec Compliance
- ✅ Spec compliant. Every item has its hunk, and each hunk matches the brief's text.
  - A9: `scripts/build-release.sh:16-17` assigns `changes=...` first, then tests it.
  - A10: `scripts/build-release.sh:48` prints `built $name`.
  - A14: `testkit_test.go:91` (gitIn uses placeEnv), `build_release_test.go:59` (runBuild uses placeEnv),
    `scripts/sync-harness.sh:21-33` (fixture_git) and its three calls at `sync-harness.sh:133-135`.
  - A28: `build_release_test.go:37-39, 52-72` (15 minute limit, process-group kill, WaitDelay).
  - A31: `build_release_test.go:92-95`. A26: `build_release_test.go:166-173`.
  - A29 and A30: `build_release_test.go:184-213`.
- Owner constraints checked line by line:
  - Scope: all five files are under tools/vault-engine/. No other file changed.
  - A14 stays as worded: `git push` in setup (`sync-harness.sh:136`), `make_place`, `hub/create-hub.sh`,
    `newWorld` and `newHub` are untouched.
  - Harness time limits: no changed line in sync-harness.sh touches a `go test` call or a `-timeout`.
    The only changed lines are fixture_git and its three calls.
  - Commit messages each name their items (3 commits, A9 A10 / A14 / A14 A26 A28 A29 A30 A31).
  - No HOME redirect added in any test.
- ⚠️ Cannot verify from diff: "no git commit --amend". Three plain commits are consistent with it;
  the controller can confirm from the reflog if it matters.

### Named risks and what was checked (one focused check each)
1. A9 really stops the script (plan auditor: proven only by grep).
   Checked with a 7-line scratch script outside the repo, same shell options (`set -euo pipefail`),
   same shape (assignment inside an `if` body), on this machine's bash 3.2.57:
   new form exits 128 and never reaches the next line; old form exits 0 and carries on as "clean".
   So the change has the stated effect. The `if` body is not a condition context, so `set -e` applies.
2. gitIn change alters behaviour for callers that pass their own environment.
   Checked every non-nil env caller: only `hub_test.go:207` and `testkit_test.go:128`, both pass
   `VAULT_HUB_PLACE=...` only. Caller values are appended after placeEnv, so they still win.
   No caller relied on a GIT_* variable from the process reaching git through gitIn
   (`repo_test.go:296-330` unsets them before its plain-git checks; `hubRepo` in `hub_test.go:336` clears them).
3. The new ceiling (`GIT_CEILING_DIRECTORIES=<parent of dir>`) breaks a helper call made from a
   sub-folder of a repository. Tallied every folder argument to mustGit/gitIn/pushAs: all are
   repository roots, a bare hub, or a parent folder used for `init`/`clone` with an explicit path.
   None is a sub-folder of a repository.
4. fixture_git lists every name in gitLocationVars except the ceiling. Read `repo.go:95-100`:
   14 names, 13 dropped plus the ceiling set. Matches `sync-harness.sh:24-28` one for one.
5. Evidence covers the whole package, not just the named groups: the gate script
   (`.superpowers/sdd/plan/verify-5.sh`) ends with an unfiltered
   `go test -count=1 -race -timeout 40m ./pkg/vaultsync/`, and the report shows its `ok ... 583.211s`.
   Not re-run here, as instructed.

### Strengths
- The diff is exactly the brief: no drive-by edits, no extra helpers.
- runBuild's timeout kills the whole process group (`Setpgid` + `Kill(-pid)`) and bounds the pipe wait,
  so a hung `go build` child cannot outlive the test.
- The A14 harness test reads the names from `gitLocationVars`, so a new name added to the product
  fails the test until the script follows.
- A26 now pins both the target name and the absence of the host-run message, so it can tell the two checks apart.
- The A30 test uses a dirty tree, which is the case that would expose a `.dirty` suffix leaking onto an explicit version.

### Issues
#### Critical (Must Fix)
None.

#### Important (Should Fix)
None.

#### Minor (Nice to Have)
1. `scripts/build-release.sh:16` — A9 has no test that makes `git status` fail; the gate only greps for the line.
   The behaviour is correct (check 1 above), but a later edit that folds the assignment back into the
   `[ -z "$(...)" ]` form with different text would pass every test. A fixture test with a corrupt
   `.git/index` (rev-parse still works, status fails) would pin it. Plan-noted gap, not a defect in this diff.
2. `pkg/vaultsync/harness_test.go:127-140` — the check searches the whole script text for `-u NAME `,
   not the fixture_git function. It proves the names are present somewhere, not that fixture_git is
   the function that drops them, and not that the three calls go through it. Acceptable as a parity
   guard; a behavioural test (run setup with GIT_DIR exported) would be stronger and belongs with the
   A14 follow-up, since `git push` and `make_place` still inherit those variables by owner decision.
3. `pkg/vaultsync/build_release_test.go:206-212` — the host-binary check is skipped without a word when
   the host is not one of the three targets (for example linux/arm64). A `t.Log` would make the skip visible.
4. `pkg/vaultsync/build_release_test.go:11,61-62` — `syscall.SysProcAttr{Setpgid}` and `syscall.Kill` make
   this test file Unix-only. Fine for a package whose tests already drive bash scripts; noted only so
   it is a known limit.

### Assessment
**Task quality:** Approved
**Reasoning:** The diff implements all eight items as worded, stays inside every owner constraint, and the two
named risks (A9 under `set -e`, gitIn callers) were each checked and hold. The four Minor items are coverage
and visibility notes; none makes the batch untrustworthy.
