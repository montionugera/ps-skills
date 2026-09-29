# Autonomous Multi-Agent Vault Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete, persistent, autonomous multi-agent execution loop (Olivier, Bestie, Philip) for the Obsidian vault, turning raw inbox drops into fully researched, triaged, and OCC-committed candidate records automatically.

**Architecture:** An event-driven autonomous architecture consisting of:
1. A persistent Go workflow state machine runner (`vault-engine run-workflow` / `tick`) executing declarative DAGs with instance state persistence in `_meta/instances/`.
2. A deterministic subagent adapter dispatching Bestie (BA) and Philip (PD) in parallel with strict schema sandboxing (`--json-schema`).
3. An autonomous watcher/daemon (`vault-engine daemon`) and macOS `launchd` service that continuously monitors `_inbox/human/` and drives lifecycle transitions.
4. Resilient Obsidian presentation with Dataview dashboards and pure-markdown fallback MOCs.

**Tech Stack:** Go 1.22 (static binary `vault-engine`), JSON Schema Draft 2020-12, Antigravity CLI / Codex subagent harnesses, macOS `launchd`, Obsidian YAML properties.

**Spec:** [`/tmp/thinker_plan_verification.md`](file:///tmp/thinker_plan_verification.md) and [`/tmp/thinker_consult_result.md`](file:///tmp/thinker_consult_result.md).

## Global Constraints

- **LLMs Propose; Engine Commits:** Subagents never write directly to canonical vault files. All updates pass through optimistic concurrency control (`vault-engine commit --expected-sha`).
- **No Infinite Loops:** Workflow DAGs must be strictly acyclic; state transitions are finite state machine steps.
- **Deterministic Schemas:** Bestie outputs must match `schemas/research-notes-v1.json`; Philip outputs must match `schemas/technical-audit-v1.json`.
- **Zero Raw Shell for Recruited Agents:** Recruited subagents have no `define_subagent` or raw shell tools.
- **Git Provenance:** All engine source code lives under `tools/vault-engine/` in `ps-skills` (`feat/F-015`) with full test coverage.

---

### Task 1: Persistent Workflow Instance Runner in Go

**Files:**
- Create: `tools/vault-engine/pkg/workflow/runner.go`
- Modify: `tools/vault-engine/pkg/workflow/dag.go`
- Test: `tools/vault-engine/pkg/workflow/runner_test.go`
- CLI: `tools/vault-engine/cmd/vault-engine/main.go`

**Interfaces:**
- `RunWorkflow(wf *WorkflowDAG, instanceID string, initialPayload map[string]interface{}) (*WorkflowInstance, error)`
- Instance state stored at `_meta/instances/<instance-id>.json`.

- [ ] **Step 1.1**: Define `WorkflowInstance` and `NodeAttempt` structs in `pkg/workflow/runner.go` with fields: `InstanceID`, `WorkflowID`, `CurrentState`, `Status` (`running`, `completed`, `failed`, `quarantined`), `Attempts`, `Artifacts`, `CreatedAt`, `UpdatedAt`.
- [ ] **Step 1.2**: Implement state transition logic: handle `handler`, `parallel_join`, and `terminal` node types.
- [ ] **Step 1.3**: Write unit tests in `pkg/workflow/runner_test.go` testing state progression, crash resumption, and terminal states.
- [ ] **Step 1.4**: Expose CLI command `vault-engine run-workflow <workflow_file> <payload_json>` in `cmd/vault-engine/main.go`.
- [ ] **Step 1.5**: Phase Gate: Run `go test -v ./pkg/workflow` and verify 100% pass.

---

### Task 2: Multi-Agent Subagent Execution Adapter

**Files:**
- Create: `tools/vault-engine/pkg/adapter/harness.go`
- Test: `tools/vault-engine/pkg/adapter/harness_test.go`
- Schemas: `tools/vault-engine/schemas/research-notes-v1.json`, `technical-audit-v1.json`

**Interfaces:**
- `ExecuteAgent(manifest *agent.AgentManifest, taskPrompt string, schemaPath string) (json.RawMessage, error)`
- Uses local agent CLI (`agy` or configured subagent worker) with `--json-schema` and `--print-timeout`.

- [ ] **Step 2.1**: Implement `HarnessAdapter` in `pkg/adapter/harness.go` that constructs bounded prompt envelopes, injects required schemas, and invokes the worker.
- [ ] **Step 2.2**: Add output validation: parse worker stdout, validate against target JSON Schema, reject malformed payloads, and isolate to dead-letter queue if unrepairable.
- [ ] **Step 2.3**: Wire Bestie and Philip execution into the parallel join state in `pkg/workflow/runner.go`.
- [ ] **Step 2.4**: Write unit/mock tests in `pkg/adapter/harness_test.go` verifying timeout handling and schema enforcement.
- [ ] **Step 2.5**: Phase Gate: Run `go test -v ./...` and commit to `feat/F-015`.

---

### Task 3: Autonomous Vault Ingest & Watcher Daemon

**Files:**
- Create: `tools/vault-engine/pkg/daemon/watcher.go`
- Create: `tools/vault-engine/scripts/com.pasit.vault-daemon.plist`
- Modify: `tools/vault-engine/cmd/vault-engine/main.go`

**Interfaces:**
- `StartDaemon(vaultRoot string, interval time.Duration)`
- Polls `_inbox/human/` for incoming `.md` files.
- Automatically executes ingest -> launches `idea-evaluation-pipeline` workflow instance.

- [ ] **Step 3.1**: Implement `Watcher` in `pkg/daemon/watcher.go` with debouncing, singleton process guard (`_meta/guards/daemon.guard`), and graceful shutdown.
- [ ] **Step 3.2**: Add `vault-engine daemon [--interval 5s] [--once]` CLI command.
- [ ] **Step 3.3**: Create macOS `launchd` plist template for background auto-run.
- [ ] **Step 3.4**: Test watcher with `--once` flag: drop note in `_inbox/human/`, run `vault-engine daemon --once`, verify automatic workflow initiation.
- [ ] **Step 3.5**: Phase Gate: Verify `daemon --once` completes ingest and triggers workflow instance without error.

---

### Task 4: Obsidian Dashboard & Resilience Optimization

**Files:**
- Modify: `/Users/pasitnusso/Documents/Obsidian Vault/Dashboard.md`
- Create: `/Users/pasitnusso/Documents/Obsidian Vault/01_Ideas/Ideas MOC.md`
- Check: `/Users/pasitnusso/Documents/Obsidian Vault/.obsidian/community-plugins.json`

- [ ] **Step 4.1**: Check `.obsidian` configuration in the vault to confirm Dataview plugin status.
- [ ] **Step 4.2**: Add static Markdown MOC (`Ideas MOC.md`) automatically updated by `vault-engine rebuild-index` so the vault remains 100% navigable even if community plugins are disabled.
- [ ] **Step 4.3**: Ensure `Dashboard.md` includes both bounded Dataview queries (with `LIMIT 15`) and static links to top hubs.
- [ ] **Step 4.4**: Phase Gate: Inspect notes in Obsidian and confirm rendering without plugin errors.

---

### Task 5: End-to-End Live Verification & Documentation

**Files:**
- Modify: `tools/vault-engine/README.md`
- Modify: `README.md` in `ps-skills`
- Test: `tools/vault-engine/test_e2e.sh`

- [ ] **Step 5.1**: Update `tools/vault-engine/README.md` with complete architecture diagrams, CLI reference, and daemon instructions.
- [ ] **Step 5.2**: Update root `README.md` in `ps-skills` documenting the new `vault-engine` tool and multi-agent workflow capabilities.
- [ ] **Step 5.3**: Run full `test_e2e.sh` verifying unit tests, DAG validation, daemon processing, and OCC commits.
- [ ] **Step 5.4**: Independent Review: Review diff against quality gates and ensure clean git status.
- [ ] **Step 5.5**: Phase Gate: Commit all final artifacts and report evidence.
