---
title: "Automatic knowledge save and retrieve for agent sessions (Jev-gated)"
id: I-039
status: idea
---

# Automatic knowledge save and retrieve for agent sessions (Jev-gated)

User request, verbatim: "want it help auto save knowledge + auto retrieve knowledge to session" and "make sure it is token efficient".

## Goal

Agent sessions in any repo get the relevant agentic-vault notes without anyone asking, and lessons from finished sessions reach `04_Knowledge/` without anyone running a command, at a token cost small enough to leave on permanently.

The user will confirm this by (a) typing a prompt about a topic the vault covers in a new session and seeing a `<vault-context>` block naming the matching note, and (b) running `vault-distill --report` the next morning and seeing sessions gated, notes published, and bytes sent per stage.

## Problem (measured 2026-11-11)

- **Retrieve is dead.** The SessionStart hook `agent-harness/scripts/vault-bootstrap.py` runs `vault-engine context --cwd <dir>`. The binary has no `context` command, so it prints usage to stderr, the hook prints nothing and exits 0.
- **Save stores pointers, not knowledge.** The Stop hook `vault-session-summary.sh` appends one line (repo, cwd, session id, transcript path) per turn to `_inbox/agent/session-summaries.md`. The file is 5,730 lines and 2 MB. Nothing reads it.
- **The nightly summarizer reads another vault.** Cron `55 23 * * *` runs `vault-nightly-summary.sh`, which reads `obsidian-vault/wiki/meta/session-inbox.md`, not the agentic-vault inbox.
- **Search matches only id, title and path.** `SearchIndexes` in `tools/vault-engine/pkg/vault/vault.go:1104` never reads tags or bodies. Queries `codex`, `worktree`, `quota`, `handoff` return nothing across 27 knowledge notes.

## Non-goals

- Embeddings, vector stores, or a long-running daemon.
- Changing the Stop hook, `vault-bootstrap.py`, or the old nightly script in `agent-harness`.
- The Joy voice vault (S3). This is the agentic vault only.
- Retrieval for AGY / T3 Code sessions (their hooks are disabled, see `install.sh` line 102).
- Rewriting or merging existing knowledge notes automatically. The extractor may only propose.

## Users & jobs

The owner, working through Claude Code sessions across many repos. They want a session to start already knowing the traps and decisions recorded earlier, and they do not want to remember to write lessons down.

## Success measure

- Retrieval: on a fixed set of 20 prompts with a known matching note, the right note is in the injected set for at least 16.
- Save: over 7 nights, at least 80% of auto-published notes are still unarchived after the owner's weekly look.
- Cost: median injected context per session is at most 2,400 bytes. A nightly run sends at most 12 KB per session to Jev and runs at most 20 extractions.

## Token budget (hard limits, all enforced in code and tested)

| Where | Limit |
|---|---|
| SessionStart `<vault-context>` block | 800 bytes |
| Per-prompt injection | 3 notes, 1,200 bytes, and nothing at all below the score threshold |
| Per-session total injection | 6 distinct notes, 2,400 bytes; a note is injected once per session |
| Injected form | id, title, one-line summary, path. Never the note body; the agent reads the note if it needs it |
| Session digest sent to Jev | 12,000 bytes (first 2,000 + last 10,000), tool output stripped |
| Extractor input | the same digest, never the raw transcript |
| Extractor runs | only on a confident yes; at most 20 per night (`VAULT_DISTILL_MAX`) |
| Draft note size | 1,500 bytes |
| Review | one Argon-low call for the whole night's drafts |

## Requirements

### Slice 1: retrieve (no LLM calls)

