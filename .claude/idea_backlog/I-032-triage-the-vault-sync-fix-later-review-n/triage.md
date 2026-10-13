# Triage of the fix-later review notes — checked against main on 2026-10-13

Every finding in `research.md` Parts 1 and 2 was compared with the code on `main`
(commit 74dd026, code under `tools/vault-engine/`). Read-only: no tests or builds were run.

## How this was produced

1. Two agents marked the findings, one per part.
2. An independent reviewer re-checked every FIXED mark, the judgement-call NA marks, the
   four unsure marks, and a sample of 12 OPEN marks. It changed 12 marks; those rows are
   tagged in the tables and explained in "Reviewer corrections" below.

## Marks

- FIXED: the code now does what the finding asked.
- OPEN: the issue is still in the code.
- NA: the code or text is gone, or a review ruled the finding "not a defect / no change wanted".

Policy used for NA: where the final whole-branch review ruled a finding "not a defect",
it is NA even though the code is unchanged. Nine Part 2 rows are NA only for that reason
(t2-code-2, t2-go-3, t2-rr1-2, t2-rr2-4, t3-go-2, t3-go-8, t4-go-2, t5-code-4, t5-go-5).
To reopen them, flip those nine and their Part 1 twins (46, 47, 49, 50, 51, 52, 53) to OPEN.

## Counts

| | checked | FIXED | OPEN | NA |
|---|---|---|---|---|
| Part 1, final code review list | 59 | 8 | 35 | 16 |
| Part 2, per-task Minor findings | 63 | 6 | 41 | 16 |

The two parts overlap: many Part 1 entries were drawn from Part 2. The parts have NOT been
merged into one de-duplicated list, so the number of distinct open findings is not known;
it is at most 76 and likely well below.

Not covered: the unnumbered Part 1 remark that `README.md:61` says the stop is "at once".

## Part 1 table


