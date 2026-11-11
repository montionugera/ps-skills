---
title: "vault-distill nightly knowledge save in shadow mode (I-039 slice 2)"
id: I-043
status: idea
from_idea: I-040
---

> **Scope of I-040:** slice 2 only (R6-R13, R16, R19, R10/R10f, R11/R11a and the save rows of the token budget). This is the spec the owner approved for I-039 / F-027, copied unchanged below; slice 1 shipped as F-027 on 2026-11-11 and slice 3 gets its own feature.


# Automatic knowledge save and retrieve for agent sessions (Jev-gated)

User request, verbatim: "want it help auto save knowledge + auto retrieve knowledge to session", "make sure it is token efficient", "consider speed , session result, knowledge reusability , scale , robust, production grade", "visibility + readiness", "auto integrate + publish if pass", and (on junk) "Token typesafe is cheap".

## Goal

Agent sessions in any repo get the relevant agentic-vault notes without anyone asking, and lessons from finished sessions are integrated and published into `04_Knowledge/` without anyone running a command, at a token cost small enough to leave on permanently.

The user will confirm this by (a) typing a prompt about a topic the vault covers in a new session and seeing a `<vault-context>` block naming the matching note and the terms that matched, (b) running `vault-distill --report` the next morning and seeing sessions gated, notes published or merged, bytes sent per stage and used-rate per note, and (c) running `ps-skills-doctor` and seeing the vault section all green.

## Problem (measured 2026-11-11)

- **Retrieve is dead.** The SessionStart hook `agent-harness/scripts/vault-bootstrap.py` runs `vault-engine context --cwd <dir>`. The binary has no `context` command, so the hook prints nothing and exits 0.
- **Save stores pointers, not knowledge.** The Stop hook `vault-session-summary.sh` appends one line (repo, cwd, session id, transcript path) per turn to `_inbox/agent/session-summaries.md`: 5,730 lines, 2 MB, read by nothing.
- **The nightly summarizer reads another vault.** Cron `55 23 * * *` runs `vault-nightly-summary.sh` against `obsidian-vault/wiki/meta/session-inbox.md`.
- **Search matches only id, title and path** (`SearchIndexes`, `tools/vault-engine/pkg/vault/vault.go:1101`). `codex`, `worktree`, `quota`, `handoff` return nothing across 27 notes.
- **`publish-knowledge` can overwrite a note.** `PublishKnowledge` (`vault.go:963`) writes with `os.WriteFile` and no existence check, and `commit` (`CommitRecord`, `vault.go:1004`) patches frontmatter only, so nothing can safely add to a note's body.

## Non-goals

- Embeddings, vector stores, or a long-running daemon.
- Editing the Stop hook, `vault-bootstrap.py`, or the old nightly script in `agent-harness`.
- The Joy voice vault (S3), and retrieval in AGY / T3 Code sessions (their hooks are disabled in `install.sh`).
- Rewriting or deleting existing note text. Integration only appends a dated section.

## Users & jobs

The owner, working through Claude Code sessions across many repos. They want a session to start already knowing recorded traps and decisions, and they do not want to remember to write lessons down or to approve each one.

## Success measure

- Retrieval: `tools/vault-engine/recall_eval.sh` over `tests/fixtures/vault_recall_set.jsonl` (20 prompts with an expected note id) scores at least 16.
- Session result: over 7 nights, at least 30% of injected notes are used (read or cited) in the session that received them.
- Save: over 7 nights, at least 80% of auto-published or auto-merged notes are still unarchived after the owner's weekly look, and at most 5 notes are published per night.
- Cost: median injected context per session is at most 2,400 bytes including SessionStart; a nightly run sends at most 12,000 bytes per session to Jev and runs at most 20 extractions.

## Quality attributes (each maps to requirements below)

