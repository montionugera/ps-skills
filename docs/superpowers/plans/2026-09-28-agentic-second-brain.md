# Agentic Second Brain — Go-Native Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Agentic Second Brain operating system in **Golang** (`tools/vault-engine`) to guide knowledge through 4 Big Phases (**Idea Generate**, **Refine + Go/No-Go**, **Implement**, **Learn/Unlearn**) across 3 Core Categories (**Product/Feature**, **Process/Workflow**, **Knowledge Thesis/Rules**) with zero file corruption, zero lost ideas, >80% test coverage, and human-in-the-loop control.

**Architecture:** A compiled Go static binary (`tools/vault-engine/bin/vault-engine`) serves as the sole authoritative agent write boundary. It enforces "check before saving" (Optimistic Concurrency Control with `expected_sha256`), an append-only capture ledger, atomic multi-note backup journaling, purpose-based folder routing, and projects state into 5 human review queues.

**Tech Stack:** Go 1.22+, POSIX File Locking (`syscall.Flock`), SHA-256 Hashing, `gopkg.in/yaml.v3`, JSON Schema Draft 2020-12, Shell E2E Test Suite.

**Spec Reference:** `docs/superpowers/specs/2026-09-28-agentic-second-brain/00-INDEX.md`

**Target Quality Metrics:**
- **Statement Test Coverage:** `> 80%` across all Go packages (`pkg/vault`, `pkg/workflow`, `pkg/agent`, `pkg/daemon`).
- **End-to-End Suite:** `test_e2e.sh` passing 100% with zero flakes.
- **Binary Size & Performance:** Single static binary `< 25MB`, CLI execution latency `< 10ms`.

---

## The 4 System Pillars & Architectural Invariants

1. **Simple (Zero Fluff):** Pure Markdown on disk. Files ARE the vault. No hidden databases or proprietary silos.
2. **Scale (10,000+ Notes Smoothly):** Fast local indexing (<150ms search), sub-5ms CLI execution, lightweight daemon (<15MB RAM).
3. **Observable (Everything Visible):** 5 exclusive review queues (`Inbox`, `Working`, `Review Needed`, `Conflicts`, `Completed`) with clear human diff cards.
4. **Readiness Proved (Battle-Tested):** High-coverage unit tests (>80%), typing race conflict tests, crash rollback tests, and automated E2E verification.

---

## Wave 1: Foundation & "Idea Generate" (Capture, Deduplication & Routing)

### Task 1: Core Record & Category Models in Go [DONE & VERIFIED]
- **Files:** `tools/vault-engine/pkg/vault/contracts.go`, `contracts_test.go`
- **Interfaces:** `CategoryTrack` (`product_feature`, `process_workflow`, `knowledge_thesis`), `LifecyclePhase` (`idea_generate`, `refine_go_nogo`, `implement`, `learn_unlearn`), `RecordKind`, `FrontmatterContract`.
- [x] Step 1.1: Define Go constants and frontmatter structs with YAML and JSON tags.
- [x] Step 1.2: Write unit test `TestCategoryTracksAndPhases`.
- [x] Step 1.3: Run `go test -v ./pkg/vault` (PASS).

---

### Task 2: Black-Box Capture Ledger & SHA-256 Deduplication
- **Files:**
  - Create: `tools/vault-engine/pkg/vault/ledger.go`
  - Test: `tools/vault-engine/pkg/vault/ledger_test.go`
- **Interfaces:**
  - `CaptureEntry`: `RunID`, `IdempotencyKey`, `Category`, `SourceOrigin`, `PayloadSHA256`, `RawPayloadPath`, `Timestamp`.
  - `CaptureLedger`: `RecordCapture(idempotencyKey, category, sourceOrigin, rawPayload) (*CaptureEntry, error)`.
  - `ErrConflictPayload`: returned when idempotency key is reused with modified payload.