- R1. When `vault-engine context --cwd <dir>` runs, the engine shall print a `<vault-context>` block of at most 800 bytes listing knowledge notes whose `project_ids` or tags match the repo name of `<dir>`, newest first.
- R1f. If no note matches or the vault is missing, then the engine shall print nothing and exit 0.
- R2. When `vault-engine context --query <text>` runs, the engine shall score each note in `04_Knowledge/` by the number of distinct query terms (lower-case, at least 4 characters, stop words removed) found in the title (weight 3), tags (weight 2) and body (weight 1), and print the top 3 notes with a score of at least 4.
- R2f. If no note reaches the threshold, then the engine shall print nothing and exit 0.
- R3. When the user submits a prompt, the `vault-recall.py` UserPromptSubmit hook shall pass the prompt to `context --query` and emit the result as additional context.
- R3f. If the engine is missing, errors, or takes longer than 2 seconds, then the hook shall emit nothing and exit 0.
- R4. While a session is running, the hook shall not inject a note id it has already injected in that session, and shall stop injecting after 6 notes or 2,400 bytes.
- R5. Where the prompt is shorter than 12 characters, starts with `/`, or `VAULT_CONTEXT_BOOTSTRAP=0` is set (worker and subagent sessions), the hook shall do nothing.

### Slice 2: save (nightly batch)

