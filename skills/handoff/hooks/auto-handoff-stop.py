#!/usr/bin/env python3
# ~/.claude/skills/handoff/hooks/auto-handoff-stop.py (symlinked from ~/.claude/hooks/)
# Claude Code Stop hook: when session context (input + cache tokens) exceeds the
# threshold, force the agent to run the handoff skill (one-shot per session).
#
# Past the threshold the hook waits for a safe point: it does not fire while this
# session has background work still running or the working tree has uncommitted
# tracked changes. Past the hard cap it fires regardless, so it cannot wait forever.
#
# Env overrides:
#   CLAUDE_AUTO_HANDOFF_THRESHOLD   token threshold (default 200000)
#   CLAUDE_AUTO_HANDOFF_HARD_CAP    fire regardless of the safe point (default 1.5 x threshold)
#   CLAUDE_AUTO_HANDOFF=0           disable entirely

import json
import os
import pathlib
import re
import subprocess
import sys

THRESHOLD = int(os.environ.get("CLAUDE_AUTO_HANDOFF_THRESHOLD", "200000"))
HARD_CAP = int(os.environ.get("CLAUDE_AUTO_HANDOFF_HARD_CAP", str(THRESHOLD * 3 // 2)))
HANDOFF_SCRIPT = os.path.expanduser("~/.claude/skills/handoff/scripts/herdr-handoff.sh")

# Background work is found in the raw transcript text: a launch line names the task
# id, and a task-notification names it again when the task ends.
LAUNCHED = re.compile(r"agentId: (\w+)|Command running in background with ID: (\w+)")
FINISHED = re.compile(r"<task-id>(\w+)</task-id>")


def dirty_tree(cwd):
    """True when cwd is a git checkout with uncommitted changes to tracked files."""
    if not cwd:
        return False
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return False
    return out.returncode == 0 and bool(out.stdout.strip())


def main():
    if os.environ.get("CLAUDE_AUTO_HANDOFF") == "0":
        return
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    if data.get("stop_hook_active"):
        return

    transcript = data.get("transcript_path")
    session_id = data.get("session_id") or "unknown"
    if not transcript or not os.path.isfile(transcript):
        return

    usage = None
    launched, finished = set(), set()
    with open(transcript, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            launched.update(a or b for a, b in LAUNCHED.findall(line))
            finished.update(FINISHED.findall(line))
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("type") != "assistant":
                continue
            u = (entry.get("message") or {}).get("usage")
            if u:
                usage = u

    if not usage:
        return

    context = (
        int(usage.get("input_tokens") or 0)
        + int(usage.get("cache_read_input_tokens") or 0)
        + int(usage.get("cache_creation_input_tokens") or 0)
    )
    if context < THRESHOLD:
        return

    flag = pathlib.Path("/tmp") / f"claude-auto-handoff-{session_id}.flag"
    if flag.exists():
        return
    # Not a safe point yet: say nothing, and look again after the next turn.
    if context < HARD_CAP and (launched - finished or dirty_tree(data.get("cwd"))):
        return
    try:
        flag.write_text(str(context))
    except Exception:
        pass

    reason = (
        f"AUTO-HANDOFF: this session's context reached {context} tokens "
        f"(threshold {THRESHOLD}). Do not continue the current task. "
        "Execute the handoff skill now: compact this session into "
        "/tmp/handoff-<YYYY-MM-DD-HHMMSS>-<slug>.md following the handoff skill "
        "template, then run "
        f"{HANDOFF_SCRIPT} "
        "\"<doc-path>\" --kind claude --mode <code|plan> --prompt \"auto-handoff: "
        "continue the work in the new tab\". Pick --mode code (starts Sonnet) when "
        "the Immediate Next Action is implementation: editing code, running/fixing "
        "tests, or executing tasks of an already-approved plan. Pick --mode plan "
        "(default model) for brainstorming, specs, plans, research, review/audit, "
        "or debugging with an unknown root cause; if unsure, pick plan. "
        "Report the handoff file path, Herdr tab id, and chosen mode, then stop."
    )
    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    main()
