---
title: "vault-distill extractor: agy call fails on its flags and is not tool-less (found in go-live G4)"
id: F-030
status: refined
from_idea: I-042
---

# vault-distill extractor and reviewer call (follow-up to F-029, slice 2 of I-039)

Owner's goal, verbatim: "want it help auto save knowledge + auto retrieve knowledge to session", "make sure it is token efficient", "robust, production grade".

## Problem (measured 2026-11-11, go-live step G4 of F-029)

`ask_agy` in `bin/vault-distill` runs `agy -p … --mode plan --disable-slash-commands --sandbox --json-schema <schema> --output-format text`. Checked with harmless test prompts and dummy files only:

1. **The call fails at once.** `agy` exits 1 with "--json-schema can only be used when --output-format is 'json' or 'stream-json'". Reproduced again at 20:30. `ask_agy` drops stderr, so `--extract-default` printed nothing and exited 1. No extraction or review can run.
2. **With `--output-format json` it works.** The reply is one JSON envelope with the keys `conversation_id`, `duration_seconds`, `json_schema`, `num_turns`, `response` (the answer as text), `status` (`SUCCESS` on a good run), `structured_output` (the answer as an object) and `usage`.
3. **`--disable-slash-commands` turns plan mode off** ("--mode plan has no effect while slash command expansion is disabled").
4. **The call is not tool-less, with or without plan mode.** Probe at 20:40, empty temp directory as cwd, no `--dangerously-skip-permissions`, a dummy directory under the home directory. Both `--mode plan --sandbox` and `--mode plan --sandbox --disable-slash-commands` read the dummy file and created a new file next to it. `agy --help` lists no flag that removes tools. F-029 plan Deviation 1 assumed zero tool calls.
5. **Each call carries 17,000 to 28,000 input tokens** of agent overhead for a one-line prompt. A call that uses tools costs more: the two probe calls used 55,556 and 87,772 input tokens.

## Decision (owner, 2026-11-11): option C

The owner was shown the options (A direct Gemini HTTP call with a key, B `agy` inside an OS sandbox, C `agy` as it is, D extraction stays off) and the risk of C, and chose **C: keep `agy` and accept the access**.

Accepted risk, recorded so nobody reads this later as an oversight:

- The digest is untrusted text (assistant output can quote fetched pages). An instruction hidden in it can make the model read a file under the home directory, which then reaches Google's servers in that conversation, or write a file under the home directory.
- The job runs unattended at night over sessions from every repo.
- What limits it: the digest is scanned for credential patterns before the call and the draft after it (pattern-based, so an unknown key format passes); shell commands were blocked in the probe; the vault has no git remote.
- The vault is not machine-local: the Obsidian Sync plugin is enabled in the vault's settings, and reports, drafts and error lines are written under `_inbox/agent/distill/`. Whatever lands there can reach the owner's other devices through that sync. Whether sync is signed in was not checked.

Requirement X2 of the first draft ("shall not be able to read or write any path outside a temp directory") is dropped with this decision. Options A and B stay possible later without changing the caller: the seams `VAULT_DISTILL_EXTRACT_CMD` and `VAULT_DISTILL_REVIEW_CMD` already exist.

## State before this change

The nightly job is meant to run with `VAULT_DISTILL_MAX=0`: Jev classification, the seen-file and the report work; 339 sessions wait as `extract-pending`. No `agy` call is made. The cron line is not installed yet (the owner runs it).

## Design

One file, `bin/vault-distill`, plus its tests and one README line.

