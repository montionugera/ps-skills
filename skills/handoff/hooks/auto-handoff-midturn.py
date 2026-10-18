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

TAIL_BYTES = 1 << 20  # the newest usage record is always near the end
BYTES_PER_TOKEN = 4


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

    # Only fall back to SQLite .db + .db-wal size when no JSONL transcript exists yet
    # (SQLite pre-allocates ~480KB WAL frames which otherwise inflate new sessions to 122,880 tokens).
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
        transcript, total_bytes = resolve_agy_transcript_and_bytes(data, session_id)
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
        log = os.environ.get("CLAUDE_AUTO_HANDOFF_LOG") or os.path.expanduser("~/.claude/logs/auto-handoff.log")
        d = os.path.dirname(log)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "session": session_id,
                                "context": context, "decision": "midturn-notice",
                                "why": f"level {level}", "dry_run": dry}) + "\n")
    except Exception:
        pass
    if dry:
        if is_agy:
            print("{}")
        return
    note = (
        f"AUTO-HANDOFF (mid-turn): context is {context} tokens, past {level}. This tool call "
        "is allowed. Finish the unit of work in progress (get it verified and committed), "
        "start nothing new, launch no new background work, then end your turn so the "
        "handoff can run. Do not hand off in the middle of a change."
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
