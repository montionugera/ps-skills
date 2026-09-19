---
name: agy-worker
description: "Dispatch coding and implementation tasks to Antigravity CLI (agy), OpenAI Codex (gpt-5.6-terra), or Cursor CLI (cursor-agent) with proactive quota/on-demand checking and automated fallback to Claude internal subagents."
argument-hint: "[task prompt] [--agent agy|codex|cursor|auto] [--priority <chain>] [--allow-on-demand] [--cwd <dir>]"
---

# External Worker Dispatcher (`agy-worker`, `codex-worker`, `cursor-worker`)

## Overview

Offloads coding, refactoring, and test execution tasks to **Google Antigravity CLI (`agy`)**, **OpenAI Codex (`codex` with `gpt-5.6-terra`)**, or **Cursor CLI (`cursor-agent`)** running in headless mode.

This workflow:
1. **Preserves Primary Token Quota**: Coding tasks run on external provider infrastructure instead of depleting Claude limits.
2. **Proactive Rate Limit Protection**: Reads live provider quota before dispatching. If remaining quota is **< 30% for 5-hour** or **< 10% for weekly**, it returns exit code `10` (`FALLBACK_INTERNAL`), instructing caller orchestrators to seamlessly route to Claude's internal `sonnet` subagents.
3. **Preference Chain & Dynamic Auto-Routing**:
   - Supports declarative priority chains via `--priority` or `AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_ROUTING_PREFERENCE` (e.g. `cursor:gemini-3.8-flash > agy > codex:terra:5.6`).
   - Evaluates left-to-right, respecting `--mode {subscription_quota_remaining,on_demand}` (or `AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_MODE`) to guard against unexpected metered billing.
   - Defaults to best-runway auto-routing across flat providers (`agy` vs `codex`).
4. **Prompt Contract & Scoped Verification**: Wraps prompts with non-negotiable standing rules (TDD cycle, new commits only / never amend, preserving protected configs like `.release.json`, running targeted tests for touched modules rather than the full 10+ minute monorepo suite).
5. **Isolated Execution (`--isolated`) & Salvage**: Cuts a temporary git worktree off `HEAD`, executes within it, and merges changes back on success. If a worker fails or times out (default 900s / 15m, configurable via `AI_AGENT_AUTO_DISPATCH_TIMEOUT`), any partial work is automatically preserved to `/tmp/worker-salvage-<timestamp>.patch` before cleanup.
6. **Enforces Thin Orchestration**: Returns a standardized **≤ 15-line report** (status, modified files, diff summary, and execution output) so orchestrator context windows remain clean and free from archaeological bloat.

---

## CLI Usage

The dispatcher binary is symlinked to `dispatch-agy-worker`, `dispatch-codex-worker`, `dispatch-cursor-worker`, and `dispatch-worker`:

```bash
# Check quota / auth status
dispatch-agy-worker --check-quota            # Checks Antigravity quota
dispatch-codex-worker --check-quota          # Checks Codex quota
dispatch-cursor-worker --check-quota         # Checks Cursor authentication
dispatch-worker --agent auto --check-quota    # Evaluates preference chain or best runway

# Priority chain routing (Cursor On-Demand -> AGY -> Codex)
dispatch-worker --priority "cursor:gemini-3.8-flash > agy > codex" --mode on_demand --task "..."

# Dispatch a coding task to Cursor with specific model
dispatch-cursor-worker --model gemini-3.8-flash --task "Implement task from brief..." --cwd "$WORKTREE_DIR"

# Dispatch a coding task to Codex Terra 5.6
dispatch-codex-worker --task "Implement task from brief..." --cwd "$WORKTREE_DIR"
# or
dispatch-worker --agent auto --task "..." --cwd "$WORKTREE_DIR" --isolated

# --- Parallel Batch Mode (Zero Cold-Start LLM Tax, Python Concurrency) ---
# Run multiple independent tasks concurrently in separate git worktrees
dispatch-worker --batch "Fix test A in src/auth" "Fix test B in src/billing" --cwd "$REPO_DIR"

# Or from a manifest file (JSON list or one-task-per-line txt)
dispatch-worker --batch-file tasks.json --max-parallel 4 --cwd "$REPO_DIR"

# --- Detached / Async Mode (Non-Blocking Fire-and-Forget) ---
# Fire off in background immediately (returns job ID, exits 0)
dispatch-worker --task "Heavy refactor in src/engine" --detach --cwd "$REPO_DIR"

# Inspect active jobs (0 LLM tokens, 3-line status)
dispatch-worker --status dw-1789785000-a1b2
dispatch-worker --status all

# Wait for completion when ready (Python blocks locally, 0 LLM polling tokens)
dispatch-worker --wait dw-1789785000-a1b2
dispatch-worker --wait all
```

### Exit Codes Contract

| Exit Code | Meaning | Action for Orchestrator |
| :--- | :--- | :--- |
| `0` | **Success** | Review git diff and advance to Review Gate |
| `1` | **Execution Failed** | Re-dispatch or diagnose failure |
| `2` | **Invalid Arguments** | Fix parameters |
| `10` | **`FALLBACK_INTERNAL`** | External quota below threshold; dispatch internal Claude Sonnet agent |

---

## Integration with Subagent-Driven Development (SDD)

When using `subagent-driven-development`:

### 1. Synchronous or Detached Single Batch
```bash
dispatch-codex-worker \
  --task "Read brief: [BRIEF_FILE]. Implement exactly what is specified. Run tests and keep output." \
  --cwd "[directory]"
```
- If exit code is `0`: Process the ≤ 15-line report and proceed directly to Gate 1 / Review Gate.
- If exit code is `10`: Automatically fallback to internal subagent:
  ```
  Agent:
    subagent_type: general-purpose
    description: "Implement Task N: [task name]"
    model: sonnet
  ```

### 2. Multi-Task Parallel Execution (Optimal Tokenomics)
Instead of spawning N separate Claude subagents (which burn ~70K cold-start tokens each), dispatch all tasks in a single batch call:
```bash
dispatch-worker \
  --batch "Implement task 1 from brief 1" "Implement task 2 from brief 2" \
  --cwd "[directory]"
```
Python runs the tasks concurrently in isolated worktrees and merges back sequentially without burning primary context tokens.
