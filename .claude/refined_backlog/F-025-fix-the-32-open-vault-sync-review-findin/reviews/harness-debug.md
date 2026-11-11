# Harness failure investigation: scenario 05 and scenario 06 (2026-10-13)

Goal (verbatim): find the root cause of the two scenario failures in the full
harness run on HEAD 8c277b8, and decide regression vs pre-existing. Investigation
only: no tracked file was edited, nothing was committed.

## Short answer

- Neither failure could be reproduced. Every re-run on HEAD passed, including one
  full scenario round run exactly the way the harness runs it.
- Verdict for both: **flaky (timing / load sensitive), not shown to be a regression.**
  No changed line in 3204b99..8c277b8 could be tied to either failure.
- The real failure text of scenario 05 is **lost**: the harness filters the test
  output and throws away the `t.Fatalf` lines. That filter is the reason the
  cause cannot be named.
- The Mac was **not idle** during the failing run (evidence below).

## What the original log actually contains

`scratchpad/final-harness.log` is only 20 lines. The scenario round is run by
`scripts/sync-harness.sh:151-152`:

    VAULT_SYNC_ROUNDS=full go test ./pkg/vaultsync/ -run 'TestScenario' -count=1 -timeout 90m -v 2>&1 \
        | grep -E '^(--- |ok|FAIL|LATENCY|KILLS|panic)'

Go prints a failure message indented (`    scenario_test.go:NNN: ...`), so the
grep drops it. No REPORT, REFUSED or timeout line survives either. All the log
has for the two failures is:

    --- FAIL: TestScenario05_SaveRacesIncomingUpdate (933.05s)
    LATENCY runs=50 median=1686ms worst=14717ms target_worst<5000ms
    --- FAIL: TestScenario06_DelayBetweenPlaces (172.55s)

- Scenario 06: the message is certain from the code. The only check after the
  LATENCY line is `scenario_test.go:417-418`:
  `worst delay 14.717s is not under the 5 s target`.
- Scenario 05: unknown. It died at 933 s, well before the end (a full 1,000
  rounds needs 1,870 to 2,480 s on this Mac), so it was a mid-loop stop.
  The only mid-loop stop is `scenario_test.go:364-365`
  (`round N: exit codes [...], want both 0`), i.e. one save ended with a
  non-zero exit. Which exit code, and why, is not recorded. (Inferred from the
  code and the timing, not seen.)

Harness timeline, rebuilt from the log file's birth time (15:07:49) and the
durations: scenario 05 ran 15:24:43 to 15:40:16, scenario 06 15:40:16 to 15:43:08.

## Runs I made (all with VAULT_SYNC_ROUNDS=full, one at a time)

