"""Shared by auto-handoff-midturn.py and auto-handoff-stop.py: one context measure and one
set of Stop rules, so the mid-turn hook never promises a handoff the Stop hook will not run.

Not a hook itself. install.sh links every file in this folder next to the hooks, and Python
puts the real (symlink-resolved) script folder first on sys.path, so a plain import finds it.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import time

CONTEXT_FIELDS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "cache_read_tokens")
BYTES_PER_TOKEN = 4


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
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == "assistant":
                u = (entry.get("message") or {}).get("usage")
                if u:
                    usage = u
                    last_text = entry_text(entry)
            elif entry.get("type") == "PLANNER_RESPONSE":
                if entry.get("input_tokens") is not None or entry.get("cache_read_tokens") is not None:
                    usage = entry
                    if isinstance(entry.get("content"), str):
                        last_text = entry.get("content") or ""
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


def stop_would_hand_off(context, threshold, hard_cap, flag_exists, pending, dirty, agy_not_idle=False, low_quota=False):
    """True when the Stop hook, seeing this state, returns its handoff decision."""
    return (
        (context >= threshold or (low_quota and context > 0))
        and not flag_exists
        and not safe_point_blocked(context, hard_cap, pending, dirty, agy_not_idle)
    )


AGY_ARGON_DEFAULT_MODEL = "gemini-4-argon-medium"
AGY_CARBON_DEFAULT_MODEL = "gemini-4-carbon-medium"
AGY_HYDROGEN_CODE_MODEL = "gemini-4-hydrogen-high"
AGY_ARGON_CODE_MODEL = AGY_HYDROGEN_CODE_MODEL
DEFAULT_LOW_QUOTA_THRESHOLD_PERCENT = 10.0


def quota_state_dirs():
    """Directories where herdr-agent-quota writes provider quota snapshots."""
    custom = os.environ.get("HERDR_PLUGIN_STATE_DIR", "").strip()
    if custom:
        return [Path(custom).expanduser()]
    # When unit tests isolate state via CLAUDE_AUTO_HANDOFF_STATE_DIR, only read
    # quota files inside that test state dir so host quota state does not leak.
    test_state = os.environ.get("CLAUDE_AUTO_HANDOFF_STATE_DIR", "").strip()
    if test_state:
        return [Path(test_state).expanduser() / "herdr-agent-quota"]
    home = Path.home()
    return [
        home / ".local" / "state" / "herdr" / "plugins" / "herdr-agent-quota",
        home / "Library" / "Application Support" / "dev.herdr.herdr-agent-quota",
    ]


def low_quota_threshold_percent(dirs=None):
    """Remaining-percent threshold below/at which Claude is considered low on quota.

    Env `CLAUDE_LOW_QUOTA_THRESHOLD` wins ("off" or <=0 disables; default 10%).
    Otherwise reads `low-quota-alert` in the herdr-agent-quota state dir.
    """
    env_val = os.environ.get("CLAUDE_LOW_QUOTA_THRESHOLD", "").strip()
    if env_val:
        if env_val.lower() in ("off", "false", "0", "none"):
            return 0.0
        try:
            return max(0.0, float(env_val))
        except ValueError:
            pass
    for d in (dirs or quota_state_dirs()):
        alert_file = d / "low-quota-alert"
        try:
            raw = alert_file.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not raw:
            continue
        if raw.lower() in ("off", "false", "0", "none"):
            return 0.0
        try:
            return max(0.0, float(raw))
        except ValueError:
            continue
    return DEFAULT_LOW_QUOTA_THRESHOLD_PERCENT


def claude_low_quota(now=None):
    """Inspect Claude quota snapshot written by herdr-agent-quota.

    Returns (is_low, remaining_percent, threshold_percent, window_kind).
    If no fresh snapshot exists or alerts are disabled, returns (False, None, threshold, None).
    """
    dirs = quota_state_dirs()
    threshold = low_quota_threshold_percent(dirs)
    if threshold <= 0:
        return False, None, threshold, None
    now_ts = int(time.time() if now is None else now)
    candidates = ("claude-statusline.json", "claude.json", "claude-statusline.observation.json")
    for d in dirs:
        for name in candidates:
            path = d / name
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except OSError:
                continue
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            snap = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else data
            windows = snap.get("windows") if isinstance(snap, dict) else None
            if not isinstance(windows, list) or not windows:
                continue
            min_rem = None
            min_kind = None
            for w in windows:
                if not isinstance(w, dict):
                    continue
                resets_at = w.get("resets_at")
                if isinstance(resets_at, (int, float)) and resets_at > 0 and resets_at <= now_ts:
                    continue  # window already reset
                rem = w.get("remaining_percent")
                if rem is None:
                    used = w.get("used_percent")
                    if isinstance(used, (int, float)):
                        rem = max(0.0, 100.0 - float(used))
                if not isinstance(rem, (int, float)):
                    continue
                rem = float(rem)
                if min_rem is None or rem < min_rem:
                    min_rem = rem
                    min_kind = str(w.get("kind") or "quota")
            if min_rem is not None:
                return (min_rem <= threshold), round(min_rem, 1), threshold, min_kind
    return False, None, threshold, None


AGY_SUBAGENT_HEADER = re.compile(
    r'"type"\s*:\s*"SYSTEM_MESSAGE".*?<SYSTEM_MESSAGE>\\n\[Message\]\s+timestamp=[^\n]*?\bsender=[0-9a-fA-F-]{8,}\b'
)


def is_agy_payload(data):
    """Detect Antigravity (AGY) payload (camelCase keys) vs Claude Code (snake_case)."""
    return any(
        k in data
        for k in (
            "conversationId",
            "terminationReason",
            "workspacePaths",
            "transcriptPath",
            "fullyIdle",
        )
    )


def resolve_agy_app_dirs():
    """Return candidate Antigravity appDataDir roots for transcript / DB lookup."""
    override = os.environ.get("AGY_APP_DATA_DIR") or os.environ.get("ANTIGRAVITY_APP_DATA_DIR")
    if override:
        return [Path(override).expanduser()]
    dirs = []
    gemini_home = os.environ.get("GEMINI_HOME")
    if gemini_home:
        gh_acp = Path(gemini_home).expanduser() / "antigravity-acp"
        if gh_acp.is_dir():
            dirs.append(gh_acp)
    dirs.extend([
        Path("~/.gemini/antigravity-cli").expanduser(),
        Path("~/.gemini/antigravity").expanduser(),
    ])
    t3_prov = Path("~/.t3/userdata/providers/antigravity").expanduser()
    if t3_prov.is_dir():
        for sub in sorted(t3_prov.glob("*/antigravity-acp")):
            if sub.is_dir() and sub not in dirs:
                dirs.append(sub)
    return dirs


def active_transcript_bytes(path):
    """Return active bytes after the last compaction CHECKPOINT line in a JSONL transcript."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return 0
    total = len(raw)
    if total == 0:
        return 0
    if b"CHECKPOINT" not in raw and b"# Resuming from a compaction" not in raw:
        return total
    offset = 0
    last_reset_end = 0
    for line in raw.splitlines(keepends=True):
        offset += len(line)
        if (b"CHECKPOINT" in line and b"type" in line) or b"# Resuming from a compaction" in line:
            last_reset_end = offset
    return max(0, total - last_reset_end)


