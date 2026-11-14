#!/usr/bin/env python3
# PreToolUse (Claude Code) & PreInvocation (Antigravity / AGY) hook:
# mid-turn / pre-invocation context check for the auto-handoff rule.
#
# A Stop hook only runs when a turn ends, and a single turn can add hundreds of
# thousands of tokens. This check reads the newest usage record from the tail of
# the transcript (or estimates context bytes in AGY brain logs / conversation DB)
# and, the first time the main session passes each level, adds a note to the
# model's context.
#
# Output contract:
#   - Claude Code PreToolUse:
#       {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": note}}
#   - Antigravity (AGY) PreInvocation:
#       {"injectSteps": [{"ephemeralMessage": note}]}
#
# Env:
#   CLAUDE_AUTO_HANDOFF=0 / AGY_AUTO_HANDOFF=0
#       disable (same switch as the Stop hook)
#   CLAUDE_AUTO_HANDOFF_MIDTURN_LEVELS / AGY_AUTO_HANDOFF_MIDTURN_LEVELS
#       comma list of token levels (default 250000,300000,400000,500000 for Claude;
#       100000,128000,160000,200000 for AGY)
#   CLAUDE_AUTO_HANDOFF_NOTICES=1 / AGY_AUTO_HANDOFF_NOTICES=1
#       add the note to the context (Claude default: log only unless =1;
#       AGY default: emit unless AGY_AUTO_HANDOFF_NOTICES=0)
#   CLAUDE_AUTO_HANDOFF_LOG
#       decision log (default ~/.claude/logs/auto-handoff.log)
#   CLAUDE_AUTO_HANDOFF_STATE_DIR
#       marker files (default /tmp)
#   AGY_APP_DATA_DIR / ANTIGRAVITY_APP_DATA_DIR
#       override Antigravity app data root

import json
import os
import pathlib
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from handoff_usage import (
    BYTES_PER_TOKEN,
    active_transcript_bytes,
    dirty_tree,
    is_agy_payload,
    is_delegated_subagent,
    parse_transcript_usage_and_tasks,
    resolve_agy_app_dirs,
    resolve_agy_transcript_and_bytes,
    stop_thresholds,
    stop_would_hand_off,
    usage_context,
)

TAIL_BYTES = 1 << 20  # the newest usage record is always near the end


def levels(is_agy=False):
    env_key = "AGY_AUTO_HANDOFF_MIDTURN_LEVELS" if is_agy and "AGY_AUTO_HANDOFF_MIDTURN_LEVELS" in os.environ else "CLAUDE_AUTO_HANDOFF_MIDTURN_LEVELS"
    try:
        return sorted(int(x) for x in os.environ[env_key].split(","))
    except (KeyError, ValueError):
        return [100000, 128000, 160000, 200000] if is_agy else [250000, 300000, 400000, 500000]


