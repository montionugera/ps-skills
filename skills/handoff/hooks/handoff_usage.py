"""Shared by auto-handoff-midturn.py and auto-handoff-stop.py: one context measure and one
set of Stop rules, so the mid-turn hook never promises a handoff the Stop hook will not run.

Not a hook itself. install.sh links every file in this folder next to the hooks, and Python
puts the real (symlink-resolved) script folder first on sys.path, so a plain import finds it.
"""
import json
import os
import re
import subprocess

CONTEXT_FIELDS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def _sum(usage):
    return sum(int(usage.get(k) or 0) for k in CONTEXT_FIELDS)


def usage_context(usage):
    """Prompt size of one assistant record.

    When a response runs several executor iterations (advisor calls, multi-pass responses),
    the top-level usage fields are the SUM across iterations, so they double-count. The real
    context is the last iteration of type "message". Fall back to the top-level sum only for
    records without such an iteration.
    """
    if not usage:
        return 0
    iterations = usage.get("iterations") or []
    messages = [it for it in iterations if isinstance(it, dict) and it.get("type") == "message"]
    return _sum(messages[-1]) if messages else _sum(usage)


def env_int(name, default):
    """An integer setting; a missing or non-numeric value falls back to the default."""
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def stop_thresholds(is_agy):
    """(threshold, hard_cap) exactly as the Stop hook resolves them."""
    if is_agy:
        threshold = env_int("AGY_AUTO_HANDOFF_THRESHOLD", env_int("CLAUDE_AUTO_HANDOFF_THRESHOLD", 128000))
        hard_cap = env_int("AGY_AUTO_HANDOFF_HARD_CAP", env_int("CLAUDE_AUTO_HANDOFF_HARD_CAP", threshold * 3 // 2))
    else:
        threshold = env_int("CLAUDE_AUTO_HANDOFF_THRESHOLD", 200000)
        hard_cap = env_int("CLAUDE_AUTO_HANDOFF_HARD_CAP", threshold * 3 // 2)
    return threshold, hard_cap


# Background work is found in the raw transcript text: a launch line names the task
# id, and a task-notification names it again when the task ends, whatever its status.
LAUNCHED = re.compile(
    r"Async agent launched successfully.{0,400}?agentId: ([\w-]+)"
    r"|Command running in background with ID: ([\w-]+)"
    r"|moved to the background \(ID: ([\w-]+)\)"
    r"|Tool is running as a background task with task id: ([\w/-]+)"
    r'|(?:\\?"taskId\\?"\s*:\s*\\?"(node:delegated-task:[^"\\]+)\\?".*?\\?"status\\?"\s*:\s*\\?"running\\?")'
)
FINISHED = re.compile(
    r"<task-id>([\w-]+)</task-id>"
    r'|Task id \\?"([\w/-]+)\\?" finished with result:'
    r"|sender=([\w/-]+)\s+priority="
    r"|Successfully killed task ([\w/-]+)"
    r"|Task ([\w/-]+) is not running"
    r"|Delegated task (node:delegated-task:[^\s.]+?)\.? reached a terminal state"
    r'|(?:\\?"taskId\\?"\s*:\s*\\?"(node:delegated-task:[^"\\]+)\\?".*?\\?"status\\?"\s*:\s*\\?"(?:completed|failed|cancelled|canceled)\\?")'
)
# A SendMessage that wakes an agent which had already reported names it again here.
RESUMED = re.compile(r'\\?"resumedAgentId\\?"\s*:\s*\\?"([\w-]+)')
# Entries that only copy other entries' text (requests, queue operations) are not events.
COPY_TYPES = ("api-request-blob", "api-request", "api-request-shape", "queue-operation")
# The lines herdr-handoff.sh prints, so a manual /handoff (which logs nothing) is seen too.
# The dash is matched loosely because a transcript line may hold it as a \u2014 escape.
HANDOFF_BANNER = re.compile(
    r"HANDOFF CONFIRMED .{1,8}? \w+ is \w+ in tab"
    r"|DO NOT CLOSE THIS TAB .{1,8}? new agent NOT"
    r"|KEEP THIS TAB OPEN .{1,8}? \d+ agents still running"
)


def entry_text(entry):
    """The text blocks of an assistant entry, joined."""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    return " ".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def parse_transcript_usage_and_tasks(transcript):
    """Replay a JSONL transcript in order: (last usage, ids still running, last assistant text,
    whether a herdr-handoff.sh banner was printed).

    Per id the last event wins: a launch or a resume sets it running, a notification or kill
    sets it done. So an agent that reported once and was then resumed is running again."""
    usage, last_text, banner = None, "", False
    state = {}
    if not transcript or not os.path.isfile(transcript):
        return None, set(), last_text, banner
    with open(transcript, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if ("CHECKPOINT" in line and ("type" in line)) or "# Resuming from a compaction" in line:
                usage, last_text, banner = None, "", False
                state.clear()
            try:
                entry = json.loads(line)
            except Exception:
                entry = None
            if isinstance(entry, dict) and entry.get("type") in COPY_TYPES:
                continue
            banner = banner or bool(HANDOFF_BANNER.search(line))
            events = []
            if "Task Description: Timer:" not in line:
                events += [(m.start(), next(filter(None, m.groups())), True) for m in LAUNCHED.finditer(line)]
            events += [(m.start(), m.group(1), True) for m in RESUMED.finditer(line)]
            events += [(m.start(), next(filter(None, m.groups())), False) for m in FINISHED.finditer(line)]
            for _, task_id, running in sorted(events):
                state[task_id] = running
            if not isinstance(entry, dict) or entry.get("type") != "assistant":
                continue
            u = (entry.get("message") or {}).get("usage")
            if u:
                usage = u
                last_text = entry_text(entry)
    return usage, {i for i, running in state.items() if running}, last_text, banner


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


def safe_point_blocked(context, hard_cap, pending, dirty, agy_not_idle=False):
    """The Stop hook waits (drain) instead of handing off: work in flight, under the hard cap."""
    return context < hard_cap and bool(pending or agy_not_idle or dirty)


def stop_would_hand_off(context, threshold, hard_cap, flag_exists, pending, dirty, agy_not_idle=False):
    """True when the Stop hook, seeing this state, returns its handoff decision."""
    return (
        context >= threshold
        and not flag_exists
        and not safe_point_blocked(context, hard_cap, pending, dirty, agy_not_idle)
    )
