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

## Decision (owner, 2026-11-11): option A, direct Gemini API

The owner first chose C (keep `agy`, accept the access). After seeing the cost (17,000 to 88,000 input tokens a call, 6 to 30 million tokens for the backlog) the owner switched: "แพงจริง ให้ใช้ API", "use AI Studio API key". OpenRouter was offered and declined.

- The key is the owner's Google AI Studio key, kept in the macOS Keychain (service `joy-companion`, account `gemini`); `~/.zshrc` exports it only through the `with-gemini-key` wrapper. `GEMINI_API_KEY` in the environment wins when set.
- Probed 2026-11-11 21:10 with a harmless prompt: `gemini-3.8-flash` and `gemini-4-argon` on `v1beta/models/<model>:generateContent` both returned the schema JSON with `finishReason` `STOP`. Usage of a one-line prompt: 15 prompt tokens (flash), against 17,000 or more through `agy`.
- A plain HTTP call has no tools, so the file-access risk of C is gone. The digest still goes to Google, which the standing external-send ruling covers. Reports and drafts sit in the vault, which has Obsidian Sync enabled.

## State before this change

The nightly job is meant to run with `VAULT_DISTILL_MAX=0`: Jev classification, the seen-file and the report work; 339 sessions wait as `extract-pending`. No `agy` call is made. The cron line is not installed yet (the owner runs it).

## Design

One file, `bin/vault-distill`, plus its tests and one README line.

1. `ask_agy` is replaced by `ask_gemini(model, prompt, schema)`: one `POST https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent` with `urllib`, timeout 120 s, body `{"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": schema, "maxOutputTokens": 8000}}`. The key goes in the `x-goog-api-key` header, never in the URL, so it cannot reach a log line.
2. Key lookup: `GEMINI_API_KEY` from the environment, else `security find-generic-password -s joy-companion -a gemini -w`. No key is a tool failure with the reason "no Gemini key (env GEMINI_API_KEY or Keychain joy-companion/gemini)".
3. Reading the reply: the answer is the text of the last part of `candidates[0].content.parts` that is not a thought, parsed with the existing `parse_json`. A `finishReason` other than `STOP`, no candidate, or a `promptFeedback.blockReason` is a tool failure whose reason names it. An HTTP error is a tool failure with the reason `HTTP <code> <error.status>`; the response body is not copied into the reason. Timeouts and connection errors are tool failures named by their exception class.
4. Models: `EXTRACT_MODEL = "gemini-3.8-flash"`, `REVIEW_MODEL = "gemini-4-argon"` (the AI Studio names of the models F-029 chose).
5. Two kinds of failure, told apart on the wire. A **tool failure** (design 2 and 3) is printed by `--extract-default` / `--review-default` as `{"fallback": true, "error": "<reason>"}` on stdout with exit 0. This is the contract `bin/jev-gate` already uses and `Run.call` already treats as a failure. A **bad answer** (unparsable, or an extractor answer without a `lesson` key) exits 1 with the reason on stderr.
6. `Run.call` puts the reason into the report. The text is `error` from a fallback reply, else the last line of the child's stderr, else the name of the exception (timeout, OS error). It appends `"<stage> failed: <text>"` to `run.notes`. The text is checked against `SECRET_RE` first (a match becomes "error text withheld"), then cut to one line of at most 200 characters. The same line is added once per run, and a stage adds at most 5 different lines.
7. A tool failure does not use up the session. Today a failed extract call marks the session `invalid`, which is final, so one night without `agy` login or quota would discard the 20 best sessions. After this change a session whose extract call had a tool failure goes back to `extract-pending` with a try count; at the third tool failure it is marked `invalid`. A bad answer is `invalid` at once, as F-029 R9f says.
8. Two tool failures in a row stop extraction for the night: the sessions not yet tried stay `extract-pending` and no further `agy` call is made. This saves 18 calls that would fail the same way.
9. Token use becomes visible. `--extract-default` adds `"tokens": <usageMetadata.totalTokenCount>` to its output, and the nightly run sums it into a new report count `extract_tokens`. shortcut: the review call (one a night) is not counted, because its output is a bare list; count it when the review seam changes shape.
10. Comments, the docstring and the test name `test_extract_default_is_one_tool_free_flash_call…` say "Gemini API call" instead of "agy print-mode call". The "Use no tools." line in both prompts may go: an API call has no tools.

