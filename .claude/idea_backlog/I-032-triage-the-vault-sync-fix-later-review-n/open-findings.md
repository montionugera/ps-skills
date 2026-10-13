# Open findings, one list — vault sync fix-later notes (checked against main on 2026-10-13)

The 76 rows marked OPEN in `triage.md` (35 in Part 1, 41 in Part 2) are the same
32 distinct findings counted more than once. This is the list to plan from.

- Sizes: S = comment or text only (5), M = small code change (17), L = behaviour change or new test (10).
- Paths are relative to `tools/vault-engine/`; `pv/` = `pkg/vaultsync/`.
- "source rows" point back to `triage.md`: `P1-<n>` is Part 1 row n, `t...` ids are Part 2 rows.
- How it was made: one agent merged the rows; a script confirmed all 76 open rows appear
  exactly once; an independent reviewer checked every merged group (no wrong merges, 10
  items had their text, place or size corrected, already applied here).
- Not included: the nine findings a review ruled "not a defect" (see `triage.md`).

## Sync engine (3 items)

| item | what to change (max 25 words, plain English) | where (file:line now) | size | source rows |
|---|---|---|---|---|
| A1 | Make the confirm retry loop leave when the daemon is stopped instead of sleeping 500 ms; also reword README "ends at once" to "within a couple of seconds". | pv/syncer.go:344-346; README.md:61 | M | P1-2, P1-20, t3-code-1, t3-go-3 |
| A2 | Add one sentence to the Repo type and its stop field saying it is not safe for use from more than one goroutine. | pv/repo.go:34-60 | S | P1-26, t3-go-4 |
| A3 | Add a comment on errorOutcome saying the answer depends on the order of the cases. | pv/syncer.go:54-68 | S | P1-31, t4-go-3 |

## Recovery and undo (4 items)

| item | what to change (max 25 words, plain English) | where (file:line now) | size | source rows |
|---|---|---|---|---|
| A4 | Make Undo refuse when the marker file is missing (for example after a successful Recover). First check whether any existing test calls Undo with no marker on disk. Do before A16. | pv/recover.go:197-215 | L | P1-7, P1-18, t2-rr2-1 |
| A5 | When a stop kills the hash comparison, do not quarantine the leftover file and write a REPORT line; treat an interrupted compare as unknown. | pv/recover.go:638-648 | L | P1-23, t3-code-6 |
| A6 | Add context to the bare errors returned by writeMarker and the undo marker write, for example "record undo start". | pv/recover.go:113-122,328-329 | M | P1-13, t2-go-2 |
| A7 | In writeFileAtomic, fsync the parent folder after the rename, and add a comment that callers must hold a lock because the .tmp name is fixed. | pv/recover.go:514-538 | M | P1-14, t2-go-4, t4-code-1, t4-go-4 |

## Hub and lock (1 items)

| item | what to change (max 25 words, plain English) | where (file:line now) | size | source rows |
|---|---|---|---|---|
| A8 | Report a pushed tree or blob (not a commit) as "type not allowed", not as engine-error, when the ancestor check cannot run. | pv/hub.go:28,112-118 | L | P1-9, t1-code-1 |

## Build and release script (2 items)

| item | what to change (max 25 words, plain English) | where (file:line now) | size | source rows |
|---|---|---|---|---|
| A9 | Assign the "git status" output to a variable first so a failing git status stops the script, then test the variable for the dirty suffix. | scripts/build-release.sh:16 | M | P1-33, t5-code-2 |
| A10 | Change the per-target message to "built $name" so it does not name bin/release/ while the file is still in staging. | scripts/build-release.sh:49 | S | P1-34, t5-code-3 |

## Agent rules and README text (1 items)

| item | what to change (max 25 words, plain English) | where (file:line now) | size | source rows |
|---|---|---|---|---|
| A11 | Soften "Your input is fine." in case b of rule 5 so it does not overstate. | templates/vault-rules/AGENTS.section.md:50 | S | t5-code-1 |

## Tests (21 items)