def is_delegated_subagent(data, transcript=None, session_id=None):
    """True when invoked inside a native subagent (Claude/AGY) or a T3 Code delegate_task child."""
    if os.environ.get("T3_DELEGATED_TASK") == "1":
        return True
    if data.get("agent_id") or data.get("parentConversationId"):
        return True
    if transcript and os.path.isfile(transcript):
        try:
            with open(transcript, "rb") as f:
                head = f.read(16384).decode("utf-8", "replace")
            if "Act as the " in head and "sub-agent for this task." in head:
                return True
            # Native AGY invoke_subagent transcripts start with a SYSTEM_MESSAGE carrying
            # `sender=<parent-conversation-uuid>` and no human `USER_INPUT` step.
            if (
                '"type":"USER_INPUT"' not in head
                and '"type": "USER_INPUT"' not in head
                and AGY_SUBAGENT_HEADER.search(head)
            ):
                return True
        except OSError:
            pass
    if session_id and session_id != "unknown" and len(session_id) >= 8:
        t3_db = os.environ.get("T3_STATE_DB") or os.path.expanduser("~/.t3/userdata/statev2.sqlite")
        if os.path.isfile(t3_db):
            try:
                import sqlite3
                uri = f"file:{t3_db}?mode=ro"
                with sqlite3.connect(uri, uri=True, timeout=0.2) as conn:
                    cur = conn.cursor()
                    pat = f"%{session_id}%"
                    cur.execute(
                        "SELECT 1 FROM orchestration_v2_projection_provider_threads "
                        "WHERE (thread_id LIKE 'thread:delegated-task:%' OR thread_id LIKE 'thread:provider:%') "
                        "AND (provider_thread_id LIKE ? OR payload_json LIKE ?) LIMIT 1",
                        (pat, pat),
                    )
                    if cur.fetchone():
                        return True
            except Exception:
                pass
    return False


def resolve_agy_transcript_and_bytes(data, conversation_id, allow_db_fallback=True):
    """Resolve (transcript_file_or_None, total_bytes) for an AGY conversation.

    In PreInvocation (`allow_db_fallback=False`), Turn 0 runs before `transcript.jsonl`
    exists while SQLite has already pre-allocated ~450-560 KB of empty `.db-wal` frames;
    skipping the `.db` fallback there prevents false Turn-0 114k/139k warnings.
    """
    explicit = data.get("transcriptPath") or data.get("transcript_path") or ""
    explicit_db_root = None
    if explicit and os.path.isfile(explicit):
        if str(explicit).endswith((".db", ".sqlite", ".sqlite3")):
            explicit_db_root = Path(explicit).resolve().parent.parent
        else:
            try:
                return explicit, active_transcript_bytes(explicit)
            except OSError:
                pass

    if not conversation_id or conversation_id == "unknown":
        return None, 0

    best_transcript = None
    best_raw_size = 0
    best_bytes = 0
    app_dirs = resolve_agy_app_dirs()
    if explicit_db_root and explicit_db_root.is_dir() and explicit_db_root not in app_dirs:
        app_dirs = [explicit_db_root] + app_dirs

    for root in app_dirs:
        logs_dir = root / "brain" / conversation_id / ".system_generated" / "logs"
        for name in ("transcript.jsonl", "transcript_full.jsonl"):
            candidate = logs_dir / name
            if candidate.is_file():
                try:
                    raw_sz = candidate.stat().st_size
                    if raw_sz > 0:
                        if raw_sz > best_raw_size:
                            best_raw_size = raw_sz
                            best_bytes = active_transcript_bytes(candidate)
                            best_transcript = str(candidate)
                        break
                except OSError:
                    pass

    if best_transcript is None and allow_db_fallback:
        for root in app_dirs:
            conv_dir = root / "conversations"
            db_file = conv_dir / f"{conversation_id}.db"
            wal_file = conv_dir / f"{conversation_id}.db-wal"
            db_bytes = 0
            for fpath in (db_file, wal_file):
                if fpath.is_file():
                    try:
                        db_bytes += fpath.stat().st_size
                    except OSError:
                        pass
            if db_bytes > best_bytes:
                best_bytes = db_bytes

    return best_transcript, best_bytes

