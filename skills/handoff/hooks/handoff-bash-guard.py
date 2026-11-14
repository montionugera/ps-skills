#!/usr/bin/env python3
"""PreToolUse(Bash) guard for herdr-handoff.sh.

Why this hook exists (Root Cause 2026-11-08):
1. In Claude Code `auto` mode (`2.1.319`), `Bash(/Users/.../herdr-handoff.sh*)` in
   `permissions.allow` bypasses the server-side auto-mode classifier ONLY when
   `herdr-handoff.sh` is invoked as a single simple command matching the rule prefix.
2. When an agent pipes `herdr-handoff.sh ... 2>&1 | tail -15`, Claude Code's `veo()`
   sees a pipeline where `tail -15` is only allowed by the built-in `readOnly` rule,
   triggers `serverHeldShellAllow`, and revokes `behavior: "allow"` back to `"ask"`.
   That sends the command to the server-side auto-mode classifier, which flags
   agent-spawning scripts with:
     "Tool call Bash(...) was denied with no reason given" /
     "The server-side auto mode classifier judged this action dangerous (it gave no explanation)"
3. Similarly, chaining `cd ... && cat <<EOF > /tmp/handoff-... && herdr-handoff.sh`,
   using an unexpanded `~` path, or passing `--no-yolo` either forfeits the allow rule
   or causes the child tab to stall on its Section-0 claim prompt.
4. In `auto` mode, a PreToolUse hook MUST NOT rewrite `updatedInput` (which voids the
   classifier verdict with `server_input_rewritten`). Instead, a clean standalone call
   must pass through with zero output, and any malformed call must be denied immediately
   by this hook with an explicit `permissionDecisionReason` and the exact corrected
   standalone command to run.

Escape hatch: HANDOFF_BASH_GUARD=0 in environment.
"""

import json
import os
import re
import shlex
import sys
import time

CANONICAL_SCRIPT = os.path.expanduser("~/.claude/skills/handoff/scripts/herdr-handoff.sh")
ALLOWED_SCRIPT_PATHS = {
    CANONICAL_SCRIPT,
    "/Users/pasitnusso/.claude/skills/handoff/scripts/herdr-handoff.sh",
    "/Users/pasitnusso/ps-skills/skills/handoff/scripts/herdr-handoff.sh",
}

OPTIONS_WITH_VALUE = {
    "--kind",
    "--multiplexer",
    "--mux",
    "--label",
    "--topic",
    "--cwd",
    "--prompt",
    "--mode",
    "--model",
    "--effort",
    "--running",
}

BOOLEAN_OPTIONS = {
    "--cloud",
    "--no-cloud",
    "--jev",
    "--no-jev",
    "--no-agent",
    "--no-focus",
    "--use-agent-manager",
    "--close-source",
    "--yolo",
    "--no-yolo",
    "--allow-subdir",
    "--no-quota-switch",
    "--dry-run",
    "--help",
    "-h",
}

UNQUOTED_REDIR_RE = re.compile(
    r"(?:^|(?<=\s))(?:\d*>>?\s*[^\s'\"]+|\d*>&\d+|&>>?\s*[^\s'\"]+|<(?:\([^\)]*\)|\s*[^\s'\"]+))"
)