- [ ] **Step 2.1: Write failing unit test** `TestCaptureLedger_DeduplicationAndConflict` verifying identical keys replay cleanly and changed payloads return `ErrConflictPayload`.
- [ ] **Step 2.2: Verify test fails** (`go test -v ./pkg/vault -run TestCaptureLedger`).
- [ ] **Step 2.3: Implement `CaptureLedger`** with atomic append to `_meta/ledger/captures.jsonl` and raw payload persistence in `_meta/ledger/raw/<run_id>.raw`.
- [ ] **Step 2.4: Verify test passes** (`go test -v ./pkg/vault -run TestCaptureLedger`).
- [ ] **Step 2.5: Phase Quality Gate:** Run `go test -cover ./pkg/vault` and verify clean execution.

---

### Task 3: Purpose-Based Folder Routing & Path Resolver
- **Files:**
  - Create: `tools/vault-engine/pkg/vault/router.go`
  - Test: `tools/vault-engine/pkg/vault/router_test.go`
- **Interfaces:**
  - `PathResolver`: `Resolve(category CategoryTrack, kind RecordKind, slug string, owner string) string`.
  - Rules:
    - Product Idea -> `01_Ideas/<slug>.md`
    - Process Decision / ADR -> `02_Projects/<owner>/decisions/<slug>.md` (or `04_Knowledge/decisions/<slug>.md` if global)
    - Thesis / Research -> `07_Research/<slug>.md`
    - Task -> `02_Projects/<owner>/tasks/<slug>.md`
- [ ] **Step 3.1: Write failing unit test** `TestPathResolver_CategoryAwareRouting`.
- [ ] **Step 3.2: Verify test fails**.
- [ ] **Step 3.3: Implement `PathResolver`** in `router.go`.
- [ ] **Step 3.4: Verify test passes**.
- [ ] **Step 3.5: Phase Quality Gate:** Run `go test -cover ./pkg/vault`.

---

## Wave 2: "Refine + Go / No-Go" (Validation, Citations & Queues)

### Task 4: ChangeProposal Contract & Evidence Citation Validator
- **Files:**
  - Create: `tools/vault-engine/pkg/vault/proposal.go`
  - Test: `tools/vault-engine/pkg/vault/proposal_test.go`
- **Interfaces:**
  - `ChangeProposal`: `ProposalID`, `RunID`, `Actor`, `ContractVersion`, `Operation` (`create`, `patch`, `archive`), `TargetPath`, `BaseSHA256`, `ProposedContent`, `Reason`, `Confidence`, `EvidenceRefs`.
  - Invariant: If `Confidence > 0.8`, `EvidenceRefs` MUST have at least 1 verified source reference; otherwise fail with `ErrMissingEvidence`.
- [ ] **Step 4.1: Write failing unit test** `TestChangeProposal_EvidenceValidation`.
- [ ] **Step 4.2: Verify test fails**.
- [ ] **Step 4.3: Implement `ChangeProposal`** with validation method `Validate() error`.
- [ ] **Step 4.4: Verify test passes**.
- [ ] **Step 4.5: Phase Quality Gate:** Run `go test -cover ./pkg/vault`.

---

### Task 5: The 5 Exclusive Review Queues / Buckets Engine
- **Files:**
  - Create: `tools/vault-engine/pkg/vault/buckets.go`
  - Test: `tools/vault-engine/pkg/vault/buckets_test.go`
- **Interfaces:**
  - `BucketType`: `BucketInbox`, `BucketWorking`, `BucketReviewNeeded`, `BucketConflicts`, `BucketCompleted`.
  - `BucketManager`: `GetQueue(bucket BucketType) ([]RecordEnvelope, error)`, `ClassifyRecord(rec *RecordEnvelope) BucketType`.
  - Invariant: Every record belongs to **exactly one** bucket at any point in time.
