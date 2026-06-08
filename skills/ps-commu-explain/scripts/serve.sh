#!/usr/bin/env bash
# serve.sh — start the server for a ps-commu workspace.
# Usage: serve.sh <slug> [--dev] [--keep-alive <dur>]
#   --dev         React tier only: run vite dev (fix loop). Default serves app/dist.
#   --keep-alive  Watchdog lifetime: 10s | 90m | 8h | 72h. Default 24h (spec D6).
# All servers bind 127.0.0.1 ONLY (spec D9). The server command line contains the
# workspace path — the kill-safety marker (spec D7). Binding is authoritative:
# on bind failure the next port is tried, up to 7799 (spec D3).
set -euo pipefail
source "$(dirname "$0")/common.sh"

usage() { grep '^#' "$0" | cut -c3-; exit "${1:-0}"; }
slug="" dev=0 keep="24h"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev) dev=1 ;;
    --keep-alive) [[ $# -ge 2 ]] || { echo "--keep-alive requires a value" >&2; exit 1; }
                  keep="$2"; shift ;;
    -h|--help) usage ;;
    *) slug="$1" ;;
  esac
  shift
done
[[ -n "$slug" ]] || usage 1
ws="$PS_COMMU_ROOT/$slug"
[[ -d "$ws" ]] || { echo "no workspace: $ws (run init.sh first)" >&2; exit 1; }
tier="$(meta_get "$slug" tier)"
[[ "$tier" == "html" || "$tier" == "react" ]] || { echo "bad tier='$tier' in meta.json for $slug (re-run init.sh)" >&2; exit 1; }

# Replace any previous server for this slug (marker-verified).
old_pid="$(meta_get "$slug" pid)"
if [[ -n "$old_pid" ]] && pid_has_marker "$old_pid" "$slug"; then
  kill "$old_pid" 2>/dev/null || true
fi

if [[ "$tier" == "react" && "$dev" == 0 ]]; then
  [[ -d "$ws/app/dist" ]] || { echo "react tier: run 'npm run build' first (no app/dist)" >&2; exit 1; }
fi

keep_secs="$(parse_duration "$keep")" || exit 1
server_pid=""

# Truncate log once per invocation; start_one appends per-attempt headers.
: >"$ws/server.log"

start_one() {  # port → 0 once HTTP responds; 1 if process died (port taken)
  local port="$1"
  echo "--- attempt port $port $(date -u +%H:%M:%SZ) ---" >>"$ws/server.log"
  if [[ "$tier" == "react" && "$dev" == 1 ]]; then
    node "$ws/app/node_modules/vite/bin/vite.js" "$ws/app" \
      --host 127.0.0.1 --port "$port" --strictPort >>"$ws/server.log" 2>&1 &
  else
    local docroot="$ws"
    [[ "$tier" == "react" ]] && docroot="$ws/app/dist"
    # httpserve.py = SimpleHTTPRequestHandler + Cache-Control: no-store, so the
    # browser never shows a stale fix-loop page. $docroot in argv keeps the
    # kill-safety marker (D7); it binds 127.0.0.1 only (D9).
    python3 "$(dirname "$0")/httpserve.py" "$port" "$docroot" \
      >>"$ws/server.log" 2>&1 &
  fi
  server_pid=$!
  for _ in $(seq 1 25); do
    kill -0 "$server_pid" 2>/dev/null || return 1
    # Verify our specific PID owns the port (lsof -a = AND: pid AND socket filter).
    # Without -a, lsof ORs the filters and would match pre-existing servers.
    if lsof -a -p "$server_pid" -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>/dev/null; then
      curl -sf -o /dev/null "http://127.0.0.1:$port/" && return 0
    fi
    sleep 0.2
  done
  kill "$server_pid" 2>/dev/null || true
  return 1
}

port="$(meta_get "$slug" port)"
[[ "$port" =~ ^[0-9]+$ ]] || port=7700
ok=0
while (( port <= 7799 )); do
  if start_one "$port"; then ok=1; break; fi
  port=$((port+1))
done
(( ok )) || { echo "no free port in 7700-7799 — try clean.sh" >&2; exit 1; }

meta_set "$slug" pid "$server_pid"
meta_set "$slug" port "$port"
meta_set "$slug" started_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Self-destruct watchdog (spec D6): marker-verified kill after the TTL.
(
  sleep "$keep_secs"
  if ps -p "$server_pid" -o command= 2>/dev/null | grep -qF "$PS_COMMU_ROOT/$slug"; then
    kill "$server_pid" 2>/dev/null || true
  fi
) >/dev/null 2>&1 &
disown

echo "serving $slug at http://localhost:$port (pid=$server_pid ttl=$keep)"