| # | Checkout | Command (`go test ./pkg/vaultsync/ -count=1 -v ...`) | Exit | Result |
|---|----------|------------------------------------------------------|------|--------|
| 1 | baseline 3204b99 | `-run TestScenario06 -timeout 40m` | 0 | PASS 153.9 s, `median=1780ms worst=2879ms` |
| 2 | HEAD 8c277b8 | `-run TestScenario06 -timeout 40m` | 0 | PASS 155.0 s, `median=1873ms worst=2907ms` |
| 3 | HEAD 8c277b8 | `-run TestScenario05 -timeout 40m` | 0 | PASS 1870.1 s |
| 4 | HEAD 8c277b8 | `-run TestScenario -timeout 90m` (the harness's own scenario command, unfiltered) | 0 | all 7 PASS; scenario 05 2478.3 s; scenario 06 160.4 s `median=1767ms worst=3615ms` |
| 5 | baseline 3204b99 | `-run TestScenario05 -timeout 40m` | 1 | **not a test failure**: `panic: test timed out after 40m0s`. It had finished about 918 of 1,000 rounds (1,837 commits on the hub) with no failed save. |

Outputs: `scratchpad/base-s06.log`, `head-s06.log`, `head-s05.log`,
`head-all.log`, `base-s05.log`, `head-all.time`.

Run 5 is inconclusive as pass/fail: my 40-minute limit was too short (the
harness allows 90). It still shows two things: the baseline did not fail in 918
rounds, and the baseline is not faster than HEAD.

## Hypotheses tested

1. **The feature made saves slower (folder sync added in `writeFileAtomic`,
   recover.go:574) and that pushed a timing limit over.** Not supported.
   Seconds per round of scenario 05: HEAD alone 1.87, HEAD in the full round
   2.48, baseline alone about 2.6. The baseline was the slowest. Scenario 06
   latency is the same on both (worst 2879 ms baseline, 2907 ms HEAD).
2. **Scenario 06 fails on HEAD repeatably.** Refuted: passed 2 of 2 on HEAD.
3. **The failures need the earlier scenarios to run first (same process).**
   Refuted: run 4 repeats the harness order and passed.
4. **Fixture git environment change (A14), hub `dir` argument, Undo refusal,
   confirm-loop stop.** No evidence for any of them: these are deterministic
   changes, and a deterministic break would show in runs 2, 3 and 4. Not
   individually disproved beyond that.
5. **Load on the machine at the time.** Supported, but only by timing:
   - `pmset -g log` shows Spotlight indexing (mds 6 min 11 s, mds_stores
     6 min 30 s) running from about 15:35 to 15:42. That is the longest burst
     of the afternoon (others were 1 to 2 minutes) and it covers the scenario 05
     stop (15:40:16) and all of scenario 06.
   - The same log shows about one `caffeinate`-wrapped command ending every
     minute all afternoon, so other sessions were running commands. The Mac was
     not idle.
   - Two test daemons leaked on 2026-10-11 are still running and still syncing
     (PIDs 93367 and 97028, 13.7 % and 7.1 % CPU, 353 and 284 CPU-minutes).

## Why these two scenarios are sensitive (read from the code, not observed failing)

- Scenario 06 uses the real 3,000 ms poll (`scenario_test.go:385`). A change is
  picked up on the next pass, so the worst case is already about 2.9 to 3.6 s
  against a 5 s limit. One missed or failed pass adds 3 s and breaks the limit;
  14.7 s means about four passes in a row did not deliver. The daemon logs the
  reason for a failed pass (daemon.go:81-82) but `startDaemon`
  (`scenario_test.go:269-281`) does not capture its output, so the reason is lost.
- Scenario 05 runs two saves, a daemon and a lock-grabbing observer against one
  folder 1,000 times. A save can end non-zero for timing reasons alone: the hub
  kept moving for 5 tries (syncer.go:120-126, `max_retries` 5), the folder lock
  wait ran out (15 s), or a network step ran out (10 s) (config.go:43).

## Not done / limits

- No failing run was captured, so no mechanism is proven. "Flaky" here means:
  failed once in the harness, then passed in every re-run (HEAD: scenario 06
  three times, scenario 05 twice; baseline: scenario 06 once, scenario 05 for
  918 rounds).
- I did not finish a full baseline scenario 05, and did not run the full
  harness on the baseline.

## Smallest changes I would propose (not applied)

1. `scripts/sync-harness.sh:151-152`: keep the whole `-v` output in a file and
   print the filtered view from it, or at least add `|^\s+\S+_test\.go:[0-9]+:`
   to the grep. Without this the next failure will be just as unreadable.
2. `scenario_test.go` `startDaemon`: send the daemon's stderr to the test log,
   so a failed pass in scenario 06 says why.
3. Then re-run the harness. If scenario 05 or 06 fails again, the message will
   name the cause; only then decide on a code or test change.

## Off-goal findings (filed, not chased)

- A scenario test that is killed by the test timeout leaves its `sync-daemon`
  running forever. Two from 2026-10-11 are still alive (PIDs 93367, 97028),
  with their temp folders. My run 5 leaked one too (PID 59965); I stopped that
  one with SIGTERM. I did not touch the two older ones.
- Scenario 05 gets slower as it goes (about 2.25 s per round early, 2.6 s
  average on the baseline) and can take 31 to 41+ minutes alone.

## Clean-up

- The throwaway baseline checkout was removed with `git worktree remove` (exit 0).
- Left behind: the temp folder of the timed-out run 5,
  `$TMPDIR/TestScenario05_SaveRacesIncomingUpdate1140049642`.
