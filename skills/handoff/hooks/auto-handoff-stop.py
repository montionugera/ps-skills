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
#   CLAUDE_AUTO_HANDOFF_REFIRE_STEP remind again after this much growth past the last fire (default 25000)
#   CLAUDE_AUTO_HANDOFF_NOTICES=1   send the two new messages (drain notice, retired reminder); default 0 (log only)
#   CLAUDE_AUTO_HANDOFF_LOG         decision log (default ~/.claude/logs/auto-handoff.log)
#   CLAUDE_AUTO_HANDOFF_STATE_DIR   where the per-session marker files live (default /tmp)

import json
import os
import pathlib
import re
import subprocess
import sys
import time

def env_int(name, default):
    """An integer setting; a missing or non-numeric value falls back to the default."""
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


THRESHOLD = env_int("CLAUDE_AUTO_HANDOFF_THRESHOLD", 200000)
HARD_CAP = env_int("CLAUDE_AUTO_HANDOFF_HARD_CAP", THRESHOLD * 3 // 2)
REFIRE_STEP = env_int("CLAUDE_AUTO_HANDOFF_REFIRE_STEP", 25000)
NOTICES = os.environ.get("CLAUDE_AUTO_HANDOFF_NOTICES") == "1"
LOG = os.environ.get("CLAUDE_AUTO_HANDOFF_LOG") or os.path.expanduser("~/.claude/logs/auto-handoff.log")
STATE_DIR = pathlib.Path(os.environ.get("CLAUDE_AUTO_HANDOFF_STATE_DIR") or "/tmp")
HANDOFF_SCRIPT = os.path.expanduser("~/.claude/skills/handoff/scripts/herdr-handoff.sh")

# Background work is found in the raw transcript text: a launch line names the task
# id, and a task-notification names it again when the task ends, whatever its status.
# The agent pattern is tied to the background wording: a foreground agent's result
# also carries an agentId, and it never gets a notification.
LAUNCHED = re.compile(
    r"Async agent launched successfully.{0,400}?agentId: ([\w-]+)"
    r"|Command running in background with ID: ([\w-]+)"
    r"|moved to the background \(ID: ([\w-]+)\)"
)
FINISHED = re.compile(r"<task-id>([\w-]+)</task-id>")


def dirty_tree(cwd):
    """True when cwd is a git checkout with uncommitted changes to tracked files."""
    if not cwd:
        return False
    try:
        out = subprocess.run(
            ["git", "--no-optional-locks", "-C", cwd, "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return False
    return out.returncode == 0 and bool(out.stdout.strip())


def log(session_id, context, decision, why):
    """One line per decision taken at or over the threshold; never raises."""
    try:
        d = os.path.dirname(LOG)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "session": session_id,
                                "context": context, "decision": decision, "why": why,
                                "notices": NOTICES, "dry_run": not NOTICES}) + "\n")
    except Exception:
        pass


def mark(path, context):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(context))
    except Exception:
        pass


def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))


def main():
    if os.environ.get("CLAUDE_AUTO_HANDOFF") == "0":
        return
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    if not isinstance(data, dict):
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
            launched.update(next(filter(None, ids)) for ids in LAUNCHED.findall(line))
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
    flag = STATE_DIR / f"claude-auto-handoff-{session_id}.flag"
    dry = ".dry" if not NOTICES else ""
    drain = STATE_DIR / f"claude-auto-handoff-{session_id}.drain{dry}"
    refire = STATE_DIR / f"claude-auto-handoff-{session_id}.refire{dry}"
    if context < THRESHOLD:
        # Back under the threshold (compaction): re-arm, so the next crossing fires again.
        for p in (
            flag,
            drain,
            refire,
            STATE_DIR / f"claude-auto-handoff-{session_id}.drain",
            STATE_DIR / f"claude-auto-handoff-{session_id}.drain.dry",
            STATE_DIR / f"claude-auto-handoff-{session_id}.refire",
            STATE_DIR / f"claude-auto-handoff-{session_id}.refire.dry",
        ):
            try:
                p.unlink()
            except OSError:
                pass
        return

    if flag.exists():
        # Already handed off. The old session keeps getting woken (task notifications,
        # peer messages, prompts); remind it each REFIRE_STEP of further growth.
        try:
            last = max(int(p.read_text()) for p in (flag, refire) if p.exists())
        except Exception:
            last = context
            mark(refire, context)
        if context < last + REFIRE_STEP:
            return
        mark(refire, context)
        log(session_id, context, "retired-reminder", f"grew {context - last} since the last fire")
        if NOTICES:
            block(
                f"AUTO-HANDOFF: this session already handed off and has since grown to {context} "
                "tokens. It is retired: do not start or continue work here. If the handoff tab "
                "is not running, run the handoff skill again; otherwise reply in one line that "
                "the work moved to the handoff tab, then stop."
            )
        return

    pending = sorted(launched - finished)
    dirty = dirty_tree(data.get("cwd"))
    if context < HARD_CAP and (pending or dirty):
        # Not a safe point yet. Say so once, so the session drains instead of launching
        # more work; after that stay silent and look again after each turn.
        if drain.exists():
            return
        mark(drain, context)
        why = f"background={len(pending)} dirty_tree={dirty}"
        log(session_id, context, "drain-notice", why)
        if NOTICES:
            block(
                f"AUTO-HANDOFF pending: context is {context} tokens (threshold {THRESHOLD}) but "
                f"this is not a safe point yet ({why}). Do not start a new task and do not "
                "launch new background agents or commands. Finish the unit of work in progress, "
                "let the running background work report back, commit, then end your turn; the "
                f"handoff runs at the next clean stop, or regardless at {HARD_CAP} tokens. "
                "If nothing is left to do right now, reply in one line and stop."
            )
        return
    mark(flag, context)
    log(session_id, context, "handoff", "hard-cap" if (pending or dirty) else "safe-point")

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
    try:
        main()
    except Exception:
        pass  # a Stop hook must never break the session it watches
