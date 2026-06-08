#!/usr/bin/env bash
# clean.sh — kill ALL ps-commu servers (marker-verified) and wipe /tmp/ps-commu.
# Every deletion is realpath-validated under /tmp/ps-commu (spec D8).
set -uo pipefail
source "$(dirname "$0")/common.sh"
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { grep '^#' "$0" | cut -c3-; exit 0; }
[[ -d "$PS_COMMU_ROOT" ]] || { echo "nothing to clean"; exit 0; }
for ws in "$PS_COMMU_ROOT"/*; do
  [[ -e "$ws" || -L "${ws%/}" ]] || continue   # -L: also process dangling symlinks
  s="$(basename "$ws")"
  pid="$(meta_get "$s" pid)"
  if [[ -n "$pid" ]] && pid_has_marker "$pid" "$s"; then
    kill "$pid" 2>/dev/null && echo "killed $s (pid $pid)"
  fi
  if target="$(validate_workspace_path "$ws")"; then
    rm -rf "$target"
  else
    # rm -f (no -r): removes a symlink/file name only; on a real directory it is a
    # no-op, so even a guard false-negative cannot delete a directory tree here.
    rm -f "${ws%/}" 2>/dev/null   # remove the symlink itself, never its target
    echo "removed suspicious link: $ws (target untouched)" >&2
  fi
done
rmdir "$PS_COMMU_ROOT" 2>/dev/null || true
echo "cleaned"