## Requirements

- X1. The extractor and the reviewer shall each make one Gemini API call with the JSON schema and return the parsed object.
- X2. The API key shall be sent only in the `x-goog-api-key` header and shall not appear in any report line, note, stderr text or file the run writes.
- X3. When a stage call fails, the report shall name the stage and carry the reason (the fallback `error`, else the last stderr line, else the exception name), at most 200 characters on one line.
- X4. When the same error repeats in one run, the report shall carry it once; one stage shall add at most 5 different error lines.
- X5. When the full error text matches `SECRET_RE`, checked before it is cut, the report shall say "error text withheld" in its place.
- X8. When an extract call has a tool failure, the session shall return to `extract-pending` with its try count raised by one; at the third tool failure it shall be marked `invalid`.
- X9. When two extract calls in a row have a tool failure, the run shall make no further extract call that night and shall leave the untried sessions `extract-pending`.
- X11. An extractor answer without a `lesson` key shall count as a bad answer.
- X6. `bin/vault-distill` shall no longer call `agy`.
- X7. The README vault-distill paragraph shall say that the extractor and reviewer are direct Gemini API calls with no tools, where the key comes from, and that the report carries `extract_tokens`.
- X10. The report shall carry `extract_tokens`, the sum of `usageMetadata.totalTokenCount` over the night's extract calls.

## Acceptance criteria

Tests make no network call: they replace the HTTP call in process (the module is loaded with `load_distill()`), or point the code at a local stub server.

- [ ] Given a stubbed reply with `finishReason` `STOP` and the lesson JSON as text, when `--extract-default` runs, then it prints `{"path": …, "tokens": …}`, exits 0 and the draft has the five sections.
- [ ] Given a stubbed reply whose first part is a thought and whose last part holds the JSON, then the result is the same.
- [ ] Given a stubbed reply with `finishReason` `MAX_TOKENS`, when `--extract-default` runs, then it exits 0 and prints a fallback whose error names `MAX_TOKENS`.
- [ ] Given a stubbed HTTP 403, then the extractor prints a fallback whose error is `HTTP 403 <status>` and holds no part of the response body.
- [ ] Given no `GEMINI_API_KEY` and a Keychain lookup that fails, then the extractor prints a fallback naming the missing key and makes no HTTP call.
- [ ] Given a stubbed request, then the key is in the `x-goog-api-key` header, is not in the URL, and the body carries `responseJsonSchema`.
- [ ] Given a stubbed reply with a `verdicts` list, when `--review-default` runs, then it prints that list and exits 0, and the request went to `gemini-4-argon`.
- [ ] Given a nightly run whose extract command prints a fallback for one session and works for the next, then the first session is `extract-pending` with try count 1 and the second is processed.
- [ ] Given a session already at try count 2 whose extract call has a tool failure again, then it is marked `invalid`.
- [ ] Given a nightly run with 5 queued sessions whose extract command always prints a fallback, then exactly 2 extract calls are made and all 5 sessions are `extract-pending`.
- [ ] Given a nightly run whose extract command reports `"tokens": 1000` for each of 2 sessions, then the report shows `extract_tokens` 2000.
- [ ] Given a Jev stage call that returns a fallback with an error text, then the report has one line "<stage> failed: <that text>".
- [ ] Given a nightly run whose extract command fails three times with the same error text, then the report has one line "extract failed: <text>" and the failed count for extract is 3.
- [ ] Given a failing stage whose error text holds a string that matches `SECRET_RE`, then the report line says "error text withheld" and does not hold the string.
- [x] ~~Given any default call, then the logged argv has `--output-format json`, …~~ Struck: route A makes no `agy` call (review finding, 2026-11-11).
- [ ] Given any default call, then the request body has `thinkingConfig` `{"thinkingLevel": "low"}`.
- [ ] Given an `http.client.HTTPException` or a malformed reply shape, then the call is a fallback (tool failure), not a crash.
- [ ] Given a failed call that used tokens (fallback or bad answer), then its tokens are counted in `extract_tokens`.
- [ ] Given failures on calls 1, 3 and 4 and a success on call 2, then the night stops after call 4 (a success resets the two-in-a-row counter).
- [ ] Given an extract command that exits 1, then the session is `invalid` at once.
- [ ] `grep -n "agy" bin/vault-distill` finds no call to `agy`.
- [ ] `python3 -m unittest tests.test_vault_distill tests.test_vault_distill_drafts tests.test_vault_distill_audit tests.test_vault_distill_gemini_api -v` passes.

