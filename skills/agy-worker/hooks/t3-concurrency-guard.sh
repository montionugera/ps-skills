#!/usr/bin/env bash
# PreToolUse hook (Claude Code + Claude Agent SDK inside T3 Code): cap concurrent T3 Code agent threads.
# Matcher: delegate_task|mcp__t3-code__t3_thread_launch
# Counts `claude` CLI processes whose parent is the T3 Code app (each T3 thread runs one). At or above the cap it
# denies the launch; below it, it adds the current count as context. Evidence 2026-11-01: up to 15 concurrent T3
# sessions pushed the Mac into swap (3.9 GB) and froze T3; T3 restarts then time out on backend readiness.
# Env: T3_MAX_THREADS (default 4), T3_CONCURRENCY_GUARD=off to disable, T3_GUARD_PS_CMD (tests: fake ps).
set -u
[ "${T3_CONCURRENCY_GUARD:-on}" = "off" ] && exit 0
LIMIT="${T3_MAX_THREADS:-4}"
PS_CMD="${T3_GUARD_PS_CMD:-ps -Ao pid,ppid,command}"
INPUT="$(head -c 65536 2>/dev/null || true)"
TOOL="$(printf '%s' "$INPUT" | sed -nE 's/.*"tool_name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' | head -1)"
case "$TOOL" in delegate_task|mcp__t3-code__t3_thread_launch) ;; *) exit 0 ;; esac
# one pass: cmd[pid]; every `claude` CLI whose parent command is the T3 Code app counts as one T3 thread
T3COUNT="$($PS_CMD 2>/dev/null | awk '
  NR==1 && $1=="PID" {next}
  { pid=$1; ppid=$2; $1=""; $2=""; cmd=substr($0,3); cmds[pid]=cmd
    if (cmd ~ /(^|[ \/])claude( |$)/ && cmd !~ /t3-concurrency-guard/) { parent[pid]=ppid } }
  END { n=0; for (c in parent) if (cmds[parent[c]] ~ /T3 Code/) n++; print n+0 }')"
if [ "$T3COUNT" -ge "$LIMIT" ]; then
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"T3 concurrency cap: %s T3 Code agent threads are already running (limit %s, env T3_MAX_THREADS). Launching more pushes this Mac into swap and freezes T3. Wait for one to finish with a single blocking t3_thread_wait, then launch."}}\n' "$T3COUNT" "$LIMIT"
else
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"T3 threads running: %s of %s allowed. Before ending the turn with T3 tasks pending, block ONCE on t3_thread_wait: T3 closes idle provider sessions after 30 min and a late task notification is lost."}}\n' "$T3COUNT" "$LIMIT"
fi
exit 0