1. `ask_agy` uses the flag set that was probed: `--mode plan --disable-slash-commands --sandbox --json-schema <schema> --output-format json`. `--disable-slash-commands` stays because the digest is untrusted and must not be expanded as a slash command or skill. `--mode plan` stays only so the shipped flags equal the probed flags.
2. `ask_agy` reads the envelope. A reply is an envelope when it is a JSON object with a `status` key. A status other than `SUCCESS` is a tool failure. With `SUCCESS`, the answer is `structured_output` when that is an object, else the JSON found in `response`. A reply that is not an envelope is parsed as before. An extractor answer without a `lesson` key is a bad answer, not "no lesson".
3. Two kinds of failure, told apart on the wire. A **tool failure** (`agy` exits non-zero, times out, cannot start, or returns a status other than `SUCCESS`) is printed by `--extract-default` / `--review-default` as `{"fallback": true, "error": "<reason>"}` on stdout with exit 0. This is the contract `bin/jev-gate` already uses and `Run.call` already treats as a failure. A **bad answer** (unparsable, or no `lesson` key) exits 1 with the reason on stderr.
4. `Run.call` puts the reason into the report. The text is `error` from a fallback reply, else the last line of the child's stderr, else the name of the exception (timeout, OS error). It appends `"<stage> failed: <text>"` to `run.notes`. The text is checked against `SECRET_RE` first (a match becomes "error text withheld"), then cut to one line of at most 200 characters. The same line is added once per run, and a stage adds at most 5 different lines.
5. A tool failure does not use up the session. Today a failed extract call marks the session `invalid`, which is final, so one night without `agy` login or quota would discard the 20 best sessions. After this change a session whose extract call had a tool failure goes back to `extract-pending` with a try count; at the third tool failure it is marked `invalid`. A bad answer is `invalid` at once, as F-029 R9f says.
6. Two tool failures in a row stop extraction for the night: the sessions not yet tried stay `extract-pending` and no further `agy` call is made. This saves the tokens of 18 calls that would fail the same way.
7. Token use becomes visible. `--extract-default` adds `"tokens": <usage.total_tokens>` to its output, and the nightly run sums it into a new report count `extract_tokens`. shortcut: the review call (one a night) is not counted, because its output is a bare list; count it when the review seam changes shape.
8. The comment above the default extractor, the `ask_agy` docstring and the name of the test `test_extract_default_is_one_tool_free_flash_call…` stop saying the call has no tools. The "Use no tools." line in both prompts stays: it is an instruction to the model, not a claim.

## Requirements

- X1. The extractor and the reviewer call shall return the structured object from the `agy` JSON envelope.
- X2. (dropped, see Decision.)
- X3. When a stage call fails, the report shall name the stage and carry the reason (the fallback `error`, else the last stderr line, else the exception name), at most 200 characters on one line.
- X4. When the same error repeats in one run, the report shall carry it once; one stage shall add at most 5 different error lines.
- X5. When the full error text matches `SECRET_RE`, checked before it is cut, the report shall say "error text withheld" in its place.
- X6. The `agy` call shall keep `--disable-slash-commands` and `--sandbox`, and shall not carry `--dangerously-skip-permissions` or `--add-dir`.
- X8. When an extract call has a tool failure, the session shall return to `extract-pending` with its try count raised by one; at the third tool failure it shall be marked `invalid`.
- X9. When two extract calls in a row have a tool failure, the run shall make no further extract call that night and shall leave the untried sessions `extract-pending`.
- X10. The report shall carry `extract_tokens`, the sum of `usage.total_tokens` over the night's extract calls.
- X11. An extractor answer without a `lesson` key shall count as a bad answer.
- X7. The README shall say that the default extractor and reviewer are `agy` agent calls that can read and write files under the home directory, and that the owner accepted this on 2026-11-11.

## Acceptance criteria

