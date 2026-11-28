---
title: "Recall failure is visible in the session: engine install guard, hook heartbeat and error record, doctor accepts launchd distill"
id: F-033
status: refined
epic: E-003
from_idea: I-046
---

# Recall failure is visible in the session

Slice 1 of E-003. Approved by the owner on 2026-11-28 as phase 0, items 2, 3 and 5 of the plan.

## Problem

The installed `vault-engine` lost its `context` command on 2026-11-13. The recall hook fails
open, so every interactive session ran without recall for 15 days and nothing said so. The
doctor's distill check also warns on a machine where the nightly job runs under launchd, not cron.

## Changes

1. `install.sh` (the `vault-engine` block): build to a temp path, run `<temp> context --cwd "$REPO"`,
   and install to `$BIN_HOME` (and copy to the AGY path) only when that exits 0. On failure print one
   line naming the reason, keep the installed binary, and carry on with the rest of the install.
2. `skills/agentic-vault/hooks/vault-recall.py`: on the first prompt of a session write exactly one record.
   - Engine exit 0 on the seed call: append `{ts, session_id, ok: true}` to `heartbeat.jsonl`.
   - Anything else (non-zero exit, timeout, missing binary, any exception that reaches the handler):
     append `{ts, session_id, kind, detail}` to `errors.jsonl`, `kind` one of `exit`, `timeout`,
     `missing`, `exception`, and print one context line telling the session that recall is down.
   - The session state file gains a `reported` flag, so the second engine call of a first prompt and
     every later prompt add nothing.
   - Both files live in the hook's state dir (`~/.claude/state/vault-recall/`, or `VAULT_RECALL_STATE`).
   - The hook still exits 0 in every case.
3. `bin/ps-skills-doctor` `check_vault_distill`: accept the launchd job `local.vault-distill` as well as a
   crontab line; warn only when neither exists.

## Acceptance criteria

- [ ] With `VAULT_ENGINE=/usr/bin/false`, a first prompt leaves 1 line in `errors.jsonl` with `kind: "exit"`, prints one recall-is-down line, and exits 0; a second run with the same session id leaves the count at 1.
- [ ] With an engine that sleeps past the hook timeout the one line has `kind: "timeout"`; with `VAULT_ENGINE=/nonexistent` it has `kind: "missing"`.
- [ ] With a working engine a first prompt adds 1 line to `heartbeat.jsonl` and 0 lines to `errors.jsonl`; a second prompt in the same session adds nothing to either.
- [ ] `install.sh` run with a `go` build whose binary fails `context` leaves the previously installed `vault-engine` byte-identical and prints the reason; with a good build it installs it.
- [ ] `check_vault_distill` returns no "no cron line" warning when `launchctl list` shows `local.vault-distill` and the crontab is empty, and still warns when both are absent.
- [ ] `python3 -m unittest tests.test_vault_recall tests.test_ps_skills_doctor_distill tests.test_install -v` ends with `OK`.

## Out of scope

Rebuilding the engine on this machine (done by hand on 2026-11-28), recall precision (F-031), and any change to what recall injects.
