#!/usr/bin/env python3
# PreToolUse hook: mid-turn context check for the auto-handoff rule.
#
# A Stop hook only runs when a turn ends, and a single turn can add hundreds of
# thousands of tokens. This check reads the newest usage record from the tail of
# the transcript before each tool call and, the first time the main session passes
# each level, adds a note to the model's context. It never denies a tool call, so it
# cannot interrupt a change in progress; it only asks the agent to wrap up the unit
# of work and end the turn, where auto-handoff-stop.py takes over.
#
# Env:
#   CLAUDE_AUTO_HANDOFF=0                  disable (same switch as the Stop hook)
#   CLAUDE_AUTO_HANDOFF_MIDTURN_LEVELS     comma list of token levels (default 250000,300000,400000,500000)
#   CLAUDE_AUTO_HANDOFF_NOTICES=1          add the note to the context (default: log only, same switch as the Stop hook)
#   CLAUDE_AUTO_HANDOFF_LOG                decision log (default ~/.claude/logs/auto-handoff.log)
#   CLAUDE_AUTO_HANDOFF_STATE_DIR          marker files (default /tmp)

import json
import os
import pathlib
import sys
import time

TAIL_BYTES = 1 << 20  # the newest usage record is always near the end


def levels():
    try:
        return sorted(int(x) for x in os.environ["CLAUDE_AUTO_HANDOFF_MIDTURN_LEVELS"].split(","))
    except (KeyError, ValueError):
        return [250000, 300000, 400000, 500000]


def latest_context(transcript):
    """Context size of the newest main-session assistant record in the file's tail, or 0."""
    with open(transcript, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        lines = f.read().decode("utf-8", "replace").splitlines()
    if size > TAIL_BYTES:
        lines = lines[1:]  # the first line of the tail is cut in the middle
    for line in reversed(lines):
        if '"usage"' not in line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        u = (entry.get("message") or {}).get("usage")
        if not u:
            continue
        context = (
            int(u.get("input_tokens") or 0)
            + int(u.get("cache_read_input_tokens") or 0)
            + int(u.get("cache_creation_input_tokens") or 0)
        )
        if context:  # synthetic records carry an all-zero usage
            return context
    return 0


def main():
    if os.environ.get("CLAUDE_AUTO_HANDOFF") == "0":
        return
    data = json.load(sys.stdin)
    if data.get("agent_id"):  # a subagent's tool call: its context is not the session's
        return
    transcript = data.get("transcript_path")
    if not transcript or not os.path.isfile(transcript):
        return
    context = latest_context(transcript)
    passed = [lv for lv in levels() if context >= lv]
    if not passed:
        return
    level = passed[-1]
    dry = os.environ.get("CLAUDE_AUTO_HANDOFF_NOTICES") != "1"
    state = pathlib.Path(os.environ.get("CLAUDE_AUTO_HANDOFF_STATE_DIR") or "/tmp")
    session_id = "".join(c for c in str(data.get("session_id") or "unknown") if c.isalnum() or c in "-_") or "unknown"
    marker = state / f"claude-auto-handoff-{session_id}.midturn{'.dry' if dry else ''}"
    try:
        if int(marker.read_text()) >= level:
            return  # already said so at this level
    except Exception:
        pass
    try:
        marker.write_text(str(level))
    except Exception:
        return  # without the marker this would repeat on every tool call
    try:
        log = os.environ.get("CLAUDE_AUTO_HANDOFF_LOG") or os.path.expanduser("~/.claude/logs/auto-handoff.log")
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "session": session_id,
                                "context": context, "decision": "midturn-notice",
                                "why": f"level {level}", "dry_run": dry}) + "\n")
    except Exception:
        pass
    if dry:
        return
    note = (
        f"AUTO-HANDOFF (mid-turn): context is {context} tokens, past {level}. This tool call "
        "is allowed. Finish the unit of work in progress (get it verified and committed), "
        "start nothing new, launch no new background work, then end your turn so the "
        "handoff can run. Do not hand off in the middle of a change."
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": note}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a hook must never break the session it watches
