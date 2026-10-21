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
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from handoff_usage import (
    dirty_tree,
    env_int,
    parse_transcript_usage_and_tasks,
    safe_point_blocked,
    stop_thresholds,
    usage_context,
)

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


def active_transcript_bytes(path):
    """Return active bytes after the last compaction CHECKPOINT line in a JSONL transcript."""
    try:
        raw = pathlib.Path(path).read_bytes()
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
    """True when invoked inside a native subagent or a T3 Code delegate_task child run."""
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


def resolve_agy_transcript_and_bytes(data, conversation_id):
    """Resolve (transcript_file_or_None, total_bytes) for an AGY conversation.

    Checks:
      1. Explicit `transcriptPath` / `transcript_path` in hook payload.
      2. `<appDataDir>/brain/<conversationId>/.system_generated/logs/transcript_full.jsonl`
         and `transcript.jsonl` (counting only post-CHECKPOINT bytes).
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
        # Prefer compact transcript.jsonl (actual model context with truncated large outputs)
        # over transcript_full.jsonl (which stores untruncated raw tool dumps).
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
                        # A non-empty compact transcript is this root's answer, even when
                        # another spelling of the same root already chose it.
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


REFIRE_STEP = env_int("CLAUDE_AUTO_HANDOFF_REFIRE_STEP", 25000)
LOG = os.environ.get("CLAUDE_AUTO_HANDOFF_LOG") or os.path.expanduser("~/.claude/logs/auto-handoff.log")
STATE_DIR = pathlib.Path(os.environ.get("CLAUDE_AUTO_HANDOFF_STATE_DIR") or "/tmp")
HANDOFF_SCRIPT = os.path.expanduser("~/.claude/skills/handoff/scripts/herdr-handoff.sh")

# Text that tells the owner a handoff is happening (checked only when none ran).
HANDOFF_CLAIM = re.compile(
    r"(?:next step|work) (?:happens|continues|moved) in the new tab|handing off now",
    re.I,
)


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


def noticed_without_handoff(session_id):
    """True when the log holds a midturn or drain notice for this session and no handoff
    (the transcript's banner check is the caller's)."""
    seen = set()
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            for line in f:
                if session_id not in line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("session") == session_id:
                    seen.add(rec.get("decision"))
    except OSError:
        return False
    return "handoff" not in seen and bool(seen & {"midturn-notice", "drain-notice"})


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



# Text that tells the owner a handoff is happening (checked only when none ran).
HANDOFF_CLAIM = re.compile(
    r"(?:next step|work) (?:happens|continues|moved) in the new tab|handing off now",
    re.I,
)


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

    if data.get("agent_id") or data.get("parentConversationId"):
        emit_noop(is_agy)
        return

    if is_agy:
        term_reason = data.get("terminationReason")
        if term_reason is not None and term_reason not in ALLOWED_AGY_TERMINATION_REASONS:
            emit_noop(True)
            return
        threshold, hard_cap = stop_thresholds(is_agy=True)
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
        if is_delegated_subagent(data, transcript=transcript, session_id=session_id):
            emit_noop(True)
            return
        usage, running, last_text, banner = parse_transcript_usage_and_tasks(transcript)
        if usage:
            context = usage_context(usage)
        else:
            context = total_bytes // BYTES_PER_TOKEN
        if context <= 0:
            emit_noop(True)
            return
        prefix = "agy-auto-handoff"
    else:
        threshold, hard_cap = stop_thresholds(is_agy=False)
        notices = os.environ.get("CLAUDE_AUTO_HANDOFF_NOTICES") == "1"
        transcript = data.get("transcript_path")
        raw_session_id = data.get("session_id") or "unknown"
        session_id = "".join(c for c in str(raw_session_id) if c.isalnum() or c in "-_") or "unknown"
        cwd = data.get("cwd")
        if not transcript or not os.path.isfile(transcript):
            return
        if is_delegated_subagent(data, transcript=transcript, session_id=session_id):
            return
        usage, running, last_text, banner = parse_transcript_usage_and_tasks(transcript)
        if not usage:
            return
        context = usage_context(usage)
        prefix = "claude-auto-handoff"

    # stop_hook_active means some Stop hook blocked the last stop. Stay silent only when that
    # block was our own drain notice; a block by another hook (mesh guard, prompt-type verify)
    # must not suppress the handoff the mid-turn hook already announced. The .drainblock marker
    # is one-shot: consumed by the continuation stop it belongs to, so it cannot go stale.
    drainblock = STATE_DIR / f"{prefix}-{session_id}.drainblock"
    if data.get("stop_hook_active") and drainblock.exists():
        drainblock.unlink(missing_ok=True)
        emit_noop(is_agy)
        return

    flag = STATE_DIR / f"{prefix}-{session_id}.flag"
    draining = STATE_DIR / f"{prefix}-{session_id}.draining"
    dry = ".dry" if not notices else ""
    drain = STATE_DIR / f"{prefix}-{session_id}.drain{dry}"
    refire = STATE_DIR / f"{prefix}-{session_id}.refire{dry}"

    # Claim guard: a notice went out, no handoff ran, and the model says one is happening.
    guard = STATE_DIR / f"{prefix}-{session_id}.claimguard"
    if HANDOFF_CLAIM.search(last_text) and not guard.exists() and not banner and noticed_without_handoff(session_id):
        mark(guard, context)
        log(session_id, context, "claim-guard", "claimed a handoff that did not run", notices=notices)
        if notices:
            emit_decision(is_agy, "AUTO-HANDOFF: No handoff ran. Correct it in one line and keep working.")
        else:
            emit_noop(is_agy)
        return

    if context < threshold:
        for p in (
            *((flag, draining) if (notices or is_agy) else ()),
            drain,
            refire,
            drainblock,
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

    pending = sorted(running)
    if flag.exists():
        if draining.exists() and not pending:
            draining.unlink(missing_ok=True)
            log(session_id, context, "relay-done", "last agent reported", notices=notices)
            if notices:
                emit_decision(
                    is_agy,
                    "AUTO-HANDOFF: the last agent reported. Relay its result to the new tab "
                    "(SendMessage) and append it to the handoff file's \"Late results\" "
                    "section, then print 🟢 SAFE TO CLOSE THIS TAB and stop.",
                )
            else:
                emit_noop(is_agy)
            return
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
        if notices and draining.exists():
            emit_decision(
                is_agy,
                f"AUTO-HANDOFF: this session already handed off but {len(pending)} background "
                "agents it started are still running. Start nothing. Relay each report to the "
                "new tab (SendMessage) and append it to the handoff file's \"Late results\" "
                "section; after the last one reports, print 🟢 SAFE TO CLOSE THIS TAB and stop.",
            )
        elif notices:
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

    agy_not_idle = is_agy and (data.get("fullyIdle") is False)
    dirty = dirty_tree(cwd)
    if safe_point_blocked(context, hard_cap, pending, dirty, agy_not_idle):
        if drain.exists():
            emit_noop(is_agy)
            return
        mark(drain, context)
        if notices:
            mark(drainblock, context)
        bg_count = len(pending) + (1 if agy_not_idle and not pending else 0)
        why = f"background={bg_count} dirty_tree={dirty}"
        log(session_id, context, "drain-notice", why, notices=notices)
        if notices:
            emit_decision(
                is_agy,
                f"AUTO-HANDOFF pending: context is {context} tokens (threshold {threshold}) but "
                f"this is not a safe point yet ({why}). Do not start a new task and do not "
                "launch new background agents or commands on your own. A newer owner instruction wins; "
                "the handoff just waits until that work reports back. Finish the unit of work in "
                "progress, let the running background work report back, commit, then end your turn; "
                f"the handoff runs at the next clean stop, or regardless at {hard_cap} tokens. "
                "If nothing is left to do right now, reply in one line and stop.",
            )
        else:
            emit_noop(is_agy)
        return

    mark(flag, context)
    n_running = len(pending) + (1 if agy_not_idle and not pending else 0)
    if n_running:
        mark(draining, context)
    log(session_id, context, "handoff", "hard-cap" if (pending or agy_not_idle or dirty) else "safe-point", notices=notices)
    running_hint = f"--running {n_running}"
    running_note = (
        " That N is this hook's count; raise it if your own check in handoff skill step 3a "
        "finds more agents still running."
    )

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
            f"the new tab\" {running_hint} (absolute path).{running_note} If running inside T3 Code with t3_thread_launch "
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
            f"continue the work in the new tab\" {running_hint}.{running_note} Pick --mode code (starts Sonnet) when "
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
