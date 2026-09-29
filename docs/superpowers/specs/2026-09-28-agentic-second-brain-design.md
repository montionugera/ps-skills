# Agentic Second Brain Design

**Date:** 2026-09-28  
**Status:** Proposed design; no live migration or installation authorized  
**Sources:** [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain), [architecture](https://github.com/eugeniughelbur/obsidian-second-brain/blob/main/architecture.md), [AI-first rules](https://github.com/eugeniughelbur/obsidian-second-brain/blob/main/references/ai-first-rules.md), [local research comparison](../../../research/agentic-vault-landscape-2026-09-28.md)

## Orientation

Build an agent-agnostic knowledge operating system around the experience shown in the reference repository. Any supported agent should follow the same capture, research, decision, task, review, and recovery workflow; a human should see current ideas, projects, tasks, evidence, and failures in Obsidian. Preserve the existing vault's notes and IDs. Use the reference project as the primary skill and interaction candidate, while one local gateway governs every canonical **agent** write. This ownership boundary is settled for the target design; the isolated pilot still tests upstream behavior without granting it live-vault writes.

<div class="callout info">The reference README describes a broad feature catalogue. It is the product target for this design, not evidence that each feature already meets this vault's acceptance criteria.</div>

## Product objective and meaning of sync

The forthcoming implementation plan is for the **whole cross-agent workflow**, not a folder migration or a single Obsidian plugin. It must deliver one versioned rule/command/schema contract, adapters for supported agents, a deterministic vault read/write and recovery layer, lifecycle-aware knowledge operations, and a human-facing dashboard and review surface. The Obsidian plugin is a thin client of those contracts, not the sole owner of workflow logic; a CLI must remain capable of the same essential read, review, and recovery actions.

"In sync" has three separate, testable meanings: installed agent adapters are inventoried and checked against one active command/rule version; notes and derived indexes/views converge after each recorded change; and health checks identify stale, conflicting, orphaned, or unprocessed knowledge. It does **not** mean automatic truth resolution or cross-device file synchronization. The latter needs its own transport and conflict policy if requested later.

## Goals and boundaries

- A human can capture, find, understand, correct, and recover knowledge from Obsidian without learning agent internals.
- Claude, Codex, Gemini, and later agent CLIs consume one versioned command and note contract. Their adapters may differ; their behavior and write rules may not.
- Agents can propose in parallel, but cannot silently overwrite a human edit or another agent's result. Every canonical change has an actor, reason, source, prior revision, and observable outcome.
- Markdown remains portable and readable. Search indexes, views, workflow instances, and embeddings are rebuildable derivatives.
- A human can see idea stage, project/task progress, blocked work, stale knowledge, last agent activity, and failed or conflicted runs without opening every note. Unknown progress is labeled unknown, never presented as zero or complete.
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

The shared contract defines record kinds and lifecycle states, folder routing, commands, capabilities, and rule versions. Claude/Codex/Gemini adapters expose it in their native skill formats; conformance tests verify equivalent inputs, outputs, and denial behavior. The gateway rejects mutating requests with an unsupported contract version; installed-surface inventory records adapter and hook hashes, and health reports stale versions. Host-level permissions and instructions remain authoritative; skills cannot override them, and gateway invariants do not depend on any agent obeying prose. A conflict between installed rules and the active gateway contract fails closed for writes and appears in health. A thin Obsidian plugin and CLI read the same indexed state and submit review actions through the gateway. A reconciler compares canonical notes, events, source links, and derived indexes and reports drift rather than silently rewriting disputed knowledge.

### End-to-end workflow

<div class="schematic"><pre>
Capture → Triage → Agent work → Proposal → Review policy → Gateway commit
   │          │          │                         │                 │
   └─ raw     └─ route   └─ typed findings         ├─ human review  ├─ conflict / failed
      inbox      or hold     with evidence          └─ eligible     └─ committed notes
                                                               │
                                      Reconcile links + index ←┘ → Dashboard + health
</pre></div>

| Stage | Owner and durable output | Exit rule |
|---|---|---|
| Capture | Human, CLI, plugin, or agent submits through the ingest/gateway API; before any note write or inbox deletion, a protected durable capture ledger records `run_id`, source identity, idempotency key, payload hash, and recoverable raw input. | An identical retry returns the existing run; the same key with changed payload fails as a conflict. |
| Triage | Search and classify as idea, project, task, decision, research, person, or unresolved; record candidate owner and possible duplicates. | Unclear ownership, duplicate risk, or missing consent stays in inbox with a next action. |
| Agent work | One or more agents read a pinned snapshot and return typed, cited findings; parallel agents do not edit canonical notes. | Missing evidence or invalid output produces `review_needed` or `failed`, never an invented score. |
| Proposal and review | Assemble affected IDs, expected revisions, diff, evidence, confidence, and capability; policy selects eligible or human review. | Broad rewrites, contradiction resolution, archives, sensitive data, and low-confidence claims require approval. |
| Commit | Gateway validates contract version, actor, schema, idempotency key, and nonempty expected hashes; journals each note change. | Conflict or crash is visible and recoverable; partial multi-note commits never report full success. |
| Reconcile and surface | Recorded events refresh derived backlinks, index, boards, and dashboard; canonical link edits require their own gateway proposal. Health compares projections with canonical notes. | Index lag, broken links, stale claims, and failed runs appear with owner and next action rather than being silently repaired. |

A **workflow run** and a **knowledge record** have different states. New run states are `captured`, `triaged`, `working`, `review_needed`, `committing`, `completed`, `partial`, `conflicted`, `failed`, `quarantined`, or `cancelled`; every transition records actor, time, reason, input revision, and next action. Allowed normal mutation path: `captured → triaged → working → review_needed or committing → completed`; a read-only run may complete from `working`. `committing` may instead enter `partial`, `conflicted`, or `failed`; invalid/security-sensitive output enters `quarantined`. A retry from `failed`, `quarantined`, `partial`, or `conflicted` starts a new attempt on the **same run**, preserving prior events; rebase requires re-read and a new proposal revision, never silent application of a stale one. `completed` and `cancelled` are terminal.

The existing engine's `running/completed/failed/quarantined` instances are historical compatibility inputs, not evidence that it already implements the new transitions. Imported `running` maps to `in progress` with unknown substage, while the other three retain their outcome; missing history remains `unknown`, not fabricated. Record states are kind-specific: an idea may be explored or promoted, a task open or done, and a project active or completed. Completing an agent run does not imply that its idea or task was approved or finished. The dashboard derives run queues from events and record progress from the corresponding record contracts; it never merges the two state machines.

Every entry point, including a scheduled job, uses this same flow and policy. Retries reuse the run/idempotency identity and require the same payload hash; a worker lease limits duplicate execution but is not the correctness guarantee. Two agents can analyze the same snapshot in parallel; their proposals remain separate and stale revisions conflict at commit. A paused or failed run remains visible for retry, rebase, dismiss, or human resolution. No scheduler, plugin, or skill may bypass the gateway by writing a canonical file directly. In the initial pilot all mutation proposals require review; later unattended eligibility cannot be enabled until writer confinement, concurrent-human-edit safety, durable journal/event recovery, and an executable review policy pass their gates.

### Note ownership and shape

Keep `01_Ideas/`, `02_Projects/`, `03_Areas/`, `04_Knowledge/`, `_inbox/`, `_archive/`, and `_meta/`. The target uses a small, purpose-based folder map rather than a catch-all `_secondary/` or separate root folders for every record type. Create new folders only when their feature is enabled; existing files do not move during the pilot.

| Logical content | Proposed home | Routing rule |
|---|---|---|
| Daily notes | `05_Daily/YYYY/YYYY-MM-DD.md` | One note per local calendar day; link to owned work rather than duplicate it. |
| People | `06_People/` | Person records have stable IDs; this collection stays disabled until its privacy policy is enforced. |
| Research synthesis | `07_Research/` | Dated, source-bound working synthesis; each claim links to retained evidence. |
| Original evidence | `_sources/SRC-<stable-id>--<safe-slug>/` | Stable source-record identity plus a readable name; unchanged payloads are content-addressed separately and follow the deletion policy. |
| Decisions | `02_Projects/<project>/decisions/` or `03_Areas/<area>/decisions/` | One owner; cross-cutting decisions live in `04_Knowledge/decisions/`. |
| Tasks | `02_Projects/<project>/tasks/` or `03_Areas/<area>/tasks/` | One owner and stable task ID; unassigned captures stay in `_inbox/` until triaged. Global boards are derived views. |
| Machine state | `_meta/` | Schemas, events, indexes, run state, and recovery artifacts; never the home for human knowledge. |

These are proposed paths, not folders or schemas already present. A versioned folder-map contract resolves logical type plus owner to path; every mutating skill and CLI adapter reads the same contract instead of hard-coding paths. New canonical tasks are ID-bearing records; ordinary note checkboxes remain valid Obsidian Tasks input and are shown as legacy tasks, not silently duplicated as new records. A reviewed import maps a legacy checkbox to one ID and updates derived views before its old representation is retired. Renaming or moving a managed note preserves its ID and requires a reviewed link/index update. An importance tier belongs in metadata or a view, not in a vague `_secondary/` folder.

Each capture gets an immutable gateway-allocated source-record ID and a sanitized, bounded slug from a non-sensitive title (for example `SRC-2026-000123--agentic-vault-design/`). If no safe title exists, use `untitled-source`. The slug does not change automatically when the title changes. Its `Source.md` manifest presents `title`, `source_type`, `origin`, `captured_at`, ingest reason, payload SHA-256, rights/consent metadata, and a labeled summary so an agent or person can identify the source without opening the raw file. A generic slug or redacted display title is required when filenames themselves would leak private data; the sensitive-data gate still applies. Identical payload bytes can share one content-addressed blob, but **never merge distinct source records or capture/provenance events** merely because hashes match.

`07_Research/` holds dated investigations, including uncertainty and source-bound claims. `04_Knowledge/` holds durable, reusable concepts and references. Promotion is a reviewed distillation that links back to the research record rather than copying a competing version. The existing `_meta/schemas/research-notes-v1.json` describes Bestie's idea-analysis output; it must not be repurposed as the schema for canonical research notes.

Managed records have an immutable ID independent of path; existing IDs remain unchanged. New managed records require frontmatter `schema`, `id`, `kind`, `title`, `created`, and `updated`, plus type-specific fields. Their body begins with a brief `## For future agent` summary and then human-readable sections. Existing navigation/MOC and legacy notes remain valid readable inputs even if they lack this shape; inventory and classify them before import, then migrate only with an explicit diff and backup. Changing claims point to a source and carry observation/validity dates; superseded claims remain traceable. Long research evidence lives in linked artifacts, not a large frontmatter object.

Each record/result type has one named, versioned schema source; agent-result schemas and canonical-note schemas are distinct contracts. The gateway validates canonical notes at writes, while a read-only linter finds legacy or human-edited violations. Skills and manifests name schema versions and logical collection names; generated adapters and docs are checked against those sources.

### Sensitive data boundary

The vault currently tracks canonical notes and events in Git; a frontmatter privacy label alone does not prevent a commit, sync, backup, or plugin from reading them. Before enabling `06_People/`, `_sources/`, body snapshots, or sensitive research, define and enforce classification, consent for captured personal data, retention/deletion, Git and sync exclusions, encrypted backup/storage where required, and outbound-provider rules. Default new people/source/snapshot content to local-private and **do not create it** until the storage policy and a leak test are in place. The gate checks `git status`, tracked-file state, configured sync/backup destinations, event payloads, and derived indexes; `.gitignore` alone does not protect already-tracked content. Any declassification or history cleanup is a separate reviewed operation. This policy does not claim protection from a local plugin or process with unrestricted vault filesystem access.

### Change proposal and commit contract

A proposal contains `proposal_id`, `run_id`, `actor`, `contract_version`, `operation` (`create`, `patch`, or `archive`), `target_id` or requested new type, `base_sha256`, structured changes, source references, confidence, reason, and idempotency key. Agent outputs also carry role/version, input revision, status (`complete`, `partial`, `failed`), findings, evidence, and error details. Invalid or missing outputs cannot be turned into scores by a default value.

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

The Obsidian dashboard and CLI show five exclusive run queues: **inbox** (`captured` or unresolved `triaged`), **in progress** (routed `triaged`, `working`, `committing`; `researching` is a filter), **review needed** (`review_needed`), **failed/conflicted** (`partial`, `conflicted`, `failed`, `quarantined`, with a quarantine badge), and **completed** (`completed`). `cancelled` is retained in a closed-history filter, not counted as success. Their overview shows ideas by stage, project progress, actionable and overdue tasks, blocked owners, stale knowledge, and last successful/failed agent run. Progress derives from canonical task states or an explicitly labeled legacy-checkbox adapter, with source counts and `unknown` when coverage is incomplete. Each count displays its event/index **as-of revision and lag**; completed history is paginated and retained under a declared policy. A run becomes `completed` after required canonical commits and audit events are durable, even if a derived index is still catching up. Each run exposes its input note, agents, source links, proposed changes, final event, and retry or dismiss action. Bases may render these views, but metadata and workflow events remain the source. A read-only health command reports schema/rule drift across agent adapters, stale claims, duplicates, broken links, orphan artifacts, failed runs, and index lag by severity. Repairs are separate proposals.

### Implementation-plan scope

The full plan must cover these dependent deliverables: (1) contract, run/record state machines, and conformance fixtures; (2) gateway durability, permissions, and recovery; (3) capture/triage/knowledge/task workflows with source provenance; (4) native agent adapters; (5) Obsidian plugin and CLI views/review controls; and (6) health/reconciliation, optional scheduling, and scale/privacy gates. Each deliverable ends with verification, independent review, refactor, and re-verification before the next depends on it. Folder creation or command installation alone is not a completed second brain. Rollback restores prior skill registrations and leaves existing Markdown readable; no phase assumes that installing a new plugin or adapter migrates historical notes.

## Integration and migration

1. Inventory installed Obsidian commands, hooks, global aliases, and live-vault paths before registration. Pin the upstream commit and inspect its `commands/`, adapters, and build scripts; its [architecture document](https://github.com/eugeniughelbur/obsidian-second-brain/blob/main/architecture.md) describes a shared cross-CLI command source but was last reviewed against an older commit, so do not treat its command inventory as current. Run the pinned build under isolated names and config against a disposable sample vault, never a global skills path. Disable the current prototype watcher in that pilot and before any target-vault enablement: it currently inserts hard-coded Bestie/Philip findings and scores ideas without the proposed evidence/review gate. Exercise save, world, find, health, one thinking command, and one source ingest on the same fixture. Record files read/written, source preservation, CLI parity, and failure behavior. Its README and command files are inputs to this test, not proof of behavior.
2. Build a command capability matrix from the pinned upstream source: read/write/network/schedule behavior, target schema and gateway mapping, per-CLI support, privacy risk, and test outcome. Decide **reuse, gateway-wrap, selective replacement, or skip** for each command before building local adapters; do not create a parallel full command catalogue by default. Keep upstream files unmodified during the pilot; preserve license and provenance for any code later adapted. Resolve naming collisions before live registration.
3. Before the first mutating workflow path, implement the protected capture ledger, non-destructive ingest, journaled commit/event recovery, nonempty expected-hash check, and idempotent transition API. Prove owner-based task/decision routing, stable IDs across path changes, and Obsidian readability. Run crash/retry, changed-payload idempotency, event-write failure, and adversarial save-between-hash-and-rename fixtures; if coordinated writes cannot be enforced, keep auto-commit disabled and prove snapshot-based detection/recovery instead of claiming guaranteed OCC for direct Obsidian edits. Older idea notes with no retained capture are labeled provenance `unknown`, not backfilled with invented source claims.
4. Import existing notes in place by validating and indexing them. Any later path migration is a separately reviewed operation with a mapping report, backup, reversible move plan, and link checks.
5. Before any live target-vault write, inventory every installed skill, MCP connector, CLI, and shell-capable automation with access to that vault. Repoint mutators to the gateway or deny their target-vault write capability at runtime; test the denial with a direct-write attempt. The currently connected personal Obsidian MCP vault is a different path and is not disabled globally. An agent with unrestricted filesystem write access to the target vault cannot qualify for unattended gateway-only operation.
6. Based on the pilot's matrix, adopt or adapt one canonical command source and generate Claude/Codex/Gemini surfaces; do not assume a new local catalogue is needed. Add a repository build/CI target that regenerates adapters and fails on any diff, then runs a shared fixture for path resolution, schema versions, command descriptions, capability restrictions, and equivalent result states across CLIs. Inventory the **installed** copies, symlinks, and hooks as well as repo source; require a runtime contract-version handshake for mutating calls and test stale-install rejection plus a version-skew rollback path.

## Acceptance scenarios

- A saved conversation updates an existing decision/project note when search finds it, preserves the old text and source trail, and creates no duplicate.
- One capture is traceable through inbox item, triage decision, agent findings, proposal/review, gateway event, updated note, and dashboard state. A duplicate delivery or retry does not create a second run or note.
- Replaying the same key and payload after a crash resumes the same run; replaying the key with changed payload reports a conflict. The current prototype watcher is off, so hard-coded analysis cannot create a candidate score.
- Bestie and Philip each produce schema-valid, cited artifacts for an idea. Missing or conflicting evidence yields `review needed`, never a fabricated candidate score.
- A completed research run with an unresolved idea leaves the idea's own lifecycle unchanged. A conflict or partial commit remains in the run's visible queue with a next action and is not counted as completed work.
- Every run state maps to exactly one dashboard queue or the closed-history filter. Imported legacy instances show their known outcome but do not invent a detailed stage; all visible counts show projection revision and lag.
- A human edits the target note before commit; a coordinated adapter rejects the stale proposal and leaves both versions inspectable. An adversarial uncoordinated Obsidian save during compare-and-rename must either be prevented by the chosen protocol or make unattended writes fail qualification; snapshot recovery is demonstrated in review-only mode.
- Crash injection immediately before and after note rename, and a simulated event-write failure, never yield an unreported success. Reconciliation identifies the final note revision and audit state.
- Two captures arriving together receive distinct immutable IDs. A repeated delivery with the same idempotency key creates one logical result.
- A task or decision created for a project resolves beneath that project, an area-owned one resolves beneath its area, and an unassigned capture stays in the inbox; no skill invents a `_secondary/` or global tasks/decisions root. Global views show all three without duplicating canonical records.
- A source is visible as `SRC-<stable-id>--<safe-slug>/` with a manifest that explains its title, type, origin, capture reason, and summary. Two captures of identical bytes from different origins retain two source records and provenance trails while sharing one content-addressed payload; a sensitive title never appears in its path or an unauthorized index.
- A legacy checkbox task remains visible to Obsidian Tasks and the status view; a reviewed conversion yields exactly one ID-bearing task with no duplicate in the global view. A reviewed research promotion leaves the dated investigation intact and links the durable knowledge note to it.
- Claude, Codex, and Gemini run the same fixture and agree on command meaning, note routing, lifecycle state, and write denial. An installed stale adapter is visible in health and cannot mutate; a rollback fixture demonstrates how a compatible prior version resumes safely. The Obsidian and CLI views show the same idea/task/project counts and identify unknown or lagging progress instead of fabricating a percentage.
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
- 2026-09-28 objective clarification: the target is a full, agent-agnostic skills/gateway/plugin system with synchronized contracts, knowledge health, and visible progress. Source folders gain safe human-readable slugs without making a title the identity; the implementation plan must cover all layers, not merely the folder map.
- 2026-09-28 self-grill-audit: safe with fixes. Corrected source-record versus payload identity, enforced installed adapter-version checks, and made the pinned upstream command build the reuse-first pilot rather than assuming a duplicate local command catalogue. Clarified host-rule precedence and rollback. Open: design approval before an implementation plan.
- 2026-09-28 workflow revision: added one end-to-end capture-to-dashboard flow, separate run and record state machines, explicit review/conflict/retry paths, and workflow traceability acceptance tests. No runtime workflow was changed.
- 2026-09-28 workflow self-grill-audit: safe with fixes as a design, unsafe to run on the current engine. Added a pre-side-effect capture ledger and payload-aware idempotency, disabled the hard-coded prototype watcher in pilot/live target, mapped legacy run states and all dashboard queues (including quarantine/partial), and made durable commit recovery a prerequisite. Older provenance remains unknown where raw input was discarded.
