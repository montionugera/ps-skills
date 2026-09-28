# Agentic Second Brain Design

**Date:** 2026-09-28  
**Status:** Proposed design; no live migration or installation authorized  
**Sources:** [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain), [architecture](https://github.com/eugeniughelbur/obsidian-second-brain/blob/main/architecture.md), [AI-first rules](https://github.com/eugeniughelbur/obsidian-second-brain/blob/main/references/ai-first-rules.md), [local research comparison](../../../research/agentic-vault-landscape-2026-09-28.md)

## Orientation

Build a full second brain around the experience shown in the reference repository: durable memory, daily work, contextual recall, thinking tools, research, multimedia ingestion, and optional maintenance. Preserve the existing vault's notes and IDs. Use the reference project as the primary skill and interaction candidate, while one local gateway governs every canonical **agent** write. This ownership boundary is settled for the target design; the isolated pilot still tests upstream behavior without granting it live-vault writes.

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
| Split ownership: upstream writes general memory; engine writes ideas/projects | Fastest interim experience | Two write protocols make cross-links, recovery, and audit harder to explain. Permit only inside a disposable pilot, never in the live target. |
| Upstream-inspired skill layer over one vault gateway | Broad experience with consistent writes, validation, and recovery | Requires adapters for upstream mutating commands. **Chosen target.** |

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

Keep `01_Ideas/`, `02_Projects/`, `03_Areas/`, `04_Knowledge/`, `_inbox/`, `_archive/`, and `_meta/`. The target uses a small, purpose-based folder map rather than a catch-all `_secondary/` or separate root folders for every record type. Create new folders only when their feature is enabled; existing files do not move during the pilot.

| Logical content | Proposed home | Routing rule |
|---|---|---|
| Daily notes | `05_Daily/YYYY/YYYY-MM-DD.md` | One note per local calendar day; link to owned work rather than duplicate it. |
| People | `06_People/` | Person records have stable IDs; this collection stays disabled until its privacy policy is enforced. |
| Research synthesis | `07_Research/` | Dated, source-bound working synthesis; each claim links to retained evidence. |
| Original evidence | `_sources/<content-hash>/` | Content-addressed captures remain unchanged while retained, then follow the deletion policy; never a substitute for a readable research note. |
| Decisions | `02_Projects/<project>/decisions/` or `03_Areas/<area>/decisions/` | One owner; cross-cutting decisions live in `04_Knowledge/decisions/`. |
| Tasks | `02_Projects/<project>/tasks/` or `03_Areas/<area>/tasks/` | One owner and stable task ID; unassigned captures stay in `_inbox/` until triaged. Global boards are derived views. |
| Machine state | `_meta/` | Schemas, events, indexes, run state, and recovery artifacts; never the home for human knowledge. |

These are proposed paths, not folders or schemas already present. A versioned folder-map contract resolves logical type plus owner to path; every mutating skill and CLI adapter reads the same contract instead of hard-coding paths. New canonical tasks are ID-bearing records; ordinary note checkboxes remain valid Obsidian Tasks input and are shown as legacy tasks, not silently duplicated as new records. A reviewed import maps a legacy checkbox to one ID and updates derived views before its old representation is retired. Renaming or moving a managed note preserves its ID and requires a reviewed link/index update. An importance tier belongs in metadata or a view, not in a vague `_secondary/` folder.

`07_Research/` holds dated investigations, including uncertainty and source-bound claims. `04_Knowledge/` holds durable, reusable concepts and references. Promotion is a reviewed distillation that links back to the research record rather than copying a competing version. The existing `_meta/schemas/research-notes-v1.json` describes Bestie's idea-analysis output; it must not be repurposed as the schema for canonical research notes.

Managed records have an immutable ID independent of path; existing IDs remain unchanged. New managed records require frontmatter `schema`, `id`, `kind`, `title`, `created`, and `updated`, plus type-specific fields. Their body begins with a brief `## For future agent` summary and then human-readable sections. Existing navigation/MOC and legacy notes remain valid readable inputs even if they lack this shape; inventory and classify them before import, then migrate only with an explicit diff and backup. Changing claims point to a source and carry observation/validity dates; superseded claims remain traceable. Long research evidence lives in linked artifacts, not a large frontmatter object.

Each record/result type has one named, versioned schema source; agent-result schemas and canonical-note schemas are distinct contracts. The gateway validates canonical notes at writes, while a read-only linter finds legacy or human-edited violations. Skills and manifests name schema versions and logical collection names; generated adapters and docs are checked against those sources.

### Sensitive data boundary

The vault currently tracks canonical notes and events in Git; a frontmatter privacy label alone does not prevent a commit, sync, backup, or plugin from reading them. Before enabling `06_People/`, `_sources/`, body snapshots, or sensitive research, define and enforce classification, consent for captured personal data, retention/deletion, Git and sync exclusions, encrypted backup/storage where required, and outbound-provider rules. Default new people/source/snapshot content to local-private and **do not create it** until the storage policy and a leak test are in place. The gate checks `git status`, tracked-file state, configured sync/backup destinations, event payloads, and derived indexes; `.gitignore` alone does not protect already-tracked content. Any declassification or history cleanup is a separate reviewed operation. This policy does not claim protection from a local plugin or process with unrestricted vault filesystem access.

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
3. Implement the versioned folder-map and gateway proposal adapters for one mutating command. Prove owner-based task/decision routing, stable IDs across path changes, and Obsidian readability. Run an adversarial save between hash comparison and rename: if coordinated writes cannot be enforced, keep auto-commit disabled and prove snapshot-based detection/recovery instead of claiming guaranteed OCC for direct Obsidian edits.
4. Import existing notes in place by validating and indexing them. Any later path migration is a separately reviewed operation with a mapping report, backup, reversible move plan, and link checks.
5. Before any live target-vault write, inventory every installed skill, MCP connector, CLI, and shell-capable automation with access to that vault. Repoint mutators to the gateway or deny their target-vault write capability at runtime; test the denial with a direct-write attempt. The currently connected personal Obsidian MCP vault is a different path and is not disabled globally. An agent with unrestricted filesystem write access to the target vault cannot qualify for unattended gateway-only operation.
6. Publish one canonical command source and generate Claude/Codex/Gemini surfaces. Add a repository build/CI target that regenerates adapters and fails on any diff, then runs a shared fixture for path resolution, schema versions, command descriptions, capability restrictions, and equivalent result states across CLIs.

## Acceptance scenarios

- A saved conversation updates an existing decision/project note when search finds it, preserves the old text and source trail, and creates no duplicate.
- Bestie and Philip each produce schema-valid, cited artifacts for an idea. Missing or conflicting evidence yields `review needed`, never a fabricated candidate score.
- A human edits the target note before commit; a coordinated adapter rejects the stale proposal and leaves both versions inspectable. An adversarial uncoordinated Obsidian save during compare-and-rename must either be prevented by the chosen protocol or make unattended writes fail qualification; snapshot recovery is demonstrated in review-only mode.
- Crash injection immediately before and after note rename, and a simulated event-write failure, never yield an unreported success. Reconciliation identifies the final note revision and audit state.
- Two captures arriving together receive distinct immutable IDs. A repeated delivery with the same idempotency key creates one logical result.
- A task or decision created for a project resolves beneath that project, an area-owned one resolves beneath its area, and an unassigned capture stays in the inbox; no skill invents a `_secondary/` or global tasks/decisions root. Global views show all three without duplicating canonical records.
- A legacy checkbox task remains visible to Obsidian Tasks and the status view; a reviewed conversion yields exactly one ID-bearing task with no duplicate in the global view. A reviewed research promotion leaves the dated investigation intact and links the durable knowledge note to it.
- A tool with direct target-vault write capability is refused in the unattended runtime; a sensitive person note, source, snapshot, event, or index cannot be created or synced before its privacy gate passes.
- A process stops between the first and second note of a broad save; the run resumes or reports partial completion without claiming all notes were updated.
- `world` and recall load bounded, cited context; a low-confidence query injects nothing. The same known-note fixture is retrievable across supported CLIs.
- A scheduled run fails or exceeds its budget; the dashboard shows the failed run and leaves canonical notes unchanged unless completed commits are individually listed.
- Search and dashboard queries use a derived index on a 10,000-note fixture rather than scanning every Markdown file per request. The benchmark records reference hardware and p95 latency before a performance target is accepted.

## Settled boundary and remaining gate

Every canonical agent write, including new daily, person, research, source, task, and decision records, goes through the gateway. Upstream skills may write freely only in the disposable pilot. Live adapters must enforce this through capabilities and configuration, not merely through prose; until target-vault write access is confined, gateway-only remains a design contract rather than an achieved guarantee. Direct human Obsidian editing remains allowed; unattended agent commits to those notes stay disabled until the coordinating-writer test passes. Any migration of existing paths is a separate reviewed change, not implied by adopting this design.

## Appendix — audit trail

- 2026-09-28 initial design: broadened the product scope from idea triage to full second-brain operations, thinking, context, research, and optional automation.
- 2026-09-28 independent audit: safe with fixes. Corrected four high-priority gaps: direct Obsidian edits cannot share a gateway lock; note replacement and event logging need a durable recovery protocol; MOC/legacy notes need classification; isolated pilot must inventory command collisions before installation. Also added body history, outbound-data controls, and an executable adapter conformance gate. These are design requirements, not claims that the current engine implements them.
- 2026-09-28 design revision: settled gateway-only canonical agent writes and replaced six proposed new root collections with purpose-based daily/people/research/source homes plus owner-local tasks and decisions. Rejected `_secondary/` as an ambiguous catch-all. No live files moved.
- 2026-09-28 independent revision audit: safe with fixes. Added a target-vault mutator confinement gate and a sensitive-data storage gate before live enablement; preserved legacy checkbox task behavior and separated working research from durable knowledge and from the existing Bestie result schema. These gates are not implemented by this document.
