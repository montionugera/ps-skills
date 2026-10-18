#!/usr/bin/env python3
# ~/.claude/skills/handoff/hooks/auto-handoff-stop.py
# Symlinked from ~/.claude/hooks/auto-handoff-stop.py and ~/.gemini/config/hooks/auto-handoff-stop.py
#
# Dual-harness Stop hook (Claude Code + Antigravity / AGY):
# When session context exceeds the threshold, instruct the agent to run the handoff
# skill (one-shot per session/conversation).
#
# Past the threshold the hook waits for a safe point: it does not fire while this
# session has background work still running or the working tree has uncommitted
# tracked changes. Past the hard cap it fires regardless, so it cannot wait forever.
#
# Env overrides:
#   CLAUDE_AUTO_HANDOFF_THRESHOLD / AGY_AUTO_HANDOFF_THRESHOLD
#       token threshold (default 200000 for Claude, 128000 for AGY)
#   CLAUDE_AUTO_HANDOFF_HARD_CAP / AGY_AUTO_HANDOFF_HARD_CAP
#       fire regardless of the safe point (default 1.5 x threshold)
#   CLAUDE_AUTO_HANDOFF=0 / AGY_AUTO_HANDOFF=0
#       disable entirely
#   CLAUDE_AUTO_HANDOFF_REFIRE_STEP
#       remind again after this much growth past the last fire (default 25000)
#   CLAUDE_AUTO_HANDOFF_NOTICES=1 / AGY_AUTO_HANDOFF_NOTICES=1
#       send the two intermediate messages (drain notice, retired reminder); default 0 (log only)
#   CLAUDE_AUTO_HANDOFF_LOG
#       decision log (default ~/.claude/logs/auto-handoff.log)
#   CLAUDE_AUTO_HANDOFF_STATE_DIR
#       where the per-session marker files live (default /tmp)
#   AGY_APP_DATA_DIR / ANTIGRAVITY_APP_DATA_DIR
#       override Antigravity app data root (default ~/.gemini/antigravity-cli and ~/.gemini/antigravity)

import json
import os
import pathlib
import re
import subprocess
import sys
import time

BYTES_PER_TOKEN = 4

# Antigravity (AGY) Stop hook sends camelCase terminationReason values.
# Natural model stops in AGY emit "NO_TOOL_CALL" (or legacy "model_stop");
# budget/invocation caps emit "MAX_TOKEN_BUDGET_EXCEEDED" / "MAX_INVOCATIONS".
ALLOWED_AGY_TERMINATION_REASONS = (
    "NO_TOOL_CALL",
    "MAX_TOKEN_BUDGET_EXCEEDED",
    "MAX_INVOCATIONS",
    "model_stop",
)


def env_int(name, default):
    """An integer setting; a missing or non-numeric value falls back to the default."""
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def is_agy_payload(data):
    """Detect Antigravity (AGY) Stop payload (camelCase keys) vs Claude Code (snake_case)."""
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
        return [pathlib.Path(override).expanduser()]
    dirs = []
    gemini_home = os.environ.get("GEMINI_HOME")
    if gemini_home:
        gh_acp = pathlib.Path(gemini_home).expanduser() / "antigravity-acp"
        if gh_acp.is_dir():
            dirs.append(gh_acp)
    dirs.extend([
        pathlib.Path("~/.gemini/antigravity-cli").expanduser(),
        pathlib.Path("~/.gemini/antigravity").expanduser(),
    ])
    t3_prov = pathlib.Path("~/.t3/userdata/providers/antigravity").expanduser()
    if t3_prov.is_dir():
        for sub in sorted(t3_prov.glob("*/antigravity-acp")):
            if sub.is_dir() and sub not in dirs:
                dirs.append(sub)
    return dirs


