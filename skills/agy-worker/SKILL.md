---
name: agy-worker
description: "Use when a task is bulk mechanical work a brief fully specifies (bulk edits, sweeps, renames, spec fix-ups, diagram redraws, command-only checks, plan tasks with exact files and tests). Dispatches it to Antigravity CLI via dispatch-worker --agent agy with a verify command and acceptance criteria, falling back to a Sonnet subagent when quota is low."
argument-hint: "[task prompt] --agent agy [--cwd <dir>] [--verify-cmd <cmd>] [--acceptance-file <file>] [--timeout <seconds>]"
---

# External Worker Dispatcher (`agy-worker`, `cursor-worker`)

## Overview

Offloads coding, refactoring, and test execution tasks to **Google Antigravity CLI (`agy`)** or **Cursor CLI (`cursor-agent`)** running in headless mode.

**Codex is disabled (2026-10-03): never dispatch to it.** `--agent codex` and `dispatch-codex-worker` exit 2 with `codex is disabled`; a `--priority` chain entry naming codex is dropped with a one-line stderr notice and routing continues with the rest (a chain naming only codex exits 2).

This workflow:
1. **Preserves Primary Token Quota**: Coding tasks run on external provider infrastructure instead of depleting Claude limits.
2. **Proactive Rate Limit Protection**: Reads live provider quota before dispatching. If remaining quota is **< 30% for 5-hour** or **< 10% for weekly**, it returns exit code `10` (`FALLBACK_INTERNAL`), instructing caller orchestrators to seamlessly route to Claude's internal `sonnet` subagents.
3. **Preference Chain & Dynamic Auto-Routing**:
   - Supports declarative priority chains via `--priority` or `AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_ROUTING_PREFERENCE` (e.g. `cursor:gemini-3.8-flash > agy`).
   - Evaluates left-to-right, respecting `--mode {subscription_quota_remaining,on_demand}` (or `AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_MODE`) to guard against unexpected metered billing.
   - **Always pass `--agent agy`.** The tool's own default is `auto`; never rely on it and never write `--agent auto`.
4. **Prompt Contract & Scoped Verification**: Wraps prompts with non-negotiable standing rules (TDD cycle, new commits only / never amend, preserving protected configs like `.release.json`, running targeted tests for touched modules, and visual integrity forbidding invented CSS classes).
5. **Isolated Execution (`--isolated`) & Salvage**: Cuts a temporary git worktree off `HEAD`, executes within it, and merges changes back on success. If a worker fails or times out (default 900s / 15m, configurable via `AI_AGENT_AUTO_DISPATCH_TIMEOUT`), any partial work is automatically preserved to `/tmp/worker-salvage-<timestamp>.patch` before cleanup.
6. **Enforces Thin Orchestration**: Returns a standardized **≤ 15-line report** (status, modified files, diff summary, and execution output) so orchestrator context windows remain clean and free from archaeological bloat.

---

## CLI Usage

The dispatcher binary is symlinked to `dispatch-agy-worker`, `dispatch-cursor-worker`, and `dispatch-worker`:

