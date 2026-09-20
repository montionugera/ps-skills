---
name: handoff
description: "Compact the current conversation into a high-density, action-first handoff document (zero-indirection, self-contained frontier) and auto-spawn a new tab/agent in Herdr."
argument-hint: "[agent-kind (e.g. opencode, claude, codex, gemini, agy)] [goal or next step instructions]"
---

# Handoff (with Herdr Auto-Tab)

## Overview

When an agent session grows large (>100k tokens), attention degrades and reasoning degrades.
The **Handoff** skill solves this by:
1. Compacting the current session into a high-density, self-contained **Frontier Capsule** (zero pointer indirection).
2. Saving it to the OS temporary directory (`/tmp/handoff-<timestamp>-<slug>.md`).
3. Automatically opening a **new tab** in **Herdr**, starting a fresh coding agent (`opencode`, `claude`, `agy`, etc.), and prompting it to execute the immediate next action directly without burning tokens on historical archaeology.

### Auto-Trigger (context-size detection)

`hooks/auto-handoff-stop.py` is a Claude Code **Stop hook**. After each turn it reads the transcript's last `usage` block (input + cache tokens); once context reaches the threshold it blocks the stop and instructs the agent to run this skill end to end (doc → `herdr-handoff.sh --kind claude --mode <code|plan>`). One-shot per session (flag file `/tmp/claude-auto-handoff-<session_id>.flag`).

- Threshold: `CLAUDE_AUTO_HANDOFF_THRESHOLD` (default `200000`). Disable: `CLAUDE_AUTO_HANDOFF=0`.
- Install on a new machine:
  ```bash
  ln -s ~/.claude/skills/handoff/hooks/auto-handoff-stop.py ~/.claude/hooks/auto-handoff-stop.py
  ```
  then add to `~/.claude/settings.json` under `hooks.Stop[].hooks`:
  ```json
  { "type": "command", "command": "python3 ~/.claude/hooks/auto-handoff-stop.py", "timeout": 10 }
  ```

---

## Non-Negotiable Handoff Rules (Anti-Slop Guardrails)

1. **Self-Contained Frontier (No Nested Handoffs):**
   - ❌ **NEVER** write `"Read previous handoff HANDOFF-YYYY-MM-DD.md"`.
   - ❌ **NEVER** give reading lists of historical review sheets or audit logs for orientation.
   - ✅ **ALWAYS** state the live frontier directly at `git HEAD` (branch, commit, test status, active review state).
2. **Action-First Contract:**
   - The **Immediate Next Action** must begin with the **exact shell command to run** or **exact file:line to edit**.
   - Must include an explicit fallback: *"If local files are missing, do not search other directories; run `<command>` immediately."*
3. **No Skill Slop or Ceremony:**
   - Do NOT generate generic "Suggested Skills" sections that bloat context.
   - Keep the document lean (target ≤ 1KB - 2KB). Every line must serve the immediate next action.
