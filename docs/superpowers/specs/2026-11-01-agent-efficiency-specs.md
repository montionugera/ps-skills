# Agent Efficiency Design Specs: Ideas 1, 3, 7, 8

Grounded against `efficiency-diagnosis-2026-11-01.md`, `/Users/pasitnusso/ps-skills`, `/Users/pasitnusso/.gemini/skills`, `/Users/pasitnusso/workspace/tools/herdr-board`, and `herdr` CLI v0.8+ (protocol 22).

---

## Idea 1: Event-Driven Ledger Orchestration (`<= 2 KB` State, Script Waits)

- **Problem:** In `joy-quest`, 71–93% of main-thread tokens came from `task-notification` wake-ups re-reading 150–250K of context; across all three repos, 15–34% of turns were polling/waiting and 40–70% were ceremony. Even with `bin/dispatch-worker --wait`, waking the main LLM between every mechanical step (implement → package diff → review → simplify) burns ~250K cached tokens per transition when no judgment is needed.
- **Smallest Design That Works:**
  1. Add a Python driver `/Users/pasitnusso/ps-skills/bin/sdd-drive` that executes the `subagent-driven-development` batch loop outside the LLM turn and blocks until a human/frontier decision point occurs.
  2. Maintain a compact JSON+markdown state file at `<repo>/.superpowers/sdd/<plan-slug>/progress.md` (resolved via `~/.gemini/skills/subagent-driven-development/scripts/sdd-workspace`), atomically mutated under `engine/ps-release-workflow/lib/state.py`'s `mutate_state` flock pattern and hard-capped at `<= 2048` bytes (`{plan, base_sha, batches:[{id, status, head_sha, round, blocker}]}`). Verbose worker outputs stay in `task-<N>-report.md` and `task-<N>-review.md`.
  3. For each batch in `--plan <plan.md>`, `sdd-drive` runs:
     - `scripts/task-brief <plan.md> <N>` to extract the task brief;
     - `bin/dispatch-worker --agent agy --cwd <worktree> --task "Read brief: ..." --verify-cmd "<cmd>" --acceptance-file <brief> --output-file <report>` (blocking inside the script);
     - on `exit_code == 0` and `Verified: true`, runs `scripts/review-package <plan.md> <base> <head>` and `bin/jev-gate triage-diff --repo <worktree> --base <base> --head <head> --hook-line`;
     - dispatches one consolidated reviewer (`bin/dispatch-worker` on `gemini-3.8-flash-high` when `tier=single_flash_reviewer` / `RISK: R2`, else `bin/dispatch-thinker --agent agy --model gemini-4-argon-medium`).
  4. **Wake-up filter (decision points only):** If review is `Approved`, `sdd-drive` updates the ledger and advances to Batch `N+1` without waking the orchestrator LLM. If review reports `Needs fixes`, `sdd-drive` automatically runs **Round 1** fix + scoped re-review once. It exits back to the LLM orchestrator **only** on: (a) unresolved findings after Round 1, (b) worker `BLOCKED` / `NEEDS_CONTEXT` / `VERIFY_FAILED`, (c) `FALLBACK_INTERNAL` (exit `10`), or (d) all batches green and ready for `psrw ship`.
  5. Note on the `psrw` ledger: `.claude/state/claims.json` remains the repo-level feature claim ledger; `sdd-drive` drives batches inside the claimed worktree.
- **Exact Files / Commands Touched:**
  - Create `/Users/pasitnusso/ps-skills/bin/sdd-drive` and symlink `~/.local/bin/sdd-drive`.
  - Create `/Users/pasitnusso/ps-skills/tests/test_sdd_drive.py`.
  - Edit `/Users/pasitnusso/.gemini/skills/subagent-driven-development/SKILL.md` (and `~/.claude/CLAUDE.md` → `bin/sync-agent-rules --write`) to call `sdd-drive --plan <plan.md> --cwd <worktree>` as a single blocking command.
- **Checkable Success Measure:**
  - `wc -c < <worktree>/.superpowers/sdd/<plan-slug>/progress.md` is `<= 2048` after every batch; a 4-batch green plan wakes the main LLM thread **1 time** (at completion) instead of 8–12 times, cutting main-thread `task-notification` turns by `>= 75%` in `bin/agent-spend`.
- **Risks & How to Undo:**
  - *Risk:* A misclassified reviewer verdict could auto-advance a broken batch or hang silently inside `sdd-drive` if `--timeout` is too high.
  - *Undo:* Pass `--no-drive` (or `SDD_DRIVE=off`), or `git revert` the `bin/sdd-drive` commit to fall back to per-step LLM orchestration.