- R6. When `vault-distill` runs, it shall rename `_inbox/agent/session-summaries.md` to a dated work file (an atomic rename, so the Stop hook's next append starts a fresh file), keep one entry per session id, and skip sessions already recorded in its seen-file. Sessions active in the last 30 minutes are written back to the live file for the next run.
- R7. When a session is selected, `vault-distill` shall build a digest of at most 12,000 bytes from the transcript: user prompts and the last assistant text of each turn, with tool output removed.
- R7f. If the transcript file is missing or unreadable, then the session shall be marked seen with reason `no-transcript` and skipped.
- R8. When a digest is built, `jev-gate classify-lesson` shall return the probability that it holds a durable lesson, decision or trap. At 0.85 or above the session is extracted; at 0.15 or below it is dropped; in between it is listed in `_inbox/agent/distill/unsure.md`.
- R8f. If `TYPESAFE_API_KEY` is unset or the call fails, then the session shall be treated as unsure and no extractor shall run.
- R9. When a session is extracted, a flash worker (`gemini-3.8-flash-high` through `dispatch-worker --agent agy`) shall write one `knowledge/v1` draft of at most 1,500 bytes to `_inbox/agent/distill/`, citing the session id, after running `context --query` on its own title; if an existing note covers the lesson it shall write a proposed addition naming that note id instead of a new note.
- R9f. If the draft fails `vault-engine validate` or the worker fails, then the draft shall stay in the inbox marked `invalid` and shall not be published.
- R10. When the night's drafts exist, one Argon-low review call shall return publish or reject with a reason for each, and `vault-distill` shall run `vault-engine publish-knowledge` for each publish verdict with the tag `auto-distilled`.
- R10f. If the review call fails, then no draft shall be published and all drafts shall stay in the inbox.
- R11. When a digest or draft matches the secret scan, it shall be written to `_inbox/private/` and shall not be sent to any model.
- R12. When `vault-distill --report` runs, it shall print for the last run: sessions seen, dropped, unsure, extracted, published, rejected, and bytes sent per stage.
- R13. When `vault-distill` finishes, it shall delete the dated work file, so pointer lines for seen sessions are gone and the inbox stops growing.
- R13f. If the run crashes before finishing, then the dated work file shall remain and the next run shall process it first.

## Acceptance criteria

- [ ] Given the current vault, when `vault-engine context --query "codegen drift gate fails in CI"` runs, then the output names `CONCEPT-codegen-drift-gate` and is at most 1,200 bytes.
- [ ] Given the current vault, when `vault-engine context --query "zzzz qqqq"` runs, then stdout is empty and the exit code is 0.
- [ ] Given a new Claude Code session in `ps-skills`, when the SessionStart hook runs, then `vault-bootstrap.py` prints a `<vault-context>` block of at most 800 bytes, or nothing if no note is tied to the repo.
- [ ] Given a hook payload whose prompt matches a note, when `vault-recall.py` runs twice with the same session id, then the first run emits the note and the second emits nothing.
- [ ] Given `vault-engine` removed from PATH, when `vault-recall.py` runs, then it exits 0 with empty stdout in under 2 seconds.
- [ ] Given an inbox with 40 pointer lines for 3 session ids, when `vault-distill --dry-run` runs with stubbed Jev answers 0.95, 0.05 and 0.5, then it reports extracted 1, dropped 1, unsure 1 and sends 3 digests of at most 12,000 bytes each.
- [ ] Given `TYPESAFE_API_KEY` unset, when `vault-distill` runs, then every session is reported unsure and no worker is dispatched.
- [ ] Given a draft containing a string that matches the secret scan, when `vault-distill` runs, then the draft is in `_inbox/private/` and the report shows 0 bytes sent for it.
- [ ] Given a review verdict of reject for a draft, when `vault-distill` finishes, then `04_Knowledge/` is unchanged and the draft is still in the inbox with the reason.
- [ ] Given 30 past sessions labelled lesson / no lesson, when `jev-gate classify-lesson` scores them, then at most 3 sessions labelled lesson score 0.15 or below.

## End-to-end verification

`bash tools/vault-engine/test_e2e.sh` extended with one case: seed a temp vault with two notes and a fake transcript, run `vault-distill` with stubbed Jev, extractor and reviewer, then assert `context --query` returns the newly published note and `_meta/events/` holds one publish event by `agent-distiller`.

## Interfaces & files

- `tools/vault-engine/cmd/vault-engine/main.go`, `pkg/vault/`: new `context` command and scoring, with Go tests.
- `skills/agentic-vault/hooks/vault-recall.py`: new UserPromptSubmit hook. `install.sh` links it; registering it in `~/.claude/settings.json` is one manual entry.
- `bin/jev-gate`: new `classify-lesson` subcommand, same shape as `triage-spec`.
- `bin/vault-distill`: new stdlib Python CLI. `install.sh` adds it to the bin list.
- Cron: one new line for `vault-distill` at 23:40.
- `tests/test_vault_recall.py`, `tests/test_vault_distill.py`, `tests/test_jev_gate.py` additions.
- `README.md` and `skills/agentic-vault/SKILL.md`: document the two commands, the hook, and the env vars `VAULT_DISTILL_MAX`, `VAULT_DISTILL_SKIP_REPOS`.

## Alternatives considered

- **Do nothing.** Retrieval stays silently dead and the inbox grows 2 MB of unread pointers.
- **Enable the installed `claude-mem` plugin.** Works without new code, but adds a second store outside the vault with no OCC commits, no schema and no review before a lesson becomes durable.
- **Embeddings.** Better recall than keywords, but needs a model call per prompt or a local index. Not justified for 27 notes; revisit above about 2,000 notes or if the 20-prompt recall set drops below 16.
- **Extract in the Stop hook.** Stop fires every turn, so one session would be gated many times. A nightly batch sees each session once.

## Assumptions

- ASSUMED: slice 1 (retrieve) ships before slice 2 (save) — reversible: Y
- ASSUMED: keyword scoring with threshold 4 and no embeddings — reversible: Y
- ASSUMED: new hook and CLIs live in `ps-skills`; `agent-harness` scripts are not edited — reversible: Y
- ASSUMED: the old 23:55 nightly script is left running; its stale vault path is filed as a separate backlog line — reversible: Y
- ASSUMED: seen-sessions state is a plain file at `~/.claude/state/vault-distill-seen.txt` — reversible: Y
- ASSUMED: the secret scan reused is the one `ps-skills-sync --push` runs; confirm its entry point when planning — reversible: Y
- ASSUMED: the 30-session calibration set is labelled by Argon-low and the owner spot-checks 10 — reversible: Y
- ASSUMED: notes are published automatically after the Argon review, tagged `auto-distilled`, and undone by moving to `_archive/` — reversible: Y
- ASSUMED: session digests from every repo may be sent to TypeSafe (Jev) and Gemini after the secret scan, except repos named in `VAULT_DISTILL_SKIP_REPOS` — reversible: N (sent data cannot be recalled)
