# Task 5 review (Go + bash reader): build script and its tests

Range 20e41c7..a59069e. Written by the independent reviewer from the brief and the diff only;
the earlier file at this path (implementer-authored) was not read and is overwritten.

Checks I ran myself: `bash -n` on both scripts (ok), `go vet ./...` in tools/vault-engine (exit 0,
no output, Go 1.27.2), two throwaway shell experiments in the session scratch folder under
/bin/bash 3.2.57 (described below), and focused greps of unchanged code for three named risks.
No test suite or harness run. The working tree was clean when I started.

### Spec Compliance
- ✅ Spec compliant. Every listed file has its hunk, and each hunk matches the brief's text:
  - A9, A10: scripts/build-release.sh:17-20 and :47.
  - A14: pkg/vaultsync/testkit_test.go:88-91 (gitIn), pkg/vaultsync/build_release_test.go:51
    (runBuild), scripts/sync-harness.sh:22-33 and :130-132 (fixture_git and its three calls).
    Nothing else in sync-harness.sh changed: the plain `git push` at :133, make_place,
    create-hub.sh and the `go test` time limits are untouched, as the owner decided.
  - A28: build_release_test.go:31, :44-66. A31: :91-94. A26: :162-169. A29: :176-185. A30: :187-206.
  - Tests: harness_test.go:119-136 and :140-157.
  - Scope: five files, all under tools/vault-engine/. Three new commits, each names its items, no amend.
- ⚠️ Cannot verify from the diff: that a timed-out build leaves no `go build` running. The code
  is right by reading (see Strengths), but no run exercises it: the limit is a 15 minute constant.

### Strengths
- A9 really has the effect, not just the grep. Experiment: the HEAD script run under bash 3.2 with a
  stand-in `git` whose `status` exits 128 and a stand-in `go` that reports being reached. HEAD
  script: exit 128, `go` never reached, no bin/ folder created. BASE script, same set-up: went on to
  `go build` with a version that had no `.dirty`. A bare assignment whose value is a command
  substitution takes that command's exit status, and the statement sits in an `if` body (not its
  condition), so `set -e` applies.
- gitIn (named risk: callers that pass their own environment). Checked every caller: only three
  pass an environment (hub_test.go:207, testkit_test.go:128 via pushAs, and one more gitIn), and
  all pass only VAULT_HUB_PLACE. The caller's entries are appended after placeEnv, and os/exec
  keeps the last duplicate, so a caller's value still wins. No test sets a GIT_* variable with
  t.Setenv and then expects a helper to honour it.
- gitIn (named risk: the new ceiling breaks a call made from a subfolder of a repository).
  Checked the folder argument of all helper calls: every one is a repository root, a bare hub, a
  fresh temp folder, or the parent of a clone target (hub_test.go:200). None is a subfolder.
- runBuild: duplicate keys are ordered correctly (inherited value, then the emptied one, then
  `extra`), so VERSION=9.9.9-explicit wins. Setpgid plus Kill(-pid, SIGKILL) reaches bash and
  every compiler and linker it started; Cancel only runs after Start, so cmd.Process is set;
  WaitDelay bounds the wait on the output pipe.
- fixture_git: lists exactly the thirteen names in gitLocationVars (repo.go:95-100) other than the
  ceiling. Experiment under bash 3.2 with GIT_DIR and GIT_WORK_TREE exported at another repository
  and a space in the fixture path: init, add, commit and rev-parse all acted on the fixture; the
  other repository gained no objects. `local dir=$1` does not split on the space. `$root` is
  already absolute and symlink-resolved (`pwd -P`), so the ceiling is a path git accepts. `env -u`
  is supported by macOS and GNU env.
- TestGitIn_IgnoresAnExportedGitDir is a real behaviour test: it fails without the fix (the
  report's failing run shows the right message) and touches only temp folders either way.
- A26's assertion would fail if the in-file check were removed (the host check names a different
  file, or on a host with no matching binary the build would pass).
- A29: cmd/vault-engine/main.go:21 is `var version = "dev"`, so the pinned text is present today.

### Issues
#### Critical (Must Fix)
None.

#### Important (Should Fix)
None.

#### Minor (Nice to Have)
1. scripts/build-release.sh:19 — A9 has no regression test; the only guard is the grep in the
   verify command. A later tidy-up back to the one-line form would pass every test. A small test
   could put a stand-in `git` first on PATH through runBuild's new `extra` parameter and expect a
   failure before any build. Follow-up, not a blocker: the behaviour is confirmed above.
2. pkg/vaultsync/build_release_test.go:58-60 — the kill path is never exercised (the limit is a
   constant). Also, because the script now runs in its own process group, Ctrl-C at the terminal
   and `go test -timeout` no longer reach it: an interrupted test run can leave a build going
   until it ends by itself. Before this change Ctrl-C did reach it. Acceptable for a test helper;
   worth a line in the comment at :44-47.
3. pkg/vaultsync/harness_test.go:128 — the check searches the whole script for `-u NAME `, not
   the body of fixture_git, and only one way round (a name dropped by the script but absent from
   the map is not noticed). It also depends on a space following each name, which the line
   continuations happen to supply. Plan-mandated wording; fine as a tripwire.
4. pkg/vaultsync/build_release_test.go:164 — the test hard-codes `vault-engine-darwin-amd64` as
   the first target, so reordering the target list in the script fails this test for a reason
   unrelated to stamping. Plan-mandated.
5. pkg/vaultsync/build_release_test.go:200-205 — the host binary is run with plain exec.Command
   (no time limit), and the whole check is skipped silently when the host platform is not one of
   the three targets. Trivial program, so low risk; a t.Log on the skipped branch would make it visible.
6. Report evidence: the failing-first run is shown only for the two A14 tests, with lines elided
   by "..."; A26's tightened assertion has no mutation evidence in the report (I judged it by reading).

### Assessment
**Task quality:** Approved
**Reasoning:** The diff is the brief, line for line, stays inside the owner's A14 boundary, and the
two points the plan could only assert (A9 under `set -e`, gitIn's effect on existing callers) hold
up under an experiment and a caller check. Remaining items are coverage and polish.
