# Auto-Handoff Hooks

### Auto-Trigger (context-size detection)

`hooks/auto-handoff-stop.py` is a Claude Code **Stop hook**. After each turn it reads the transcript's last `usage` block (input + cache tokens); once context reaches the threshold it blocks the stop and instructs the agent to run this skill end to end (doc → `herdr-handoff.sh --kind claude --mode <code|plan>`). One-shot per session (flag file `/tmp/claude-auto-handoff-<session_id>.flag`).

- Threshold: `CLAUDE_AUTO_HANDOFF_THRESHOLD` (default `200000`). Disable: `CLAUDE_AUTO_HANDOFF=0`.
- **It waits for a safe point.** Past the threshold the hook stays silent while this session has background work running or the session's working tree has uncommitted changes to tracked files; it looks again after the next turn. Running work is found by replaying the transcript in order, per task id: a launch (an agent, a background command) or a `SendMessage` resume sets it running, a task notification or kill sets it done, and whatever is running at the end counts. So an agent that reported once and was then resumed holds the handoff back again. Past the hard cap, `CLAUDE_AUTO_HANDOFF_HARD_CAP` (default 1.5 x the threshold), it fires regardless. When it fires, the instruction carries `--running N` with its own count, and with N>0 it writes a `.draining` marker so later reminders tell this tab to relay results instead of "stop", and one more tells it when the last agent has reported. A newer owner instruction wins over the drain notice. Context is the last `message` iteration of the newest usage record (an advisor call adds an iteration that the top-level totals would double-count). A guard blocks once when this session got a drain or mid-turn notice, no handoff ran, and the last reply claims one is happening; a `herdr-handoff.sh` banner in the transcript (a manual run) counts as a handoff. Limits: only the session's own directory is checked for uncommitted changes, not other worktrees it edits; untracked files do not count; transcript text that merely quotes a launch line counts as a launch, which only delays the handoff until the hard cap; so does a background task that ends without a task notification (for example one that dies with a restarted session). Subagents the transcript cannot show (AGY `manage_subagents`) are covered only by your own count in step 3a. Tests: `tests/test_auto_handoff_stop.py`, `tests/test_herdr_handoff.py`.
- Install on a new machine:
  ```bash
  ln -s ~/.claude/skills/handoff/hooks/auto-handoff-stop.py ~/.claude/hooks/auto-handoff-stop.py
  ```
  then add to `~/.claude/settings.json` under `hooks.Stop[].hooks`:
  ```json
  { "type": "command", "command": "python3 ~/.claude/hooks/auto-handoff-stop.py", "timeout": 10 }
  ```
- **Mid-turn check (optional).** A Stop hook only runs when a turn ends, and one long turn can add hundreds of thousands of tokens. `hooks/auto-handoff-midturn.py` is a **PreToolUse hook** that reads the newest main-session usage record before each tool call and, once per level (`CLAUDE_AUTO_HANDOFF_MIDTURN_LEVELS`, default `250000,300000,400000,500000`), adds a note asking the agent to finish the unit of work and end the turn so the Stop hook can hand off. It never denies a tool call and ignores subagents. **Notes are off unless `CLAUDE_AUTO_HANDOFF_NOTICES=1`** (log only otherwise). Install like the Stop hook, under `hooks.PreToolUse[].hooks`. Tests: `tests/test_auto_handoff_midturn.py`.

### AGY Native Auto-Handoff (`~/.gemini/config/hooks.json`)

In Google Antigravity (`agy`), auto-handoff hooks operate natively via AGY's JSON hook schema:
- **`Stop` Hook**: Fires when `terminationReason in ("NO_TOOL_CALL", "MAX_TOKEN_BUDGET_EXCEEDED")`. Inspects session token growth from `conversations/<id>.db*` or `transcript_full.jsonl`. When exceeding threshold (>200k tokens), blocks termination and returns `{"decision": "continue", "injectSteps": [{"type": "USER_INPUT", "content": "Context threshold exceeded. Execute handoff skill to new tab/session."}]}`.
- **`PreInvocation` Hook**: Mid-turn hook that monitors cumulative token consumption before LLM calls. If approaching capacity, injects advisory notices instructing the agent to wrap up the current logical unit of work.
