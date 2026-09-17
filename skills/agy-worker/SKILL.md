---
name: agy-worker
description: "Dispatch coding and implementation tasks to Antigravity CLI (agy) or OpenAI Codex (gpt-5.6-terra) with proactive quota checking (>30% 5h, >10% weekly) and automated fallback to Claude internal subagents."
argument-hint: "[task prompt] [--agent agy|codex|auto] [--cwd <dir>] [--min-5h <num>] [--min-weekly <num>]"
---

# External Worker Dispatcher (`agy-worker` & `codex-worker`)

## Overview

Offloads coding, refactoring, and test execution tasks to **Google Antigravity CLI (`agy`)** or **OpenAI Codex (`codex` with `gpt-5.6-terra`)** running in headless mode.

This workflow:
1. **Preserves Primary Token Quota**: Coding tasks run on external provider infrastructure instead of depleting Claude limits.
2. **Proactive Rate Limit Protection**: Reads live provider quota before dispatching. If remaining quota is **< 30% for 5-hour** or **< 10% for weekly**, it returns exit code `10` (`FALLBACK_INTERNAL`), instructing caller orchestrators to seamlessly route to Claude's internal `sonnet` subagents.
3. **Dynamic Best-Runway Auto-Routing**: With `--agent auto`, computes runway score `min(5h_remaining - min_5h, weekly_remaining - min_weekly)` and dispatches to the agent with the highest runway surplus. If both fail minimum thresholds, falls back to internal Claude subagents (exit code `10`).
4. **Prompt Contract Enforcement**: Wraps prompts with non-negotiable standing rules (TDD cycle, new commits only / never amend, preserving protected configs like `.release.json`, evidence-based verification).
5. **Isolated Execution (`--isolated`)**: Cuts a temporary git worktree off `HEAD`, executes within it, and merges changes back on success while guaranteeing cleanup in all exit paths.
6. **Enforces Thin Orchestration**: Returns a standardized **≤ 15-line report** (status, modified files, diff summary, and execution output) so orchestrator context windows remain clean and free from archaeological bloat.

---

## CLI Usage

The dispatcher binary is symlinked to `dispatch-agy-worker`, `dispatch-codex-worker`, and `dispatch-worker`:

```bash
# Check quota status
dispatch-agy-worker --check-quota         # Checks Antigravity quota
dispatch-codex-worker --check-quota       # Checks Codex quota
dispatch-worker --agent auto --check-quota # Auto-selects best runway

# Dispatch a coding task to Antigravity
dispatch-agy-worker --task "Implement task from brief..." --cwd "$WORKTREE_DIR"

# Dispatch a coding task to Codex Terra 5.6
dispatch-codex-worker --task "Implement task from brief..." --cwd "$WORKTREE_DIR"
# or
dispatch-worker --agent auto --task "..." --cwd "$WORKTREE_DIR" --isolated

# Dry run (verify quota and parameters without invoking agent)
dispatch-codex-worker --task "..." --dry-run --isolated
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

When using `subagent-driven-development`, the orchestrator executes each batch with:

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