def latest_context(transcript):
    """Context size of the newest main-session assistant record in the file's tail, or 0."""
    if not transcript or not os.path.isfile(transcript):
        return 0
    with open(transcript, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        lines = f.read().decode("utf-8", "replace").splitlines()
    if size > TAIL_BYTES:
        lines = lines[1:]  # the first line of the tail is cut in the middle
    for line in reversed(lines):
        if ("CHECKPOINT" in line and "type" in line) or "# Resuming from a compaction" in line:
            break
        if '"usage"' not in line and '"PLANNER_RESPONSE"' not in line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if entry.get("type") == "PLANNER_RESPONSE":
            context = usage_context(entry)
            if context:
                return context
            continue
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        u = (entry.get("message") or {}).get("usage")
        if not u:
            continue
        context = usage_context(u)
        if context:  # synthetic records carry an all-zero usage
            return context
    return 0


def next_stop_hands_off(data, is_agy, transcript, context, flag, drain):
    """True only when the Stop hook, under its own rules, is certain to return its handoff
    decision at the next stop. Telling the agent to end its turn otherwise strands it: the
    Stop hook stays silent and nothing resumes the session.

    A `.drain` marker means the Stop hook already sent its drain notice; it stays silent while
    the stop is still unsafe, so treat that as uncertain rather than tell the agent to stop.
    AGY: fullyIdle at the next stop cannot be known mid-turn, so only the hard cap is certain.
    """
    if drain.exists():
        return False
    threshold, hard_cap = stop_thresholds(is_agy)
    if is_agy:
        return stop_would_hand_off(context, threshold, hard_cap, flag.exists(), (), False, agy_not_idle=True)
    _, running, _, _ = parse_transcript_usage_and_tasks(transcript)
    return stop_would_hand_off(context, threshold, hard_cap, flag.exists(), running,
                               dirty_tree(data.get("cwd")))


def main():
    if os.environ.get("CLAUDE_AUTO_HANDOFF") == "0":
        return
    data = json.load(sys.stdin)
    if not isinstance(data, dict):
        return

    is_agy = is_agy_payload(data)
    if is_agy and os.environ.get("AGY_AUTO_HANDOFF") == "0":
        print("{}")
        return

    if data.get("agent_id") or data.get("parentConversationId"):
        if is_agy:
            print("{}")
        return

    raw_session_id = data.get("conversationId") if is_agy else data.get("session_id")
    session_id = "".join(c for c in str(raw_session_id or "unknown") if c.isalnum() or c in "-_") or "unknown"

    if is_agy:
        transcript, total_bytes = resolve_agy_transcript_and_bytes(data, session_id, allow_db_fallback=False)
        if is_delegated_subagent(data, transcript=transcript, session_id=session_id):
            print("{}")
            return
        context = latest_context(transcript) or (total_bytes // BYTES_PER_TOKEN)
        dry = os.environ.get("AGY_AUTO_HANDOFF_NOTICES") == "0" or (
            "AGY_AUTO_HANDOFF_NOTICES" not in os.environ
            and "CLAUDE_AUTO_HANDOFF_NOTICES" in os.environ
            and os.environ.get("CLAUDE_AUTO_HANDOFF_NOTICES") != "1"
        )
        prefix = "agy-auto-handoff"
    else:
        transcript = data.get("transcript_path")
        if not transcript or not os.path.isfile(transcript):
            return
        if is_delegated_subagent(data, transcript=transcript, session_id=session_id):
            return
        context = latest_context(transcript)
        dry = os.environ.get("CLAUDE_AUTO_HANDOFF_NOTICES") != "1"
        prefix = "claude-auto-handoff"

    passed = [lv for lv in levels(is_agy=is_agy) if context >= lv]
    if not passed:
        if is_agy:
            print("{}")
        return
    level = passed[-1]
    state = pathlib.Path(os.environ.get("CLAUDE_AUTO_HANDOFF_STATE_DIR") or "/tmp")
    marker = state / f"{prefix}-{session_id}.midturn{'.dry' if dry else ''}"
    try:
        if int(marker.read_text()) >= level:
            if is_agy:
                print("{}")
            return  # already said so at this level
    except Exception:
        pass
    try:
        marker.write_text(str(level))
    except Exception:
        if is_agy:
            print("{}")
        return  # without the marker this would repeat on every tool call
    try:
        stop = next_stop_hands_off(data, is_agy, transcript, context, state / f"{prefix}-{session_id}.flag",
                                   state / f"{prefix}-{session_id}.drain")
    except Exception:
        stop = False  # unsure: warn rather than strand the turn
    try:
        log = os.environ.get("CLAUDE_AUTO_HANDOFF_LOG") or os.path.expanduser("~/.claude/logs/auto-handoff.log")
        d = os.path.dirname(log)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "session": session_id,
                                "context": context, "decision": "midturn-notice" if stop else "midturn-warning",
                                "why": f"level {level}", "dry_run": dry}) + "\n")
    except Exception:
        pass
    if dry:
        if is_agy:
            print("{}")
        return
    if stop:
        note = (
            f"AUTO-HANDOFF (mid-turn): context is {context} tokens, past {level}. This tool call "
            "is allowed. Finish the unit of work in progress (get it verified and committed), "
            "start nothing new, launch no new background work, then end your turn. The Stop hook "
            "decides whether a handoff runs. Do not tell the owner a handoff, new tab or tab "
            "close is happening unless herdr-handoff.sh's banner is in your output. Do not hand "
            "off in the middle of a change."
        )
    else:
        note = (
            f"AUTO-HANDOFF (mid-turn, warning only): context is {context} tokens, past {level}. "
            "Context is high; continue your current work. A handoff will be offered at a safe "
            "point (a stop with no background work running and changes committed). Keep working; "
            "this note is not a reason to stop."
        )
    if is_agy:
        print(json.dumps({"injectSteps": [{"ephemeralMessage": note}]}))
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": note}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a hook must never break the session it watches
