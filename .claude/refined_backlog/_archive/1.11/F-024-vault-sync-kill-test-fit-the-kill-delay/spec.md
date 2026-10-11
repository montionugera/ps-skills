---
title: "Vault sync kill test: fit the kill delay to the machine so kills land mid-update on a fast runner"
id: F-024
status: refined
from_idea: I-031
---

# Vault sync kill test: fit the kill delay to the machine so kills land mid-update on a fast runner

Canonical spec: `/Users/pasitnusso/workspace/docs/superpowers/specs/2026-10-11-vault-sync-kill-test-delay-design.md`

## Problem

On pull request 38, CI job "vault-engine (go test + e2e)" failed: `TestScenario07_KilledMidSaveAndMidUpdate`, `scenario_test.go:502: kills proven mid-operation: 8 saves and 3 updates out of 8 rounds, want at least 4 of each`. The run before passed with exactly 4. The update round sleeps `rand.Intn(40)` ms before the kill (`scenario_test.go:476-477`); on the Linux runner an update lasts roughly 15-20 ms, so most kills land after it ended and are not counted. The engine recovered in all rounds (`converge` passed). On a Mac the count is 8 of 8.

## Why now

It blocks promoting release 1.11. In CI the short variant passes about half the time.

## Sketch

Test only. Time one uninterrupted update before the rounds, then draw each update round's pre-kill delay from `[0, measured)` instead of a fixed `[0, 40 ms)`. Floors stay 4 of 8 and 15 of 30. Handle a measured time of zero without panicking (`rand.Intn(0)` panics).

## Acceptance criteria

- [ ] The update round's pre-kill delay is drawn from the measured length of one uninterrupted update, not from a fixed 40 ms.
- [ ] The floors (4 of 8 short, 15 of 30 full) and every other assertion in the test are unchanged.
- [ ] A measured length of zero does not panic.
- [ ] No file outside `tools/vault-engine/pkg/vaultsync/scenario_test.go` changes (test helpers in the same package are allowed if needed).
- [ ] `TestScenario07_KilledMidSaveAndMidUpdate` passes 10 of 10 in the short variant locally.
- [ ] In `tools/vault-engine`: `gofmt -l cmd pkg/vaultsync` prints nothing, `go vet ./...` exits 0, `go test -count=1 -race ./...` passes.
- [ ] All seven CI jobs are green on the release pull request.
