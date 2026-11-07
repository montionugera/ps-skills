#!/usr/bin/env bash
# PreToolUse hook (Claude Code; also runs inside Claude Agent SDK threads in T3 Code): machine-wide agent budget.
# Matcher: Agent|Task|delegate_task|mcp__t3-code__t3_thread_launch
# Denies a new dispatch when (a) swap is nearly full, or (b) too many worker `claude` processes already run
# machine-wide, or (c) too many were spawned by T3 Code. Below the caps it adds the live counts as context.
# It also caps review fan-out: a reviewer-type Agent whose brief says `RISK: R2` is denied while another reviewer
# runs in this session (Rule 7: R2 gets ONE consolidated reviewer). Off switch: AGENT_R2_REVIEW_GUARD=off.
# A "worker" is a claude CLI whose parent is not an interactive shell/terminal (so your own tabs don't count).
# Env: AGENT_MAX_WORKERS (default 8), T3_MAX_THREADS (default 4), AGENT_SWAP_DENY (default 0.85 of swap total),
#      AGENT_SWAP_WARN (default 0.70), AGENT_CONCURRENCY_GUARD=off to disable,
#      AGENT_GUARD_PS_CMD / AGENT_GUARD_SWAP_CMD (tests: fake ps / fake sysctl).
set -u
[ "${AGENT_CONCURRENCY_GUARD:-on}" = "off" ] && exit 0
MAXW="${AGENT_MAX_WORKERS:-8}"; MAXT3="${T3_MAX_THREADS:-4}"; DENY="${AGENT_SWAP_DENY:-0.85}"; WARN="${AGENT_SWAP_WARN:-0.70}"
PS_CMD="${AGENT_GUARD_PS_CMD:-ps -Ao pid,ppid,command}"; SWAP_CMD="${AGENT_GUARD_SWAP_CMD:-sysctl -n vm.swapusage}"
INPUT="$(head -c 65536 2>/dev/null || true)"
TOOL="$(printf '%s' "$INPUT" | sed -nE 's/.*"tool_name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' | head -1)"
case "$TOOL" in Agent|Task|delegate_task|mcp__t3-code__t3_thread_launch) ;; *) exit 0 ;; esac
read -r WORKERS T3COUNT <<<"$($PS_CMD 2>/dev/null | awk '
  NR==1 && $1=="PID" {next}
  { pid=$1; ppid=$2; $1=""; $2=""; cmd=substr($0,3); cmds[pid]=cmd
    if (cmd ~ /(^|[ \/])claude( |$)/ && cmd !~ /concurrency-guard/) parent[pid]=ppid }
  END { w=0; t=0
    for (c in parent) { p=cmds[parent[c]]
      if (p ~ /T3 Code/) { t++; w++ }
      else if (p !~ /(^|\/|-)(zsh|bash|sh|fish|login|tmux|screen|Terminal|iTerm|ghostty|kitty|herdr|WarpTerminal)( |$|-)/) w++ }
    print w+0, t+0 }')"
