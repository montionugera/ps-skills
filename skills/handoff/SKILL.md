---
name: handoff
description: "Compact the current conversation into a high-density, action-first handoff document (zero-indirection, self-contained frontier) and auto-spawn a new tab/agent in Herdr or T3Code. Supports AGY native auto-handoff hooks."
argument-hint: "[agent-kind (e.g. opencode, claude, codex, gemini, agy, t3code)] [--multiplexer herdr|t3|auto] [--topic <2-5 words>] [goal or next step instructions]"
---

# Handoff (with Herdr Auto-Tab)

## Overview

When an agent session grows large (>100k tokens), attention degrades and reasoning degrades.
The **Handoff** skill solves this by:
1. Compacting the current session into a high-density, self-contained **Frontier Capsule** (zero pointer indirection).
2. Saving it to the OS temporary directory (`/tmp/handoff-<timestamp>-<slug>.md`).
3. Automatically opening a **new tab** in **Herdr**, starting a fresh coding agent (`opencode`, `claude`, `agy`, etc.), and prompting it to execute the immediate next action directly without burning tokens on historical archaeology.

### Scope Boundary: In-Session AGY Subagents vs Herdr Handoff
- **Inside AGY (In-Session)**: For parallel feature slices, research lookups, and adversarial reviews within the same session, use AGY's native `invoke_subagent` (`Workspace: "share"`/`"branch"`, `Model: "flash"`/`"inherit"`) and `send_message` for reactive wakeup. Do NOT spawn new Herdr tabs or file handoffs for standard in-session task delegation.
- **When to Use Handoff**: Reserve this skill for:
  1. **Context Window Exhaustion**: When the primary orchestrator session reaches >100k–200k tokens and needs a clean slate.
  2. **Cross-Harness Transfers**: Handing off work between different agent harnesses (Claude Code $\leftrightarrow$ AGY $\leftrightarrow$ OpenCode).
  3. **Cross-Terminal / Cross-Repo**: Long-running background handoffs across separate terminal panes or detached repositories.

### Auto-Trigger

A Claude Code Stop hook runs this skill end to end once context reaches `CLAUDE_AUTO_HANDOFF_THRESHOLD` (default `200000`; disable with `CLAUDE_AUTO_HANDOFF=0`). It waits for a safe point, and AGY has equivalent native hooks. Read [`references/auto-handoff-hooks.md`](references/auto-handoff-hooks.md) only when installing or debugging them.

---

## Non-Negotiable Handoff Rules (Anti-Slop + Context Retention Guardrails)

1. **Preserve Main Context + Self-Contained Frontier (No Nested Handoffs):**
   - ❌ **NEVER** write `"Read previous handoff HANDOFF-YYYY-MM-DD.md"`.
   - ❌ **NEVER** give unfocused reading lists of historical review sheets or audit logs.
   - ❌ **NEVER** compress the session down to just the last 5 minutes of debugging while dropping the original user objective, active epic/spec, or user corrections.
   - ✅ **ALWAYS** include in Section 1: (a) the **Original User Objective & Definition of Done**, (b) the **Governing Spec / Plan / Epic path** (if one exists, e.g. `spec.md`, `plan.md`, `progress.md` — which the new session *should* consult when moving between tasks), and (c) **Key User Decisions & Corrections** made during this session so the new agent never repeats rejected approaches.
   - ✅ **ALWAYS** state the live frontier directly at `git HEAD` (branch, commit, test status, active review state, and any in-flight subagents/delegated tasks).
2. **Action-First Contract:**
   - The **Immediate Next Action** must begin with the **exact shell command to run** or **exact file:line to edit**, followed by the remaining roadmap steps toward the Section 1 objective.
   - Must include an explicit fallback: *"If local files are missing, do not search other directories; run `<command>` immediately."*
3. **No Skill Slop or Ceremony:**
   - Do NOT generate generic "Suggested Skills" sections that bloat context.
   - Keep the document high-density (target ≤ 2KB - 4KB): rich on main context, user decisions, and exact technical state; zero fluff.
