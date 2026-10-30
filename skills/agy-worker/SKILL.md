---
name: agy-worker
description: "Use when a task is bulk mechanical work a brief fully specifies. Supports two modes: (1) native in-session AGY multi-agent orchestration (invoke_subagent with 80/20 Flash gemini-3.8-flash-high vs Argon gemini-4-argon tiering), and (2) external CLI dispatch via dispatch-worker --agent agy with quota guarding and verify gates."
argument-hint: "[task prompt] [--agent agy] [--escalate] [--cwd <dir>] [--verify-cmd <cmd>] [--acceptance-file <file>] [--timeout <seconds>]"
---

# External Worker Dispatcher (`agy-worker`, `cursor-worker`) & Native AGY Multi-Agent

## Overview

Offloads coding, refactoring, and test execution tasks using a **Two-Mode Architecture**:
1. **Mode 1: In-Session Native AGY (`invoke_subagent`)**: When running inside Google Antigravity (`agy`), leverage native multi-agent capabilities directly with the **80/20 Flash-First pipeline**. Never shell out to `dispatch-worker` from within an active AGY session.
2. **Mode 2: External Cross-Harness CLI (`dispatch-worker --agent agy`)**: When orchestrating from Claude Code, OpenCode, or headless shell scripts, dispatch to Google Antigravity CLI (`agy`) or Cursor CLI (`cursor-agent`) in headless mode with quota guarding and verify gates.

**Codex is disabled (2026-10-03): never dispatch to it.** `--agent codex` and `dispatch-codex-worker` exit 2 with `codex is disabled`; a `--priority` chain entry naming codex is dropped with a one-line stderr notice and routing continues with the rest (a chain naming only codex exits 2).

---

## Two-Mode & 80/20 Flash-First Architecture

### Mode 1: In-Session Native AGY Orchestration (`invoke_subagent`)

When executing inside Antigravity (`agy`), orchestrators MUST prioritize native in-session multi-agent tools over shelling out to CLI scripts:
- **`invoke_subagent`**: Dispatch parallel subagents in a single turn. Set workspace isolation explicitly:
  - `Workspace: "share"`: Zero-copy shared repository worktree for parallel disjoint tasks (optimal speed & disk usage).
  - `Workspace: "branch"`: Isolated cloned/branched worktree for overlapping files or high-blast-radius edits.
  - `Workspace: "inherit"`: Shares the exact working directory for read-only research, codebase grep, or diagnostic runs.
- **`send_message`**: Multi-turn warm fix loops. In Round 2 fixes, send feedback directly to the idle implementer subagent's `conversationID`. Zero cold-start token penalty; preserves context from Round 1.
- **`define_subagent`**: Declare specialized session-scoped subagents (e.g. `code-reviewer`, `self-grill-auditor`) with tailored system prompts and tool restrictions.
- **`manage_subagents`**: Inspect running subagents (`Action: "list"`), kill stalled agents (`Action: "kill"`), or clean up.

#### The 80/20 Flash-First Model Tiering in AGY:
- **80% Fast Worker Tier (`Model: "flash"` / `gemini-3.8-flash-high`)**:
  - Codebase exploration & `graft` queries (`TypeName: "research"`, `Model: "flash"`, `Workspace: "inherit"`).
  - Diagram XML math & visual rendering (`drawio-skill` loops, `validate.py --score`, `render-spec`).
  - Round 1 & Round 2 plan implementation (`TypeName: "self"`, `Model: "flash"`, `Workspace: "share"` or `"branch"`).
  - Step 2 Test verification (`Verify`) and Step 4 simplification (`/simplify`, `README.md` sync, `graft build`).
- **20% Frontier Tier (`Model: "inherit"` / `gemini-4-argon`)**:
  - Thin orchestrator thinking, brainstorming, spec writing, and plan drafting on the main thread.
  - Step 3 Adversarial review (`code-reviewer`, `self-grill-audit`).
  - Round 3+ Escalation: If Round 2 fails review/verification, terminate the Flash subagent (`manage_subagents(Action: "kill")`) and escalate to a fresh `gemini-4-argon` subagent (`Model: "inherit"`). Also default to Argon for `[complex]` or `[architectural]` tasks.

### Mode 1b: T3 Code Native Cross-Provider Delegation (`t3-code:delegate_task`)

When running inside **T3 Code** (either as Antigravity `antigravity` or Claude Code `claudeAgent`), use the `t3-code` MCP server for cross-provider child tasks:
- **Discover live models**: Call `orchestrator_capabilities` to inspect active providers (`claudeAgent`: `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-fable-5-1`, `claude-haiku-5-5`; `antigravity`: `gemini-4-argon-*`, `gemini-3.8-flash-*`) and effort options.
- **Dispatch (`delegate_task`)**: Use `mode: "async"` with `target: {"providerInstanceId": "claudeAgent", "model": "claude-sonnet-5-5", "options": [{"id": "effort", "value": "high"}]}` (or vice versa from Claude to `antigravity`).
- **Zero-Polling Reactive Monitoring**: End your turn after `delegate_task(mode="async")`. T3 Code automatically wakes the parent thread when the child reaches a terminal state; then call `task_status(taskId)` to read the summary, or `t3_thread_read(threadId=childThreadId)` to inspect detailed steps.

