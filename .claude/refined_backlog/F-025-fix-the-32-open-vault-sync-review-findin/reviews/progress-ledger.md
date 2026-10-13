# SDD ledger — plan: /Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin/.claude/refined_backlog/F-025-fix-the-32-open-vault-sync-review-findin/plan.md

Goal (verbatim): Fix the 32 open findings from the vault sync review notes, as a feature in release 1.12, tested and reviewed, without changing anything on the main branch.
Spec: /Users/pasitnusso/workspace/docs/superpowers/specs/2026-10-13-vault-sync-fix-later-findings-design.md
Handoff claimed: /tmp/handoff-2026-10-13-123000-ps-skills-f025-plan-written.md (session specs-1b)
Review notes: copy each task's review file into .claude/refined_backlog/F-025-.../reviews/ and commit (release cleanup deletes .superpowers/sdd — idea I-033).
STOP point: after `psrw ship` and the I-032 tick. Never promote release 1.12 to main.

## Setup
- Plan amendment confirmed landed (Follow-ups section, A5 narrowed to ErrStopped, dangling-symlink test). Plan + handoff committed b2e7798 on feat/F-025.
- Preflight: branch is 0 commits behind origin/release/1.12.
- Preflight: go 1.27.2, dispatch-worker, psrw, git, bash all present.
- Preflight: baseline `go vet ./...` clean; `go test -count=1 -race -timeout 40m ./...` — pass, all 5 packages ok (vaultsync 546s), before any change.
- Plan audit (self-grill-audit, opus): running.

## Batches
- Batch 1: task 1 — recovery and undo (A4, A5, A6, A7, A15, A16, A17, A18) — engine behaviour change, own gate.
- Batch 2: task 2 — hub (A8, A12, A13, A24) — exit code and signature change, own gate.
- Batch 3: task 3 — sync engine and repo (A1 code, A21, A25, A27, A32) — engine behaviour change, own gate.
- Batch 4: task 4 — daemon tests (A19, A20, A22) — tests only, own gate (own test surface).
- Batch 5: task 5 — build script and its tests (A9, A10, A14, A26, A28, A29, A30, A31) — own gate.
- Batch 6: task 6 — wording (A2, A3, A11, A23, README for A1) — own gate.
All in one worktree, strictly in order (never two implementers at once).