def strip_heredocs(cmd: str):
    """Return (cmd_without_heredoc_bodies, has_heredoc)."""
    out = cmd
    has_heredoc = False
    for m in re.finditer(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", cmd):
        has_heredoc = True
        tag = m.group(2)
        body = re.search(
            r"%s[^\n]*\n(.*?)(?:\n[ \t]*%s[ \t]*(?=\n|$))" % (re.escape(m.group(0)), re.escape(tag)),
            out,
            re.S,
        )
        if body:
            out = out[: body.start(1)] + "\n" + out[body.end(1) :]
    return out, has_heredoc


def split_top_level_segments(cmd: str):
    """Split shell command on unquoted `|`, `&&`, `||`, `;`, or newline.

    Returns list of (segment_str, operator_after_or_empty).
    """
    normalized = cmd.replace("\\\n", " ")
    segs = []
    buf = []
    i = 0
    n = len(normalized)
    in_single = False
    in_double = False

    while i < n:
        ch = normalized[i]
        if ch == "\\" and not in_single and i + 1 < n:
            buf.append(normalized[i : i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue
        if not in_single and not in_double:
            if normalized.startswith("&&", i) or normalized.startswith("||", i):
                op = normalized[i : i + 2]
                segs.append(("".join(buf).strip(), op))
                buf = []
                i += 2
                continue
            if ch in ("|", ";", "\n"):
                op = "\n" if ch == "\n" else ch
                segs.append(("".join(buf).strip(), op))
                buf = []
                i += 1
                continue
        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail or not segs:
        segs.append((tail, ""))
    return [(s, op) for s, op in segs if s]


def strip_unquoted_redirections(seg: str):
    """Strip unquoted shell redirections (`2>&1`, `>/dev/null`, `<file`, etc.) before shlex.split.

    Returns `(cleaned_segment, had_redirection)` while preserving `<` and `>` inside quotes.
    """
    out = []
    in_single = False
    in_double = False
    had_redir = False
    i = 0
    n = len(seg)
    while i < n:
        ch = seg[i]
        if ch == "\\" and not in_single and i + 1 < n:
            out.append(seg[i : i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            out.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
            i += 1
            continue
        if not in_single and not in_double:
            # Check for optional leading fd digits right at a token boundary
            m = re.match(
                r"^(\d*(?:>>?|>&\d*|<>|<&\d*|<)|&>>?)\s*('[^']*'|\"[^\"]*\"|[^\s'\"]+)?",
                seg[i:],
            )
            if m and (
                not m.group(1)[0].isdigit()
                or i == 0
                or seg[i - 1].isspace()
            ):
                had_redir = True
                op_part = m.group(1)
                target_part = m.group(2) or ""
                # For `2>&1` or `>&2`, target is already part of op_part (`>&1`)
                if re.match(r"^\d*>&\d+$|^\d*<&\d+$", op_part):
                    i += len(op_part)
                else:
                    i += m.end()
                out.append(" ")
                continue
        out.append(ch)
        i += 1
    return "".join(out), had_redir


def parse_handoff_segment(seg: str):
    """If `seg` executes `herdr-handoff.sh`, return dict of parsed details; else None."""
    if "herdr-handoff.sh" not in seg:
        return None
    cleaned_seg, had_redir = strip_unquoted_redirections(seg)
    try:
        tokens = shlex.split(cleaned_seg)
    except ValueError:
        return None
    if not tokens:
        return None

    idx = 0
    env_vars = {}
    wrappers = []
    while idx < len(tokens):
        tok = tokens[idx]
        if "=" in tok and not tok.startswith("-") and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            k, v = tok.split("=", 1)
            env_vars[k] = v
            idx += 1
            continue
        if tok in ("env", "command", "nohup", "time", "rtk", "proxy"):
            wrappers.append(tok)
            idx += 1
            continue
        break

    if idx >= len(tokens):
        return None

    exe = tokens[idx]
    script_tok = None
    args_start = idx + 1

    if exe.endswith("herdr-handoff.sh"):
        script_tok = exe
    elif os.path.basename(exe) in ("bash", "sh", "zsh"):
        # Check flags to bash/sh/zsh (if `-n` syntax check, it is not executing)
        j = idx + 1
        shell_flags = []
        while j < len(tokens) and tokens[j].startswith("-"):
            shell_flags.append(tokens[j])
            j += 1
        if any("n" in fl.lstrip("-") for fl in shell_flags if not fl.startswith("--")):
            return None
        if j < len(tokens) and tokens[j].endswith("herdr-handoff.sh"):
            wrappers.append(exe)
            script_tok = tokens[j]
            args_start = j + 1
        else:
            return None
    else:
        # Another command (grep, ls, git, wc, sed, python3, etc.) is taking herdr-handoff.sh as an argument
        return None

    script_args = tokens[args_start:]
    return {
        "raw_tokens": tokens,
        "env_vars": env_vars,
        "wrappers": wrappers,
        "script_tok": script_tok,
        "script_args": script_args,
        "has_redirection": had_redir,
    }


def extract_handoff_args(script_args):
    """Parse herdr-handoff.sh arguments to find positional handoff_path, flags, and build clean args."""
    handoff_path = None
    custom_prompt_pos = None
    has_help_or_dry_run = False
    has_no_yolo = False
    has_allow_subdir = False
    clean_args = []

    i = 0
    while i < len(script_args):
        arg = script_args[i]
        if arg in ("--help", "-h", "--dry-run"):
            has_help_or_dry_run = True
            clean_args.append(arg)
            i += 1
        elif arg == "--no-yolo":
            has_no_yolo = True
            i += 1
        elif arg == "--allow-subdir":
            has_allow_subdir = True
            i += 1
        elif arg in OPTIONS_WITH_VALUE:
            clean_args.append(arg)
            if i + 1 < len(script_args):
                clean_args.append(script_args[i + 1])
                i += 2
            else:
                i += 1
        elif arg.startswith("-"):
            clean_args.append(arg)
            i += 1
        else:
            if handoff_path is None:
                handoff_path = arg
            elif custom_prompt_pos is None:
                custom_prompt_pos = arg
            clean_args.append(arg)
            i += 1

    return {
        "handoff_path": handoff_path,
        "has_help_or_dry_run": has_help_or_dry_run,
        "has_no_yolo": has_no_yolo,
        "has_allow_subdir": has_allow_subdir,
        "clean_args": clean_args,
    }


def format_clean_command(clean_args):
    quoted = [shlex.quote(CANONICAL_SCRIPT)] + [shlex.quote(a) for a in clean_args]
    return " ".join(quoted)


def check_command(command: str, cwd: str = None):
    """Return None if allowed, or a detailed permissionDecisionReason string if denied."""
    if os.environ.get("HANDOFF_BASH_GUARD") == "0":
        return None
    if not command or "herdr-handoff.sh" not in command:
        return None

    scannable, has_heredoc = strip_heredocs(command)
    segments = split_top_level_segments(scannable)
    if not segments:
        return None

    parsed_execs = []
    for seg_idx, (seg, op) in enumerate(segments):
        info = parse_handoff_segment(seg)
        if info is not None:
            info["seg_idx"] = seg_idx
            info["op"] = op
            parsed_execs.append(info)

    if not parsed_execs:
        # herdr-handoff.sh is only referenced by a read-only/inspection command (grep, git, bash -n, etc.)
        return None

    target = parsed_execs[-1]
    arg_info = extract_handoff_args(target["script_args"])
    if arg_info["has_help_or_dry_run"]:
        return None

    reasons = []
    short_codes = []

    # Check 1: Piped or redirected output (`| tail -15`, `2>&1`, `>`)
    has_pipe = any(op == "|" for _, op in segments)
    if has_pipe or target["has_redirection"]:
        short_codes.append("piped/redirected command")
        reasons.append(
            "Do NOT pipe (`| tail`, `| head`) or redirect (`2>&1`, `>`) `herdr-handoff.sh`. "
            "In Claude Code `auto` mode, piping `herdr-handoff.sh` to a read-only command (`tail`/`head`) "
            "triggers `serverHeldShellAllow`, which revokes the `settings.json` allow rule and forces "
            "the server-side auto-mode classifier to review (and deny) the command with no explanation."
        )

    # Check 2: Chained / compound command (`&&`, `||`, `;`, newline, or heredoc)
    has_chain = len(segments) > 1 and not (len(segments) == 2 and segments[0][1] == "|")
    if has_chain or has_heredoc:
        short_codes.append("compound/chained command")
        reasons.append(
            "Do NOT chain `herdr-handoff.sh` with `cd`, `cat <<EOF`, `&&`, `;`, or multi-line commands. "
            "Write the `/tmp/handoff-*.md` file with the `Write` tool first, then invoke `herdr-handoff.sh` "
            "as a single standalone command."
        )

    # Check 3: Non-canonical script path or wrapper (`~/.claude/...`, `bash ...`, inline env vars)
    allow_no_yolo_env = str(
        target["env_vars"].get("HERDR_HANDOFF_ALLOW_NO_YOLO")
        or os.environ.get("HERDR_HANDOFF_ALLOW_NO_YOLO")
        or ""
    ).lower() in ("1", "true")
    allow_subdir_env = str(
        target["env_vars"].get("HERDR_HANDOFF_ALLOW_SUBDIR")
        or os.environ.get("HERDR_HANDOFF_ALLOW_SUBDIR")
        or ""
    ).lower() in ("1", "true")
    non_exempt_env = {
        k: v
        for k, v in target["env_vars"].items()
        if k not in ("HERDR_HANDOFF_ALLOW_NO_YOLO", "HERDR_HANDOFF_ALLOW_SUBDIR")
    }
    if target["script_tok"] not in ALLOWED_SCRIPT_PATHS or target["wrappers"] or non_exempt_env:
        short_codes.append("non-canonical script invocation")
        reasons.append(
            f"Invoke `{CANONICAL_SCRIPT}` directly as the first token (no `~` tilde prefix, no leading "
            f"`bash`/`sh`, and no inline env vars) so it matches `Bash({CANONICAL_SCRIPT}*)` in `settings.json`."
        )

    # Check 4: Accidental `--no-yolo`
    if arg_info["has_no_yolo"] and not allow_no_yolo_env:
        short_codes.append("--no-yolo stalls child claim")
        reasons.append(
            "Do NOT pass `--no-yolo` on agent handoffs (unless `HERDR_HANDOFF_ALLOW_NO_YOLO=1` is set). "
            "`--no-yolo` launches the child tab without `--dangerously-skip-permissions`, causing the child "
            "agent to stall on its Section-0 `.claim` prompt in `auto` mode and time out unclaimed."
        )

    # Check 4b: Accidental `--allow-subdir`
    if arg_info["has_allow_subdir"] and not allow_subdir_env:
        short_codes.append("--allow-subdir triggers Trust dialog")
        reasons.append(
            "Do NOT pass `--allow-subdir` on agent handoffs (unless `HERDR_HANDOFF_ALLOW_SUBDIR=1` is set). "
            "Claude Code, Codex, and AGY store folder trust by exact startup `cwd`; spawning into a subfolder "
            "or `.claude/worktrees/*` stalls the child tab on an interactive Trust prompt."
        )

    # Check 5: Handoff file must exist on disk before invoking `herdr-handoff.sh`
    handoff_path = arg_info["handoff_path"]
    base_cwd = cwd or os.getcwd()
    if not handoff_path:
        short_codes.append("missing handoff file argument")
        reasons.append(
            "Missing `<handoff-markdown-path>` positional argument. Pass `/tmp/handoff-<YYYY-MM-DD-HHMMSS>-<slug>.md`."
        )
    else:
        expanded_doc = os.path.expanduser(os.path.expandvars(handoff_path))
        resolved_doc = expanded_doc if os.path.isabs(expanded_doc) else os.path.join(base_cwd, expanded_doc)
        if not os.path.isfile(resolved_doc):
            short_codes.append(f"handoff file not found: {handoff_path}")
            reasons.append(
                f"Handoff file `{handoff_path}` does not exist on disk yet. Create `{handoff_path}` "
                "using the `Write` tool FIRST, then run `herdr-handoff.sh` in the next tool call."
            )

    if not reasons:
        return None

    clean_args = list(arg_info["clean_args"])
    if not handoff_path:
        clean_args = ["/tmp/handoff-<YYYY-MM-DD-HHMMSS>-<slug>.md"] + clean_args
    clean_cmd = format_clean_command(clean_args)
    summary = "; ".join(short_codes)
    bullet_lines = "\n".join(f"  • {r}" for r in reasons)

    return (
        f"HANDOFF GUARD — Blocked before auto-mode classifier (Reason: {summary}):\n"
        f"{bullet_lines}\n\n"
        f"Required action:\n"
        f"  1. Ensure the handoff markdown file is written to disk with the `Write` tool.\n"
        f"  2. Run this exact standalone command (no `| tail`, no `2>&1`, no `&&`, no `--no-yolo`, no `--allow-subdir`):\n"
        f"     {clean_cmd}"
    )


def log_guard_decision(payload, reason_msg):
    log_path = os.environ.get("HERDR_HANDOFF_GUARD_LOG") or os.path.expanduser(
        "~/.local/state/handoff/guard.jsonl"
    )
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "session_id": payload.get("session_id") or payload.get("conversationId") or "unknown",
            "cwd": payload.get("cwd") or "",
            "command": (payload.get("tool_input") or {}).get("command") or "",
            "decision": "deny",
            "reason": reason_msg,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def main() -> int:
    out_mode = "claude"
    args = sys.argv[1:]
    while args:
        if args[0] == "--out" and len(args) > 1:
            out_mode = args[1]
            args = args[2:]
        else:
            args = args[1:]

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        payload = json.loads(raw)
    except Exception:
        return 0

    if not isinstance(payload, dict):
        return 0

    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0

    command = tool_input.get("command") or tool_input.get("CommandLine") or ""
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None

    reason_msg = check_command(command, cwd=cwd)
    if not reason_msg:
        return 0

    log_guard_decision(payload, reason_msg)

    if out_mode == "agy":
        print(json.dumps({"decision": "deny", "reason": reason_msg}))
    else:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason_msg,
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
