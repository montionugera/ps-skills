---
title: "Vault sync review tweaks: stale recover comment, VAULT_ROOT prefix, rule 5 example"
id: I-028
status: idea
---

# Vault sync review tweaks: stale recover comment, VAULT_ROOT prefix, rule 5 example

Canonical spec: `/Users/pasitnusso/workspace/docs/superpowers/specs/2026-10-11-vault-sync-review-tweaks-design.md`

## Problem

The final review of the leftovers build (F-021) left three small "nice to have" findings in `tools/vault-engine/`:

- `pkg/vaultsync/recover.go:31-32` — the `UndoStarted` field comment says only `Undo` writes the flag. Since `26a5456`, `Recover` sets it too.
- `scripts/build-release.sh:55` — the engine is run for `version` without `VAULT_ROOT`. Safe only while `version` stays the first branch in `cmd/vault-engine/main.go`.
- `templates/vault-rules/AGENTS.section.md:45-47` — agent rule 5 case a has no example that looks like an engine validation message.

## Why now

The owner approved exactly these three on 2026-10-11, while release 1.11 is still open and the code is fresh.

## Sketch

- Reword the field comment to name both `Undo` and `Recover`. Comment only.
- Prefix the call: `VAULT_ROOT="$STAGE" "$STAGE/$host" version`.
- Add the example "a note or value the engine says is not valid" to rule 5 case a.

## Acceptance criteria

- [ ] The `UndoStarted` field comment in `pkg/vaultsync/recover.go` says both `Undo` and `Recover` set the flag; no code line changes in that file.
- [ ] `scripts/build-release.sh` runs the staged engine's `version` with `VAULT_ROOT="$STAGE"`; `bash -n scripts/build-release.sh` exits 0.
- [ ] Rule 5 case a in `templates/vault-rules/AGENTS.section.md` lists "a note or value the engine says is not valid" as an example; the rest of rule 5 is unchanged.
- [ ] In `tools/vault-engine`: `gofmt -l cmd pkg/vaultsync` prints nothing, `go vet ./...` exits 0, `go test -count=1 -race ./...` passes.
- [ ] The diff touches only those three spots.