- **Rough Size:** Small–Medium (~180 LoC Python + ~80 LoC unit tests, 1 session).
- **Decision (user, 2026-11-01):** approved. `sdd-drive` runs one fix round and one re-check before waking the main agent.

---

## Idea 3: Pre-Registered Acceptance Test Gate

- **Problem:** `joy-quest` `F-008` burned ~40% of the entire repo's tokens (9 Workflow runs, 4x `FAIL`, 0.53B tokens) without converging because `aios-verifier` (`roles/verifier.md`) and post-hoc reviewers invent new edge cases and mutations *after* implementation, moving the goalposts on every round.
- **Smallest Design That Works:**
  1. **Emit executable acceptance tests at plan time:** In `writing-plans`, require every testable task's Step 1 (`Write the failing test`) to carry an explicit `Verify-Cmd: <exact test command covering only this task's tests>` line and fenced test block(s) tagged ` ```<lang> test:<relative/path/to/test_file> `.
  2. **Materialize & lock tests before implementer dispatch:** Add `/Users/pasitnusso/.gemini/skills/subagent-driven-development/scripts/extract-acceptance-tests PLAN_FILE TASK_N WORKTREE`:
     - Extracts the tagged test blocks from `task-<N>-brief.md` and writes them into `WORKTREE` before the implementer starts;
     - Runs `Verify-Cmd` once to confirm a valid RED state (test runner exits non-zero on assertion/missing symbol, not a syntax error in the test itself);
     - Records `sha256` hashes of the test files in `<sdd-workspace>/task-<N>-tests.sha256`.
  3. **Pass `--verify-cmd` to worker:** Dispatch the implementer with `bin/dispatch-worker --verify-cmd "<Verify-Cmd> && extract-acceptance-tests --check-intact <sdd-workspace>/task-<N>-tests.sha256"`. The `--check-intact` mode verifies that pre-registered `test_*` / `it(...)` functions were not deleted, skipped (`@skip` / `.skip`), or had `assert` statements removed (additive tests by the implementer are allowed).
  4. **Scope verifier & reviewer blocking strictly to pre-registered tests:** Update `/Users/pasitnusso/.gemini/config/skills/aios-review-chain/roles/verifier.md` and `/Users/pasitnusso/.gemini/skills/subagent-driven-development/task-reviewer-prompt.md` (matching Rule 7 Step 3): a verifier or reviewer may return a blocking `FAIL` / `Critical` / `Important` verdict **only** if (a) `Verify-Cmd` exits non-zero, (b) a pre-registered test was deleted/weakened, or (c) an R0 security/data-loss defect is present. Exploratory mutations ("try three inputs the tests do not cover") are downgraded to `Minor (deferred)` logged in `progress.md` / backlog and never trigger a fix loop.
- **Exact Files / Commands Touched:**
  - Create `/Users/pasitnusso/.gemini/skills/subagent-driven-development/scripts/extract-acceptance-tests`.
  - Edit `/Users/pasitnusso/.gemini/skills/writing-plans/SKILL.md` (mandate `Verify-Cmd:` and `test:<path>` fence header).
  - Edit `/Users/pasitnusso/.gemini/skills/subagent-driven-development/SKILL.md` and `task-reviewer-prompt.md`.
  - Edit `/Users/pasitnusso/.gemini/config/skills/aios-review-chain/roles/verifier.md` and `SKILL.md`, then run `python3 -I /Users/pasitnusso/.gemini/config/skills/aios-review-chain/scripts/sync.py` (via user-run apply script for `~/.claude/agents/aios-*.md` and `~/.codex/agents/aios-*.toml`).
- **Checkable Success Measure:**
  - `extract-acceptance-tests` exits `0` on a plan task and exits non-zero if a test assertion is deleted; across subsequent features, verifier/review fix rounds per task never exceed `1` when `Verify-Cmd` exits `0`.
- **Risks & How to Undo:**
  - *Risk:* A plan writer emits a `test:<path>` block with broken imports before the module exists, causing the pre-dispatch RED check to flag a syntax error vs missing-module ImportError. (Mitigation: treat `ImportError`/`ModuleNotFoundError` on the target module as valid RED; fail only on `SyntaxError`.)
  - *Undo:* Remove `--check-intact` from `--verify-cmd` and restore `verifier.md` / `task-reviewer-prompt.md` from backup.
- **Rough Size:** Small (~120 LoC bash/Python script + ~35 lines of skill prompt edits + unit tests).
- **Decision (user, 2026-11-01):** approved. The implementer may adjust test setup such as imports and fixtures, but may not remove or skip a check; new tests are allowed.

---

## Idea 7: Herdr Auto-Close of Sessions Idle Over 1 Hour