### Mode 2: External Cross-Harness CLI Dispatch (`dispatch-worker --agent agy`)

When orchestrating from Claude Code, OpenCode, or headless CI:
1. **Preserves Primary Token Quota**: Coding tasks run on external provider infrastructure instead of depleting Claude limits.
2. **Proactive Rate Limit Protection**: Reads live provider quota before dispatching. If remaining quota is **< 30% for 5-hour** or **< 10% for weekly**, it returns exit code `10` (`FALLBACK_INTERNAL`), instructing caller orchestrators to seamlessly route to Claude's internal `sonnet` subagents.
3. **Preference Chain & Dynamic Auto-Routing**:
   - Supports declarative priority chains via `--priority` or `AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_ROUTING_PREFERENCE` (e.g. `cursor:gemini-3.8-flash > agy`).
   - Default worker model is `agy:gemini-3.8-flash-high`.
   - **Always pass `--agent agy`.** The tool's own default is `auto`; never rely on it and never write `--agent auto`.
4. **Escalation Flag (`--escalate`)**:
   - Pass `--escalate` to route implementation tasks directly to `gemini-4-argon` (for Round 3+ retries or complex tasks).
5. **Frontier Thinking Mode (`dispatch-thinker` / `--capability deep-design-v1`)**:
   - Routes to **Claude Opus 5.5** or **Gemini 4 Argon** (`gemini-4-argon`). Fails closed (exit code `12`) if neither frontier model is available or an ineligible model is requested.
6. **Prompt Contract & Scoped Verification**: Wraps prompts with non-negotiable standing rules (TDD cycle, new commits only / never amend, preserving protected configs like `.release.json`, running targeted tests for touched modules, and visual integrity forbidding invented CSS classes).
7. **Isolated Execution (`--isolated`) & Salvage**: Cuts a temporary git worktree off `HEAD`, executes within it, and merges changes back on success. If a worker fails or times out, any partial work is automatically preserved to `/tmp/worker-salvage-<timestamp>.patch` before cleanup.
8. **Enforces Thin Orchestration**: Returns a standardized **≤ 15-line report** (status, modified files, diff summary, and execution output) so orchestrator context windows remain clean and free from archaeological bloat.

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

# --- Escalation Mode (Frontier Gemini 4 Argon Implementation) ---
# Escalate from default 3.8-flash worker to frontier Gemini 4 Argon for Round 3 fixes or complex architectural tasks
dispatch-worker --agent agy --escalate --task "Fix complex concurrency race in src/engine" \
  --cwd "$WORKTREE_DIR" --verify-cmd "<cmd>"

# --- Heavy Thinking & Architecture Mode (Capability deep-design-v1) ---
# Offload deep reasoning, RFC generation, or code reviews: Claude Opus 5.5 or Gemini 4 Argon (`gemini-4-argon`).
# There is no fallback thinker: a failed run is reported as a failure.
# Defaults reasoning effort to 'medium' (--effort overrides, or THINK_EFFORT / AGY_THINK_EFFORT env vars).
# Fails closed (exit code 12) if neither frontier model is available or an ineligible model is specified.
dispatch-thinker --agent agy --model gemini-4-argon --task "Synthesize multi-wave portal architecture" \
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
- **Agy streaming and self-healing**: agy runs always use `--output-format stream-json`; the final `response` is the job output, the `conversation_id` is saved in the job state (and the `finish` event) as soon as agy reports it, and the job log gets one `[agy] step ...` heartbeat line per 30s. `DISPATCH_AGY_IDLE_SECONDS` (default 1200, `0` disables) kills a run that emits no event for that long (`idle_timeout` event); when the limit expires and files in the folder changed since the previous check the timer resets instead. **Remaining limit: a silent step longer than the limit that changes no files is killed.** `--timeout` stays the hard cap. A run that already sent its `SUCCESS` result and only lingers counts as finished (no resume). After either kill, if a conversation id is known, the job resumes **once** (`resume` event, budget `min(max(900, timeout/2), timeout)`, so a job waits at most 2x `--timeout` in total, `resumed: true`); a second stall ends it as `TIMEOUT_*`. `DISPATCH_AGY_RESUME=0` turns the resume off. A killed run's output carries the last step and any error events (bounded tail). A run that exits 0 without a `result` event or with a non-string `response`, or a resumed run whose answer ends in a question, is a failure.
- **Per-job file counts**: `Files Modified` counts only paths new or changed since the job started (size/mtime compared, not file content), not the folder's cumulative dirt. If git status failed at the start the report says `count not baseline-adjusted`.
- **Check `Status`, never `$?`**: `RESUMED_UNVERIFIED` and `NO_CHANGES_UNVERIFIED` both exit 0 on purpose (a non-zero exit would trigger the runtime fallback on a folder holding partial work). On either one, run your own verify before accepting. A resumed job with 0 files changed and no artifact reports `NO_CHANGES_UNVERIFIED`.
- **Stall detection**: `dispatch-worker --status` shows `last output Ns ago` for RUNNING jobs and marks `STALLED?` after 300s of silence. Check `--tail` before killing it.
- **Stats**: `dispatch-worker --stats [DAYS]` (default 7) prints runs, success %, timeouts, fallbacks, verify failures and median duration per agent.
- **Recovery**: a run pinned with `--agent agy` is never retried on another agent, and a quota observation older than 60 minutes counts as not eligible.
- **Stale quota reading**: only an interactive agy session's status line rewrites the reading (`agy -p` does not), so when it is over 60 minutes old `dispatch-worker` starts an idle agy on a pseudo-terminal, sends no prompt, spends no quota, and rereads it (about 3s, 20s limit). A `FALLBACK_INTERNAL` message that still contains `[stale: observation` means that refresh failed: the reading is old, not low. Follow the refresh hint in the message, re-run the same dispatch once, and if it is still stale take the Sonnet fallback and say in your report that the cause was a stale reading, not low quota.
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
| `RESUMED_UNVERIFIED` (`Resumed: true`) | **Unverified, not done.** agy was killed once (no events for `DISPATCH_AGY_IDLE_SECONDS`, or `--timeout` hit) and auto-resumed with `--conversation`; a resume can lose the killed turn's prompt, so exit 0 proves nothing. Inspect the work or run the verify command yourself; a resumed job with a passing `--verify-cmd` reports plain `SUCCESS` |
| `Files Modified:` ends with `[shared folder: ...]` | The count is not attributable: another job was running in the same `--cwd`. Check `git status` yourself |
| `TIMEOUT_PARTIAL_WORK` | **Failed, but keep the work.** The edits are in the worktree (or the salvage patch). Re-dispatch in the same `--cwd` with a larger `--timeout` and "continue from the existing changes"; never start over from the default 900s |