4. **Claim Protocol (mandatory, added 2026-09-14):**
   - A Herdr tab, and a receiving agent inside it, can end up duplicated (observed: one Herdr tab with `pane_count: 2`, both panes running an agent against the same handoff — root cause on Herdr's side, unconfirmed, not fixed here) or a human can reopen the same handoff prompt in an unrelated tab. `herdr tab list` / `ListAgents` do not catch this — they show a peer is *busy*, not that it is busy with *this exact handoff*.
   - Every generated handoff doc MUST embed the claim command from the template below as the literal first thing the receiving agent is told to run — before it reads the goal, before it acts. This makes the doc self-defending even if it reaches two agents at once, per rule (1) above: nothing about the fix should require the receiving agent to already know this skill or this rule.

---

## Step 1: Generate the Handoff Document

Extract the operational state from the current session.

Leave `<this-file's-own-absolute-path>` in section 0 as written: `herdr-handoff.sh` fills in the real path, and adds section 0 if a doc lacks it.

The `# Handoff:` title becomes the tab name when `--topic` is not given, so start it with what the next session will do.

### Required Markdown Template:

```markdown
# Handoff: <Task Title / Slug>
**Worktree:** `<path>` | **Branch:** `<branch>` | **HEAD:** `<commit-hash> <commit-msg>`

## 0. Claim This Handoff (run this FIRST, before reading further)
```bash
mkdir "<this-file's-own-absolute-path>.claim" 2>/dev/null && echo "$(whoami) pid $$ $(date -Iseconds)" > "<this-file's-own-absolute-path>.claim/owner" && echo CLAIMED || { echo "ALREADY CLAIMED by:"; cat "<this-file's-own-absolute-path>.claim/owner"; }
```
If it prints `ALREADY CLAIMED`: STOP. Another agent (possibly a duplicate pane/tab of this same spawn) already owns this handoff. Do not read further or dispatch anything — message that session/owner if you can identify it, or tell the user two sessions raced this handoff, and end your turn.
If it prints `CLAIMED`: proceed to section 1.

## 1. Main Context (Big Picture & User Decisions)
- **Original User Objective & Definition of Done:** <What the user originally asked for and what complete success looks like across the whole task/epic>
- **Governing Spec / Plan / Epic:** <Exact path to active `spec.md`, `plan.md`, `progress.md`, or epic/feature folder — or `None` if ad-hoc. Read this when transitioning between plan steps.>
- **Key User Decisions & Non-Negotiables:**
  - <Decision/correction 1 from the user during this session, e.g., architectural choice, rejected approach, or preference>
  - <Decision/correction 2>

## 2. Accomplished This Session
- <Key milestone / file created / test suite passing with exact count, e.g. "107/107 green">
- <Commit made, e.g. "000e34c: Forge tab redesign">

## 3. Live Frontier (Truth at HEAD)
- **Verified State:** `<file:line>` — <exact state verified by command or test>
- **Active Review/Gate Status:** <exact state of the current loop/gate, e.g. "Segment control operating at s0.45; latest verdict is Verdict #11 (materials-probe)">
- **In-Flight Subagents / Delegated Tasks:** <`None`, or list active `taskId` + `childThreadId` (for T3 `delegate_task` — note: the new thread must use `t3_thread_wait`/`t3_thread_read` on `childThreadId` since `task_status` is bound to the old parent thread) and `conversationId` (for AGY `invoke_subagent`)>
- **Assumptions / Unverified:** <any unverified assumptions stated explicitly>

## 4. Immediate Next Action & Remaining Roadmap (Zero Ambiguity)
1. **First Action / Command to Run:**
   ```bash
   <exact shell command to execute>
   ```
2. **Fallback on Missing Assets:** If local assets/PNGs are missing, DO NOT explore or search checkouts — run `<command>` immediately.
3. **Remaining Roadmap Steps (toward Section 1 Objective):**
   - <Next step after the immediate action>
   - <Final verification / completion gate>

## 5. Known Traps & Constraints
- <Trap 1: e.g. "GPU tunnel must be up on port 8188 (curl -s http://127.0.0.1:8188/system_stats)">
- <Trap 2: e.g. "Classification R2 (local commits), psrw ship is R0">

## 6. Target Files (Only what this step touches)
- [`<filename>`](file://<abs-path>) — <purpose/expected edit>
```

---

## Step 2: Save the File

Save the generated markdown to `/tmp/`:
```bash
/tmp/handoff-$(date +%Y-%m-%d-%H%M%S)-<slug>.md
```

---

## Step 3: Auto-Spawn New Tab in Herdr (or T3 Code)

**3a. Background-work check (BEFORE running the script).**
- In **Claude Code**: Run `ListAgents` and look at the `Subagents` block, plus any `run_in_background` Bash / Monitor tasks you started.
- In **Antigravity (`agy`)**: Check both `manage_subagents(Action: "list")` and `manage_task(Action: "list")`.
- In **T3 Code (any harness)**: Check any T3-owned `delegate_task` runs launched in this thread (`task_status`). Note: `task_status` is bound to the parent thread that created the task, so if a handoff must occur while a T3 `delegate_task` is still running, record its `childThreadId` in Section 3 so the new thread can inspect/wait on it via `t3_thread_wait(threadId=childThreadId)` and `t3_thread_read(threadId=childThreadId)`.
Count the ones still `running`:
Always pass `--running N`: your own count, or the larger of it and the `--running` the auto-handoff instruction gave you (the hook's count; it cannot see AGY `manage_subagents`).
- **`--running 0`** → the script treats it as `--close-source`: once the new agent is confirmed alive, it closes THIS tab after 20s.
- **`--running N`, N ≥ 1** → the tab never closes itself. It must stay open to receive their results (2026-09-13 fact-board I-074: the handoff fired with 4 plan-writer agents still running; auto-closing would have lost 4 slice plans). Start nothing new. As each agent reports, `SendMessage` the report to the new tab (peer sessions show in `ListAgents`) and append it to `<handoff>.md` under "Late results" as the fallback; after the last one, print `🟢 SAFE TO CLOSE THIS TAB`.
- **No `--running`** (manual use) → the banner says "count unknown" and never SAFE; you still decide from this count.
- **Native T3 Code Thread Launch (Optional when running inside T3 Code with `t3_thread_launch` MCP tool available):** After running `herdr-handoff.sh` (which writes `$PROMPT_FILE` with the full inlined handoff document and copies it to clipboard), you may also directly spawn the continuation thread in T3 Code by calling `t3_thread_launch` with `title` set to the label the script prints, the matching `workspaceStrategy` (`existing_worktree` or `root`), and `message` set to the contents of `$PROMPT_FILE`.

Run the bundled Herdr handoff script:

```bash
~/.claude/skills/handoff/scripts/herdr-handoff.sh "/tmp/handoff-<timestamp>-<slug>.md" --kind <agent-kind> --mode <code|plan> --topic "<2-5 words on what the next session does>" --prompt "<immediate next steps>" --running <N> [--no-yolo]
```

The script ends with a banner — `✅ HANDOFF CONFIRMED` followed by `⛔ KEEP THIS TAB OPEN — N agents still running` (N ≥ 1), `🚪 Closing THIS tab in 20s` (0 running), `🟢 SAFE TO CLOSE` (0 running, no tab id to close) or `⚠️ agents running: count unknown` (no `--running`); or `⚠️ new tab started, status unknown` / `⛔ DO NOT CLOSE` (no agent confirmed after 60s; exit 1). **Only the handoff's `.claim` directory confirms** (typically 5-15s, `HERDR_HANDOFF_CONFIRM_TIMEOUT` default 90): it proves the agent got its prompt and ran the first command. A pane that merely shows an agent proves neither, since it can be stuck on a dialog, so the parent never closes on status alone. An already-claimed doc is refused before any tab opens.

### Tab Names

`<project> · <topic> #N`, e.g. `play-joymify · real audio shipped #3`, capped at `HERDR_HANDOFF_LABEL_MAX` (default 36, the sidebar's maximum width) characters.
- **project:** the main repo's folder name, also from inside a worktree.
- **topic:** `--topic`, else the first clause of the doc title, else the filename slug. Pass `--topic`: it is the only source written for a narrow sidebar.
- **#N:** the handoff number in this chain, read from the parent tab's label, so a chain can be followed after its parents close.
- `--label` overrides all of it. A Claude session gets the same name (`--name`), so `/resume` matches the tab. A parent kept open to relay agents is renamed `⏳ relay → <label>`.

### Where the Tab Opens

In the caller's own workspace, resolved live from `herdr pane current`, then verified against the created tab; a mismatch prints a ⚠️ line. Focus follows only if the user is on the parent tab, so a handoff never pulls them off other work. `--no-focus` forces it off. Without `--cwd`, the tab starts in the doc's `**Worktree:**` or `**Repo:**` directory.

Each handoff appends one line to `~/.local/state/handoff/ledger.jsonl` (parent and child tab, workspaces, seconds to claim, outcome). If the script warns that the skill is behind `origin/main`, merged fixes are not active in this checkout.

### YOLO Mode (Default):
All handoffs launch with permission-skipping enabled by default (`--dangerously-skip-permissions` for `claude`, `agy`, and `gemini`), ensuring the incoming agent never gets stalled on interactive permission prompts. Pass `--no-yolo` to disable.

### Choosing `--mode` (always pass it for `--kind claude`):
- `code` → new session starts on **Sonnet**. Use when the Immediate Next Action is implementation: editing code, running/fixing tests, executing tasks of an already-approved plan.
- `plan` → new session starts on the **default model**. Use for brainstorming, specs, plans, research, review/audit, or debugging with an unknown root cause.
- Unsure → `plan`. `--model <name>` overrides both.

### Supported Agent Kinds (`--kind`):
- **Auto-detected by default** from the current session's environment (`agy`/`gemini` when in Antigravity, `codex` when in Codex, `claude` when in Claude Code, `opencode` when in OpenCode, `cursor` when in Cursor, `t3code` when targeting T3Code). Can be explicitly overridden with `--kind <name>` or `$HERDR_HANDOFF_AGENT_KIND`.
- `agy` / `gemini`
- `claude`
- `codex`
- `opencode`
- `cursor`
- `t3code`

### Multiplexer Support (`--multiplexer {herdr,t3,auto}`):
- **Herdr (`--multiplexer herdr`)**:
  - Creates a new tab in the caller's workspace: `herdr tab create --workspace <caller> --cwd <target> --label "<project> · <topic> #N"` (`--workspace` is omitted only outside Herdr)
  - Starts the chosen agent in the pane via `herdr agent start`
  - Delivers the execution-first prompt to execute the immediate action without forensic delay.
- **T3Code (`--multiplexer t3` / `--kind t3code`)**:
  - Integrates directly with T3Code desktop app:
    ```bash
    t3 project add "$TARGET_CWD"
    t3 app "$TARGET_CWD"
    ```
  - Automatically copies the self-contained bootstrap prompt to system clipboard for one-click pasting into the fresh T3Code agent panel.
- **Auto (`--multiplexer auto` - default)**:
  - Detects active Herdr daemon first; falls back to T3Code if available; otherwise gracefully outputs the path to the handoff file and a copy-pasteable prompt for manual startup.

---

## Step 4: Report to User

Return a concise summary (≤10 lines). The FIRST line is the close verdict, as a heading so it can't be missed:
Copy the verdict from the script's banner; never write a green line the banner did not print.
- `# 🟢 SAFE TO CLOSE THIS TAB` — banner confirmed AND `--running 0` (or `# 🚪 THIS TAB CLOSES ITSELF IN 20s` when the banner says it closes)
- `# ⛔ DON'T CLOSE THIS TAB YET — <N> background agents still running` — then say you will relay each report to the new tab and print `🟢 SAFE TO CLOSE THIS TAB` when the last one lands (and do so)
- `# ⚠️ CHECK THE NEW TAB FIRST` — banner said status unknown; do not close until it is seen working
- `# ⛔ DON'T CLOSE — handoff not confirmed` — script exited 1; give the manual launch command

Then:
- 📁 **Handoff File:** `/tmp/handoff-...md`
- 🖥️ **Herdr Tab:** `<tab_id>` (if spawned) / Agent: `<kind>`
- 🎯 **Next Action:** <Exact command/step delivered to the incoming agent>