4. **Claim Protocol (mandatory, added 2026-09-14):**
   - A Herdr tab, and a receiving agent inside it, can end up duplicated (observed: one Herdr tab with `pane_count: 2`, both panes running an agent against the same handoff — root cause on Herdr's side, unconfirmed, not fixed here) or a human can reopen the same handoff prompt in an unrelated tab. `herdr tab list` / `ListAgents` do not catch this — they show a peer is *busy*, not that it is busy with *this exact handoff*.
   - Every generated handoff doc MUST embed the claim command from the template below as the literal first thing the receiving agent is told to run — before it reads the goal, before it acts. This makes the doc self-defending even if it reaches two agents at once, per rule (1) above: nothing about the fix should require the receiving agent to already know this skill or this rule.

---

## Step 1: Generate the Handoff Document

Extract the operational state from the current session.

Note: you don't know the file's own final path until Step 2 writes it. Generate the doc first with a placeholder, then substitute the real `/tmp/handoff-<timestamp>-<slug>.md` path into section 0's two `<this-file's-own-absolute-path>` occurrences before or immediately after saving (e.g. `sed -i '' "s#<this-file's-own-absolute-path>#$HANDOFF_PATH#g" "$HANDOFF_PATH"`).

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

## 1. Goal (Verbatim)
<One clear sentence stating the objective>

## 2. Accomplished This Session
- <Key milestone / file created / test suite passing with exact count, e.g. "107/107 green">
- <Commit made, e.g. "000e34c: Forge tab redesign">

## 3. Live Frontier (Truth at HEAD)
- **Verified State:** `<file:line>` — <exact state verified by command or test>
- **Active Review/Gate Status:** <exact state of the current loop/gate, e.g. "Segment control operating at s0.45; latest verdict is Verdict #11 (materials-probe)">
- **Assumptions / Unverified:** <any unverified assumptions stated explicitly>

## 4. Immediate Next Action (Zero Ambiguity)
1. **First Action / Command to Run:**
   ```bash
   <exact shell command to execute>
   ```
2. **Fallback on Missing Assets:** If local assets/PNGs are missing, DO NOT explore or search checkouts — run `<command>` immediately.
3. **Subsequent Actions:** <1-2 short bullet points for the follow-up steps>

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

## Step 3: Auto-Spawn New Tab in Herdr

**3a. Background-work check (BEFORE running the script).** Run `ListAgents` and look at the `Subagents` block, plus any `run_in_background` Bash / Monitor tasks you started. Count the ones still `running`.
- **0 running** → add `--close-source`: once the new agent is confirmed alive, the script closes THIS tab automatically after 20s.
- **≥1 running** → do NOT pass `--close-source`. This tab must stay open to receive their results (2026-09-13 fact-board I-074: the handoff fired with 4 plan-writer agents still running; auto-closing would have lost 4 slice plans). Relay their results to the new tab via a file in the work folder, then report "safe to close" when the last one lands.

Run the bundled Herdr handoff script:

```bash
~/.claude/skills/handoff/scripts/herdr-handoff.sh "/tmp/handoff-<timestamp>-<slug>.md" --kind <agent-kind> --mode <code|plan> --prompt "<immediate next steps>" [--close-source] [--no-yolo]
```

The script ends with a banner — `✅ HANDOFF CONFIRMED` + `🟢 SAFE TO CLOSE` / `🚪 Closing THIS tab in 20s`, or `⛔ DO NOT CLOSE` (new agent not confirmed running after 60s; exit 1). It verifies via `herdr pane get` that the new pane actually runs an agent — "launched" is not "running".

### YOLO Mode (Default):
All handoffs launch with permission-skipping enabled by default (`--dangerously-skip-permissions` for `claude`, `agy`, and `gemini`), ensuring the incoming agent never gets stalled on interactive permission prompts. Pass `--no-yolo` to disable.

### Choosing `--mode` (always pass it for `--kind claude`):
- `code` → new session starts on **Sonnet**. Use when the Immediate Next Action is implementation: editing code, running/fixing tests, executing tasks of an already-approved plan.
- `plan` → new session starts on the **default model**. Use for brainstorming, specs, plans, research, review/audit, or debugging with an unknown root cause.
- Unsure → `plan`. `--model <name>` overrides both.

### Supported Agent Kinds (`--kind`):
- **Auto-detected by default** from the current session's environment (`agy`/`gemini` when in Antigravity, `codex` when in Codex, `claude` when in Claude Code, `opencode` when in OpenCode, `cursor` when in Cursor). Can be explicitly overridden with `--kind <name>` or `$HERDR_HANDOFF_AGENT_KIND`.
- `agy` / `gemini`
- `claude`
- `codex`
- `opencode`
- `cursor`

### Behavior:
1. If **Herdr** is running:
   - Creates a new tab: `herdr tab create --cwd "$PWD" --label "Handoff: <slug>" --focus`
   - Starts the chosen agent in the pane via `herdr agent start`
   - Delivers the execution-first prompt to execute the immediate action without forensic delay.
2. If **Herdr** is not running:
   - Gracefully outputs the path to the handoff file and a copy-pasteable prompt for manual startup.

---

## Step 4: Report to User

Return a concise summary (≤10 lines). The FIRST line is the close verdict, as a heading so it can't be missed:
- `# 🟢 SAFE TO CLOSE THIS TAB` — script banner confirmed AND 0 background agents running (or `# 🚪 THIS TAB CLOSES ITSELF IN 20s` when `--close-source` was passed)
- `# ⛔ DON'T CLOSE THIS TAB YET — <N> background agents still running` — then say what they'll produce and that you'll announce `🟢 SAFE TO CLOSE` when the last one lands (and do so)
- `# ⛔ DON'T CLOSE — handoff not confirmed` — script exited 1; give the manual launch command

Then:
- 📁 **Handoff File:** `/tmp/handoff-...md`
- 🖥️ **Herdr Tab:** `<tab_id>` (if spawned) / Agent: `<kind>`
- 🎯 **Next Action:** <Exact command/step delivered to the incoming agent>
