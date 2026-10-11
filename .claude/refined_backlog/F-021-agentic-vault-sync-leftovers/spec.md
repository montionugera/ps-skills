---
title: "Agentic vault sync leftovers"
id: F-021
status: refined
from_idea: I-027
---

# Agentic vault sync leftovers

Canonical spec (binding): `/Users/pasitnusso/workspace/docs/superpowers/specs/2026-10-10-agentic-vault-multi-place-sync-design.md`
Approved, audited plan: `/Users/pasitnusso/workspace/docs/superpowers/plans/2026-10-11-agentic-vault-sync-leftovers.md`

## Problem

Plan 1 of agent notes folder sync (feature F-020, code under `tools/vault-engine`) shipped
into release 1.11. Its reviews left a list of small defects that were judged safe to ship
but are still true in the code:

- The shared copy ("hub") reports a git failure in its forward-only check as a history rewrite.
- `Undo` trusts its list on a second call for the same marker.
- A cancel does not stop a running git command, or a wait for the folder lock.
- Several small Go clean-ups, `scripts/build-release.sh` gaps (dirty marker, stamp check,
  stale checksum file), test hygiene items (scenarios 07 and 18, the harness set-up message,
  one fixed wait), and wrong wording in agent rule 5 and the README.

## Why now

The code is fresh and the review findings are still accurate. Release 1.11 is still open,
so the fixes can ride with the feature they belong to.

## Sketch

No new parts. Three small behaviour changes in `pkg/vaultsync`, each its own task with its
own review; one batch of tiny Go clean-ups; one batch of script, test and documentation
fixes; a final full verification. Eight tasks in the plan above.

## Acceptance criteria

- [ ] A git failure in the hub's forward-only check is reported as an engine error, not as a history rewrite.
- [ ] `Undo` trusts its list only once per marker.
- [ ] A cancel stops a running git command and a wait for the folder lock.
- [ ] The grouped small Go clean-ups from the plan's Task 4 are applied.
- [ ] `scripts/build-release.sh` marks a dirty tree, checks the stamp, and leaves no stale checksum file.
- [ ] Test hygiene items in the plan's Task 6 are fixed (scenarios 07 and 18, harness set-up message, the fixed wait).
- [ ] Agent rule 5 and the README are corrected.
- [ ] With no sync config file present, command behaviour stays byte-for-byte as before, and every refusal still fails closed.

## Acceptance evidence

- [ ] From `tools/vault-engine`: `gofmt -l cmd pkg/vaultsync` prints nothing, `go vet ./...` passes, `go test -count=1 -race ./...` passes.
- [ ] The full harness `scripts/sync-harness.sh run` passes all scenarios, with the measured worst delay under 5000 ms.
