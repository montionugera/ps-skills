#!/usr/bin/env bash
# list.sh — show all ps-commu apps. Registry is assembled from per-workspace
# meta.json files (spec D4); PIDs are marker-verified on read (spec D7).
set -uo pipefail
source "$(dirname "$0")/common.sh"
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { grep '^#' "$0" | cut -c3-; exit 0; }
printf '%-40s %-6s %-6s %-9s %s\n' SLUG TIER PORT STATUS URL
live_tailnet_ports=" "
for ws in "$PS_COMMU_ROOT"/*/; do
  [[ -f "$ws/meta.json" ]] || continue
  s="$(basename "$ws")"
  tier="$(meta_get "$s" tier)"; port="$(meta_get "$s" port)"; pid="$(meta_get "$s" pid)"
  if [[ -n "$pid" ]] && pid_has_marker "$pid" "$s"; then
    printf '%-40s %-6s %-6s %-9s %s\n' "$s" "$tier" "$port" running "http://localhost:$port"
    tport="$(meta_get "$s" tailnet_port)"
    [[ -n "$tport" ]] && live_tailnet_ports="${live_tailnet_ports}${tport} "
    turl="$(meta_get "$s" tailnet_url)"
    if [[ -n "$turl" ]]; then
      printf '%s\n' "$turl"
    fi
  else
    printf '%-40s %-6s %-6s %-9s %s\n' "$s" "$tier" "$port" stopped "-"
  fi
done
if status_json="$(ts_serve_status_json 2>/dev/null)"; then
  printf '%s' "$status_json" | python3 /dev/fd/3 "$live_tailnet_ports" 3<<'PY'
import json, re, sys
live_tailnet_ports = set(sys.argv[1].split())
try:
    data = json.loads(sys.stdin.read() or "{}")
except Exception:
    sys.exit(0)
if not isinstance(data, dict):
    sys.exit(0)
web = data.get("Web") or {}
for host_port, entry in sorted(web.items()):
    if ":" not in host_port:
        continue
    _, ts_port = host_port.rsplit(":", 1)
    if not re.match(r"^177[0-9]{2}$", ts_port):
        continue
    handlers = (entry or {}).get("Handlers") or {}
    proxy = (handlers.get("/") or {}).get("Proxy") or ""
    m = re.match(r"^http://127\.0\.0\.1:(77[0-9]{2})$", proxy)
    if not m:
        continue
    if ts_port not in live_tailnet_ports:
        print(f"ORPHANED tailnet listener: https://{host_port}/ -> {proxy} (no live server)")
PY
fi