- [ ] **Step 5.1: Write failing unit test** `TestBucketManager_ExclusiveClassification` testing transitions across all 5 states.
- [ ] **Step 5.2: Verify test fails**.
- [ ] **Step 5.3: Implement `BucketManager`** in `buckets.go`.
- [ ] **Step 5.4: Verify test passes**.
- [ ] **Step 5.5: Phase Quality Gate:** Run `go test -cover ./pkg/vault`.

---

### Task 6: Multi-Agent Adapter & JSON Schema Sandboxing
- **Files:**
  - Enhance: `tools/vault-engine/pkg/agent/manifest.go`
  - Schemas: `tools/vault-engine/schemas/research-notes-v1.json`, `technical-audit-v1.json`
  - Test: `tools/vault-engine/pkg/agent/manifest_test.go`
- **Interfaces:**
  - Manifest validation for Olivier (Orchestrator), Bestie (BA), Philip (Tech Director).
  - Enforce `--json-schema` outputs and zero direct shell tool execution for recruited subagents.
- [ ] **Step 6.1: Write failing unit test** `TestAgentManifest_ValidationAndSchemaCheck`.
- [ ] **Step 6.2: Verify test fails**.
- [ ] **Step 6.3: Implement schema enforcement** in `manifest.go`.
- [ ] **Step 6.4: Verify test passes**.
- [ ] **Step 6.5: Phase Quality Gate:** Run `go test -cover ./pkg/agent` (target >80%).

---

## Wave 3: "Implement" (Safe Gateway Commit, OCC & Journal Rollback)

### Task 7: Optimistic Concurrency Control (Check-Before-Saving)
- **Files:**
  - Enhance: `tools/vault-engine/pkg/vault/vault.go`
  - Test: `tools/vault-engine/pkg/vault/vault_test.go`
- **Interfaces:**
  - `CommitIdea(req CommitRequest) error`: Verifies `ExpectedSHA256 == CurrentSHA256`.
  - Returns `ErrConflict` if record changed mid-flight.
- [ ] **Step 7.1: Verify existing test** `TestBC08_OptimisticConcurrencyCommit` and add edge cases (missing base SHA, empty file, concurrently updated frontmatter).
- [ ] **Step 7.2: Refactor and harden** `CommitIdea` error reporting to include expected vs actual SHA.
- [ ] **Step 7.3: Verify test passes**.
- [ ] **Step 7.4: Phase Quality Gate:** Run `go test -cover ./pkg/vault`.

---

### Task 8: Pre-Write Backup Snapshots & Atomic Multi-Note Commit Journal
- **Files:**
  - Create: `tools/vault-engine/pkg/vault/journal.go`
  - Test: `tools/vault-engine/pkg/vault/journal_test.go`
- **Interfaces:**
  - `Journal`: `BeginTx(txID string) (*Transaction, error)`.
  - `Transaction`: `Snapshot(filePath string) error`, `Commit() error`, `Rollback() error`.
  - Snapshots stored in `_meta/snapshots/<tx_id>/`.
  - On simulated crash before commit, `RecoverUnfinishedTransactions()` restores pre-write snapshots automatically.
- [ ] **Step 8.1: Write failing unit test** `TestJournal_CrashRecoveryAndRollback`.
- [ ] **Step 8.2: Verify test fails**.
- [ ] **Step 8.3: Implement `Journal` and `Transaction`** in `journal.go`.
- [ ] **Step 8.4: Verify test passes**.
- [ ] **Step 8.5: Phase Quality Gate:** Run `go test -cover ./pkg/vault`.

---

### Task 9: Persistent Workflow DAG Runner & Finite State Machine
- **Files:**
  - Enhance: `tools/vault-engine/pkg/workflow/runner.go`
  - Test: `tools/vault-engine/pkg/workflow/runner_test.go`
- **Interfaces:**
  - `WorkflowInstance`: Execution states persisted in `_meta/instances/<id>.json`.
  - Parallel join node execution for Bestie & Philip.
