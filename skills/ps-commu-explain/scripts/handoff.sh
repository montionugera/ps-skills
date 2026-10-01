#!/usr/bin/env bash
# handoff.sh — print the Stage 6 handoff for a ps-commu workspace.
# Usage: handoff.sh <slug>
#   Prints, in order: the page URL (live marker-verified server only), the
#   brief's Q1-Q3, a "Reader-gate answers:" line (the one part you fill in,
#   from the reader subagent's reply), list.sh output, the cleanup hint and
#   the re-serve command. Commands are printed with absolute paths.
# Exit 0 = printed with a live URL; 1 = printed, but no live server (no URL to
# hand over: run serve.sh <slug> first); 2 = bad slug, no workspace, or no 00-brief.md.
set -uo pipefail
source "$(dirname "$0")/common.sh"

usage() { grep '^#' "$0" | cut -c3-; exit "${1:-0}"; }
case "${1:-}" in -h|--help) usage ;; "") usage 1 ;; esac
slug="$1"
[[ "$slug" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || { echo "bad slug: '$slug' (use kebab-case)" >&2; exit 2; }
dir="$(cd "$(dirname "$0")" && pwd)"
ws="$PS_COMMU_ROOT/$slug"
[[ -f "$ws/00-brief.md" ]] || { echo "no $ws/00-brief.md (run init.sh first)" >&2; exit 2; }
trap 'log_timing handoff.sh "$SECONDS"' EXIT

port="$(meta_get "$slug" port)"; pid="$(meta_get "$slug" pid)"
rc=0
if [[ -n "$pid" ]] && pid_has_marker "$pid" "$slug"; then
  echo "URL: http://localhost:$port"
else
  echo "URL: none, no live server (run $dir/serve.sh $slug)"; rc=1
fi
echo
echo "Reader questions:"
sed -n 's/^\(Q[1-3]:\)[[:space:]]*/\1 /p' "$ws/00-brief.md"
echo
echo "Reader-gate answers: (add the reader subagent's Q1-Q3 lines and its Verdict here)"
echo
echo "Apps (list.sh):"
"$dir/list.sh"
echo
echo "Cleanup: $dir/stop.sh $slug (this app) or $dir/clean.sh (wipes ALL apps)"
echo "Re-serve: $dir/serve.sh $slug"
exit "$rc"