def resolve_agy_transcript_and_bytes(data, conversation_id):
    """Resolve (transcript_file_or_None, total_bytes) for an AGY conversation.

    Checks:
      1. Explicit `transcriptPath` / `transcript_path` in hook payload.
      2. `<appDataDir>/brain/<conversationId>/.system_generated/logs/transcript_full.jsonl`
         and `transcript.jsonl`.
      3. `<appDataDir>/conversations/<conversationId>.db` (+ `.db-wal`) ONLY as a fallback
         when no JSONL transcript file exists yet.
    """
    explicit = data.get("transcriptPath") or data.get("transcript_path") or ""
    explicit_db_root = None
    if explicit and os.path.isfile(explicit):
        if str(explicit).endswith((".db", ".sqlite", ".sqlite3")):
            # Antigravity passes conversations/<id>.db as transcriptPath; use its parent
            # appDataDir to locate brain/<id>/.system_generated/logs/transcript.jsonl first.
            explicit_db_root = pathlib.Path(explicit).resolve().parent.parent
        else:
            try:
                return explicit, os.path.getsize(explicit)
            except OSError:
                pass

    if not conversation_id or conversation_id == "unknown":
        return None, 0

    best_transcript = None
    best_bytes = 0
    app_dirs = resolve_agy_app_dirs()
    if explicit_db_root and explicit_db_root.is_dir() and explicit_db_root not in app_dirs:
        app_dirs = [explicit_db_root] + app_dirs

    for root in app_dirs:
        logs_dir = root / "brain" / conversation_id / ".system_generated" / "logs"
        # Prefer compact transcript.jsonl (actual model context with truncated large outputs)
        # over transcript_full.jsonl (which stores untruncated raw tool dumps).
        for name in ("transcript.jsonl", "transcript_full.jsonl"):
            candidate = logs_dir / name
            if candidate.is_file():
                try:
                    sz = candidate.stat().st_size
                    if sz > 0 and sz > best_bytes:
                        best_bytes = sz
                        best_transcript = str(candidate)
                        break
                except OSError:
                    pass

    if best_transcript is None:
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


THRESHOLD_CLAUDE = env_int("CLAUDE_AUTO_HANDOFF_THRESHOLD", 200000)
REFIRE_STEP = env_int("CLAUDE_AUTO_HANDOFF_REFIRE_STEP", 25000)
LOG = os.environ.get("CLAUDE_AUTO_HANDOFF_LOG") or os.path.expanduser("~/.claude/logs/auto-handoff.log")
STATE_DIR = pathlib.Path(os.environ.get("CLAUDE_AUTO_HANDOFF_STATE_DIR") or "/tmp")
HANDOFF_SCRIPT = os.path.expanduser("~/.claude/skills/handoff/scripts/herdr-handoff.sh")

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


def log(session_id, context, decision, why, notices=False):
    """One line per decision taken at or over the threshold; never raises."""
    try:
        d = os.path.dirname(LOG)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "session": session_id,
                                "context": context, "decision": decision, "why": why,
                                "notices": notices, "dry_run": not notices}) + "\n")
    except Exception:
        pass


def mark(path, context):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(context))
    except Exception:
        pass


def emit_decision(is_agy, reason):
    """Emit harness-appropriate Stop decision JSON (`continue` for AGY, `block` for Claude)."""
    decision = "continue" if is_agy else "block"
    print(json.dumps({"decision": decision, "reason": reason}))


def emit_noop(is_agy):
    """AGY hooks expect `{}` on stdout when no action is taken; Claude expects empty stdout."""
    if is_agy:
        print("{}")


