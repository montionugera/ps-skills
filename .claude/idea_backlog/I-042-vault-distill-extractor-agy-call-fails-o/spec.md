---
title: "vault-distill extractor: agy call fails on its flags and is not tool-less (found in go-live G4)"
id: I-042
status: idea
---

# vault-distill extractor and reviewer call (follow-up to F-029, slice 2 of I-039)

Owner's goal, verbatim: "want it help auto save knowledge + auto retrieve knowledge to session", "make sure it is token efficient", "robust, production grade".

## Problem (measured 2026-11-11, go-live step G4 of F-029)

`ask_agy` in `bin/vault-distill` runs `agy -p … --mode plan --disable-slash-commands --sandbox --json-schema <schema> --output-format text`. Checked with harmless test prompts only:

1. **The call fails at once.** `agy` exits 1 with "--json-schema can only be used when --output-format is 'json' or 'stream-json'". `ask_agy` drops stderr, so `--extract-default` printed nothing and exited 1. No extraction or review can run.
2. **With `--output-format json` it works.** The reply is an envelope: `status`, `num_turns`, `response` (the JSON as text) and `structured_output` (the object).
3. **`--disable-slash-commands` turns plan mode off** ("--mode plan has no effect while slash command expansion is disabled").
4. **The call is not tool-less.** With `--mode plan --sandbox`, no `--dangerously-skip-permissions` and an empty temp directory as cwd, the model created a file in a different directory and read a file under the home directory. Only the shell command was blocked. F-029 plan Deviation 1 assumed zero tool calls.
5. **Each call carries 17,000 to 28,000 input tokens** of agent overhead for a one-line prompt.

The digest is untrusted text (assistant output can quote fetched pages). An unattended nightly model call that can read and write under the home directory is a prompt-injection path to secrets and to files outside the inbox.

## State after go-live

The nightly job runs with `VAULT_DISTILL_MAX=0`: Jev classification, the seen-file and the report work; sessions picked for extraction wait as `extract-pending`. No `agy` call is made.

## Options (owner's call)

- A. One direct Gemini HTTP call with a key the owner provides. No tools, and about a tenth of the tokens.
- B. Keep `agy`, run it inside an OS sandbox (`sandbox-exec`) that allows only its own config directory and a temp directory.
- C. Keep `agy` as it is and accept the access (the spec's own route, `dispatch-worker --agent agy`, has more).

## Requirements (once the option is chosen)

- X1. The extractor and the reviewer call shall return the structured object, and a failed call shall put the tool's error text in the run's notes.
- X2. The extractor and the reviewer shall not be able to read or write any path outside a temp directory. A test probe proves it.
- X3. When X1 and X2 hold, remove `VAULT_DISTILL_MAX=0` from the cron line.

## Acceptance criteria

- [ ] Given a digest and a stubbed model reply in the real envelope shape, when `--extract-default` runs, then it prints `{"path": …}` and exits 0.
- [ ] Given a model call that exits non-zero, then the report names the stage and carries the error text.
- [ ] Given the live extractor and a probe prompt asking it to write outside its directory and read a home file, then both fail.
