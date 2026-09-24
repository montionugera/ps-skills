#!/usr/bin/env bash
# serve.sh — start the server for a ps-commu workspace.
# Usage: serve.sh <slug> [--dev] [--keep-alive <dur>] [--no-lint]
#   --dev         React tier only: run vite dev (fix loop). Default serves app/dist.
#   --keep-alive  Watchdog lifetime: 10s | 90m | 8h | 72h. Default 24h (spec D6).
#   --no-lint     Skip the scripts/lint.sh authoring-chain gate before serving.
#                 Intended for the html/react tiers' dev loops — and, until
#                 assets/template-infographic/content.md is itself lint-clean
#                 (Task 6/7), this repo's own render-gate lifecycle tests.
#                 Prints a warning. Without it, serve.sh refuses (exit 1,
#                 printing the lint output) when scripts/lint.sh <slug> fails.
# All servers bind 127.0.0.1 ONLY (spec D9). The server command line contains the
# workspace path — the kill-safety marker (spec D7). Binding is authoritative:
# on bind failure the next port is tried, up to 7799 (spec D3).
set -euo pipefail
source "$(dirname "$0")/common.sh"

usage() { grep '^#' "$0" | cut -c3-; exit "${1:-0}"; }
slug="" dev=0 keep="24h" no_lint=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev) dev=1 ;;
    --keep-alive) [[ $# -ge 2 ]] || { echo "--keep-alive requires a value" >&2; exit 1; }
                  keep="$2"; shift ;;
    --no-lint) no_lint=1 ;;
    -h|--help) usage ;;
    *) slug="$1" ;;
  esac
  shift
done
[[ -n "$slug" ]] || usage 1
ws="$PS_COMMU_ROOT/$slug"
[[ -d "$ws" ]] || { echo "no workspace: $ws (run init.sh first)" >&2; exit 1; }
tier="$(meta_get "$slug" tier)"
[[ "$tier" == "infographic" || "$tier" == "html" || "$tier" == "react" ]] || { echo "bad tier='$tier' in meta.json for $slug (re-run init.sh)" >&2; exit 1; }

# --- authoring-chain lint gate ---
if [[ "$no_lint" == 1 ]]; then
  echo "WARNING: --no-lint skips the authoring-chain lint gate (scripts/lint.sh $slug)" >&2
else
  lint_out=""
  if ! lint_out="$("$(dirname "$0")/lint.sh" "$slug" 2>&1)"; then
    echo "$lint_out"
    echo "lint failed for $slug — fix the issues above, or pass --no-lint (see --no-lint in --help)" >&2
    exit 1
  fi
fi

# Replace any previous server for this slug (marker-verified).
old_pid="$(meta_get "$slug" pid)"
if [[ -n "$old_pid" ]] && pid_has_marker "$old_pid" "$slug"; then
  kill "$old_pid" 2>/dev/null || true
fi

if [[ "$tier" == "react" && "$dev" == 0 ]]; then
  [[ -d "$ws/app/dist" ]] || { echo "react tier: run 'npm run build' first (no app/dist)" >&2; exit 1; }
fi
if [[ "$tier" == "html" || "$tier" == "infographic" ]]; then
  [[ -d "$ws/app" ]] || { echo "$tier tier: no app/ dir (re-run init.sh, then edit app/)" >&2; exit 1; }
fi

keep_secs="$(parse_duration "$keep")" || exit 1
server_pid=""

# Truncate log once per invocation; start_one appends per-attempt headers.
: >"$ws/server.log"

ready="$ws/.ready"
# port → 0 once serving; 1 if the process died (port taken — try the next port);
# 2 if it stayed alive but never became ready (systemic — do NOT walk all 100
# ports: that turned one failure into a 10+ minute hang on CI).
start_one() {
  local port="$1"
  echo "--- attempt port $port $(date -u +%H:%M:%SZ) ---" >>"$ws/server.log"
  rm -f "$ready"
  if [[ "$tier" == "react" && "$dev" == 1 ]]; then
    node "$ws/app/node_modules/vite/bin/vite.js" "$ws/app" \
      --host 127.0.0.1 --port "$port" --strictPort >>"$ws/server.log" 2>&1 &
    server_pid=$!
    for _ in $(seq 1 50); do
      kill -0 "$server_pid" 2>/dev/null || return 1
      # Verify our specific PID owns the port (lsof -a = AND: pid AND socket filter).
      # Without -a, lsof ORs the filters and would match pre-existing servers.
      if lsof -nP -a -p "$server_pid" -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>/dev/null; then
        curl -sf --max-time 2 -o /dev/null "http://127.0.0.1:$port/" && return 0
      fi
      sleep 0.2
    done
  else
    # Doc root is the app/ dir: "/" serves app/index.html (clean URL), and the
    # planning docs (01-factsheet.md etc., possibly private — spec D2) stay OUT
    # of the served tree. React serves its built bundle.
    local docroot="$ws/app"
    [[ "$tier" == "react" ]] && docroot="$ws/app/dist"
    # httpserve.py = SimpleHTTPRequestHandler + Cache-Control: no-store, so the
    # browser never shows a stale fix-loop page. $docroot in argv keeps the
    # kill-safety marker (D7); it binds 127.0.0.1 only (D9).
    # Readiness = httpserve.py writes its PID to $ready right after bind()
    # succeeds (a taken port makes it exit instead). The old lsof+curl probe
    # never passed on the GitHub macOS runner, stalling every port attempt.
    python3 "$(dirname "$0")/httpserve.py" "$port" "$docroot" "$ready" \
      >>"$ws/server.log" 2>&1 &
    server_pid=$!
    for _ in $(seq 1 50); do
      if [[ -s "$ready" ]]; then
        server_pid="$(cat "$ready")"   # the PID that actually bound the port
        return 0
      fi
      kill -0 "$server_pid" 2>/dev/null || return 1
      sleep 0.2
    done
  fi
  kill "$server_pid" 2>/dev/null || true
  return 2
}

port="$(meta_get "$slug" port)"
[[ "$port" =~ ^[0-9]+$ ]] || port=7700
ok=0 rc=0
while (( port <= 7799 )); do
  start_one "$port" && rc=0 || rc=$?
  if (( rc == 0 )); then ok=1; break; fi
  if (( rc == 2 )); then
    echo "server on port $port started but never became ready (10s) — see $ws/server.log:" >&2
    tail -n 20 "$ws/server.log" >&2
    exit 1
  fi
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