- [ ] **Step 9.1: Write unit tests** for parallel join resumption and error isolation.
- [ ] **Step 9.2: Implement clean state advancement**.
- [ ] **Step 9.3: Verify test passes**.
- [ ] **Step 9.4: Phase Quality Gate:** Run `go test -cover ./pkg/workflow` (target >80%).

---

## Wave 4: "Learn / Unlearn" (Reconciliation, Privacy & E2E Verification)

### Task 10: Health Auditor (Broken Links & 90-Day Stale Claims)
- **Files:**
  - Create: `tools/vault-engine/pkg/vault/health.go`
  - Test: `tools/vault-engine/pkg/vault/health_test.go`
- **Interfaces:**
  - `AuditVault(vaultRoot string) (*AuditReport, error)`.
  - Detects broken `[[wikilinks]]`.
  - Flags claims/notes in `04_Knowledge/` unchanged for >90 days without re-verification.
- [ ] **Step 10.1: Write failing unit test** `TestHealthAuditor_BrokenLinksAndStaleClaims`.
- [ ] **Step 10.2: Verify test fails**.
- [ ] **Step 10.3: Implement `AuditVault`** in `health.go`.
- [ ] **Step 10.4: Verify test passes**.
- [ ] **Step 10.5: Phase Quality Gate:** Run `go test -cover ./pkg/vault`.

---

### Task 11: Git Privacy Quarantine Gate
- **Files:**
  - Create: `tools/vault-engine/pkg/vault/privacy.go`
  - Test: `tools/vault-engine/pkg/vault/privacy_test.go`
- **Interfaces:**
  - `CheckGitPrivacy(vaultRoot string) error`.
  - Asserts that `.gitignore` excludes `_inbox/private/`, `_meta/locks/`, `_meta/snapshots/`, and all raw capture payloads.
  - Simulates `git status --porcelain` to prove zero leaks.
- [ ] **Step 11.1: Write unit test** `TestGitPrivacy_QuarantineRules`.
- [ ] **Step 11.2: Implement `CheckGitPrivacy`** in `privacy.go`.
- [ ] **Step 11.3: Verify test passes**.
- [ ] **Step 11.4: Phase Quality Gate:** Run `go test -cover ./pkg/vault`.

---

### Task 12: CLI Commands & End-to-End Integration Suite
- **Files:**
  - CLI: `tools/vault-engine/cmd/vault-engine/main.go`
  - Suite: `tools/vault-engine/test_e2e.sh`
- **Commands Added:**
  - `vault-engine capture <key> <category> <origin> <payload>`
  - `vault-engine route <category> <kind> <slug>`
  - `vault-engine audit-health`
  - `vault-engine check-privacy`
  - `vault-engine list-queue <bucket>`
- [ ] **Step 12.1: Wire CLI commands** into `main.go`.
- [ ] **Step 12.2: Compile static binary**: `go build -o bin/vault-engine ./cmd/vault-engine`.
- [ ] **Step 12.3: Run full E2E suite**: `./test_e2e.sh`.
- [ ] **Step 12.4: Verify 100% PASS on end-to-end integration**.

---

### Task 13: Strict Statement Test Coverage Gate (>80%) & README Sync
- [ ] **Step 13.1: Run coverage analysis across all packages**:
  ```bash
  go test -cover ./pkg/...
  ```
  **Gate Rule:** EVERY package (`pkg/vault`, `pkg/workflow`, `pkg/agent`, `pkg/daemon`) MUST exceed 80.0% statement coverage.
- [ ] **Step 13.2: Synchronize `README.md` and `skills/agentic-vault/SKILL.md`** reflecting newly compiled CLI commands, options, and architecture diagrams.
- [ ] **Step 13.3: Final Commit**:
  ```bash
  git add tools/vault-engine/ README.md skills/agentic-vault/
  git commit -m "feat(vault-engine): complete Go-native 4-phase second brain with >80% test coverage"
  ```
