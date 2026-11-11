---
name: agent-mesh-coordination
description: Agent-agnostic coordination, cross-session message bus, resource claims with TTL leases, and anti-stall execution supervisor across Claude Code, Antigravity, and Codex. For in-session AGY work, native invoke_subagent + send_message replaces mesh; reserve mesh for cross-terminal / cross-repo coordination.
---

# Agent Mesh Coordination (`mesh`)

A lightweight, daemon-free coordination layer for autonomous AI coding agents (Claude Code, Antigravity CLI, OpenAI Codex, Cursor).

## Core Capabilities

1. **Deterministic Mutual Exclusion (`claims`)**:
   - Prevent two agents or sessions from editing the same resource or file concurrently.
   - All claims have automatic TTL expiration and incrementing fencing tokens to prevent zombie agent overwrites.
2. **Cross-Session Direct Messaging (`messages`)**:
   - Deliver addressed JSON messages between sessions and across different repositories.
   - Mailboxes are persistent in SQLite (`~/.agentmesh/mesh.db`) with read and ack receipts.
3. **Autonomous Anti-Stall Execution (`mesh-run`)**:
   - External supervisor for Antigravity (`agy`) and headless CLI runs.
   - Automatically catches premature turn stops and reinjects prompts until the task is complete.
4. **Durable Idea / Discovery Backlog (`ideas`)**:
   - Stores Rule 4 discoveries ("file off-goal findings; never chase them") so agents remain scoped without losing good ideas.

---

## Coordination Boundary: In-Session AGY vs Cross-Session Mesh

| Context | Recommended Mechanism | Tooling & Primitives | Why |
| :--- | :--- | :--- | :--- |
| **In-Session Multi-Agent (inside AGY)** | Native AGY Subagents | `invoke_subagent`, `send_message`, `define_subagent`, `manage_subagents` | Reactive event loop: child completions & messages automatically wake parent orchestrator with zero polling. Workspaces (`branch` / `share`) handle filesystem isolation natively. |
| **Cross-Terminal / Cross-Process** | SQLite Agent Mesh (`mesh`) | `mesh claim`, `mesh send`, `mesh inbox`, `mesh status` | Independent sessions in different terminal tabs or tmux panes lack shared in-memory event loops and require SQLite-backed persistent leases and mailboxes. |
| **Cross-Repository** | SQLite Agent Mesh (`mesh`) | `mesh send --to <agent-id>`, `mesh claim` | Cross-repo boundaries where workspaces cannot be linked via `Workspace: "share"`. |
| **Headless Anti-Stall Runner** | CLI Supervisor (`mesh-run`) | `mesh-run "<prompt>" --max-turns 15` | External supervisor ensuring headless CLI agents complete tasks without premature turn abandonment. |

> [!IMPORTANT]
> When executing inside an active Google Antigravity (`agy`) session, **do NOT use `mesh` polling or SQLite message queues for subagents**. Native `invoke_subagent` and `send_message` provide reactive, zero-polling wakeup and in-memory lifecycle management. Reserve `mesh` exclusively for cross-terminal tabs, external daemon processes, or cross-repository coordination.

---

## CLI Usage

The single CLI binary `mesh` is installed at `~/.local/bin/mesh`.

### Status and Health
```bash
mesh status              # View active agents, held claims, open tasks, unread messages
mesh doctor              # Run database integrity check and health diagnostics
```

### Claiming Resources (Safe Locking)
```bash
# Claim a file or resource for 5 minutes
mesh claim src/auth/service.ts --ttl 300 --note "Refactoring auth token validation"

# Release when done
mesh release src/auth/service.ts
```

### Passing Messages Across Sessions / Repos
```bash
# Send a message to an agent
mesh send --to <agent-id> --kind handoff --body '{"summary": "API updated", "next_step": "Run integration tests"}'

# Read and acknowledge incoming inbox
mesh inbox
mesh ack <message-id>
```

### Tracking Tasks and Off-Goal Ideas
```bash
# Add a task
mesh task-add "Implement payment webhook signature validation"

# File an off-goal idea (Rule 4)
mesh idea-add "Add redis caching layer for session queries" --priority normal --blast-radius R2
```

## Anti-Stall Runner

For headless tasks in Antigravity CLI, run via the `mesh-run` wrapper:
```bash
mesh-run "Run all test suites and fix any failures" --max-turns 15
```
If the model yields turn control on plain text without finishing, `mesh-run` automatically sends a continuation signal.
