#!/usr/bin/env bash
# list.sh — show all ps-commu apps. Registry is assembled from per-workspace
# meta.json files (spec D4); PIDs are marker-verified on read (spec D7).
set -uo pipefail
source "$(dirname "$0")/common.sh"
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { grep '^#' "$0" | cut -c3-; exit 0; }
printf '%-40s %-6s %-6s %-9s %s\n' SLUG TIER PORT STATUS URL
for ws in "$PS_COMMU_ROOT"/*/; do
  [[ -f "$ws/meta.json" ]] || continue
  s="$(basename "$ws")"
  tier="$(meta_get "$s" tier)"; port="$(meta_get "$s" port)"; pid="$(meta_get "$s" pid)"
  if [[ -n "$pid" ]] && pid_has_marker "$pid" "$s"; then
    printf '%-40s %-6s %-6s %-9s %s\n' "$s" "$tier" "$port" running "http://localhost:$port"
  else
    printf '%-40s %-6s %-6s %-9s %s\n' "$s" "$tier" "$port" stopped "-"
  fi
done
