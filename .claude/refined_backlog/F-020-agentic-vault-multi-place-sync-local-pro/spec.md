---
title: "Agentic vault multi-place sync - local proof"
id: F-020
status: refined
from_idea: I-026
---

# Agentic vault multi-place sync - local proof

Canonical spec (draft 4, owner-approved 2026-10-10):
`/Users/pasitnusso/workspace/docs/superpowers/specs/2026-10-10-agentic-vault-multi-place-sync-design.md`

Plan (Plan 1, 10 tasks, independently audited):
`/Users/pasitnusso/workspace/docs/superpowers/plans/2026-10-10-agentic-vault-multi-place-sync.md`

## Problem

The agent notes folder has to be worked on from several places at once. Today nothing
keeps the copies in step, nothing stops two places from storing conflicting versions of
one note, and nothing stops a large or wrong-type file from bloating every copy.

## Why now

Worker pods that write to the folder are about to be built. The save and sync behaviour
has to be proven on one machine, on test copies, before the real folder or a server is
touched.

## Sketch

The save step is built into `vault-engine` (new package `pkg/vaultsync`): folder lock,
fetch and fast-forward, engine operation, limit check, commit, push, confirm, retry on a
lost race. The shared copy ("hub") is a forward-only bare git repository whose door check
enforces size, type, path, count and daily-allowance limits. A `sync-daemon` command
brings each place up to date. Rule templates (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`) tell
agents how to handle a refusal. Everything in this feature runs against throwaway test
copies on one Mac.

## Acceptance criteria

- [ ] `go test ./...` passes in `tools/vault-engine`, including the hub, save, recovery, daemon and scenario tests.
- [ ] `bash scripts/sync-harness.sh run` with full rounds passes spec tests 1, 2, 4, 5, 6, 7 and 18, and prints a `LATENCY` line with a worst delay under 5 seconds.
- [ ] Spec tests 8 to 17 are each covered by a passing named test, as mapped in the plan's Task 9 table.
- [ ] Without a sync config the engine behaves exactly as before (existing tests unchanged and passing).
- [ ] After every scenario both test places are identical and `vault-engine validate` is clean in both.
- [ ] The real folder `~/workspace/agentic-vault` is never read for writing or modified, and no cluster command is run.
- [ ] `tools/vault-engine/README.md` documents the shared-folder mode, the hub, the limits and the harness.

## Acceptance evidence

Command output captured at the end of the plan's Task 9 and Task 10: the `go test ./...`
summary, the full-rounds harness run with its `LATENCY` line, and the three build outputs
from the build script. Spec tests 3 (live Claude and Gemini agents) and 19 (worker pod
restart) are out of scope here and deferred to later plans.