def parse_transcript_usage_and_tasks(transcript):
    """Scan a JSONL transcript for Claude usage records and background task markers."""
    usage = None
    launched, finished = set(), set()
    if not transcript or not os.path.isfile(transcript):
        return None, launched, finished
    with open(transcript, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if ("CHECKPOINT" in line and ("type" in line)) or "# Resuming from a compaction" in line:
                launched.clear()
                finished.clear()
            if "Task Description: Timer:" not in line:
                launched.update(next(filter(None, ids)) for ids in LAUNCHED.findall(line))
            finished.update(
                (ids if isinstance(ids, str) else next(filter(None, ids)))
                for ids in FINISHED.findall(line)
            )
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("type") != "assistant":
                continue
            u = (entry.get("message") or {}).get("usage")
            if u:
                usage = u
    return usage, launched, finished


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    if not isinstance(data, dict):
        return

    is_agy = is_agy_payload(data)

    if os.environ.get("CLAUDE_AUTO_HANDOFF") == "0" or (is_agy and os.environ.get("AGY_AUTO_HANDOFF") == "0"):
        emit_noop(is_agy)
        return

    if data.get("stop_hook_active") or data.get("agent_id") or data.get("parentConversationId"):
        emit_noop(is_agy)
        return

    if is_agy:
        term_reason = data.get("terminationReason")
        if term_reason is not None and term_reason not in ALLOWED_AGY_TERMINATION_REASONS:
            emit_noop(True)
            return
        threshold = env_int("AGY_AUTO_HANDOFF_THRESHOLD", env_int("CLAUDE_AUTO_HANDOFF_THRESHOLD", 128000))
        hard_cap = env_int("AGY_AUTO_HANDOFF_HARD_CAP", env_int("CLAUDE_AUTO_HANDOFF_HARD_CAP", threshold * 3 // 2))
        notices = (
            os.environ.get("AGY_AUTO_HANDOFF_NOTICES") != "0"
            and os.environ.get("CLAUDE_AUTO_HANDOFF_NOTICES") != "0"
        )
        raw_session_id = data.get("conversationId") or data.get("session_id") or "unknown"
        session_id = "".join(c for c in str(raw_session_id) if c.isalnum() or c in "-_") or "unknown"
        workspaces = data.get("workspacePaths") or []
        non_skill_workspaces = [
            w for w in workspaces
            if not str(w).rstrip("/").endswith(("/skills", "/.gemini/skills", "/.agents/skills"))
        ]
        cwd = data.get("cwd") or (
            non_skill_workspaces[0] if non_skill_workspaces else (workspaces[0] if workspaces else None)
        )
        transcript, total_bytes = resolve_agy_transcript_and_bytes(data, session_id)
        usage, launched, finished = parse_transcript_usage_and_tasks(transcript)
        if usage:
            context = (
                int(usage.get("input_tokens") or 0)
                + int(usage.get("cache_read_input_tokens") or 0)
                + int(usage.get("cache_creation_input_tokens") or 0)
            )
        else:
            context = total_bytes // BYTES_PER_TOKEN
        if context <= 0:
            emit_noop(True)
            return
        prefix = "agy-auto-handoff"
    else:
        threshold = THRESHOLD_CLAUDE
        hard_cap = env_int("CLAUDE_AUTO_HANDOFF_HARD_CAP", threshold * 3 // 2)
        notices = os.environ.get("CLAUDE_AUTO_HANDOFF_NOTICES") == "1"
        transcript = data.get("transcript_path")
        raw_session_id = data.get("session_id") or "unknown"
        session_id = "".join(c for c in str(raw_session_id) if c.isalnum() or c in "-_") or "unknown"
        cwd = data.get("cwd")
        if not transcript or not os.path.isfile(transcript):
            return
        usage, launched, finished = parse_transcript_usage_and_tasks(transcript)
        if not usage:
            return
        context = (
            int(usage.get("input_tokens") or 0)
            + int(usage.get("cache_read_input_tokens") or 0)
            + int(usage.get("cache_creation_input_tokens") or 0)
        )
        prefix = "claude-auto-handoff"

    flag = STATE_DIR / f"{prefix}-{session_id}.flag"
    dry = ".dry" if not notices else ""
    drain = STATE_DIR / f"{prefix}-{session_id}.drain{dry}"
    refire = STATE_DIR / f"{prefix}-{session_id}.refire{dry}"

    if context < threshold:
        for p in (
            *((flag,) if (notices or is_agy) else ()),
            drain,
            refire,
            STATE_DIR / f"{prefix}-{session_id}.drain",
            STATE_DIR / f"{prefix}-{session_id}.drain.dry",
            STATE_DIR / f"{prefix}-{session_id}.refire",
            STATE_DIR / f"{prefix}-{session_id}.refire.dry",
        ):
            try:
                p.unlink()
            except OSError:
                pass
        emit_noop(is_agy)
        return

    if flag.exists():
        try:
            last = max(int(p.read_text()) for p in (flag, refire) if p.exists())
        except Exception:
            last = context
            mark(refire, context)
        if context < last + REFIRE_STEP:
            emit_noop(is_agy)
            return
        mark(refire, context)
        log(session_id, context, "retired-reminder", f"grew {context - last} since the last fire", notices=notices)
        if notices:
            emit_decision(
                is_agy,
                f"AUTO-HANDOFF: this session already handed off and has since grown to {context} "
                "tokens. It is retired: do not start or continue work here. If the handoff tab "
                "is not running, run the handoff skill again; otherwise reply in one line that "
                "the work moved to the handoff tab, then stop.",
            )
        else:
            emit_noop(is_agy)
        return

    pending = sorted(launched - finished)
    agy_not_idle = is_agy and (data.get("fullyIdle") is False)
    dirty = dirty_tree(cwd)
    if context < hard_cap and (pending or agy_not_idle or dirty):
        if drain.exists():
            emit_noop(is_agy)
            return
        mark(drain, context)
        bg_count = len(pending) + (1 if agy_not_idle and not pending else 0)
        why = f"background={bg_count} dirty_tree={dirty}"
        log(session_id, context, "drain-notice", why, notices=notices)
        if notices:
            emit_decision(
                is_agy,
                f"AUTO-HANDOFF pending: context is {context} tokens (threshold {threshold}) but "
                f"this is not a safe point yet ({why}). Do not start a new task and do not "
                "launch new background agents or commands. Finish the unit of work in progress, "
                "let the running background work report back, commit, then end your turn; the "
                f"handoff runs at the next clean stop, or regardless at {hard_cap} tokens. "
                "If nothing is left to do right now, reply in one line and stop.",
            )
        else:
            emit_noop(is_agy)
        return

    mark(flag, context)
    log(session_id, context, "handoff", "hard-cap" if (pending or agy_not_idle or dirty) else "safe-point", notices=notices)

    if is_agy:
        reason = (
            f"AUTO-HANDOFF: this conversation's context reached ~{context} tokens "
            f"(threshold {threshold}). Do not continue the current task. "
            "Execute the handoff skill now: compact this session into "
            "/tmp/handoff-<YYYY-MM-DD-HHMMSS>-<slug>.md following the handoff skill "
            "template (MUST include Section 1 Main Context: Original User Objective, "
            "Governing Spec/Plan/Epic path, and Key User Decisions/Corrections so the "
            "new session does not lose the big picture), then run "
            f"{HANDOFF_SCRIPT} "
            "\"<doc-path>\" --kind agy --prompt \"auto-handoff: continue the work in "
            "the new tab\" (absolute path). If running inside T3 Code with t3_thread_launch "
            "available, also call t3_thread_launch with the generated .prompt.txt content "
            "and matching workspaceStrategy. Report the handoff file path and Herdr/T3 "
            "target, then stop."
        )
    else:
        reason = (
            f"AUTO-HANDOFF: this session's context reached {context} tokens "
            f"(threshold {threshold}). Do not continue the current task. "
            "Execute the handoff skill now: compact this session into "
            "/tmp/handoff-<YYYY-MM-DD-HHMMSS>-<slug>.md following the handoff skill "
            "template (MUST include Section 1 Main Context: Original User Objective, "
            "Governing Spec/Plan/Epic path, and Key User Decisions/Corrections so the "
            "new session does not lose the big picture), then run "
            f"{HANDOFF_SCRIPT} "
            "\"<doc-path>\" --kind claude --mode <code|plan> --prompt \"auto-handoff: "
            "continue the work in the new tab\". Pick --mode code (starts Sonnet) when "
            "the Immediate Next Action is implementation: editing code, running/fixing "
            "tests, or executing tasks of an already-approved plan. Pick --mode plan "
            "(default model) for brainstorming, specs, plans, research, review/audit, "
            "or debugging with an unknown root cause; if unsure, pick plan. "
            "Report the handoff file path, Herdr tab id, and chosen mode, then stop."
        )
    emit_decision(is_agy, reason)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a Stop hook must never break the session it watches
