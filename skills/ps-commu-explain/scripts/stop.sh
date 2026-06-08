#!/usr/bin/env bash
# stop.sh — stop one ps-commu app's server (marker-verified, spec D7).
# Usage: stop.sh <slug>
set -euo pipefail
source "$(dirname "$0")/common.sh"
slug="${1:-}"
[[ -n "$slug" && "$slug" != "-h" && "$slug" != "--help" ]] || { grep '^#' "$0" | cut -c3-; exit 1; }
pid="$(meta_get "$slug" pid)"
if [[ -n "$pid" ]] && pid_has_marker "$pid" "$slug"; then
  kill "$pid" 2>/dev/null && echo "stopped $slug (pid $pid)" || echo "$slug: pid $pid already gone"
else
  echo "$slug: no live marker-verified server (pid='$pid') — nothing killed"
fi
meta_set "$slug" pid ""