| # | section | mark | file:line now | evidence (max 25 words) | finding (max 15 words) |
|---|---|---|---|---|---|
| 1 | 1A | FIXED | scripts/build-release.sh:52 | `said="$(VAULT_ROOT="$STAGE" "$STAGE/$host" version)"` | Built engine run without VAULT_ROOT |
| 2 | 1A | OPEN | pv/syncer.go:344-346 | Confirm loop still `time.Sleep(500ms)` on Fetch error, no ErrStopped check | Confirm loop sleeps after daemon stop |
| 3 | 1A | FIXED | pv/recover.go:31-33 | Comment now says set "by Undo, by Recover and by a save that fails early" | Stale UndoStarted comment |
| 4 | 1A | FIXED | templates/vault-rules/AGENTS.section.md:47 | Case a now lists "a note or value the engine says is not valid" | Rule 5 case a needs example |
| 5 | 1B | FIXED | templates/vault-rules/AGENTS.section.md:47 | Same line 47 adds the "engine says ... not valid" example | Rule 5 case a omits invalid-note case |
| 6 | 1B | NA | pv/harness_test.go:98 | Notes class as not a defect; HOME= still set there; the optional comment was not added | HOME= in harness test, optional comment |
| 7 | 1B | OPEN | pv/recover.go:197-215 | Undo's comment: missing marker file means "the caller's marker decides"; no refusal | Undo after successful Recover not refused |
| 8 | 1B | OPEN | pv/testkit_test.go:82 | gitIn uses `append(os.Environ(), env...)`, GIT_* passed through; build_release_test.go:42 same | Test git helpers pass GIT_* through |
| 9 | 1C | OPEN | pv/hub.go:28,117-118 | hubFault = "engine-error"; rev-list/diff-tree failure still refused as engine-error | Non-commit object reads engine-error |
| 10 | 1C | OPEN | pv/hub_test.go:372 | Asserts `code == 0 \|\| !HasPrefix(...)`; still no `code != 1` check | Test asserts code==0 only |
| 11 | 1C | OPEN | pv/hub_test.go:365-375 | [mark changed by reviewer; see the corrections table for the reason, the text that follows is superseded] Test rewritten: uses fake SHAs and PreReceive, no git run in source checkout | Hub test ran git in source checkout |
| 12 | 1C | OPEN | pv/recover.go:322-330 | Branch resetting UndoStarted on write failure exists; no test mentions it (recover_test.go) | Marker-unwritable branch untested |
| 13 | 1C | OPEN | pv/recover.go:113-122,328-329 | writeMarker and undo return `err` bare, no context added | Errors returned bare |
| 14 | 1C | OPEN | pv/recover.go:516-537 | writeFileAtomic fixed ".tmp" name, no parent-dir fsync, no lock comment | No parent fsync; .tmp needs lock comment |
| 15 | 1C | OPEN | pv/recover_test.go:53,71,161,179 | Many `original, _ := os.ReadFile(...)` and `now, _ :=` still drop errors | Dropped ReadFile errors in tests |
| 16 | 1C | OPEN | pv/recover_test.go:850-853 | undoAfterFailedPass only checks first pass returned an error, not that it failed after reset | Premise "failed after the reset" not asserted |
| 17 | 1C | FIXED | pv/recover.go:31-33 | Same as #3: comment updated to include Recover | Stale field comment |
| 18 | 1C | OPEN | pv/recover.go:197-215 | Same as #7: Undo with held marker, no marker on disk, proceeds | Undo with held marker after Recover |
| 19 | 1C | OPEN | pv/recover.go:203-209 | Foreign-marker refusal code now exists; grep of tests for it finds none; missing-marker path untested | Foreign/missing-marker paths untested |
| 20 | 1C | OPEN | pv/syncer.go:344-346 | Same as #2 | Pause after a stop |
| 21 | 1C | OPEN | pv/daemon_test.go:577-584 | pid poller `for { ... time.Sleep }` has no exit besides file appearing | Pid-file poller goroutine has no way out |
| 22 | 1C | OPEN | pv/daemon_test.go:592 | `pid, _ := strconv.Atoi(...)` still drops error | Dropped Atoi error |
| 23 | 1C | OPEN | pv/recover.go:638-648 | UNSURE: identical leftover now removed, but a killed hash-object (err1/err2 set) falls to setAside quarantine | Stop can quarantine identical leftover |
| 24 | 1C | OPEN | pv/daemon_test.go:399,482,562 | UNSURE: stop tests cover git/push/lock; none cancels without signal in merge/commit then checks next pass | No non-signal cancel test in merge/commit |
| 25 | 1C | OPEN | pv/repo.go:186-187 | Mapping to ErrStopped exists; only lock_test.go:71 asserts ErrStopped, none for run() | ErrStopped mapping has no own test |
| 26 | 1C | OPEN | pv/repo.go:36-60 | Repo type doc and `stop context.Context` field say nothing about single-goroutine use | Context in struct needs one sentence |
| 27 | 1C | OPEN | pv/daemon_test.go:545 | `time.Sleep(200 * time.Millisecond) // let it settle into the wait` unchanged | 200 ms settle can pass via wrong path |
| 28 | 1C | OPEN | pv/lock_test.go:74 | UNSURE: comment claims no descriptor left open; test only re-acquires lock, line numbers moved | Comment claims more than test proves |
| 29 | 1C | OPEN | pv/hub_test.go:245-275 | chargeDaily tests cover unreadable/corrupt ledger only; no write-failure case | Usage-file write failure untested |
| 30 | 1C | OPEN | pv/repo_test.go:437 | Still only `strings.Contains(err.Error(), "<nil>")`; no "has no refs/heads/" assertion | Empty-hub check proves only `<nil>` absent |
| 31 | 1C | OPEN | pv/syncer.go:54-68 | errorOutcome switch has no comment about case order | errorOutcome depends on case order |
| 32 | 1C | FIXED | templates/vault-rules/AGENTS.section.md:47 | Same as #5 | Rule 5 wording (item a) |
| 33 | 1C | OPEN | scripts/build-release.sh:16 | Still `[ -z "$(git status --porcelain -- .)" ] \|\| VERSION=...dirty`; failing status reads clean | Failing git status reads as clean tree |
| 34 | 1C | OPEN | scripts/build-release.sh:49 | `echo "built $OUT/$name"` runs in the loop; files still in staging until mv at line ~67 | Prints built path while file in staging |
| 35 | 1C | OPEN | pv/build_release_test.go:141-149 | Step 4 asserts only generic "does not carry version"; no binary name asserted | Step 4 cannot tell grep check from host check |
| 36 | 1C | OPEN | pv/testkit_test.go:59 | `fmt.Println("started")` printed after wait loop even if pid file never came | Helper prints started without pid file |
| 37 | 1C | OPEN | pv/testkit_test.go:82; build_release_test.go:42 | Same as #8 (item d) | GIT_* pass-through (item d) |
| 38 | 1C | OPEN | pv/build_release_test.go:39-48 | runBuild uses exec.Command with no context or timeout | No time limit on the build |
| 39 | 1C | OPEN | pv/build_release_test.go:27 | Fixture writes own main.go `var version = "dev"`; real cmd/vault-engine/main.go:21 var not pinned | Real `var version` not pinned by test |
| 40 | 1C | OPEN | pv/build_release_test.go:43 | runBuild blanks VERSION; no test case sets an explicit VERSION | No test for explicit VERSION |
| 41 | 1C | OPEN | pv/build_release_test.go:73 | `sums, _ := os.ReadFile(...)` still drops error | Dropped ReadFile error |
| 42 | 1C | OPEN | pv/repo_test.go:156-158 | Fatalf on missing "started" line with no holder.Process.Kill() | Test fails without killing holder |
| 43 | 1D | NA | pv/hub_test.go | Notes: not a defect; claim holds, engine-error covered by function-level PreReceive tests | Engine-error path tested at function level |
| 44 | 1D | NA | README.md | Notes: not a defect (plan's text); not checked in code | Nested parentheses in README |
| 45 | 1D | NA | pv/syncer.go:312 | `line, _, _ := strings.Cut(..., "\n")` still cuts at first line; claim holds | Refusal may span lines; record cuts first |
| 46 | 1D | NA | pv/recover.go:197-224 | Notes: chosen safe direction; second Undo with UndoStarted sweeps and quarantines | Second Undo quarantines provable files |
| 47 | 1D | NA | pv/repo.go:34 | Notes: theoretical; unsafeActorChars regex still handles actor names | Actor with invalid UTF-8 |
| 48 | 1D | NA | pv/lock.go:32-33 | Comment says "when ctx is cancelled while waiting"; claim holds | Lock comment already says while waiting |
| 49 | 1D | NA | pv/repo.go:185-187 | Mapping now only when `err != nil && stop.Err() != nil`; claim moot or safer | Cancel after git exits 0 reads ErrStopped |
| 50 | 1D | NA | pv/syncer.go:54-68 | Confirmed: errorOutcome has no ErrStopped case | errorOutcome lacks ErrStopped case |
| 51 | 1D | NA | pv/repo.go:105-120 | Confirmed: inner `err` shadow in placeEnv with symlink fallback | Shadowed err in placeEnv |
| 52 | 1D | NA | scripts/build-release.sh:46 | `grep -a -q -F -e "$VERSION"` still used; claim holds | Short VERSION weakens grep check |
| 53 | 1D | NA | scripts/build-release.sh:64-69 | Swap loop unchanged, no hook to test it | Swap order not tested |
| 54 | 1D | NA | pv/build_release_test.go | Confirmed: no testing.Short skip in the file | Build test not skipped under -short |
| 55 | 1D | NA | pv/recover.go:270,547 | `os.IsNotExist` idiom still used; claim holds | os.IsNotExist idiom |
| 56 | 1D | NA | pv/scenario_test.go:535 | `fmt.Printf("KILLS ...` still present; harness greps it (sync-harness.sh:142) | fmt.Printf for KILLS line |
| 57 | 1D | NA | pv/harness_test.go:98 | Same as #6; HOME= still set, claim holds | Item b |
| 58 | 1E | FIXED | pv/recover.go:326-329 | [mark changed by reviewer; see the corrections table for the reason, the text that follows is superseded] `m.UndoStarted = false` after failed writeMarker; closed claim holds | In-memory flag left set on failed write |
| 59 | 1E | FIXED | pv/repo_test.go:425-437 | [mark changed by reviewer; see the corrections table for the reason, the text that follows is superseded] Tests assert ErrNoConnection wraps the cause for Fetch/RemoteHead; closed claim holds | Fetch/RemoteHead hid the cause |

Row 33 line 16 and 34 line 49 refer to scripts/build-release.sh. Notes: row 44 not checked in code (README plan text).

TOTALS fixed=8 open=35 na=16

## Part 2 table


| id | mark | file:line now | evidence (max 25 words) | finding (max 15 words) |
|---|---|---|---|---|
| t1-code-1 | OPEN | pkg/vaultsync/hub.go:112 | Non-exit-1 ancestor failure still returns refuse(hubFault, "cannot check that ... only moves forward"); reviewer deferred to receive-path hardening plan | Tree/blob tip labelled engine-error not type-not-allowed |
| t1-code-2 | NA | pkg/vaultsync/hub_test.go:370 | Reviewer wrote "Acceptable"; function-level test TestPreReceive_AncestorCheckThatCannotRunIsAnEngineError still the coverage | engine-error path tested only at function level |
| t1-code-3 | NA | README.md:81 | Reviewer: "Plan-mandated wording; reads correctly"; nested parentheses still present, no change wanted | README nested parentheses in long sentence |
| t1-go-1 | OPEN | pkg/vaultsync/hub_test.go:375 | Still `if code == 0 \|\| !strings.HasPrefix(...)`; no `code != 1` pin | Test only proves "not accepted", not exit code 1 |
| t1-go-2 | OPEN | pkg/vaultsync/hub.go:32 | hubGit(stdin, args...) still has no dir parameter and keeps git's environment (repo.go:94 says hub keeps it) | Test runs git in cwd, inherits GIT_DIR |
| t1-go-3 | NA | pkg/vaultsync/hub.go:112 | Reviewer: consistent with other hubFault refusals, "worth one look" only; hubGit now TrimSpaces stderr (hub.go:38) | %v of hubGit error can span several lines |
| t1-go-4 | NA | README.md:81 | Reviewer: "Plan-mandated text"; wording unchanged, no change wanted | README nested parentheses read awkwardly |
| t2-code-1 | FIXED | pkg/vaultsync/recover.go:326-328 | `m.UndoStarted = true; if err := r.writeMarker(m); err != nil { m.UndoStarted = false` | UndoStarted left true in memory when write fails |
| t2-code-2 | NA | pkg/vaultsync/recover.go:214-215 | [mark changed by reviewer; see the corrections table for the reason, the text that follows is superseded] Second-Undo path still `return r.undo(m, nil, true, rebuild)`, no list derived from commit | Second Undo passes nil list, quarantines instead of removing |
| t2-code-3 | OPEN | pkg/vaultsync/recover_test.go:840 | No test for unwritable marker (grep found none); `original, _ := os.ReadFile(note)` still drops error | Fail-closed marker-write branch untested, ReadFile error dropped |
| t2-go-1 | FIXED | pkg/vaultsync/recover.go:326-328 | Flag reset to false on writeMarker error: `m.UndoStarted = false` before `return err` | In-memory UndoStarted disagrees with disk after failed write |
| t2-go-2 | OPEN | pkg/vaultsync/recover.go:329 | `return err` still bare; writeMarker (recover.go:113-121) also returns bare errors, no "record undo start" context | Marker-write errors returned bare, no context |
| t2-go-3 | NA | pkg/vaultsync/recover.go:214-215 | [mark changed by reviewer; see the corrections table for the reason, the text that follows is superseded] Same as t2-code-2: `r.undo(m, nil, true, rebuild)` for flagged marker | Second Undo does not rebuild proven list like Recover |
| t2-go-4 | OPEN | pkg/vaultsync/recover.go:516-538 | writeFileAtomic does Sync, Close, Rename; no parent directory fsync | No parent-dir fsync after rename |
| t2-go-5 | OPEN | pkg/vaultsync/recover_test.go:840,874 | `original, _ := os.ReadFile(note)` and `now, _ := os.ReadFile(note)` still discard errors | os.ReadFile errors discarded in test |
| t2-go-6 | OPEN | pkg/vaultsync/recover_test.go:~840-860 | undoAfterFailedPass kills ls-tree via gate but never asserts Head()==m.Base after first pass | Test premise "folder already moved back" not asserted |
| t2-go-7 | OPEN | pkg/vaultsync/recover_test.go | grep for marker-write-failure test (unwritable marker, UndoStarted) finds nothing | No test for "record cannot be written" branch |
| t3-code-1 | OPEN | pkg/vaultsync/syncer.go:344-346 | Confirm loop still `if r.Fetch() != nil { time.Sleep(500 * time.Millisecond); continue }`, no stop check | Confirm loop sleeps without checking stop context |
| t3-code-2 | FIXED | pkg/vaultsync/repo.go:~228,~237 | Fetch/RemoteHead now `fmt.Errorf("%w: fetch: %w: ...", ErrNoConnection, res.Err, ...)` so errors.Is(err, ErrStopped) works | Fetch/RemoteHead %v hides ErrStopped from errors.Is |
| t3-code-3 | FIXED | pkg/vaultsync/lock.go:32-33 | Comment now "when ctx is cancelled while waiting, it returns ErrStopped at once" | Lock comment overstates cancel behaviour |
| t3-code-4 | OPEN | pkg/vaultsync/daemon_test.go:577-584 | Pid-file poller `for { ... time.Sleep(10ms) }` still has no stop channel | Pid-file polling goroutine has no way out |
| t3-code-5 | OPEN | pkg/vaultsync/daemon_test.go:592 | `pid, _ := strconv.Atoi(strings.TrimSpace(string(raw)))` still drops error | Atoi error dropped, pid 0 misleads |
| t3-code-6 | OPEN | pkg/vaultsync/recover.go:640-648 | `if err1 == nil && err2 == nil && mine == theirs {...}` else setAside; stopped hash-object still counts as different | Stopped comparison quarantines file with REPORT line |
| t3-code-7 | OPEN | pkg/vaultsync/daemon_test.go | UNSURE: daemon tests listed (StopSignalDuringGit/Push, CancelCutsRunningGit, CancelEndsLockWait) show none cancelling during merge/commit | No test cancels during folder-changing command then checks recovery |
| t3-go-1 | OPEN | pkg/vaultsync/repo.go:188-189 | `case err != nil && stop.Err() != nil: err = ErrStopped` exists; no test sets r.stop and asserts ErrStopped from run | ErrStopped mapping in run has no test |
| t3-go-2 | NA | pkg/vaultsync/repo.go:161 | [mark changed by reviewer; see the corrections table for the reason, the text that follows is superseded] `cmd.Cancel = func() error { return syscall.Kill(-pid, SIGKILL) }`; no ESRCH to ErrProcessDone, no ProcessState check | Cancel race turns finished push into ErrStopped |
| t3-go-3 | OPEN | pkg/vaultsync/syncer.go:344-346 | Same loop as t3-code-1: uncut 500ms sleeps after failed Fetch | Stop cannot cut confirm retry sleeps; README claim loose |
| t3-go-4 | OPEN | pkg/vaultsync/repo.go:34-36 | Repo doc comment says only "git side of one place"; no "not safe for more than one goroutine" sentence | stop context field unsynchronised; document single-goroutine use |
| t3-go-5 | OPEN | pkg/vaultsync/daemon_test.go:545 | `time.Sleep(200 * time.Millisecond) // let it settle into the wait` still the only guarantee | Settle sleep may let test skip the lock wait |
| t3-go-6 | OPEN | pkg/vaultsync/daemon_test.go:577,592 | Poller goroutine without exit and ignored Atoi error both still present | Poller leak and ignored Atoi error |
| t3-go-7 | OPEN | pkg/vaultsync/lock_test.go:~75 | Comment still "must not have left the lock taken or a descriptor open on it" | Comment claims descriptor-leak proof the test cannot give |
| t3-go-8 | NA | pkg/vaultsync/syncer.go:54-67 | [mark changed by reviewer; see the corrections table for the reason, the text that follows is superseded] errorOutcome cases: violation, ErrConflict, ErrNoConnection, lock timeout, default; no ErrStopped case | ErrStopped from Save lock wait prints REFUSED engine-error |
| t4-code-1 | OPEN | pkg/vaultsync/recover.go:516-538 | No parent directory fsync in writeFileAtomic; reviewer asked only for a backlog line | Parent dir not fsynced after rename |
| t4-code-2 | OPEN | pkg/vaultsync/hub_test.go:347-360 | Hub test makes vault-usage a file, so failure is at MkdirAll (hub.go:207), not the writeFileAtomic path at hub.go:237 | No test drives usage write failure via shared helper |
| t4-code-3 | OPEN | pkg/vaultsync/repo_test.go:437 | Still `strings.Contains(err.Error(), "<nil>")` negative check; no `has no refs/heads/` assertion | Empty-hub test checks only that "<nil>" is absent |
| t4-go-1 | OPEN | pkg/vaultsync/repo_test.go:437 | Same negative-only assertion, positive text not asserted | Empty-hub assertion should check positive text |
| t4-go-2 | NA | pkg/vaultsync/repo.go:115 | [mark changed by reviewer; see the corrections table for the reason, the text that follows is superseded] placeEnv still has shadowed `err` in `if resolved, err := filepath.EvalSymlinks(abs)` with no comment that fallback is deliberate | Shadowed err and silent fallback uncommented |
| t4-go-3 | OPEN | pkg/vaultsync/syncer.go:54 | errorOutcome has no comment about case order dependence | Add comment: errorOutcome answer depends on case order |
| t4-go-4 | OPEN | pkg/vaultsync/recover.go:514-515 | Comment mentions fsync and rename only; no statement that callers must hold a lock (fixed .tmp name) | writeFileAtomic needs lock-requirement comment |
| t4-go-5 | OPEN | pkg/vaultsync/hub_test.go | No test with a `<day>.json.tmp` folder; only recover_test.go:891 unit test covers writeFileAtomic | No hub-level test for write failure charging nothing |
| t5-code-1 | OPEN | templates/vault-rules/AGENTS.section.md:43-52 | Case a now has "a note or value the engine says is not valid" (fixed), but case b still says "Your input is fine." | Partly fixed: wording in b still not softened |
| t5-code-2 | OPEN | scripts/build-release.sh:16 | Still `[ -z "$(git status --porcelain -- .)" ] \|\| VERSION=...` | Failing git status read as clean tree |
| t5-code-3 | OPEN | scripts/build-release.sh:49 | Still `echo "built $OUT/$name"` while file is in staging | Message names bin/release before the file arrives |
| t5-code-4 | NA | scripts/build-release.sh:44-47 | [mark changed by reviewer; see the corrections table for the reason, the text that follows is superseded] Comment says only "stamp is looked for in the file itself"; no note about short explicit VERSION | Short VERSION makes grep check meaningless; add comment |
| t5-code-5 | OPEN | pkg/vaultsync/build_release_test.go:144 | Still `strings.Contains(out, "does not carry version")`, binary name not asserted | Test cannot tell in-file check from host-run check |
| t5-code-6 | OPEN | pkg/vaultsync/testkit_test.go:54-59 | Loop `break`s or falls out on deadline, then `fmt.Println("started")` unconditionally | Helper prints started even after 30 s timeout |
| t5-go-1 | OPEN | pkg/vaultsync/testkit_test.go:82 | `cmd.Env = append(os.Environ(), env...)` unfiltered; runBuild also uses os.Environ() (build_release_test.go:42) | gitIn/runBuild inherit GIT_DIR from environment |
| t5-go-2 | OPEN | pkg/vaultsync/build_release_test.go:41 | `exec.Command("bash", ...)` no CommandContext or WaitDelay | runBuild has no time limit |
| t5-go-3 | OPEN | pkg/vaultsync/build_release_test.go:26-27 | Fixture writes its own main.go; no test greps real cmd/vault-engine/main.go for `var version` | Test proves script not script plus real engine |
| t5-go-4 | OPEN | pkg/vaultsync/build_release_test.go:43 | runBuild always empties VERSION; no test case for explicit VERSION used as given | No test for explicit VERSION without .dirty |
| t5-go-5 | NA | pkg/vaultsync/build_release_test.go:87 | [mark changed by reviewer; see the corrections table for the reason, the text that follows is superseded] Only one test, TestBuildRelease_StampsChecksAndKeepsTheOldSetOnFailure; no swap-order test or comment | Swap order (old sums removed first) untested |
| t5-go-6 | OPEN | pkg/vaultsync/build_release_test.go:144 | Same as t5-code-5: generic "does not carry version" match | Step 4 cannot tell in-file check from host check |
| t5-go-7 | OPEN | pkg/vaultsync/build_release_test.go:72 | `sums, _ := os.ReadFile(filepath.Join(rel, "SHA256SUMS"))` still drops error | ReadFile error dropped |
| t5-go-8 | NA | pkg/vaultsync/build_release_test.go:87 | Reviewer: "Fine as is; consider testing.Short()"; no Short skip present, no change required | Build test not skipped under -short |
| t5-go-9 | OPEN | pkg/vaultsync/testkit_test.go:54-59 | Same as t5-code-6: helper still prints started after timeout; Atoi at daemon_test.go:592 also ignored | Helper should exit non-zero on timeout |
| t5-go-10 | NA | pkg/vaultsync/scenario_test.go:341,575 | Reviewer: matches file style, "leave unless the file is swept"; os.IsNotExist still used | os.IsNotExist vs errors.Is(fs.ErrNotExist) |
| t5-go-11 | NA | pkg/vaultsync/scenario_test.go:535 | Reviewer: deliberate and correct, "noted only so nobody fixes it"; fmt.Printf KILLS line unchanged | fmt.Printf from test instead of t.Logf |
| t2-rr1-1 | FIXED | pkg/vaultsync/recover.go:31-34 | Field comment now "written to the marker before the folder is reset, by Undo, by Recover and by a save that fails early" | UndoStarted field comment stale after Recover sets it |
| t2-rr1-2 | NA | pkg/vaultsync/recover.go:324-328 | [mark changed by reviewer; see the corrections table for the reason, the text that follows is superseded] Flag still written before reset; a failing reset leaves it set while the commit exists; reviewer called it safe | Undo with failed reset quarantines more than needed |
| t2-rr2-1 | OPEN | pkg/vaultsync/recover.go:198-214 | Missing marker file still means "caller's marker decides" (comment line 199-200), list trusted; no refuse-when-missing | Stale-marker case: Recover removes marker, then Undo trusts list |
| t2-rr2-2 | OPEN | pkg/vaultsync/recover_test.go | grep for foreign-marker refusal text "not the one given" and missing-marker tests finds nothing | Foreign-marker refusal and missing-marker path untested |
| t2-rr2-3 | FIXED | pkg/vaultsync/recover.go:31-34 | Same fix as t2-rr1-1: comment now lists Undo, Recover and early-failing save | UndoStarted field comment still says Undo only |
| t2-rr2-4 | NA | pkg/vaultsync/recover.go:113-121 | [mark changed by reviewer; see the corrections table for the reason, the text that follows is superseded] writeMarker uses plain json.MarshalIndent; no UTF-8 sanitising of Actor; reviewer: theoretical, fails closed | Invalid UTF-8 Actor makes every Undo refuse |

TOTALS fixed=6 open=41 na=16

## Reviewer corrections


Paths relative to tools/vault-engine/ in the _release checkout; pv/ = pkg/vaultsync/. Read-only check by grep and small reads; no tests or builds were run.

| row id | mark given | correct mark | file:line | reason (max 30 words) |
|---|---|---|---|---|
| P1-11 | NA | OPEN | pv/hub_test.go:370-381; pv/hub.go:32-33 | Test was not rewritten. It calls PreReceive, which runs hubGit merge-base in the test's working folder (source checkout) with inherited GIT_DIR. Same as t1-go-2. |
| P1-58 | NA | FIXED | pv/recover.go:325-328 | Flag is reset to false when the marker write fails. Same finding as t2-code-1 and t2-go-1, which are FIXED. "Already closed" means fixed. |
| P1-59 | NA | FIXED | pv/repo.go:228,237 | Fetch and RemoteHead now wrap the cause with %w; repo_test.go:425-429 asserts it. Same finding as t3-code-2 (FIXED). |
| t2-code-2 | OPEN | NA | pv/recover.go:214-215 | Code unchanged, but the final review (P1-46) ruled it not a defect: chosen safe direction, owner's open point 7. Policy call, see note. |
| t2-go-3 | OPEN | NA | pv/recover.go:214-215 | Same finding as t2-code-2 and P1-46; reviewer said "plan-mandated and safe; noise only". Policy call, see note. |
| t2-rr1-2 | OPEN | NA | pv/recover.go:324-331 | Same behaviour as P1-46 (retry quarantines instead of removing); reviewer called it safe, pre-existing design. Policy call, see note. |
| t2-rr2-4 | OPEN | NA | pv/recover.go:113-121 | Same finding as P1-47; final review: theoretical, not a defect; reviewer: fails closed. Policy call, see note. |
| t3-go-2 | OPEN | NA | pv/repo.go:161,188-189 | Race still in code, but the final review (P1-49) ruled it not a defect: marker kept, Recover asks the shared copy. Policy call, see note. |
| t3-go-8 | OPEN | NA | pv/syncer.go:54-67 | Still no ErrStopped case, but final review (P1-50) ruled not a defect: one-shot commands leave stop nil (repo.go:56-57). Policy call. |
| t4-go-2 | OPEN | NA | pv/repo.go:111-116 | Shadowed err still there, but final review (P1-51) ruled not a defect: deliberate fallback. Policy call, see note. |
| t5-code-4 | OPEN | NA | scripts/build-release.sh:44-47 | No short-VERSION comment, but final review (P1-52) ruled not a defect: owner's open point 8. Policy call, see note. |
| t5-go-5 | OPEN | NA | scripts/build-release.sh:62-69 | Final review (P1-53): not testable without a hook, not a defect. The script does carry a comment explaining the swap order. Policy call. |
| P1-23 | OPEN (UNSURE) | OPEN | pv/recover.go:640-648 | Confirmed. A failed hash-object or rev-parse (err1/err2 set, including a stop) falls through to setAside, which moves the file and writes a REPORT line (recover.go:578-580). |
| P1-24 | OPEN (UNSURE) | OPEN | pv/daemon_test.go:562,600 | Confirmed. The only non-signal cancel tests cut a fetch and the lock wait. No test gates on merge or commit; scenario_test.go:273 stops by SIGTERM. |
| P1-28 | OPEN (UNSURE) | OPEN | pv/lock_test.go:77 | Confirmed. Comment still says "or a descriptor open on it"; lines 78-83 only re-take the lock. Correct line is 77, not 74. |
| t3-code-7 | OPEN (UNSURE) | OPEN | pv/daemon_test.go:562,600 | Confirmed, same as P1-24. No test name or gate in any test file targets merge or commit under a cancelled context. |

Note on the nine "policy call" rows: in every one the code is unchanged, so OPEN is factually true of the code. They are marked NA here only because the mark definition says NA covers "the reviewer/notes said not a defect", and the later whole-branch review (Part 1 section 1D) gave exactly that verdict on the same finding. If the owner prefers "code still shows it = OPEN", then leave these nine as OPEN and instead flip their Part 1 twins (P1-46, 47, 49, 50, 51, 52, 53). Either way the two tables must agree.

## Conflicting duplicates

Same finding, different marks. 15 pairs.

| Part 1 row | Part 2 row | marks | which is right |
|---|---|---|---|
| P1-11 | t1-go-2 | NA vs OPEN | OPEN. Real error in Part 1: the test still runs git in the source checkout. |
| P1-32 (also P1-4, P1-5) | t5-code-1 | FIXED vs OPEN | Both stand. Part 1 asked only for the example in case a (done, AGENTS.section.md:46-47). t5-code-1 also asked to soften "Your input is fine" in case b (line 50, not done). |
| P1-46 | t2-code-2 | NA vs OPEN | NA (policy call above). |
| P1-46 | t2-go-3 | NA vs OPEN | NA (policy call above). |
| P1-46 | t2-rr1-2 | NA vs OPEN | NA (policy call above). |
| P1-47 | t2-rr2-4 | NA vs OPEN | NA (policy call above). |
| P1-48 | t3-code-3 | NA vs FIXED | Either; nothing live. lock.go:32-33 says "while waiting", the wording asked for. FIXED is the more exact mark. Not counted as a change. |
| P1-49 | t3-go-2 | NA vs OPEN | NA (policy call above). Part 1 evidence text is wrong: the condition `err != nil && stop.Err() != nil` is the original code, not a later fix. |
| P1-50 | t3-go-8 | NA vs OPEN | NA (policy call above). |
| P1-51 | t4-go-2 | NA vs OPEN | NA (policy call above). |
| P1-52 | t5-code-4 | NA vs OPEN | NA (policy call above). |
| P1-53 | t5-go-5 | NA vs OPEN | NA (policy call above). |
| P1-58 | t2-code-1 | NA vs FIXED | FIXED. |
| P1-58 | t2-go-1 | NA vs FIXED | FIXED. |
| P1-59 | t3-code-2 | NA vs FIXED | FIXED. |

(P1-4 and P1-5 are the same finding as P1-32 and are counted once, under the P1-32 line.)

## Wrong line numbers or evidence, mark unaffected

- P1-1: the fix is at scripts/build-release.sh:55, not :52.
- P1-10 and t1-go-1: assertion is at pv/hub_test.go:375.
- P1-28: comment is at pv/lock_test.go:77.
- P1-49: evidence sentence describes original code as if it were a fix (see above).
- t5-go-5: evidence says "no ... comment"; scripts/build-release.sh:62-64 does explain the swap order (the test file has none).

## What was confirmed correct

- All 12 FIXED rows hold in full: P1-1, 3, 4, 5, 17, 32; t2-code-1, t2-go-1, t3-code-2, t3-code-3, t2-rr1-1, t2-rr2-3.
- NA rows outside 1D/1E: P1-6 holds; P1-11 does not. Part 2 NA rows t1-code-2, t1-code-3, t1-go-3, t1-go-4, t5-go-8, t5-go-10, t5-go-11 all hold (the reviewer text really says no change wanted).
- OPEN sample, all still present: P1-2, P1-10, P1-13, P1-14, P1-21, P1-29, P1-33, P1-42, t1-go-2, t3-go-1, t5-code-5, t5-go-1 (also seen in passing and still open: P1-12, P1-19, P1-22, P1-25, P1-26, P1-31, P1-34, P1-36, P1-41, t2-go-6).

CHECKED fixed=12 na=9 unsure=4 open_sample=12 CHANGES=12