- [ ] Given a fake `agy` that prints the envelope with `status` `SUCCESS` and the lesson in `structured_output`, when `--extract-default` runs, then it prints `{"path": …}`, exits 0 and the draft has the five sections.
- [ ] Given an envelope whose `structured_output` is null and whose `response` holds the JSON as text, when `--extract-default` runs, then the result is the same.
- [ ] Given an envelope with `status` other than `SUCCESS`, when `--extract-default` runs, then it exits 0 and prints `{"fallback": true, "error": …}` with the status in the error.
- [ ] Given a fake `agy` that exits 1 with "Error: boom" on stderr, when `--extract-default` runs, then it exits 0 and prints a fallback whose error contains "boom".
- [ ] Given an envelope with `SUCCESS` whose answer has no `lesson` key, when `--extract-default` runs, then it exits non-zero and writes no draft.
- [ ] Given a nightly run whose extract command prints a fallback for one session and works for the next, then the first session is `extract-pending` with try count 1 and the second is processed.
- [ ] Given a session already at try count 2 whose extract call has a tool failure again, then it is marked `invalid`.
- [ ] Given a nightly run with 5 queued sessions whose extract command always prints a fallback, then exactly 2 extract calls are made and all 5 sessions are `extract-pending`.
- [ ] Given a nightly run whose extract command reports `"tokens": 1000` for each of 2 sessions, then the report shows `extract_tokens` 2000.
- [ ] Given a Jev stage call that returns a fallback with an error text, then the report has one line "<stage> failed: <that text>".
- [ ] Given a fake `agy` that prints the envelope with a `verdicts` list, when `--review-default` runs, then it prints that list and exits 0.
- [ ] Given a nightly run whose extract command fails three times with the same stderr text, then the report has one line "extract failed: <text>" and the failed count for extract is 3.
- [ ] Given a failing stage whose stderr holds a string that matches `SECRET_RE`, then the report line says "error text withheld" and does not hold the string.
- [ ] Given any default call, then the logged argv has `--output-format json`, `--json-schema`, `--disable-slash-commands` and `--sandbox`, and has neither `--dangerously-skip-permissions` nor `--add-dir`.
- [ ] `python3 -m unittest tests.test_vault_distill tests.test_vault_distill_drafts tests.test_vault_distill_audit -v` passes.

## Go-live (after ship; not run by CI)

- L1. `VAULT_DISTILL_MAX=2 vault-distill`, then `vault-distill --report | head -45`: the extract row shows 2 calls and 0 failed, and the two sessions left `extract-pending`.
- L2. The cron line is installed without `VAULT_DISTILL_MAX=0` (default 20 extractions a night; 339 sessions wait, so the backlog needs at least 17 nights, more when new sessions and re-screened `unsure-pending` sessions take slots).
- L3. If L1 fails, the cron line keeps `VAULT_DISTILL_MAX=0` and the error text from the report goes into this idea's research.md.

## What this change touches

- `bin/vault-distill`: `ask_agy`, `extract_default`, `review_default`, `Run.call`, two comments.
- `bin/vault-distill` also: `extract_session` and `run_extractions` (X8, X9), the report counts (X10).
- `tests/test_vault_distill_drafts.py`: the fake `agy` learns to print an envelope, to exit non-zero and to write stderr; one test is renamed. New tests go in a new file `tests/test_vault_distill_agy_envelope.py`.
- `README.md`: the vault-distill paragraph (X7).
- `Run.call` also serves the Jev stages, so a Jev failure now adds a report line too (bounded by X4).
- Undo: revert the commit and put `VAULT_DISTILL_MAX=0` back on the cron line.

## Appendix: audit trail

- 2026-11-11 self-grill-audit: verdict safe-with-fixes, nothing critical. Confirmed on disk by the auditor: 339 `extract-pending`, the `text` flag, dropped stderr, the child's stderr reaching `Run.call`, no test pinned to the old flag. Corrected: Jev reports failure as a fallback on stdout, so the reason now comes from the fallback `error` first (design 4, X3); a failed call no longer discards the session (design 5 and 6, X8, X9; a narrow change to F-029 R9f for tool failures only); token use is now reported (design 7, X10); the non-SUCCESS rule contradicted its own test (design 2 and 3 now agree); "envelope" is defined and a missing `lesson` key is a failure (X11); the accepted-risk text said nothing about Obsidian Sync (added); the secret check runs before the cut (X5); "17 nights" is a lower bound. Not checked by the auditor: `num_turns` and status values of a tool-using run; whether Obsidian Sync is signed in. Open: none.