| item | what to change (max 25 words, plain English) | where (file:line now) | size | source rows |
|---|---|---|---|---|
| A12 | Make the hub test also assert the exit code is 1, not just "not 0 or not prefixed". | pv/hub_test.go:372-375 | M | P1-10, t1-go-1 |
| A13 | Stop the hub test running git in the source checkout with inherited GIT_DIR: give hubGit a working-folder argument. Do not strip hubGit's environment; the hook needs it. | pv/hub_test.go:365-381; pv/hub.go:32 | M | P1-11, t1-go-2 |
| A14 | Filter the names in gitLocationVars out of the environment used by gitIn, runBuild and fixture_git, and set GIT_CEILING_DIRECTORIES to the parent folder. | pv/testkit_test.go:82; pv/build_release_test.go:42; scripts/sync-harness.sh:18-20 | M | P1-8, P1-37, t5-go-1 |
| A15 | Add a test for the branch where the undo marker cannot be written (UndoStarted reset, nothing changed). The dropped ReadFile error from t2-code-3 is fixed under A17. | pv/recover.go:322-330 (code); test goes in pv/recover_test.go near :840 | L | P1-12, t2-code-3, t2-go-7 |
| A16 | Add tests for the foreign-marker refusal and the missing-marker path in Undo. | pv/recover_test.go (code at recover.go:203-209) | L | P1-19, t2-rr2-2 |
| A17 | Check and fail on the ReadFile errors that recover tests drop with "_". | pv/recover_test.go:53,71,161,179,840,874 | M | P1-15, t2-go-5 |
| A18 | In undoAfterFailedPass, assert the first pass failed after the folder was reset (Head equals the base). | pv/recover_test.go:850-853 | M | P1-16, t2-go-6 |
| A19 | Give the pid-file poller goroutine an exit (stop channel or deadline) and check the Atoi error. | pv/daemon_test.go:577-584,592 | M | P1-21, P1-22, t3-code-4, t3-code-5, t3-go-6 |
| A20 | Add a test that cancels the context without a signal during a merge or commit, then checks the next pass recovers. | pv/daemon_test.go:399,482,562 | L | P1-24, t3-code-7 |
| A21 | Add two run() tests: stop cancelled during a slow command gives ErrStopped; a command that ended well keeps Err nil with stop already cancelled. | pv/repo.go:186-189 (code); pv/lock_test.go:71 | L | P1-25, t3-go-1 |
| A22 | Replace the 200 ms settle sleep with a real signal that the test is waiting on the lock. | pv/daemon_test.go:545 | M | P1-27, t3-go-5 |
| A23 | Fix the comment so it only claims what the test proves (lock can be taken again), not that no descriptor is left open. | pv/lock_test.go:77 | S | P1-28, t3-go-7 |
| A24 | Add a hub test where writing the usage file fails (for example a day.json.tmp folder) and nothing is charged. | pv/hub_test.go:245-275,347-360 | L | P1-29, t4-code-2, t4-go-5 |
| A25 | In the empty-hub test, also assert the positive text "has no refs/heads/", not only that "<nil>" is absent. | pv/repo_test.go:437 | M | P1-30, t4-code-3, t4-go-1 |
| A26 | Make build test step 4 assert the binary name so it can tell the in-file check from the host-run check. | pv/build_release_test.go:141-149 | M | P1-35, t5-code-5, t5-go-6 |
| A27 | Make the test helper exit non-zero instead of printing "started" when the pid file never appears; also check the dropped Atoi error in the parent test. | pv/testkit_test.go:54-59; pv/repo_test.go:164 | M | P1-36, t5-code-6, t5-go-9 |
| A28 | Add a timeout (CommandContext or WaitDelay) to runBuild. | pv/build_release_test.go:39-48 | M | P1-38, t5-go-2 |
| A29 | Add a test that the real cmd/vault-engine/main.go still has "var version"; note the fixture ignores its arguments, so the script's "version" argument is unchecked. | pv/build_release_test.go:26-27 | L | P1-39, t5-go-3 |
| A30 | Add a test case that sets an explicit VERSION and checks it is used as given, without a .dirty suffix. | pv/build_release_test.go:43 | L | P1-40, t5-go-4 |
| A31 | Check and fail on the dropped ReadFile error when reading SHA256SUMS. | pv/build_release_test.go:72-73 | M | P1-41, t5-go-7 |
| A32 | Kill the holder process before Fatalf when the "started" line is missing. | pv/repo_test.go:156-158 | M | P1-42 |

TOTALS items=32 source_rows=76