| Attribute | How it is met |
|---|---|
| Token efficiency | Hard byte limits in the budget table; pointers injected, never bodies; extractor runs only on a confident yes |
| Speed | Query reads one index file; engine p95 at most 50 ms at 2,000 notes; hook p95 at most 150 ms, hard timeout 2 s (R2, R3) |
| Session result | Injection log plus a no-LLM used check; unused notes are demoted (R14, R15) |
| Reusability | Fixed note shape, project or global scope, merge into an existing note before creating one (R9, R10b) |
| Scale | Index scoring, inbox rotation, transcript offsets, nightly cap (R2, R6, R7) |
| Low junk | Evidence check, Jev draft score, recurrence before publish, probation with automatic archive, nightly publish cap (R9, R9c, R9d, R19, R20, R21) |
| Robustness | Every stage fails open to "parked in inbox"; file locks; idempotent publish; crash resume (all `f` rows) |
| Production grade | Tests in CI, end-to-end case, kill switches, non-zero exit on degraded runs, doctor check (R16, R17) |
| Visibility | Matched terms on each injected line; nightly report note; `--report` (R3, R12) |
| Readiness | `ps-skills-doctor` vault section; shadow mode that ends by itself when calibration passes (R17, R18) |

## Token budget (hard limits, enforced in code and tested)

| Where | Limit |
|---|---|
| SessionStart `<vault-context>` block | 800 bytes |
| Per-prompt injection | 3 notes, 1,200 bytes, nothing below the score threshold |
| Per-session total, including the SessionStart block | 6 distinct notes, 2,400 bytes; a note is injected once per session |
| Injected form | id, title, path, matched terms, and a summary of at most 120 bytes. Never more of the body |
| Session digest sent to Jev | 12,000 bytes (first 2,000 + last 10,000), tool output stripped |
| Extractor input | the same digest, never the raw transcript |
| Jev calls (cheap, per the owner) | one per session, one per draft, and at most 5 same-lesson comparisons per draft |
| Extractor runs | only on a confident yes, plus at most 3 unsure; at most 20 per night (`VAULT_DISTILL_MAX`) |
| Notes published or merged | at most 5 per night (`VAULT_DISTILL_PUBLISH_MAX`) |
| Draft note size | 1,500 bytes |
| Review | one Argon-low call per night, only for candidates that recurred or are high-stakes |

## Requirements

### Slice 1: retrieve (no LLM calls)

- R0. When `vault-engine rebuild-index` or `publish-knowledge` runs, the engine shall write for each knowledge note, into `_meta/indexes/knowledge.jsonl`: `tags`, `project_ids`, `summary` (the first non-heading body line, cut to 120 bytes) and `terms` (distinct lower-case body terms of 4 or more characters, at most 200).
- R1. When `vault-engine context --cwd <dir>` runs, the engine shall resolve `<dir>` to its main repo root (`git rev-parse --git-common-dir`, parent directory; `basename` of `<dir>` outside git), collect the ids of project notes whose `release_repo` equals that path, and print a `<vault-context>` block of at most 800 bytes listing knowledge notes whose `project_ids` contain one of those ids or whose tags contain `repo:<root basename>`, newest `updated` first.
- R1f. If no note matches or the vault is missing, then the engine shall print nothing and exit 0.
- R2. When `vault-engine context --query <text>` runs, the engine shall tokenise the query (split on non-alphanumerics, lower-case, keep terms of 4 or more characters, drop the stop-word list in `pkg/vault/stopwords.go`), and give each note a score equal to the sum, over each distinct query term, of the highest weight among the fields containing it (title 3, any tag 2, body terms 1). It shall print up to 5 notes that have status `active`, a score of at least 4 and at least one term matching the title or a tag, highest first, ties broken by newest `updated`, each with its matched terms, reading only the index file.
- R2f. If no note reaches the threshold or the index is missing, then the engine shall print nothing and exit 0.
- R2p. While the index holds 2,000 notes, `context --query` shall complete in at most 50 ms at p95 (Go benchmark).
- R3. When the user submits a prompt, the `vault-recall.py` UserPromptSubmit hook shall pass the prompt to `context --query`, drop demoted and already-injected ids, and emit the first 3 remaining notes (at most 1,200 bytes) as additional context.
- R3f. If the engine is missing, errors, or takes longer than 2 seconds, then the hook shall emit nothing and exit 0.
- R4. While a session is running, the hook shall keep `~/.claude/state/vault-recall/<session_id>.json` (`{"ids": [...], "bytes": N}`), updated under `fcntl.flock`. On its first run in a session it shall seed the file with the ids and bytes of `context --cwd <cwd>`. It shall not inject a recorded id and shall stop at 6 notes or 2,400 bytes. State files older than 7 days are deleted on each run.
- R5. Where the prompt is shorter than 12 characters, starts with `/`, or any of `VAULT_RECALL=0`, `VAULT_CONTEXT_BOOTSTRAP=0`, `CLAUDE_VAULT_SUMMARY=0` is set, the hook shall do nothing. (`CLAUDE_VAULT_SUMMARY=0` is already set in dispatch worker sessions, per `~/.claude/logs/vault-session-summary.log`.)

