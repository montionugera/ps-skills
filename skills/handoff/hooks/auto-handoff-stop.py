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
    BYTES_PER_TOKEN,
    active_transcript_bytes,
    dirty_tree,
    env_int,
    is_agy_payload,
    is_delegated_subagent,
    parse_transcript_usage_and_tasks,
    resolve_agy_app_dirs,
    resolve_agy_transcript_and_bytes,
    safe_point_blocked,
    stop_thresholds,
    usage_context,
)

# Antigravity (AGY) Stop hook sends camelCase terminationReason values.
# Natural model stops in AGY emit "NO_TOOL_CALL" (or legacy "model_stop");
# budget/invocation caps emit "MAX_TOKEN_BUDGET_EXCEEDED" / "MAX_INVOCATIONS".
ALLOWED_AGY_TERMINATION_REASONS = (
    "NO_TOOL_CALL",
    "MAX_TOKEN_BUDGET_EXCEEDED",
    "MAX_INVOCATIONS",
    "model_stop",
)

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


def state_writable():
    probe = STATE_DIR / f".probe-{os.getpid()}"
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        probe.write_text("")
        probe.unlink()
        return True
    except Exception:
        return False


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
        context = (usage_context(usage) if usage else 0) or (total_bytes // BYTES_PER_TOKEN)
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

    # stop_hook_active is not an early exit: another Stop hook (mesh guard, prompt-type verify)
    # may have blocked, and our own drain continuation is the "next clean stop" its notice
    # promises. Loops stay bounded by our markers: .drain (unsafe again -> silent), .flag/.refire.
    # Those markers are the only bound, so when they cannot be written (full disk) never re-block.
    if data.get("stop_hook_active") and not state_writable():
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
            "Execute the handoff skill now: write "
            "/tmp/handoff-<YYYY-MM-DD-HHMMSS>-<slug>.md with the Write tool following the handoff skill "
            "template (MUST include Section 1 Main Context: Original User Objective, "
            "Governing Spec/Plan/Epic path, and Key User Decisions/Corrections so the "
            "new session does not lose the big picture), then run "
            f"{HANDOFF_SCRIPT} "
            "\"<doc-path>\" --kind agy --mode plan --prompt \"auto-handoff: continue the work in "
            f"the new tab\" {running_hint} (absolute path).{running_note} Run herdr-handoff.sh as a single standalone command (no | tail, no 2>&1, no &&, no --no-yolo, no --allow-subdir). (Pass --mode plan to stay on Gemini 4 Argon for orchestration/specs/epics; only pass --mode code for a pure single-lane mechanical task.) If running inside T3 Code with t3_thread_launch "
            "available, also call t3_thread_launch with the generated .prompt.txt content "
            "and workspaceStrategy=\"root\" (never spawn into a subfolder or .claude/worktrees/*). Report the handoff file path and Herdr/T3 "
            "target, then stop."
        )
    else:
        reason = (
            f"AUTO-HANDOFF: this session's context reached {context} tokens "
            f"(threshold {threshold}). Do not continue the current task. "
            "Execute the handoff skill now: write "
            "/tmp/handoff-<YYYY-MM-DD-HHMMSS>-<slug>.md with the Write tool following the handoff skill "
            "template (MUST include Section 1 Main Context: Original User Objective, "
            "Governing Spec/Plan/Epic path, and Key User Decisions/Corrections so the "
            "new session does not lose the big picture), then run "
            f"{HANDOFF_SCRIPT} "
            "\"<doc-path>\" --kind claude --mode <code|plan> --prompt \"auto-handoff: "
            f"continue the work in the new tab\" {running_hint}.{running_note} Run herdr-handoff.sh as a single standalone command (no | tail, no 2>&1, no &&, no --no-yolo, no --allow-subdir). Pick --mode code (starts Sonnet) when "
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
