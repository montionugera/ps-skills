---
title: "Fix the 32 open vault sync review findings"
id: F-025
status: refined
from_idea: I-035
---

# Fix the 32 open vault sync review findings

Canonical design: `docs/superpowers/specs/2026-10-13-vault-sync-fix-later-findings-design.md`
(workspace docs folder). Item list: idea I-032, `open-findings.md`, items A1 to A32.

## Problem

The reviews of release 1.11 parked 32 distinct findings in the vault sync engine
(`tools/vault-engine/`) as "fix later". Five are small faults in engine behaviour:

- A1: the confirm retry loop sleeps 1.5 s even when the daemon is stopping.
- A4: Undo trusts a marker the caller passes even when the marker file is gone.
- A5: a hash comparison cut by a stop makes the leftover file get moved aside.
- A7: the atomic write does not sync the parent folder after the rename.
- A8: a pushed tree or blob is refused as `engine-error`, not "type not allowed".

The other 27 are test, build script and wording faults: tests that drop errors, sleep
on a timer, run git in the source checkout, or do not assert what their name claims.

## Why now

The findings were checked against `main` on 2026-10-13, so file and line references are
fresh. They go stale as the code moves.

## Sketch

One feature, six ordered tasks: recovery and undo; hub; sync engine and repo; daemon
tests; build script and its tests; wording. Behaviour changes are built test-first. The
nine findings a review ruled "not a defect" stay closed.

## Acceptance criteria

- [ ] Every item A1 to A32 of I-032 `open-findings.md` is addressed by a commit that names it.
- [ ] Each of the five behaviour changes (A1, A4, A5, A7, A8) has a test that fails without the fix and passes with it.
- [ ] In `tools/vault-engine/`, `go vet ./...` is clean and `go test -count=1 -race -timeout 40m ./...` passes.
- [ ] The full sync harness passes on the final code: seven scenarios PASS.
- [ ] `tools/vault-engine/README.md` matches the new stop behaviour.
- [ ] No file outside `tools/vault-engine/` and `templates/vault-rules/AGENTS.section.md` changes, apart from backlog files.