## Plan scan
(filled from the audit's cross-task findings)

## Log
- Audit returned: safe-with-fixes. 1 HIGH (Task 1 verify check could never pass; verified on disk; fixed), 5 MEDIUM, 4 LOW. Plan fixed and committed 3204b99; audit trail is the plan's appendix.
- Plan scan: taken from the audit, which checked tasks 1 to 6 in order and reported no collisions (no line edited twice, no later task relying on a signature an earlier one changes) and that all five owner decisions are implemented consistently. Not re-derived by me.
- Ruling: verify commands are run as script files (.superpowers/sdd/plan/verify-N.sh = the plan's verify-cmd line plus a gofmt check) — the inline form would be expanded by the dispatching shell in the wrong folder — costs nothing if wrong.
- Ruling: Task 5's verify script runs the whole vaultsync package, because A14 changes the gitIn helper every test group uses — costs about 10 extra minutes.
- Pointer for the Task 1 review: A7 branch where the folder sync fails after the rename (file in place, error returned; chargeDaily then refuses a send it charged; comment at recover.go:321-323).
- Task 1: BASE 3204b99. Dispatched to dispatch-worker --agent agy (timeout 5400, verify-timeout 2700). Brief task-1-brief.md, report task-1-report.md.
Task 1: implementer DONE via dispatch-worker agy (Verified: true, verify-1.sh ok 127s; commits 3204b99..596e9f0, 2 files +321/-25). Fix cap 5 (over 300 lines). Reviewers dispatched (code-reviewer + golang-reviewer, opus).
- Task 1: review — code-reviewer: spec ok, 1 Important (hub.go:237 chargeDaily: folder sync fails after rename -> usage written but send refused, retries charged again), 2 minor. golang-reviewer: approved, 6 minor (top: stale comment recover.go:327-336). Review files task-1-review.md, task-1-review-go.md.
- Task 1: Ruling: fix the chargeDaily finding now, widening this batch to hub.go/hub_test.go — it is caused by A7's change, not by Task 2's items — writeFileAtomic wraps the post-rename failure in a sentinel, chargeDaily treats it as charged — if wrong, a power cut right after a failed folder sync can under-count one send against the daily allowance. Also fix the false comment at recover.go:327.
- Task 1: minor (deferred): Begin's folder-sync branch undocumented/untested; remaining minors in the two review files.
Task 1: fix round 1/5 dispatched (agy): SUCCESS, Verified: true (verify-1b.sh ok 129s), commit 0c39bb4, 3 files +66/-3. Scoped re-review dispatched (opus).
- Task 1: fix round 1/5 (2 addressed, 0 open — chargeDaily charged-but-refused; false undo comment; commits 596e9f0..0c39bb4). Re-review file task-1-rereview-1.md.
- Task 1: minor (deferred): swallowed folder-sync error in chargeDaily is not logged; undo folder-sync branch has no test.
- Task 1: simplifier dispatched (sonnet) over 3204b99..HEAD.
- Task 1: simplify (nothing to simplify), tests unchanged since verify-1b.sh ok 129s.
- Task 1: complete (commits 3204b99..0c39bb4, review clean after 1 fix round). Notes committed under refined_backlog/F-025-.../reviews/.
- Ruling: Task 2 (hub pre-receive guard) gets no extra plan audit before dispatch — the whole plan was audited an hour ago and Task 2's tests were compiled and run by the auditor — costs a fix round if wrong.
- Task 2: BASE = contents of task-2-base. Dispatched to dispatch-worker --agent agy.
Task 2: implementer DONE via dispatch-worker agy (Verified: true, verify-2.sh ok 43s; commits 630019e..1cc6c45, 3 files +149/-22). Fix cap 5 (risky surface: hub guard). Reviewers dispatched (code-reviewer + golang-reviewer, opus).
- Task 2: review — code-reviewer: spec ok, quality approved, 0 Critical/Important, 2 minor. golang-reviewer: spec ok, approved, 6 minor. No fix loop. Files task-2-review.md, task-2-review-go.md.
- Task 2: minor (deferred): new A8 tests call PreReceive without clearing git location variables (fail harmlessly if the runner exports GIT_DIR; same family as the A14 follow-up); exit-6 test uses the PushResult seam, not a real push; rest in the review files.
- OFF-GOAL, file as an idea at Finish (do not chase): an annotated tag sent as the new tip passes the hub's ancestor check (it peels the tag); git itself then refuses the update, but the place's daily allowance is already charged (hub.go:203). An up-front type check on the new tip would fix this and the empty-hub tree/blob path. The worker's report claimed the opposite; both reviewers say that claim is false (Go reviewer confirmed in a scratch repo, git 2.54.0).
- Task 2: simplifier dispatched (sonnet) over 630019e..HEAD.
- Task 2: simplify (nothing to simplify), tests unchanged since verify-2.sh ok 43s.
- Task 2: complete (commits 630019e..1cc6c45, review clean). Notes committed under reviews/.
- Task 3: BASE = contents of task-3-base. Dispatched to dispatch-worker --agent agy.
- Task 3: implementer DONE via dispatch-worker agy (Verified: true, verify-3.sh ok 109s; commits 01dd268..2da5ecb, 4 files +110/-3). Fix cap 3. Reviewers dispatched (code-reviewer + golang-reviewer, opus).
- Task 3: review — code-reviewer: spec ok, approved, 0 Critical/Important, 2 minor. golang-reviewer: spec ok, approved, 3 minor. No fix loop. Files task-3-review.md, task-3-review-go.md.
- Task 3: minor (deferred): the signal helper's new stderr message is discarded because the parent never sets holder.Stderr (repo_test.go:148, A27); two unclear test failure messages (testkit_test.go:62, repo_test.go:462-470).
- Pointer for the Task 6 review: syncer.go:339-342 — if the stop lands before r.Head(), the answer is errorOutcome(err), not REFUSED no-connection; the README sentence for A1 must not promise more than "a stopped confirmation fetch is not retried".
- Task 3: simplifier dispatched (sonnet) over 01dd268..HEAD.
- Task 3: simplify (nothing to simplify), tests unchanged since verify-3.sh ok 109s.
- Task 3: complete (commits 01dd268..2da5ecb, review clean). Notes committed under reviews/.
- Task 4: BASE = contents of task-4-base. Dispatched to dispatch-worker --agent agy.
- Task 4: implementer DONE via dispatch-worker agy (Verified: true, verify-4.sh ok; commits 9bb0da1..96589d0, 1 file +137/-24). Fix cap 3. Reviewers dispatched (code-reviewer + golang-reviewer, opus).
- Task 4: review — code-reviewer: spec ok, approved, 0 Critical/Important, 4 minor. golang-reviewer: spec ok, approved, 6 minor. No fix loop. Files task-4-review.md, task-4-review-go.md.
- Task 4: resolved "cannot verify": three older `go func(){ done <- Run }()` starts (daemon_test.go:255, 408, 506) are outside A19 (which names only the pid-file poller) and wait for Run on the normal path. Not a gap.
- Task 4: minor (deferred): cancelledAt fails without waiting for Run when Run hangs 30 s (daemon_test.go:674-682); closedWhen stops its poller without waiting for it (:531); waitingForFolderLock matches any goroutine in the binary (:548, safe while no test is parallel).
- Task 4: simplifier dispatched (sonnet) over 9bb0da1..HEAD.
- Task 4: simplify (nothing to simplify), tests unchanged since verify-4.sh ok.
- Task 4: complete (commits 9bb0da1..96589d0, review clean). Notes committed under reviews/.
- Task 5: BASE = contents of task-5-base. Dispatched to dispatch-worker --agent agy (verify-5.sh also runs the whole vaultsync package, about 10 min).
- Task 5: implementer DONE via dispatch-worker agy (Verified: true, verify-5.sh ok incl. whole package 465s; code commits 20e41c7..a59069e, 5 files +133/-16). Fix cap 3.
- Task 5: DEFECT in the worker run: it also wrote task-5-review.md and task-5-review-go.md about its own work and committed them (7e586a7, copying my notes-commit pattern). Not reviews. Real reviewers told to overwrite them; the committed copies get replaced by the real ones in a new commit. Later dispatches must say "do not write review files and do not commit anything outside tools/vault-engine".
- Task 5: reviewers dispatched (code-reviewer + golang-reviewer, opus) on 20e41c7..a59069e.
- Task 5: review — code-reviewer: spec ok, approved, 0 Critical/Important, 4 minor. golang-reviewer: spec ok, approved, 6 minor. Both proved A9 by experiment on bash 3.2 (new script exits 128 on a failing git status, old one carried on). No fix loop. Files task-5-review.md, task-5-review-go.md (implementer's fakes overwritten).
- Task 5: minor (deferred): A9 has no regression test, only a grep; the 15-minute build time limit path is never exercised by a run (build_release_test.go:58-60); rest in the review files.
- Task 5: simplifier dispatched (sonnet) over 20e41c7..a59069e.
- Task 5: simplify (nothing to simplify), tests unchanged since verify-5.sh ok.
- Task 5: complete (commits 20e41c7..a59069e, review clean). Independent review notes committed over the worker's fakes.
- Task 6: BASE = contents of task-6-base. Dispatched to dispatch-worker --agent agy.
- Task 6: implementer DONE via dispatch-worker agy (Verified: true, verify-6.sh ok; commits 1231549..e3b6908, 6 files +21/-7; no self-review files this time). Fix cap 2.
- Ruling: Task 6 gets one reviewer (code-reviewer, opus), no separate Go reviewer — the diff is 28 lines of comments, rules text and README, no executable Go — costs a missed Go-comment nit if wrong; the final whole-branch review still covers it.
- Task 6: review — code-reviewer: spec ok, approved, 0 Critical/Important, 3 minor (plan-mandated wording a little wider than the code). File task-6-review.md.
- Task 6: minor (deferred): README:61 "ends within a couple of seconds" is not a hard bound (an index rebuild or folder scan under way is not cut short); README:82 tree-or-blob sentence is unconditional but the check only runs when the hub already has a main line; syncer.go:55-57 comment's example causes are not cases of the switch.
- Task 6: simplifier dispatched (sonnet).
- Task 6: simplify (nothing to simplify).
- Task 6: complete (commits 1231549..e3b6908, review clean). Notes committed under reviews/.
- All 6 tasks complete. Final whole-branch review dispatched on the code range 3204b99..HEAD limited to tools/vault-engine (final-review.diff). Full go test started in parallel as an early signal.
- Final review (code-reviewer, opus): ready to merge, 0 Critical/Important, all 32 items have a hunk, no deferred minor must be fixed before merge. File final-review.md.
- Final review (golang-reviewer, opus): ready to merge, 0 Critical/Important, 10 minor. File final-review-go.md. No fix wave.
- Ruling: the deferred minors stay as follow-ups (both final reviewers say none blocks the merge) — costs a later small feature. To file as ONE follow-up idea at Finish: (a) Begin refuses a save when only the folder sync failed (recover.go:107) — on a filesystem that refuses folder syncs every save would be refused; (b) build test's 15-minute limit is longer than the 10-minute default the harness short round runs under (build_release_test.go:38; take it from t.Deadline()); (c) annotated tag as new tip passes the hub check and is charged; README.md:82 wording; (d) the remaining test-hygiene minors listed above.
- Watch: record pkg/vaultsync wall time of the final run (baseline 546 s; harness short round has Go's 10-minute default).
- Final verification on 8c277b8: go vet clean, gofmt clean, go test -count=1 -race -timeout 40m ./... exit 0, all 5 packages ok (vaultsync 420 s). Harness (bash scripts/sync-harness.sh run) started in background; log scratchpad/final-harness.log.
- HARNESS FAILED on 8c277b8 (exit 1, 36 min): plain round ok (vaultsync 442 s); scenarios 01, 02, 04, 07, 18 PASS; TestScenario05_SaveRacesIncomingUpdate FAIL (933 s), TestScenario06_DelayBetweenPlaces FAIL (173 s). NOT shipped. No baseline harness run exists.
- Debug agent dispatched (opus, systematic-debugging, read-only): regression vs baseline (3204b99) for scenarios 05 and 06. Findings go to harness-debug.md.

## Harness failure — debug result (agent report, 2026-10-13)
- Debug agent verdict: scenarios 05 and 06 are flaky and load-sensitive; neither reproduced on HEAD (06 alone on baseline and HEAD passed; full scenario round on HEAD passed 7/7 per the agent). Baseline run of 05 inconclusive (agent's 40-minute limit expired, no failed save seen). Notes: harness-debug.md.
- Ruling: do not change code for an unreproduced failure; re-run the full harness myself on HEAD and ship only on exit 0 with seven scenario passes — why: the handoff's pass bar is a run by me, not an agent report — cost if wrong: a real timing regression ships to release 1.12 (not main) and is caught at promote.
- Follow-ups to file: harness grep drops the failing test's message (sync-harness.sh:151-152); daemon stderr not captured in startDaemon (scenario_test.go:269-281); scenario 06 has a 3 s poll against a 5 s limit; two test daemons leaked on Oct 11 still running (PIDs 93367, 97028) — left alone.
- Harness run 2 (mine, HEAD 28768e4, 18:02-18:12): exit 1 in the plain round — pkg/vaultsync hit go test's default 10-minute limit at 602 s (it took 442 s in run 1). Machine load average was 36 on 14 cores (OrbStack helper 290% CPU, other sessions). No scenario ran. Ruling: load, not code; wait for load under 12, then run the harness again — cost if wrong: one more hour.
- Harness run 3 (mine, HEAD 28768e4, 20:01-20:50, load ~12): exit 0, plain round all ok (vaultsync 394 s), scenario round 7/7 PASS (05 1791 s; 06 worst delay 2719 ms), vaultsync ok 2568 s. Pass bar met. Proceed to ship.