### Slice 2: save in shadow mode (nightly batch)

- R6. When `vault-distill` runs, it shall rename `_inbox/agent/session-summaries.md` to a dated work file (atomic, so the Stop hook's next append starts a fresh file) and keep one entry per session id. A session whose transcript mtime is within 30 minutes of the run start is appended back to the live file and not processed.
- R6f. If a dated work file from a crashed run exists, then the run shall process it first.
- R7. When a session is selected, `vault-distill` shall build a digest of at most 12,000 bytes from the transcript, starting at the byte offset recorded for that session in the seen-file (0 if none): user prompts and the last assistant text of each turn, tool output removed. A session whose transcript has grown by less than 4,000 bytes since its recorded offset is skipped.
- R7f. If the transcript is missing or unreadable, then the session shall be marked seen with reason `no-transcript`.
- R7s. When a digest is built, `vault-distill` shall prepend a signals line counted by script from the transcript: user corrections, test or command failures followed by a pass, hook blocks, and errors that repeat. The signals are input to Jev, never a gate: every allowed session is sent to Jev.
- R8. When a digest is built, `jev-gate classify-lesson --digest <path>` shall print `{"lesson_prob": <0..1>, "fallback": <bool>}`. At 0.85 or above the session is extracted; at 0.15 or below it is dropped; in between it is unsure.
- R8f. If no Jev key is found (env `TYPESAFE_API_KEY` or the `~/.zshrc` fallback in `_load_api_key`) or the call fails, then the session shall be treated as unsure and no extractor shall run for it that night.
- R8u. Unsure sessions shall be offered to Jev once more on the next run. If still unsure, the top 3 by probability (`VAULT_DISTILL_UNSURE_MAX`) go to the extractor and count toward `VAULT_DISTILL_MAX`; the rest are marked seen with reason `unsure`.
- R9. When a session is extracted, a flash worker (`gemini-3.8-flash-high` through `dispatch-worker --agent agy`) shall first run `context --query` on the lesson's title, then write one `knowledge/v1` draft of at most 1,500 bytes to `_inbox/agent/distill/`. The body shall be a one-sentence summary line followed by the sections `When this applies`, `Rule`, `Why`, `Source` (session id). Frontmatter shall carry the tag `auto-distilled` and either `project_ids` for the session's repo or, when the repo has no project note, the tag `repo:<name>`; a lesson that applies everywhere carries the tag `global`. If an existing note covers the lesson, the draft shall instead be a proposed addition naming that note id. The draft shall include an `Evidence` section quoting at least one string copied from the digest (an error message, command or file path). The worker may instead return `{"path": null, "reason": "no-lesson"}`, and the session is then marked seen with reason `no-lesson`.
- R9f. If the draft fails `vault-engine validate` or the worker fails, then the draft shall stay in the inbox marked `invalid`.
- R9c. If no quoted `Evidence` string is a substring of the digest, then the draft shall be marked `no-evidence` and go no further (script check, no model).
- R9d. When a draft passes R9c, `jev-gate score-draft --draft <path> --digest <path>` shall print `{"specific": p, "novel": p, "high_stakes": p}`, given the draft, the digest, the top 3 existing notes from `context --query`, and the first 20,000 bytes of `~/.claude/CLAUDE.md`. A draft with `specific` or `novel` below 0.5 is marked `junk` and goes no further.
- R9df. If the Jev call fails, then the draft shall stay in the inbox unscored and be scored on the next run.
- R19. When a draft passes R9d, it becomes a candidate in `_inbox/agent/distill/candidates/`. `jev-gate same-lesson` compares it with at most 5 existing candidates chosen by the R2 keyword score. A candidate goes to review only when a candidate from a different session matches at 0.85 or above (the two are merged, citing both sessions), or when its `high_stakes` is 0.85 or above (data loss, production failure, security). Candidates with no match after 60 days are removed and listed in the report.
- R10. When candidates are ready for review, one Argon-low review call shall return publish or reject with a reason for each.
- R10f. If the review call fails, then nothing shall be published or merged and all drafts shall stay in the inbox.
- R11. When a digest or draft matches `vault-distill`'s own copy of the credential patterns from `bin/ps-skills-sync` `SECRET_RE` (every pattern except `/Users/[a-z]+/`), it shall be written to `_inbox/private/` and not sent to any model.
- R11a. Where a session's repo is listed in `VAULT_DISTILL_SKIP_REPOS` (comma-separated repo root basenames), `vault-distill` shall mark it seen with reason `not-allowed` and send nothing. Every other repo is sent after the credential scan.
- R12. When `vault-distill` finishes, it shall write `_inbox/agent/distill/report-<date>.md` and make the same numbers available through `vault-distill --report`: sessions seen, not-allowed, dropped, unsure, no-lesson, extracted, no-evidence, junk, candidates waiting, published, merged, rejected, collisions, archived, bytes sent per stage, and used-rate per note.
- R13. `vault-distill` shall append a session id, its transcript offset and its final state to the seen-file immediately after that session reaches a final state, before the next session starts, and shall delete the dated work file when the run finishes.
- R16. When more than 50% of the night's sessions are unsure, or any stage fails for every session, `vault-distill` shall exit non-zero. Where `VAULT_DISTILL=0` is set it shall do nothing.

### Slice 3: auto integrate and publish, and the result loop

- R10a. When a new-note draft has a publish verdict and publishing is enabled, `vault-distill` shall run `vault-engine publish-knowledge <draft> <category> agent-distiller`, with the tag `probation` added, for at most 5 notes per night (highest `high_stakes`, then most sessions cited); the rest wait for the next run.
- R10af. If a note with the same path or the same `id` already exists, then `publish-knowledge` shall refuse with a non-zero exit (engine change) and the draft shall stay in the inbox marked `collision`.
- R10b. When a proposed-addition draft has a publish verdict and publishing is enabled, `vault-distill` shall read the target with `read-record`, then run `vault-engine commit <id> <sha> agent-distiller '{}' --append-body <file>` (engine change: appends the file as a dated section under the same flock and SHA check).
- R10bf. If the commit returns `OCC_CONFLICT`, then `vault-distill` shall re-read and retry once, and on a second conflict leave the draft in the inbox marked `conflict`.
- R18. While `~/.claude/state/vault-distill/calibrated` does not exist, publishing is disabled (shadow mode: drafts and verdicts are produced and reported, nothing is published or merged). `vault-distill --calibrate` scores four labelled sets under `tests/fixtures/vault_distill/` (30 sessions for the lesson gate, 20 drafts for `specific` and `novel`, 20 draft pairs for same-lesson, 20 drafts for high-stakes) and writes the marker only if every set has at most 10% of its positive examples scored below that job's threshold and at most 10% of its negative examples scored above it. Where `VAULT_DISTILL_PUBLISH=0` is set, publishing stays disabled.
- R14. When the hook injects a note, it shall append `{ts, session_id, note_id}` to `~/.claude/state/vault-recall/injections.jsonl`.
- R15. When `vault-distill` processes a session, it shall mark each injected note used if the transcript after the injection contains the note's path or id, and write per-note counts to `~/.claude/state/vault-recall/usage.json`. A note with at least 10 injections and 0 uses is demoted, and the hook drops demoted ids.
- R20. When a `probation` note is used once, `vault-distill` shall remove the tag through `vault-engine commit`.
- R21. When a `probation` note has 10 injections and 0 uses, or has not been injected for 60 days, `vault-distill` shall archive it through the engine and list it in the report. Notes without the `auto-distilled` tag are never archived automatically.
- R17. When `ps-skills-doctor` runs, its vault section shall check and report: the UserPromptSubmit hook is registered, `vault-engine context --query` on a known note title returns output, the index is newer than every note, a Jev key is found, the cron line exists, the last `vault-distill` run is under 36 hours old, and whether publishing is enabled.

## Acceptance criteria

- [ ] Given a temp vault with note A (title "codex quota") and note B (body only "codex quota handoff"), when `context --query "codex quota handoff"` runs, then A (score 6) is printed with its matched terms and B (score 3) is not.
- [ ] Given the current vault, when `context --query "zzzz qqqq"` runs, then stdout is empty and the exit code is 0.
- [ ] Given cwd `~/workspace/repos/atlas-world-svc/.claude/worktrees/F-001-x`, when `context --cwd` runs, then the output is at most 800 bytes and lists a note with `PROJ-atlas-world` in `project_ids`.
- [ ] Given a note with no summary field whose first body line is 300 bytes, when it is injected, then its summary is exactly 120 bytes.
- [ ] Given a 2,000-note index, when the Go benchmark runs, then `context --query` p95 is at most 50 ms.
- [ ] Given a stub engine returning 3 notes of 900 bytes each, when `vault-recall.py` runs for 3 prompts in one session, then total emitted bytes are at most 2,400, the state file lists at most 6 ids, and no id is emitted twice.
- [ ] Given `vault-engine` removed from PATH, or `CLAUDE_VAULT_SUMMARY=0` set, when `vault-recall.py` runs, then it exits 0 with empty stdout in under 2 seconds.
- [ ] Given an inbox with 40 pointer lines for 3 session ids and Jev stubbed to 0.95, 0.05 and 0.5, when `vault-distill --dry-run` runs, then it reports extracted 1, dropped 1, unsure 1 and sends 3 digests of at most 12,000 bytes each.
- [ ] Given a transcript touched 5 minutes before the run, when `vault-distill --dry-run` runs, then that session is not in the seen-file and its line is in the live inbox.
- [ ] Given `TYPESAFE_API_KEY` unset and `HOME` pointed at a temp dir with no `.zshrc`, when `vault-distill` runs, then every session is reported unsure, no worker is dispatched, and the exit code is non-zero.
- [ ] Given a digest that contains `/Users/x/repo` and no credential, when `vault-distill --dry-run` runs, then it is sent; given a digest containing `ghp_` plus 20 characters, then it is in `_inbox/private/` with 0 bytes sent.
- [ ] Given a session in a repo listed in `VAULT_DISTILL_SKIP_REPOS`, when `vault-distill` runs, then the report shows it as not-allowed with 0 bytes sent.
- [ ] Given a draft whose `Evidence` quote does not appear in the digest, when `vault-distill` runs, then it is marked `no-evidence` and no Jev call is made for it.
- [ ] Given Jev stubbed to `specific` 0.3 for a draft, when `vault-distill` runs, then the draft is marked `junk` and is not a candidate.
- [ ] Given one candidate from session S1 and no match, when `vault-distill` runs, then nothing is sent to review; given a second candidate from session S2 with same-lesson stubbed to 0.9, then one merged candidate citing S1 and S2 is sent to review.
- [ ] Given a single candidate with `high_stakes` stubbed to 0.9, when `vault-distill` runs, then it is sent to review without a second session.
- [ ] Given 8 publish verdicts in one night, when `vault-distill` finishes, then 5 notes are published and 3 remain candidates.
- [ ] Given a `probation` note with 10 injections and 0 uses, when `vault-distill` runs, then it is archived and listed in the report; given a human-written note with the same counts, then it is only demoted.
- [ ] Given no calibration marker, when `vault-distill` runs with a publish verdict, then `04_Knowledge/` is unchanged and the report shows the draft as "would publish".
- [ ] Given a publish verdict for a draft whose basename matches an existing note, when `vault-distill` finishes, then the existing note's sha256 is unchanged and the draft is marked `collision`.
- [ ] Given a proposed addition with a publish verdict, when `vault-distill` finishes, then the target note's body ends with the dated section, its earlier text is byte-identical, and `_meta/events/` holds one commit event by `agent-distiller`.
- [ ] Given a run killed after publishing session S1, when `vault-distill` runs again, then `04_Knowledge/` holds exactly one note citing S1.
- [ ] Given a transcript that contains an injected note's path after the injection, when `vault-distill` runs, then `usage.json` counts one use for that note; given a note with 10 injections and 0 uses, then the hook does not emit it.
- [ ] Given the hook unregistered, when `ps-skills-doctor` runs, then the vault section reports that check as failed and exits non-zero.

## End-to-end verification

`bash tools/vault-engine/test_e2e.sh`, extended with one case: seed a temp vault with two notes and a fake transcript, write the calibration marker, run `vault-distill` with stubbed Jev, extractor and reviewer, then pipe `{"session_id":"e2e","prompt":"<the published note's title>"}` into `skills/agentic-vault/hooks/vault-recall.py` with `VAULT_ROOT` at the temp vault, and assert the hook's `additionalContext` contains the published note id and `_meta/events/` holds one publish event by `agent-distiller`.

## Interfaces & files

- Before claim, run `psrw sync-main`: `bin/jev-gate` and `tests/test_jev_gate.py` exist on `main` but not yet on `release/1.12`.
- `tools/vault-engine/`: `context` command, index fields, `stopwords.go`, existence check in `publish-knowledge`, `--append-body` on `commit`, `recall_eval.sh`, Go tests and benchmark.
- `skills/agentic-vault/hooks/vault-recall.py`: UserPromptSubmit hook. `install.sh` links it; registering it in `~/.claude/settings.json` is one manual entry that the doctor check verifies.
- `bin/jev-gate`: `classify-lesson`, `score-draft` and `same-lesson`, same `_load_api_key` / `system_one` / fail-open structure as `cmd_triage_spec`.
- `bin/vault-distill`: stdlib Python CLI; `install.sh` adds it to the bin list. Stub seams: `VAULT_DISTILL_JEV_CMD`, `VAULT_DISTILL_EXTRACT_CMD`, `VAULT_DISTILL_REVIEW_CMD`; each gets input on stdin and returns JSON on stdout (Jev returns the JSON of the subcommand named in its first argument, extractor `{"path": str}`, reviewer `[{"draft": str, "verdict": "publish|reject", "reason": str}]`). Tests point them at scripts in `tests/fixtures/vault_distill/`.
- `bin/ps-skills-doctor`: vault section.
- Cron: one new line for `vault-distill` at 23:40.
- `tests/test_vault_recall.py`, `tests/test_vault_distill.py`, additions to `tests/test_jev_gate.py`, `tests/fixtures/vault_recall_set.jsonl`.
- `README.md` and `skills/agentic-vault/SKILL.md`: the commands, the hook, and the env vars `VAULT_RECALL`, `VAULT_DISTILL`, `VAULT_DISTILL_PUBLISH`, `VAULT_DISTILL_MAX`, `VAULT_DISTILL_UNSURE_MAX`, `VAULT_DISTILL_PUBLISH_MAX`, `VAULT_DISTILL_SKIP_REPOS`.

## Alternatives considered

- **Do nothing.** Retrieval stays silently dead and the inbox keeps growing unread.
- **Enable the installed `claude-mem` plugin.** No new code, but a second store outside the vault with no OCC commits, no schema and no review before a lesson becomes durable.
- **Embeddings.** Better recall, but a model call per prompt or a local index. Revisit above about 2,000 notes or if the recall set drops below 16 of 20.
- **Extract in the Stop hook.** Stop fires every turn, so one session would be gated many times. A nightly batch sees each session once.
- **Collision and append handled in `vault-distill` only.** Leaves `publish-knowledge` able to overwrite a note for every other caller; the fix belongs in the engine.

## Assumptions

- ASSUMED: three slices in order: retrieve, save in shadow mode, auto publish and result loop — reversible: Y
- ASSUMED: keyword scoring with threshold 4 and no embeddings — reversible: Y
- ASSUMED: new hook and CLIs live in `ps-skills`; `agent-harness` scripts are not edited — reversible: Y
- ASSUMED: the old 23:55 nightly script is left running; its stale vault path is a separate backlog line — reversible: Y
- ASSUMED: the SessionStart block counts toward the 2,400-byte session cap (tech lens; the QA lens proposed not counting it) — reversible: Y — raised by tech+qa
- ASSUMED: the calibration set is labelled by Argon-low and the owner spot-checks 10 — reversible: Y
- ASSUMED: a lesson is published only after it recurs in a second session, unless Jev scores it high-stakes; a one-off lesson that is important but not high-stakes waits as a candidate for 60 days and is then dropped — reversible: Y
- ASSUMED: the 0.5 thresholds for `specific` and `novel` are starting values that calibration may move — reversible: Y
- ASSUMED: archiving uses an existing engine path; if none exists, the plan adds `vault-engine archive <id> <sha> <actor>` — reversible: Y
- ASSUMED: the extractor is a single model call if AGY allows it, otherwise a `dispatch-worker` agent run — reversible: Y
- ASSUMED: integration appends a dated section and never rewrites existing text — reversible: Y
- ASSUMED: auto-published and auto-merged changes are undone by archiving the note or reverting the commit event — reversible: Y
- DECIDED (owner, 2026-11-11): session digests from every repo go to TypeSafe (Jev) and Gemini after the credential scan, except repos named in `VAULT_DISTILL_SKIP_REPOS` — reversible: N (sent data cannot be recalled). The product lens recommended an opt-in list; the owner chose the skip list.

## Appendix — spec review

- 2026-11-11 spec-review: lenses tech, qa, product (no UI terms, UX lens skipped). Findings 21 raw → 15 merged (6 dropped: bad citation 0, dup 6, low-conf 0).
  Applied: scoring rule made unambiguous (qa); `publish-knowledge` collision check and author argument (tech); summary source defined (qa+product+tech); repo resolved through `release_repo` and worktree root, plus `repo:<name>` tag (qa+product+tech); per-session state file and cap (qa+tech); stub seams named (qa); seen-file written per session, with transcript offsets (qa+product); "active" defined by transcript mtime (qa); end-to-end runs through the hook, recall set and script named (qa); unsure sessions resolved automatically (product); own credential patterns without the home-path rule (tech); `sync-main` before claim and `classify-lesson` output shape (tech); worker opt-out through an env var already set (tech); `.zshrc` key fallback in R8f and its test (tech).
  Answered from disk: 0. Asked at gate: 1 (which repos may send digests to external models). Assumed: 1 (session cap counting).
- 2026-11-11 owner additions after the review started: quality attributes table (speed, session result, reusability, scale, robustness, production grade, visibility, readiness) and automatic integrate and publish on pass (R10a, R10b, R18). These were not seen by the lenses.
- 2026-11-11 owner additions on junk and cost: evidence check, Jev draft score, recurrence before publish, probation with automatic archive, publish cap of 5, and Jev used for every screening step because TypeSafe tokens are cheap (R7s, R9c, R9d, R19, R20, R21). Not seen by the lenses.
- 2026-11-11 gate: owner approved the spec as recommended and chose the skip list for external sends.
- 2026-11-11 plan audit: R2 tightened (status `active`, one title or tag match required) to stop body-only matches on common words.
