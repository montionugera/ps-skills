# Task 2 review (Go): Hub, items A8, A12, A13, A24

Range 630019e..1cc6c45. Read: the brief, the report, the review package diff.
Outside the diff I made four focused checks, each for a named risk (listed under "Checks made").
I did not run the test suite. `go vet ./...` in tools/vault-engine: clean. `gofmt -l pkg/vaultsync cmd`: clean.

### Spec Compliance
- ✅ Spec compliant. Every listed file has its hunk, and each hunk matches the brief.
  - A13: `hubGit(dir, stdin, ...)` sets `cmd.Dir = dir` and has no `cmd.Env` (hub.go:61-75). `batchCheck` and `PreReceive` take `dir`; all six call sites inside `PreReceive` pass it on (hub.go:112, 124, 130, 164, 181, 192). main.go:42 passes `""`, so the production hook runs git exactly as before: same working folder, same inherited environment including git's quarantine variables.
  - A13 tests: `hubRepo` added above `hubLimitsCopy` (hub_test.go:332-348); all seven existing calls updated.
  - A12: the assertion is `code != 1` (hub_test.go, TestPreReceive_AncestorCheckThatCannotRunIsAnEngineError).
  - A8: the `cat-file -t` branch is where the brief puts it (hub.go:117-121); both tests added; the second asserts exit 6 (owner decision met).
  - A24: both tests added, no production change. The Task 1 `errFolderSync` branch in chargeDaily is untouched (hub.go:248-252).
  - Four commits, each names its item. Only files under tools/vault-engine/ changed. No extras.
- ⚠️ The report's off-scope "Finding 1" is wrong, and the brief asked reviewers to look hardest at this case. It says an annotated tag sent as the new tip is refused by the new check as "points it at a tag". It is not: `git merge-base --is-ancestor <old> <tag>` peels a tag that points at a commit and answers normally (I ran this in a scratch repository, git 2.54.0: exit 0), so the new branch at hub.go:119 is never reached. Such a send passes the hook; git itself then refuses the ref update ("trying to write non-commit object ... to branch"), so the hub does not end up with a tag as its tip. Not a defect of this batch (the item names only tree and blob), but the controller should not rely on the report's sentence. See Minor 1.
- ⚠️ Cannot verify from the diff: that no commit was amended, and that the reported test runs are real (I took the RED output and the final `ok` lines as given; the RED output is specific and consistent with the code before the fix).

### Strengths
- The A8 fix is narrow and fails safe. It only relabels when `cat-file -t` succeeds AND says something other than "commit"; an object the hub lacks makes `cat-file -t` fail and stays `engine-error` (pinned by the A12 test, now with exit code 1). A commit whose ancestor check failed for the hub's own reasons also stays `engine-error`. Every path still refuses, so the security decision (accept or refuse) is unchanged; only the label moves.
- Exit-code handling of merge-base is kept as it was: `errors.As` to `*exec.ExitError`, exit 1 means "not an ancestor", anything else is no answer. hubGit still wraps with `%w`, which is what makes that work.
- `hubRepo` uses `t.Setenv` to register the restore and then unsets, the right way to get "unset for this test, restored after" from the testing package; it also makes an accidental `t.Parallel()` panic rather than race.
- Real RED evidence for A8 (both sub-tests and the exit-code test fail before the fix with the expected text).
- The A24 push test covers the midnight boundary (today and one hour ahead, UTC) so it cannot flake at the day change.

### Issues
#### Critical (Must Fix)
None.

#### Important (Should Fix)
None.

#### Minor (Nice to Have)
1. hub.go:112-121. An annotated tag as the new tip is not caught by the hook (see the ⚠️ above). Because the hook passes it and git refuses afterwards, the place's daily allowance is charged for a send that is not taken in (chargeDaily runs at hub.go:203, before git's own ref check). Also a small inconsistency: a tag pointing at a tree does reach the new branch and is labelled "points it at a tag". Out of this item's scope and no way around the door check, so file it as a follow-up: check the type of `newSHA` up front, for every send, instead of only after a failed ancestor check. That would also cover the empty-hub path the owner set aside.
2. hub_test.go:476 and :497. The two A8 tests call `PreReceive(hub, ...)` in-process without `hubRepo`'s clearing of git's location variables, and `hubGit` inherits the environment. Under a runner that exports `GIT_DIR` (the case `hubRepo` exists for) these git calls would go to that repository instead of the temp hub. They are read-only (`merge-base`, `cat-file`), so nothing is damaged; the tests would simply fail. The rest of the test kit (`gitIn`, testkit_test.go:82, `os.Environ()`) has the same pre-existing weakness, so this is no worse than its neighbours. Acceptance 3 is met as written (each passes a temp bare repository as `dir`).
3. hub_test.go:341. `_ = os.Unsetenv(name)` drops an error. Plan-mandated text; it can only fail for an invalid name, and these names are fixed. A `t.Fatal` on error would cost one line.
4. hub_test.go:497. `TestSave_ATreeOrBlobRefusalFromTheHubEndsWithExitSix` only exercises a tree. The blob label is covered by the PreReceive test and the place's mapping does not depend on the kind, so nothing is unpinned; the name promises slightly more than it does.
5. hub.go:119-120. `strings.TrimSpace(typ)` is computed twice. Plan-mandated text; cosmetic.
6. hub_test.go:551-556. Third copy in this file of the six-line "make a place and point it at the hub" setup (also at :418-423 and in `seededClone`). Plan-mandated; a helper would be a refactor outside this task, so leave it and note it.

### Checks made outside the diff (one per named risk)
- Risk: a tag as the new tip (the brief's own request). Checked in a scratch repository under the session scratchpad, not in the worktree: merge-base on a tag of a commit exits 0; `update-ref refs/heads/x <tag>` is refused by git; a tag of a tree makes merge-base exit 128 and `cat-file -t` say "tag".
- Risk: new tests reaching a real repository through the environment. Read testkit_test.go:77-134 (`gitIn`, `mustGit`, `newHub`, `pushAs`, `seededClone`): helpers inherit `os.Environ()`; all repositories are under `t.TempDir()`.
- Risk: the A24 unit test assuming the temp-file name. Read chargeDaily (hub.go:214-256): the "writing usage file" wrap and the early returns match what the test asserts; the usage folder is `<limits folder>/../vault-usage`, inside the temp hub.
- Risk: the new A24 push test duplicating the existing one. Read hub_test.go:413-434: the old test blocks the ledger FOLDER (MkdirAll fails), the new one blocks the temp FILE of the write, and additionally asserts no usage file appears. Different failure point; not a duplicate.

### Assessment
**Task quality:** Approved
**Reasoning:** The change matches the brief line for line, keeps the production hook's git invocation and environment identical, and the one behaviour change (A8) only relabels refusals that were already refusals, with a failing-first test and the exit-6 assertion the owner asked for. The findings are all Minor; the one worth carrying forward is that the report's claim about tags is false and tags are stopped by git, not by the hook.
