# Final whole-branch Go review — F-025 (vault sync, findings A1 to A32)

Range: 3204b99..8c277b8, limited to `tools/vault-engine/` (18 files, +936/-99). Read from `final-review.diff` in three passes, plus the surrounding production source (`repo.go` run/placeEnv/Fetch, `syncer.go` record/attempt/sendDrops, `daemon.go` Run/tick, `lock.go`, `recover.go` Begin/setAside, `hub.go` allowance block).

Checks I ran: `go vet ./...` clean; `gofmt -l pkg/vaultsync cmd scripts` prints nothing; working tree clean at 8c277b8. I did not run `go test` or the harness (the controller is running both). Everything below about test behaviour is from reading, not from a run.

## Strengths

- **Error chains hold end to end.** `Repo.run` returns the bare `ErrStopped`; `local`, `Fetch` and `Update` all wrap with `%w`, so `errors.Is(err, ErrStopped)` works at `syncer.go:350` and `recover.go:688`. `writeFileAtomic` wraps with `%w: %w` (sentinel plus cause), so both `errors.Is(err, errFolderSync)` (`hub.go:248`) and `errors.Is(err, failed)` (the test) are true. `go.mod` says go 1.22.4, so multi-`%w` and per-iteration loop variables are both available.
- **No stop is misreported on the daemon path.** A1's `break` falls through to `pushUnconfirmed`; `daemon.go` checks `ctx.Err()` before it words anything as "not sent", and `Run` only logs a pass error while `ctx.Err() == nil`. A5's wrapped `ErrStopped` from `Update` takes the same quiet route. One-shot commands leave `Repo.stop` nil, so neither new branch can fire there.
- **A4 and A7 compose safely.** I traced the three callers of `writeFileAtomic` through the new post-rename error: the hub treats it as charged; `undo` returns before the reset with the on-disk marker saying "undo started", which makes the next pass take the keep-everything route; `Begin` leaves a marker that the next command's `Recover` settles. None of these loses data.
- **A8 is the narrowest possible change.** The type question is asked only after the ancestor check has already failed for a reason other than "not an ancestor", so the normal send path runs no extra git command.
- **Test seams are used correctly.** `syncDir` is swapped and restored through `t.Cleanup` in both tests that touch it; no test in the package is parallel (`grep t.Parallel` finds none), so the package-level variable cannot race. `cancelledAt` is deterministic: the gate cancels the context, `exec.CommandContext` then refuses to start, and `run` maps that to `ErrStopped`; `hit` is read only after `<-done`.
- **Environment order is right.** `gitIn` builds `append(placeEnv(dir), env...)` on a fresh slice (no aliasing), so `pushAs`'s `VAULT_HUB_PLACE` and `runBuild`'s `VERSION=...` extras win as the last entry.

## Issues

### Critical (Must Fix)

None.

### Important (Should Fix)

None.

### Minor (Nice to Have)