- **Problem:** Machine swap hit 3.9–4.5 GB / 5.0 GB (load 15–20) with 17 concurrent `claude` CLI processes holding 3.4 GB RSS. In `herdr --session tooling agent list`, 10 interactive Claude panes sit open across workspaces (`w3`, `wA`), 8 of them in `idle` or `done` state, each keeping a `claude` process + MCP sidecars (`graft mcp`, `nimble-sidecar`) resident in RAM indefinitely.
- **Plain-English Audit of `herdr --help` & `herdr api schema` (What Exists vs What Does Not):**
  - **Does NOT exist:** `herdr` has **no** built-in idle-timeout flag, no auto-close setting in `herdr --default-config` (`~/.config/herdr/config.toml`), and **no timestamp field** on `herdr session list --json` (`{default, name, running, session_dir, socket_path}`) or `herdr agent list` / `herdr api snapshot` (`AgentInfo` exposes `agent_status: "idle"|"done"|"working"|"blocked"|"unknown"`, `revision`, and `state_change_seq`, but no `last_active_at` unix timestamp).
  - **What DOES exist:** `herdr --session <NAME> api snapshot`, `herdr --session <NAME> pane process-info --pane <ID>`, `herdr --session <NAME> pane close <pane_id>`, `herdr tab close <tab_id>`, and `herdr session stop <NAME>`. Moreover, user work lives as multiple **agent panes** inside one persistent session (`tooling`), so closing an idle agent means `herdr --session <NAME> pane close <pane_id>` (not `herdr session stop`, which would kill the whole server and active agents).
- **Smallest Design That Works:**
  1. Create `/Users/pasitnusso/ps-skills/bin/herdr-reap-idle` (`--max-idle-seconds 3600`, `--dry-run`):
     - Lists running Herdr server sessions via `herdr session list --json` (`running == true`).
     - For each running session, calls `herdr --session <NAME> api snapshot` and iterates `.result.snapshot.agents[]`.
     - Maintains `~/.local/state/herdr/idle-panes.json` mapping `{"<session>:<pane_id>": {"seq": state_change_seq, "rev": revision, "idle_since": <unix_epoch>}}`.
     - When an agent is `"working"` or `"blocked"`, or its `(state_change_seq, revision)` changed since last check, deletes or resets `idle_since = now`.
     - When `agent_status` is `"idle"` or `"done"` and `focused == false`: computes idle age as `now - max(idle_since, mtime(~/.claude/projects/*/<agent_session.value>.jsonl))`.
     - **Safety guards before close:** Skips the pane if (a) `focused == true`, (b) any subagent in `~/.claude/projects/*/<agent_session.value>/subagents/*.meta.json` lacks `"finished": true` with mtime `< 30m`, or (c) any job in `~/.local/state/dispatch/jobs/*.json` is `RUNNING`/`PENDING` with matching `cwd`.
     - If idle `>= 3600s`, appends `{ts, session, pane_id, cwd, title: terminal_title_stripped, resume: "claude --resume <agent_session.value>"}` to `~/.local/state/herdr/reaped-panes.jsonl` and executes `herdr --session <NAME> pane close <pane_id>` (freeing the `claude` CLI + MCP child processes while keeping the conversation resumable via `claude --resume`).
  2. Run `herdr-reap-idle` every 10 minutes via a user-installed `launchd` agent `~/Library/LaunchAgents/com.pasitnusso.herdr-reap-idle.plist`.
- **Exact Files / Commands Touched:**
  - Create `/Users/pasitnusso/ps-skills/bin/herdr-reap-idle` and `/Users/pasitnusso/ps-skills/tests/test_herdr_reap_idle.py`.
  - User-run apply script installs `~/Library/LaunchAgents/com.pasitnusso.herdr-reap-idle.plist` (`launchctl bootstrap gui/$UID ...`).
- **Checkable Success Measure:**
  - `herdr-reap-idle --dry-run --max-idle-seconds 3600` lists all unfocused `idle`/`done` agent panes whose transcript mtime and `state_change_seq` are unchanged for `>1h`; when live, resident `claude` CLI count drops to `<= active + focused` panes within 10 minutes after an hour of inactivity.
- **Risks & How to Undo:**
  - *Risk:* Closing a pane loses unsaved shell scrollback (though Claude conversation state is saved in `~/.claude/projects/*/<id>.jsonl`).
  - *Undo:* `launchctl bootout gui/$UID/com.pasitnusso.herdr-reap-idle` (or `HERDR_REAP_IDLE=off`); re-open any reaped session from the exact command logged in `~/.local/state/herdr/reaped-panes.jsonl` (`cd <cwd> && claude --resume <id>`).
