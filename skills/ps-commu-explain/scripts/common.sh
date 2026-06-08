#!/usr/bin/env bash
# common.sh — shared helpers for ps-commu lifecycle scripts. Sourced, not executed.

PS_COMMU_ROOT="/tmp/ps-commu"
# Canonical root (macOS /tmp → /private/tmp); used for realpath guard comparisons only.
_PS_COMMU_ROOT_REAL="$(python3 -c 'import os; print(os.path.realpath("/tmp/ps-commu"))')"

# Kill safety (spec D7): a PID belongs to a ps-commu server for <slug> only if its
# command line (ps argv) contains the workspace path. Never kill an unverified PID.
pid_has_marker() {  # pid slug
  local pid="$1" slug="$2"
  [[ "$slug" == */* || -z "$slug" ]] && return 1
  ps -p "$pid" -o command= 2>/dev/null | grep -qF "$PS_COMMU_ROOT/$slug"
}

# Delete safety (spec D8): print realpath if it resolves under /tmp/ps-commu, else refuse.
# Output uses the logical PS_COMMU_ROOT prefix so callers are insulated from /private/tmp on macOS.
validate_workspace_path() {  # path
  local resolved
  resolved="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1")"
  case "$resolved" in
    "$_PS_COMMU_ROOT_REAL"/*|"$PS_COMMU_ROOT"/*)
      # Re-express canonical path under the logical root for consistent output
      local suffix="${resolved#"$_PS_COMMU_ROOT_REAL"}"
      suffix="${suffix#"$PS_COMMU_ROOT"}"
      printf '%s%s\n' "$PS_COMMU_ROOT" "$suffix" ;;
    *) echo "REFUSED: $1 resolves to $resolved (outside $PS_COMMU_ROOT)" >&2; return 1 ;;
  esac
}

meta_get() {  # slug key — empty output if file/key missing
  python3 - "$PS_COMMU_ROOT/$1/meta.json" "$2" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get(sys.argv[2], ""))
except Exception:
    pass
PY
}

meta_set() {  # slug key value — creates/updates meta.json
  python3 - "$PS_COMMU_ROOT/$1/meta.json" "$2" "$3" <<'PY'
import json, os, sys, tempfile
path, key, val = sys.argv[1:4]
data = {}
if os.path.exists(path):
    try:
        with open(path) as f: data = json.load(f)
    except Exception: data = {}
data[key] = val
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
with os.fdopen(fd, "w") as f: json.dump(data, f, indent=1)
os.replace(tmp, path)
PY
}

parse_duration() {  # "24h" | "90m" | "10s" | bare seconds → seconds; invalid → return 1
  local d="$1"
  case "$d" in
    *h) [[ "${d%h}" =~ ^[0-9]+$ ]] || { echo "parse_duration: invalid: $d" >&2; return 1; }
        echo $(( ${d%h} * 3600 )) ;;
    *m) [[ "${d%m}" =~ ^[0-9]+$ ]] || { echo "parse_duration: invalid: $d" >&2; return 1; }
        echo $(( ${d%m} * 60 )) ;;
    *s) [[ "${d%s}" =~ ^[0-9]+$ ]] || { echo "parse_duration: invalid: $d" >&2; return 1; }
        echo "${d%s}" ;;
    *)  [[ "$d" =~ ^[0-9]+$ ]] || { echo "parse_duration: invalid: $d" >&2; return 1; }
        echo "$d" ;;
  esac
}
