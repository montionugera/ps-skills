---
title: "Vault sync save race: show the engine's message in the test and treat a refused push as a lost race"
id: I-029
status: idea
---

# Vault sync save race: show the engine's message in the test and treat a refused push as a lost race

Canonical spec: `/Users/pasitnusso/workspace/docs/superpowers/specs/2026-10-11-vault-sync-save-race-refused-push-design.md`

## Problem

Release 1.11 cannot be promoted. On pull request 38, CI job "vault-engine (go test + e2e)" failed: `TestScenario05_SaveRacesIncomingUpdate`, `scenario_test.go:360: round 15: exit codes [0 4], want both 0`. Exit 4 is `ExitNoConnection`, yet the hub was a local folder. The test helper `saveImpact` discards the engine's output, so the log does not name the cause. Likely cause (hypothesis): the engine recognises a lost push race only by `\t[rejected]` (`pkg/vaultsync/syncer.go:320`), while git also answers `[remote rejected]` with `incorrect old value provided` or `cannot lock ref`; that falls into the "unclear answer" path, which ends in exit 4 when the hub has not moved yet.

## Why now

It blocks promoting release 1.11, which the owner approved on 2026-10-11. This was the first CI run ever for `pkg/vaultsync`.

## Sketch

1. Test only: `saveImpact` logs the engine's output when a save exits non-zero.
2. Engine, only after a failing test proves it: count `[remote rejected]` with `incorrect old value provided` or `cannot lock ref` as a lost race in `record()`, inside the existing 5-try limit. Every other `[remote rejected]` reason stays "unclear".

## Acceptance criteria

- [ ] When a save in the scenario tests exits non-zero, the test log shows what the engine printed.
- [ ] A new test feeds the engine a `[remote rejected]` push answer with each of the two reasons while the hub is unmoved; it fails before the engine change (exit 4) and passes after it.
- [ ] Any other `[remote rejected]` reason is still handled as an unclear answer; a test covers this.
- [ ] In `tools/vault-engine`: `gofmt -l cmd pkg/vaultsync` prints nothing, `go vet ./...` exits 0, `go test -count=1 -race ./...` passes.
- [ ] All seven CI jobs are green on the release pull request.