- **Rough Size:** Small (~110 LoC Python + ~60 LoC unit tests + 25-line plist).
- **Decision (user, 2026-11-01):** approved; close the whole tab with `herdr pane close <pane_id>`.

---

## Idea 8: Progress Surface (Ledger to Herdr Sidebar / `progress.md`, Zero Status Tables)

- **Problem:** 40–70% of main-thread turns across sampled sessions were ceremony and Markdown status tables. Each status table forces a 220–260K context read, adds ~1–2K output tokens that stay in context forever, and in CLI/ACP harnesses a text-only status turn with no tool call halts execution immediately (observed 4x per session).
- **Smallest Design That Works:**
  1. Create a single CLI writer `/Users/pasitnusso/ps-skills/bin/progress-sync` that updates two zero-context surfaces from `<repo>/.superpowers/sdd/<plan-slug>/progress.md` (or `psrw status --json`):
     - **File surface (`progress.md`):** Writes a compact (`<= 2 KB`) status block to `<repo>/.superpowers/sdd/<plan-slug>/progress.md` and atomically symlinks `<repo>/.superpowers/sdd/latest-progress.md` to it, so `watch -n 2 cat .superpowers/sdd/latest-progress.md` (or a file viewer pane) always shows current batch, pass/fail counts, and active worker job ID.
     - **Herdr sidebar badge (always available inside Herdr):** When `$HERDR_PANE_ID` is set, invokes `herdr pane report-metadata --pane "$HERDR_PANE_ID" --source sdd --state-label "<Batch M/N: state>"` so live progress appears directly in the Herdr sidebar row without any TUI popup or chat output.
  2. **Ban mid-run status tables in hooks & skills:** Update `~/.claude/CLAUDE.md` Rule 6 ("Quiet orchestrator") and `/Users/pasitnusso/.gemini/skills/subagent-driven-development/SKILL.md` so the orchestrator calls `progress-sync` (or lets `sdd-drive` call it automatically) and never prints Markdown tables (`|---|`) in chat before `Finish`.
- **Exact Files / Commands Touched:**
  - Create `/Users/pasitnusso/ps-skills/bin/progress-sync` and `/Users/pasitnusso/ps-skills/tests/test_progress_sync.py`.
  - Edit `/Users/pasitnusso/.gemini/skills/subagent-driven-development/SKILL.md` to replace chat status narration with `progress-sync`.
- **Checkable Success Measure:**
  - Zero Markdown tables (`^\|.*\|$` blocks `>= 3` lines) emitted in assistant turns before the final turn of a plan run; `herdr agent get "$HERDR_PANE_ID"` shows updated `state_labels`.
- **Risks & How to Undo:**
  - *Risk:* If the Herdr socket is unreachable, a synchronous `herdr` call could stall the orchestrator. (Mitigation: `progress-sync` runs `herdr` with a 1-second timeout and fails open after writing `progress.md`.)
  - *Undo:* Set `PROGRESS_SYNC=off` or remove `bin/progress-sync`; `herdr pane report-metadata --pane "$HERDR_PANE_ID" --source sdd --clear-state-labels` clears the sidebar badge.
- **Rough Size:** Small (~90 LoC Python + ~50 LoC unit tests).
- **Decision:** herdr-board is no longer in use (no `board` or `boardd` on the machine), so this idea uses only `progress.md` and the Herdr sidebar. **Approved by the user, 2026-11-01.**

---

## Recommended Build Order

1. **First — Idea 7 (`bin/herdr-reap-idle`):** Smallest, self-contained, and immediately relieves the 3.4 GB RSS / swap pressure from idle interactive Claude panes that causes system-wide freezes and `agent-concurrency-guard` swap denials (`swap >= 0.85`).
2. **Second — Idea 8 (`bin/progress-sync`):** Gives `progress.md` and the Herdr sidebar a tested writer for the `<= 2 KB` ledger before the orchestrator loop is automated.
3. **Third — Idea 3 (`extract-acceptance-tests` + verifier gate lock):** Locks down deterministic `--verify-cmd` acceptance tests from `writing-plans` and caps verifier/review blocking to pre-registered tests, preventing runaway verifier loops (like `joy-quest` `F-008`'s 0.53B sink) and giving Idea 1 a reliable binary gate.
4. **Fourth — Idea 1 (`bin/sdd-drive`):** Combines Idea 8's `<= 2 KB` ledger/progress surface and Idea 3's pre-registered `--verify-cmd` gate into one non-LLM batch runner around `bin/dispatch-worker --wait`, eliminating the 71–93% `task-notification` wake-up overhead across multi-batch plans.