## Go-live (after ship; not run by CI)

- L1. `VAULT_DISTILL_MAX=2 vault-distill`, then `vault-distill --report | head -45`: the extract row shows 2 calls and 0 failed, `extract_tokens` is filled, and the other sessions stay `extract-pending`.
- L2. Cron cannot always read the login Keychain. Run L1 once more from cron's environment (`env -i HOME=$HOME PATH=/usr/bin:/bin $HOME/.local/bin/vault-distill` with `VAULT_DISTILL_MAX=1`). If the key is not found there, the owner puts `GEMINI_API_KEY` on the cron line's environment instead.
- L3. The cron line is installed without `VAULT_DISTILL_MAX=0` (default 20 extractions a night; 339 sessions wait, so at least 17 nights).
- L4. If L1 fails, the cron line keeps `VAULT_DISTILL_MAX=0` and the error text from the report goes into research.md.

## What this change touches

- `bin/vault-distill`: `ask_agy` replaced by `ask_gemini`, `extract_default`, `review_default`, `Run.call`, `extract_session`, `run_extractions`, report counts, two model constants, comments.
- `tests/test_vault_distill_drafts.py`: the fake-`agy` helper is replaced by the HTTP stub; one test is renamed. New tests go in a new file `tests/test_vault_distill_gemini_api.py`.
- `README.md`: the vault-distill paragraph (X7).
- `Run.call` also serves the Jev stages, so a Jev failure now adds a report line too (bounded by X4).
- Undo: revert the commit and put `VAULT_DISTILL_MAX=0` back on the cron line.

## Appendix: audit trail

- 2026-11-11 self-grill-audit: verdict safe-with-fixes, nothing critical. Confirmed on disk by the auditor: 339 `extract-pending`, the `text` flag, dropped stderr, the child's stderr reaching `Run.call`, no test pinned to the old flag. Corrected: Jev reports failure as a fallback on stdout, so the reason now comes from the fallback `error` first (design 4, X3); a failed call no longer discards the session (design 5 and 6, X8, X9; a narrow change to F-029 R9f for tool failures only); token use is now reported (design 7, X10); the non-SUCCESS rule contradicted its own test (design 2 and 3 now agree); "envelope" is defined and a missing `lesson` key is a failure (X11); the accepted-risk text said nothing about Obsidian Sync (added); the secret check runs before the cut (X5); "17 nights" is a lower bound. Not checked by the auditor: `num_turns` and status values of a tool-using run; whether Obsidian Sync is signed in. Open: none.
- 2026-11-11 cost: owner asked "แพงตรงไหน"; thinking tokens (billed as output) were most of each call, so both calls send `thinkingLevel: low` (probe: 152 to 14 tokens; `minimal` is refused). Default cap stays 20 a night, which fits the AI Studio free tier (about 20 requests a day per model). Owner approved.
- 2026-11-11 owner switched route C to route A (direct Gemini API, AI Studio key from Keychain) on cost. Design 1 to 4, X1, X2, X6, X7 and the model-call tests rewritten for the API; design 5 to 9 and X3 to X5, X8 to X11 carried over unchanged from the audited route-C spec. The API reply shape was probed live; not re-audited.