```bash
# Check quota / auth status
dispatch-agy-worker --check-quota            # Checks Antigravity quota
dispatch-cursor-worker --check-quota         # Checks Cursor authentication

# Dispatch a coding task to Cursor with specific model
dispatch-cursor-worker --model gemini-3.8-flash --task "Implement task from brief..." --cwd "$WORKTREE_DIR"

# --- The canonical dispatch (use this shape for every code task) ---
# Launch detached, then block once on the result. See "The Brief" and "Accepting a Result" below.
dispatch-worker --agent agy --detach \
  --task "$(cat "$BRIEF_FILE")" \
  --cwd "$WORKTREE_DIR" \
  --verify-cmd "<the test / lint / build command that proves this task>" \
  --acceptance-file "$ACCEPTANCE_FILE" \
  --timeout 3600                              # size it to the task, see the table below
dispatch-worker --wait <job-id> --timeout 4200   # ONE blocking wait; run it as a background command

# --- Parallel Batch Mode (Zero Cold-Start LLM Tax, Python Concurrency) ---
# Run multiple independent tasks concurrently in separate git worktrees
dispatch-worker --agent agy --batch "Fix test A in src/auth" "Fix test B in src/billing" --cwd "$REPO_DIR" --verify-cmd "<cmd>"

# Or from a manifest file (JSON list or one-task-per-line txt)
dispatch-worker --agent agy --batch-file tasks.json --max-parallel 4 --cwd "$REPO_DIR" --verify-cmd "<cmd>"

# --- Detached / Async Mode (Non-Blocking Fire-and-Forget) ---
# Fire off in background immediately (returns job ID, exits 0)
dispatch-worker --agent agy --task "Heavy refactor in src/engine" --detach --cwd "$REPO_DIR" \
  --verify-cmd "<cmd>" --acceptance-file "$ACCEPTANCE_FILE" --timeout 9000

# --- Heavy Thinking & Architecture Mode (Capability deep-design-v1) ---
# Offload deep reasoning, RFC generation, or code reviews: Claude Opus 5.5 only (`claude -p`).
# There is no fallback thinker: a failed Claude run is reported as a failure.
# Defaults reasoning effort to 'medium' (--effort overrides, or THINK_EFFORT env var).
# Fails closed (exit code 12) if Claude is unavailable or a non-Claude model is specified.
dispatch-thinker --task "Synthesize multi-wave portal architecture" \
  --context docs/specs/hub.md \
  --output-file /tmp/portal-synthesis.md

# Or via dispatch-worker directly
dispatch-worker --capability deep-design-v1 --task "Review architecture for multi-tenant auth" \
  --context docs/superpowers/specs/auth-spec.md logs/auth.log \
  --output-file docs/reviews/phase-1-review.md

# --- Context Bundling (No Token Bloat on CLI) ---
# Bundle reference documents directly without stuffing prompts into CLI args
dispatch-worker --task "Implement task 2.1" --context docs/spec.md logs/test.log --cwd "$REPO_DIR"

# --- Plan Extraction Mode ---
# Extract tasks directly from an implementation plan (writing-plans markdown)
dispatch-worker --from-plan docs/superpowers/specs/2026-09-plan.md --phase 1 --cwd "$REPO_DIR"

# --- Live Log Tail & Monitoring ---
# View last N lines of a running or completed worker job
dispatch-worker --tail latest -n 20
dispatch-worker --tail dw-1789785000-a1b2 -f    # Follow live output stream
```

### The Brief

Write the brief to a file and pass it with `--task "$(cat "$BRIEF_FILE")"`. Five parts, in this order:

```markdown
Goal: <one sentence, verbatim from the plan or the user>
Files in scope: <exact paths the worker may create or edit; the worktree it must never leave>
Acceptance criteria: <checkable statements; also passed via --acceptance-file>
Verify command: <the same command given to --verify-cmd, so the worker runs it before finishing>
Out of scope: <what it must not touch or invent: routes, tables, file names, package names not already in the repo>
```

A worker with no acceptance criteria and no verify command has only the task text to judge "done" by, and it fills the gaps by inventing. Names it must use (routes, tables, file names, package names) go in the brief as exact values taken from the repo.

### Timeout and the Wait

The default `--timeout` is 900s. That fits a read-only check or a small edit; it is too short for implementation work, and a run that hits it stops as `TIMEOUT_PARTIAL_WORK` with its edits unverified and unmerged.

| Task | `--timeout` |
| :--- | :--- |
| Read-only check, audit, or a single-file edit | `900` (default) |
| One plan task implemented from a brief, with its tests | `3600` |
| A multi-task plan part, or anything whose verify command runs a full suite or a build | `9000` |

- **Wait once, never poll.** After `--detach`, run `dispatch-worker --wait <job-id> --timeout <seconds>` as a single background command and do other work until it returns. Do not loop on `--status`, `--tail`, `sleep`, or marker files, and do not end the turn with a "still running" message.
- `--wait` is bounded by its own `--timeout` (also 900s by default). Give it the job's `--timeout` plus the `--verify-timeout`; when the bound passes it reports `Status: UNKNOWN (exit 1)` while the job keeps running, so wait again rather than re-dispatching.
- `--wait all` blocks on every running job; use it for a batch.
- `--status <job-id>` is for one look when a wait returned `UNKNOWN` or a job looks stuck (`STALLED?`), not for a loop.

### Observability

- **Event log**: every run appends JSONL records to `~/.local/state/dispatch/events.jsonl` (override with `DISPATCH_EVENTS_FILE`): `route`, `start`, `fallback`, `timeout`, `verify_failed`, `finish` (agent, model, status, exit code, duration, files changed). Sync, detached and batch runs are all covered; only a task hash is logged, never any prompt text, and the file is created owner-only (0600).
- **Live output**: detached jobs stream worker stdout/stderr into their log as it arrives, so `dispatch-worker --tail <job> -f` shows progress before the worker exits.
- **Stall detection**: `dispatch-worker --status` shows `last output Ns ago` for RUNNING jobs and marks `STALLED?` after 300s of silence. Check `--tail` before killing it.
- **Stats**: `dispatch-worker --stats [DAYS]` (default 7) prints runs, success %, timeouts, fallbacks, verify failures and median duration per agent.
- **Recovery**: a run pinned with `--agent agy` is never retried on another agent, and a quota observation older than 60 minutes counts as not eligible.
- **Stale quota reading**: when the `FALLBACK_INTERNAL` message contains `[stale: observation`, the reading is old, not low. The reading is rewritten by an interactive agy session's status line, so if `herdr agent list` shows a live `agy` pane, re-run the same dispatch once. If it is still stale, take the Sonnet fallback and say in your report that the cause was a stale reading, not low quota.
- **Detached jobs do not get the runtime fallback**: a `--detach` job runs only the agent it was routed to; if it fails, re-dispatch it yourself.