# swap: "total = 10240.00M  used = 9108.94M ..." (sysctl vm.swapusage); ratio used/total
SWAPR="$($SWAP_CMD 2>/dev/null | awk '{ for(i=1;i<=NF;i++){ if($i=="total"){t=$(i+2)} if($i=="used"){u=$(i+2)} } gsub(/M/,"",t); gsub(/M/,"",u); if(t+0>0) printf "%.2f", u/t; else print "0" }')"
deny(){ printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$1"; exit 0; }
awk -v r="$SWAPR" -v d="$DENY" 'BEGIN{exit !(r+0>=d+0)}' && deny "Agent budget: swap is ${SWAPR} full (deny at ${DENY}). The machine is already paging; another agent will freeze it. Wait for running work to finish or close idle sessions before dispatching. Override: AGENT_SWAP_DENY."
[ "$WORKERS" -ge "$MAXW" ] && deny "Agent budget: ${WORKERS} worker agents already run machine-wide (limit ${MAXW}, AGENT_MAX_WORKERS). Wait for one to finish with a single blocking wait, then dispatch."
case "$TOOL" in delegate_task|mcp__t3-code__t3_thread_launch) [ "$T3COUNT" -ge "$MAXT3" ] && deny "T3 concurrency cap: ${T3COUNT} T3 Code agent threads already run (limit ${MAXT3}, T3_MAX_THREADS). Block once on t3_thread_wait, then launch." ;; esac
# subagents/*.meta.json gains "finished":true when an agent ends; a crashed agent never does, so a log idle for
# 30 min no longer counts. Reviewers fanned out in one message race the meta files, so a stamp of the last allowed reviewer
# catches them. A short mkdir lock serializes the read and write; only an allowed dispatch moves the stamp, so denied
# retries never extend the block. A lock that outlives 1 s is abandoned: clear it and fail open.
review_cap(){
  [ "${AGENT_R2_REVIEW_GUARD:-on}" = "off" ] && return 0
  case "$TOOL" in Agent|Task) ;; *) return 0 ;; esac
  local re='reviewer|aios-(verifier|falsifier|silent-failures)' sub tp dir m lock stamp now last i got label
  local msg="R2 review cap: another reviewer was dispatched in this session under a minute ago. Rule 7 gives R2 work ONE consolidated reviewer: merge the briefs into one agent. If the change is R1 or higher, label the briefs RISK: R1."
  sub="$(printf '%s' "$INPUT" | sed -nE 's/.*"subagent_type"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' | head -1)"
  printf '%s' "$sub" | grep -Eq "$re" || return 0
  # Only the brief's own first label counts: a brief may quote other labels, and "prompt" with these exact quotes is
  # the real key because quotes inside JSON strings are escaped.
  label="$(printf '%s' "$INPUT" | sed -E 's/.*"prompt"[[:space:]]*:[[:space:]]*"//' | grep -oE 'RISK:[[:space:]]*R[0-9]+' | head -1)"
  [ "${label##*[: ]}" = "R2" ] || return 0
  tp="$(printf '%s' "$INPUT" | sed -nE 's/.*"transcript_path"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' | head -1)"
  [ -n "$tp" ] || return 0
  dir="${tp%.jsonl}/subagents"; mkdir -p "$dir" 2>/dev/null || return 0
  for m in "$dir"/agent-*.meta.json; do
    [ -f "$m" ] || continue
    grep -q '"finished":true' "$m" && continue
    sed -nE 's/.*"agentType":"([^"]+)".*/\1/p' "$m" | grep -Eq "$re" || continue
    [ -n "$(find "${m%.meta.json}.jsonl" -mmin -30 2>/dev/null)" ] || continue
    deny "R2 review cap: reviewer '$(sed -nE 's/.*"description":"([^"\\]*).*/\1/p' "$m")' is still running. Rule 7 gives R2 work ONE consolidated reviewer: put this concern in that review or wait for it. If the change is R1 or higher, label the brief RISK: R1."
  done
  lock="$dir/.r2-review-lock"; stamp="$dir/.r2-review-stamp"; got=""
  # A lock is abandoned only when it is 5 s+ old (real clock), never because we waited: clearing a live holder's lock
  # let two reviewers through on a slow CI runner. A lock still busy after ~5 s of waiting fails open and is left alone.
  i=0
  while [ "$i" -lt 100 ]; do
    mkdir "$lock" 2>/dev/null && { got=1; break; }
    m="$(stat -c %Y "$lock" 2>/dev/null || stat -f %m "$lock" 2>/dev/null)"
    case "$m" in ''|*[!0-9]*) ;; *) [ $(( $(date +%s) - m )) -ge 5 ] && rmdir "$lock" 2>/dev/null && continue ;; esac
    sleep 0.05; i=$((i + 1))
  done
  [ -n "$got" ] || return 0
  now="${AGENT_GUARD_NOW:-$(date +%s)}"; last="$(cat "$stamp" 2>/dev/null)"
  case "$last" in ''|*[!0-9]*) last=0 ;; esac
  if [ $((now - last)) -lt 60 ]; then rmdir "$lock"; deny "$msg"; fi
  printf '%s' "$now" > "$stamp"; rmdir "$lock"
  return 0
}
review_cap
NOTE=""; awk -v r="$SWAPR" -v w="$WARN" 'BEGIN{exit !(r+0>=w+0)}' && NOTE=" Swap is ${SWAPR} full: keep this to one agent and no screenshots."
printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"Agent budget: %s/%s workers machine-wide, %s/%s T3 threads, swap %s full.%s Brief must carry the subagent budget; block once on the result instead of ending the turn with work pending."}}\n' "$WORKERS" "$MAXW" "$T3COUNT" "$MAXT3" "$SWAPR" "$NOTE"