1. **`pkg/vaultsync/build_release_test.go:38` — the 15-minute build limit is longer than the 10-minute default the harness runs under.** `scripts/sync-harness.sh:149` runs `go test ./... -count=1` with no `-timeout` (owner decision 5 keeps it that way). A build that hangs there is ended by the test binary's own 10-minute panic, not by `buildTimeout`, so the process-group kill added for A28 never runs and the `bash` and `go build` children are left behind in their own group (`Setpgid`, line 60). Fix: take the limit from `t.Deadline()` minus a margin, falling back to a few minutes. Not a regression (there was no limit before), but A28's protection is absent exactly where the default limit applies.
2. **`pkg/vaultsync/recover.go:107` (with `:575`) — `Begin` refuses a save whose marker is already on disk when only the folder sync failed.** The hub got a special case for this (`hub.go:248`); `Begin` did not. The caller gets no marker back, the save answers `REFUSED engine-error`, and the next command's `Recover` treats the leftover marker as a crashed save, which moves untracked files outside `_inbox/` to quarantine. Nothing is lost, but one failed folder sync costs a refused save plus a quarantine sweep, and on a filesystem that refuses a sync on a folder (I could not verify which do; some network and FUSE mounts are known for it) every save would be refused. Before this branch there was no folder sync. Fix, as a follow-up: in `Begin`, treat `errFolderSync` as "marker written" (same reasoning as the hub), or at least document and test the branch. This is the ledger's deferred Task 1 item; I agree it can ship, and rate it the most valuable follow-up.
3. **`pkg/vaultsync/recover.go:614` — a quarantine copy that is in place but whose folder sync failed returns before the `REPORT.log` line is written.** The retry finds the copy through `hasCopy` and writes the line then ("identical copy already in quarantine"), so it heals itself; worth one sentence in the `setAside` comment.
4. **`pkg/vaultsync/hub.go:248` — the swallowed folder-sync error leaves no trace anywhere.** Ledger item; fine to ship. If it is ever logged, it should go to a hub-side log, not to the sender's stderr.
5. **`pkg/vaultsync/recover.go:575` — the message reads "folder sync: sync folder <dir>: <cause>"** (sentinel text and `syncDir`'s own prefix say the same thing twice). Cosmetic.
6. **`pkg/vaultsync/build_release_test.go:60` — with `Setpgid` the build children no longer receive Ctrl-C from the terminal;** an interrupted `go test` leaves a running build behind until it ends by itself. Small, and the price of the group kill.
7. **`pkg/vaultsync/daemon_test.go:549` — `waitingForFolderLock` allocates 1 MB and stops every goroutine on each 5 ms poll.** Harmless for the short time it runs; hoist the buffer if this helper is reused. It would also miss the frame if the dump ever passed 1 MB (truncated output), which would end as the clear 20-second "never reached the step" failure, not as a false pass.
8. **`pkg/vaultsync/hub_test.go:476` and the exit-6 test below it — the two A8 tests call `PreReceive(hub, ...)` without `hubRepo`'s environment clearing,** so they fail (harmlessly) under a runner that exports `GIT_DIR`. Same family as the recorded A14 follow-up; fold into that item.
9. **`pkg/vaultsync/syncer.go:372` — a send that was itself cut by a stop is worded "the connection broke while sending".** Not changed by this branch and invisible on the daemon path (the pass ends quietly), so no action here; noted because A1 touches the lines just above.
10. **`pkg/vaultsync/recover.go:525` — `syncDir` is a package variable read by production code and written by tests.** Safe today because no test is parallel; add "tests that swap it must not be parallel" to its comment.

## Deferred / Parked Triage

- Task 1 minor: `Begin`'s folder-sync branch undocumented and untested — ships as-is; see Minor 2, best follow-up of the branch.
- Task 1 minor: swallowed folder-sync error in `chargeDaily` not logged — ships as-is (Minor 4).
- Task 1 minor: `undo`'s folder-sync branch has no test — ships as-is; I traced it by hand and the outcome is the conservative one (next pass keeps a copy of everything).
- Task 1 ruling: fix the charged-but-refused send inside Task 1, widening the batch to `hub.go` — uphold. The sentinel is the smallest correct fix and the under-count risk is as stated.
- Task 2 minor: A8 tests do not clear git's location variables — ships as-is (Minor 8, joins the A14 follow-up).
- Task 2 minor: the exit-6 test uses the `PushResult` seam, not a real push — ships as-is; the hub half is tested against a real repository and the place half against the real line the hub printed.
- Task 2 off-goal: an annotated tag as the new tip passes the ancestor check and is charged before git refuses it — ships as-is, file as an idea. Confirmed by reading: `hub.go:119` runs only after a failed ancestor check, so a tag that peels to a commit never reaches it.
- Task 3 minor: the signal helper's stderr message is discarded (`repo_test.go:148`, `holder.Stderr` never set) — ships as-is; a one-line fix (`holder.Stderr = os.Stderr`) worth taking with the next test change.
- Task 3 minor: two unclear test failure messages — ships as-is.
- Task 3 pointer: a stop before `r.Head()` answers through `errorOutcome`, not as no-connection — ships as-is; confirmed at `syncer.go:344-346`, and the README sentence does not promise more.
- Task 4 minor: `cancelledAt` fails without waiting for `Run` on its 30-second path — ships as-is; it only matters once the test has already failed.
- Task 4 minor: `closedWhen` stops its poller without waiting for it — ships as-is; the poller only reads a file or goroutine stacks, and exits within 5 ms.
- Task 4 minor: `waitingForFolderLock` matches any goroutine in the binary — ships as-is while no test is parallel (none is).
- Task 5 minor: A9 has no regression test, only a text check — ships as-is; both task reviewers proved it by experiment.
- Task 5 minor: the 15-minute limit path is never exercised — ships as-is, but see Minor 1: under the harness's default limit it cannot be reached at all.
- Task 6 minors (README "within a couple of seconds" is not a hard bound; the tree-or-blob sentence is unconditional; the `errorOutcome` comment's examples) — ship as-is; wording only, and decision 3 already records the empty-hub exception.
- Rulings on verify scripts as files, Task 5 verifying the whole package, no extra audit for Task 2, one reviewer for Task 6 — uphold; this review covered Task 6's Go comments (`repo.go:38-40`, `:64-65`, `syncer.go:53-57`, `lock_test.go:77-80`) and found them accurate.
- No `stalled` lines in the ledger.

## Recommendations

- Record the wall time of `pkg/vaultsync` from the controller's current run. The ledger shows 546 s (race, baseline) and 465 s (Task 5 verify); the harness short round has a 10-minute default and this branch adds two more full build runs plus several daemon tests. If the non-race time is anywhere near 600 s, report it under owner decision 5.
- Take Minor 1 and Minor 2 as follow-up ideas; neither blocks the merge.
- File the annotated-tag item as an idea at Finish, as the ledger already says.

## Assessment

**Ready to merge?** Yes

**Reasoning:** The production changes are small, each error path keeps its chain, no stop is reported as a refusal, and no behaviour changed beyond what the items and the recorded owner decisions asked for. All ten findings are Minor and none needs the fix loop.
