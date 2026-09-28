# Agentic Second Brain Design

**Date:** 2026-09-28  
**Status:** Proposed design; no live migration or installation authorized  
**Sources:** [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain), [architecture](https://github.com/eugeniughelbur/obsidian-second-brain/blob/main/architecture.md), [AI-first rules](https://github.com/eugeniughelbur/obsidian-second-brain/blob/main/references/ai-first-rules.md), [local research comparison](../../../research/agentic-vault-landscape-2026-09-28.md)

## Orientation

Build a full second brain around the experience shown in the reference repository: durable memory, daily work, contextual recall, thinking tools, research, multimedia ingestion, and optional maintenance. Preserve the existing vault's notes and IDs. Use the reference project as the primary skill and interaction candidate, while one local gateway governs canonical writes. This boundary is a design default pending a user preference; the isolated pilot does not depend on settling it.

<div class="callout info">The reference README describes a broad feature catalogue. It is the product target for this design, not evidence that each feature already meets this vault's acceptance criteria.</div>

## Goals and boundaries

- A human can capture, find, understand, correct, and recover knowledge from Obsidian without learning agent internals.
- Claude, Codex, Gemini, and later agent CLIs consume one versioned command and note contract. Their adapters may differ; their behavior and write rules may not.
- Agents can propose in parallel, but cannot silently overwrite a human edit or another agent's result. Every canonical change has an actor, reason, source, prior revision, and observable outcome.
- Markdown remains portable and readable. Search indexes, views, workflow instances, and embeddings are rebuildable derivatives.
- A feature may be used interactively before it is eligible for unattended scheduling.

This design does not require replacing the current folder tree, deploying a cloud service, installing every upstream command, or enabling external research providers at bootstrap.

## Approaches considered

| Approach | Benefit | Cost and decision |
|---|---|---|
| Replace the vault and engine with the upstream repo | Broad feature surface quickly | Its documented commands write Markdown directly and its Claude write hook does not enforce this vault's OCC/event contract across CLIs. Reject as the target architecture. |
| Split ownership: upstream writes general memory; engine writes ideas/projects | Fastest interim experience | Two write protocols make cross-links, recovery, and audit harder to explain. Permit only inside an isolated pilot or with explicit directory ownership. |
| Upstream-inspired skill layer over one vault gateway | Broad experience with consistent writes, validation, and recovery | Requires adapters for upstream mutating commands. **Recommended target.** |

## System shape

<div class="schematic"><pre>
Human · agents · optional scheduler
                 │
                 ▼
       Commands and CLI adapters ──────► Bounded search and context
                 │                                │
                 ▼                                ▼
          Change proposals                Canonical Markdown
                 │                                ▲
                 ▼                                │
      Vault gateway: schema · actor · OCC ────────┘
                 │
                 ├──► Run and mutation events
                 └──► Rebuildable search index and Bases views
</pre></div>

The command layer expresses user intent and produces structured findings or proposals. The gateway is the sole agent write authority. Obsidian can change a note directly, but its native filesystem writes do not cooperate with a gateway lock. A file observer can detect and import such edits after the fact; it cannot guarantee that a human save in the compare-then-rename window will not be overwritten. Therefore unattended writes to human-editable notes are **blocked** until a coordinating Obsidian edit adapter or equally enforceable writer protocol passes the concurrent-write test. The interim mode takes a versioned prewrite snapshot and requires human review of agent proposals; if an uncoordinated write is detected, it pauses that note and exposes both revisions for recovery. Indexes never decide canonical state.

### Note ownership and shape

Keep `01_Ideas/`, `02_Projects/`, `03_Areas/`, `04_Knowledge/`, `_inbox/`, `_archive/`, and `_meta/`. Add logical collections for daily notes, people, decisions, research, tasks, and immutable source captures through a versioned folder map. Initially map them to `05_Daily/`, `06_People/`, `07_Decisions/`, `08_Research/`, `09_Tasks/`, and `_sources/`; existing files do not move during the pilot. No command may hard-code its own alternative mapping.

Managed records have an immutable ID independent of path; existing IDs remain unchanged. New managed records require frontmatter `schema`, `id`, `kind`, `title`, `created`, and `updated`, plus type-specific fields. Their body begins with a brief `## For future agent` summary and then human-readable sections. Existing navigation/MOC and legacy notes remain valid readable inputs even if they lack this shape; inventory and classify them before import, then migrate only with an explicit diff and backup. Changing claims point to a source and carry observation/validity dates; superseded claims remain traceable. Long research evidence lives in linked artifacts, not a large frontmatter object.

The schema definition is singular and versioned. The gateway validates it at writes, while a read-only linter finds legacy or human-edited violations. Skills and manifests name schema versions and logical collection names; generated adapters and docs are checked against that source.

### Change proposal and commit contract

A proposal contains `proposal_id`, `run_id`, `actor`, `operation` (`create`, `patch`, or `archive`), `target_id` or requested new type, `base_sha256`, structured changes, source references, confidence, reason, and idempotency key. Agent outputs also carry role/version, input revision, status (`complete`, `partial`, `failed`), findings, evidence, and error details. Invalid or missing outputs cannot be turned into scores by a default value.

The gateway checks actor capability at runtime, validates the note and transition, and rejects a stale or empty expected hash for updates. Before replacing a note, it durably records intent, the base revision, and a recoverable body snapshot. After the atomic note replacement it durably records the outcome; startup reconciliation completes or marks any interrupted transaction. The search index advances afterward and can be rebuilt. An event-write failure is a failed or recoverable transaction, never a successful commit with a missing audit record. A multi-note proposal is a journaled sequence of individually atomic commits: it reports partial completion and can resume or compensate. It never claims filesystem-wide atomicity. Retained body revisions, not frontmatter diffs alone, make an earlier note and overwritten text inspectable. The retention period and pruning policy are explicit and user-controlled.

The user sees an affected-note list and a diff before a broad rewrite, contradiction resolution, archive, or low-confidence decision. A stale note revision produces a conflict with re-read/rebase/abstain choices. Autonomous writes are limited to explicitly enabled, bounded policies; the default for thinking tools is to report or draft.

## Feature design

| Layer | User experience | First release behavior |
|---|---|---|
| Operations | Save a conversation; capture, daily, person, project, task, decision, recap, find, export, health | Adopt upstream command language where useful; route all mutations through proposals and search before create. |
| Thinking | Challenge, distill, connect, emerge, synthesize, reconcile, graduate | Ground output in retrieved notes and cite exact sources. Challenge/connect are read-only; synthesize/reconcile/graduate produce reviewable changes. |
| Context | `world`-style session boot and bounded recall | L0 identity, L1 navigation, L2 active work, L3 on-demand detail. Recall returns small cited excerpts and abstains at low confidence; it never injects the whole vault. |
| Research | Web, vault-first deep research, NotebookLM-style grounded answer, URL/PDF/audio/video ingest | Raw input is preserved by hash; source and inference are separate. External provider/upload, cost, and retention are shown before use. Missing optional providers degrade clearly. |
| Always on | Morning brief, nightly consolidation, weekly review, health, save reminders | Ship disabled. Enable read-only health and briefs first; scheduled writes use the gateway, bounded queue, lease, budget, audit, and recovery view. |

For video and podcast notes, retain source URL, transcript origin, timestamps, and whether frames or audio were actually analyzed. A transcript-only run must not imply that the model watched the video. For vault-grounded external services, preview the exact outbound note set, scan/redact secrets and personal data, and require an explicit per-run or durable provider setting. Record provider, purpose, upload time, retention/deletion promise, and deletion result; failure to verify deletion remains visible. No live price or availability claim is stored without an as-of date.

### User-facing supervision

The Obsidian dashboard and CLI show five queues: inbox, researching, review needed, failed/conflicted, and completed. Each run exposes its input note, agents, source links, proposed changes, final event, and retry or dismiss action. Bases may render these views, but metadata and workflow events remain the source. A read-only health command reports schema drift, stale claims, duplicates, broken links, orphan artifacts, failed runs, and index lag by severity. Repairs are separate proposals.

## Integration and migration

1. Inventory installed Obsidian commands, hooks, global aliases, and live-vault paths before registration. Pin the upstream commit and inspect its install/build scripts. Run its command set under isolated names and config against a disposable sample vault, never a global skills path. Exercise save, world, find, health, one thinking command, and one source ingest on the same fixture. Record files read/written, source preservation, CLI parity, and failure behavior. Its README and command files are inputs to this test, not proof of behavior.
2. Keep upstream files unmodified during the pilot; preserve license and provenance for any code later adapted. Resolve naming collisions before live registration.
3. Implement a folder-map adapter and gateway proposal adapter for one mutating command. Prove the resulting note remains readable in Obsidian. Run an adversarial save between hash comparison and rename: if coordinated writes cannot be enforced, keep auto-commit disabled and prove snapshot-based detection/recovery instead of claiming guaranteed OCC for direct Obsidian edits.
4. Import existing notes in place by validating and indexing them. Any later path migration is a separately reviewed operation with a mapping report, backup, reversible move plan, and link checks.
5. Publish one canonical command source and generate Claude/Codex/Gemini surfaces. Add a repository build/CI target that regenerates adapters and fails on any diff, then runs a shared fixture for path resolution, schema versions, command descriptions, capability restrictions, and equivalent result states across CLIs.

## Acceptance scenarios

- A saved conversation updates an existing decision/project note when search finds it, preserves the old text and source trail, and creates no duplicate.
- Bestie and Philip each produce schema-valid, cited artifacts for an idea. Missing or conflicting evidence yields `review needed`, never a fabricated candidate score.
- A human edits the target note before commit; a coordinated adapter rejects the stale proposal and leaves both versions inspectable. An adversarial uncoordinated Obsidian save during compare-and-rename must either be prevented by the chosen protocol or make unattended writes fail qualification; snapshot recovery is demonstrated in review-only mode.
- Crash injection immediately before and after note rename, and a simulated event-write failure, never yield an unreported success. Reconciliation identifies the final note revision and audit state.
- Two captures arriving together receive distinct immutable IDs. A repeated delivery with the same idempotency key creates one logical result.
- A process stops between the first and second note of a broad save; the run resumes or reports partial completion without claiming all notes were updated.
- `world` and recall load bounded, cited context; a low-confidence query injects nothing. The same known-note fixture is retrievable across supported CLIs.
- A scheduled run fails or exceeds its budget; the dashboard shows the failed run and leaves canonical notes unchanged unless completed commits are individually listed.
- Search and dashboard queries use a derived index on a 10,000-note fixture rather than scanning every Markdown file per request. The benchmark records reference hardware and p95 latency before a performance target is accepted.

## Open design decision

The recommended target routes every canonical agent write through the gateway. An alternative allows upstream skills to write general notes directly while the engine owns only structured records. The isolated pilot is safe under either model; live integration must choose one, encode it in runtime permissions and folder ownership, and test it before enabling writes.

## Appendix — audit trail

- 2026-09-28 initial design: broadened the product scope from idea triage to full second-brain operations, thinking, context, research, and optional automation.
- 2026-09-28 independent audit: safe with fixes. Corrected four high-priority gaps: direct Obsidian edits cannot share a gateway lock; note replacement and event logging need a durable recovery protocol; MOC/legacy notes need classification; isolated pilot must inventory command collisions before installation. Also added body history, outbound-data controls, and an executable adapter conformance gate. These are design requirements, not claims that the current engine implements them.