---

## Integration with Subagent-Driven Development (SDD)

When using `subagent-driven-development`, select the execution path based on the orchestrator environment:

### Path A: In-Session Native AGY Orchestration (Preferred inside AGY)

Inside AGY, never shell out to `dispatch-worker`. Use native tools with the 80/20 Flash-First pattern:

1. **Round 1 Implementation (80% Flash Default)**:
   ```json
   invoke_subagent(
     TypeName: "self",
     Role: "Task Implementer",
     Model: "flash",
     Workspace: "share",  // use "branch" for overlapping or risky surface files
     Prompt: "Goal: Implement Task N from plan.md...\nFiles in scope: ...\nAcceptance criteria: ...\nVerify command: ..."
   )
   ```
2. **Round 2 Fix Loop (Warm Continuity via `send_message`)**:
   Instead of respawning a fresh subagent, send reviewer feedback directly to the idle implementer subagent's conversation ID:
   ```json
   send_message(
     Recipient: "<implementer-conversation-id>",
     Message: "Verification/Review failed with output: ... Please fix and re-verify."
   )
   ```
3. **Round 3+ Escalation (Argon Frontier)**:
   If Round 2 fails verification or review, terminate the Flash subagent (`manage_subagents(Action: "kill", ConversationIds: ["<implementer-conversation-id>"])`) and escalate to a fresh frontier subagent:
   ```json
   invoke_subagent(
     TypeName: "self",
     Role: "Escalated Implementer",
     Model: "inherit",  // runs on gemini-4-argon
     Workspace: "branch",
     Prompt: "Escalated: Implement Task N from plan.md...\nReason for escalation: ..."
   )
   ```
4. **Step 3 Adversarial Review Gate**:
   Always run reviews on the Frontier Tier (`Model: "inherit"` / `gemini-4-argon`):
   ```json
   define_subagent(
     name: "code-reviewer",
     description: "Adversarial code reviewer",
     system_prompt: "Adversarial code reviewer evaluating diffs against plan acceptance criteria...",
     enable_write_tools: false
   )
   invoke_subagent(
     TypeName: "code-reviewer",
     Role: "Adversarial Reviewer",
     Model: "inherit",
     Prompt: "Review git diff for Task N against plan criteria..."
   )
   ```

### Path B: External Cross-Harness CLI Dispatch (From Claude Code / Headless)

#### 1. Synchronous or Detached Single Batch
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
- If Round 2 fails, escalate to Argon on Round 3 via `--escalate`:
  ```bash
  dispatch-worker --agent agy --escalate --detach ...
  ```
- If exit code is `10`: Automatically fallback to internal subagent:
  ```
  Agent:
    subagent_type: general-purpose
    description: "Implement Task N: [task name]"
    model: sonnet
  ```

#### 2. Multi-Task Parallel Execution (Optimal Tokenomics)
Instead of spawning N separate Claude subagents (which burn ~70K cold-start tokens each), dispatch all tasks in a single batch call:
```bash
dispatch-worker --agent agy \
  --batch "Implement task 1 from brief 1" "Implement task 2 from brief 2" \
  --cwd "[directory]" \
  --verify-cmd "[test command]" --acceptance-file "[shared acceptance file]" --timeout 3600
```
Python runs the tasks concurrently in isolated worktrees and merges back sequentially without burning primary context tokens.