### Exit Codes Contract

| Exit Code | Meaning | Action for Orchestrator |
| :--- | :--- | :--- |
| `0` | **Worker and verify exited clean** | Apply "Accepting a Result" below before advancing to the Review Gate |
| `1` | **Execution Failed** | Re-dispatch or diagnose failure |
| `2` | **Invalid Arguments** | Fix parameters |
| `10` | **`FALLBACK_INTERNAL`** | External quota below threshold; dispatch internal Claude Sonnet agent |
| `13` | **`VERIFY_FAILED`** | Worker exited 0 but the verify command failed twice (one automatic fix-up retry). Nothing was merged; the worktree path is in the report. Inspect it, do NOT re-dispatch blindly |
| `12` | **`THINKER_UNAVAILABLE`** | deep-design-v1 capability unavailable or forbidden model; fail closed (do NOT fallback to inline runner) |

### Verify Before Merge

Exit code `0` from the worker is not acceptance. After the worker exits `0` and **before any merge**, the dispatcher runs a verify command inside the worker's worktree:

```bash
dispatch-worker --isolated --task "..." \
  --verify-cmd "./scripts/precheck.sh" \          # default when that script exists and is executable
  --verify-timeout 600 \                          # seconds; a timeout counts as failure
  --acceptance-file path/to/acceptance.md          # or --acceptance "<text>"; becomes the prompt's "Acceptance criteria" section
```

- No `--verify-cmd` and no executable `scripts/precheck.sh`: the run proceeds with a one-line `UNVERIFIED` warning. `--no-verify` opts out explicitly.
- On verify failure the same worker is re-invoked **once** with the last 40 lines of verify output, then verified again. A second failure is final: exit `13`, nothing merged, worktree left in place.
- Every result carries the outcome: report line `Verified: true|false|skipped (<cmd>)`, and `verified` / `verify_cmd` in detached job state and batch results.
- Always pass acceptance criteria. Omitting them only prints a warning, but the worker then has nothing but the task text to judge "done" by.
- `--no-verify` is for tasks with nothing to run (a read-only audit, a prose-only doc). A task that writes code, config, specs with checkable claims, or diagrams gets a `--verify-cmd`; when no test covers it, write a check (a `grep` for the required strings, a schema or diagram validator) and pass that.

### Accepting a Result

`Status: SUCCESS` is not acceptance. Read two lines of the report (`dispatch-worker --wait` prints it; batch results carry the same fields):

| Report shows | Treat as |
| :--- | :--- |
| `Files Modified:` above 0 **and** `Verified: true` | Accepted. Advance to the Review Gate; the verify output is the test evidence, do not re-run it |
| `Files Modified: 0` (`0 files (no git diff)`) on a task that was meant to write something | **Failed.** Nothing landed. Read `dispatch-worker --tail <job-id>`, fix the brief, re-dispatch |
| `Verified: skipped` (`verified=skipped`) on a task that wrote files | **Unverified, not done.** Run the verify command yourself once in the worktree, or re-dispatch with `--verify-cmd`. Do not send it to review as finished work |
| `TIMEOUT_PARTIAL_WORK` | **Failed, but keep the work.** The edits are in the worktree (or the salvage patch). Re-dispatch in the same `--cwd` with a larger `--timeout` and "continue from the existing changes"; never start over from the default 900s |

---

## Integration with Subagent-Driven Development (SDD)

When using `subagent-driven-development`:

### 1. Synchronous or Detached Single Batch
```bash
dispatch-worker --agent agy --detach \
  --task "Read brief: [BRIEF_FILE]. Implement exactly what is specified. Run tests and keep output." \
  --cwd "[directory]" \
  --verify-cmd "[the plan's test command for this task]" \
  --acceptance-file "[BRIEF_FILE]" \
  --timeout 3600
dispatch-worker --wait [job-id] --timeout 4200
```
- If exit code is `0`: apply "Accepting a Result", then proceed to Gate 1 / Review Gate with the ≤ 15-line report as the test evidence.
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
dispatch-worker --agent agy \
  --batch "Implement task 1 from brief 1" "Implement task 2 from brief 2" \
  --cwd "[directory]" \
  --verify-cmd "[test command]" --acceptance-file "[shared acceptance file]" --timeout 3600
```
Python runs the tasks concurrently in isolated worktrees and merges back sequentially without burning primary context tokens.
