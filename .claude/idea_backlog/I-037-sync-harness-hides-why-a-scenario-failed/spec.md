---
title: "Sync harness hides why a scenario failed and breaks on a busy Mac"
id: I-037
status: idea
---

# Sync harness hides why a scenario failed and breaks on a busy Mac

## Problem

While verifying F-025, the vault sync harness (`tools/vault-engine/scripts/sync-harness.sh run`) failed twice and passed once on the same code.

- Run 1: scenarios 05 (save races incoming update) and 06 (delay between places) failed. The harness keeps only summary lines (lines 151-152), so the message saying why scenario 05 failed was lost. Scenario 06 reported a worst delay of 14.7 s against a 5 s target.
- Run 2: the quick round hit go test's default 10-minute limit (602 s) with the Mac at load 36 on 14 cores. No scenario ran.
- Run 3, with load near 12: exit 0, all seven scenarios passed, worst delay 2.7 s.

A debugging agent could not reproduce either failure and found no changed line to blame. Its notes are in the F-025 backlog folder (`reviews/harness-debug.md`).

Also seen: two test daemons leaked on 2026-10-11 were still running two days later and using processor time.

## Why now

A failure that cannot be read cannot be told apart from a real regression. Each harness run costs about an hour.

## Sketch

- Keep the full verbose output in a file, and print the failing test's own lines.
- Capture the daemon's stderr in `startDaemon` (`pkg/vaultsync/scenario_test.go`, lines 269-281).
- Give the quick round an explicit time limit instead of the 10-minute default.
- Look at scenario 06's margin: a 3 s poll against a 5 s target leaves little room.
- Make sure a timed-out or killed test run does not leave daemons behind.

## Acceptance criteria

- [ ] When a scenario fails, the harness output shows the failing assertion's message.
- [ ] The daemon's stderr is kept for a failed scenario.
- [ ] The quick round has an explicit time limit that fits a moderately busy machine.
- [ ] A killed or timed-out run leaves no vault-engine daemon running.
