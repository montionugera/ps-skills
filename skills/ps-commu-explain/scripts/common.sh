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

# Timing log (F-018): append "<ISO-8601 UTC> <script> <seconds>" to <workspace>/timings.log.
# The workspace is the caller's $ws (every ps-commu script names it that). Script time only —
# model time shows up as the gaps between entries. Never fails the caller.
log_timing() {  # script seconds
  [[ -n "${ws:-}" && -d "${ws:-}" ]] || return 0
  printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" >>"$ws/timings.log" 2>/dev/null || true
}

# --- Tailscale Serve helpers (R2) ---
TAILSCALE_BIN="${TAILSCALE_BIN:-tailscale}"

_ts_bin_ok() {
  if [[ "$TAILSCALE_BIN" == */* ]]; then
    [[ -x "$TAILSCALE_BIN" ]]
  else
    command -v "$TAILSCALE_BIN" >/dev/null 2>&1
  fi
}

ts_status_json() {
  _ts_bin_ok || return 1
  "$TAILSCALE_BIN" status --self --json 2>/dev/null
}

ts_hostname() {
  local raw
  raw="$(ts_status_json)" || return 1
  printf '%s' "$raw" | python3 /dev/fd/3 3<<'PY'
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
if not isinstance(data, dict) or data.get("BackendState") != "Running":
    sys.exit(1)
dns = ((data.get("Self") or {}).get("DNSName") or "").strip().rstrip(".")
if not dns:
    sys.exit(1)
print(dns)
PY
}

ts_is_ready() {
  local host
  host="$(ts_hostname 2>/dev/null)" || return 1
  [[ -n "$host" ]]
}

ts_serve_status_json() {
  _ts_bin_ok || return 1
  "$TAILSCALE_BIN" serve status --json 2>/dev/null
}

# Remove an owned 17700-17799 tailscale serve listener for <slug>.
# Ownership invariant: meta.json must record tailnet_port in 17700-17799 AND
# `tailscale serve status --json` must show Web["<host>:<tailnet_port>"]["Handlers"]["/"]["Proxy"]
# matching http://127.0.0.1:77xx (with no AllowFunnel and no extra handlers).
# Never calls `reset` or `funnel`, and never touches :8443, :8444, :9443.
ts_unpublish_owned() {  # slug
  local slug="$1"
  local ts_port status_json verdict
  ts_port="$(meta_get "$slug" tailnet_port)"
  [[ -n "$ts_port" ]] || return 0
  if ! [[ "$ts_port" =~ ^177[0-9]{2}$ ]]; then
    echo "REFUSED: $slug tailnet_port='$ts_port' outside owned range 17700-17799" >&2
    return 1
  fi
  if ! status_json="$(ts_serve_status_json)"; then
    echo "WARNING: cannot query tailscale serve status for $slug (port $ts_port)" >&2
    return 0
  fi
  verdict="$(printf '%s' "$status_json" | python3 /dev/fd/3 "$ts_port" 3<<'PY'
import json, re, sys
ts_port = sys.argv[1]
try:
    data = json.loads(sys.stdin.read() or "{}")
except Exception:
    print("INVALID")
    sys.exit(0)
if not isinstance(data, dict):
    print("INVALID")
    sys.exit(0)
web = data.get("Web") or {}
allow_funnel = data.get("AllowFunnel") or {}
matches = [(hp, entry) for hp, entry in web.items() if hp.endswith(":" + ts_port)]
if not matches:
    print("GONE")
    sys.exit(0)
for hp, entry in matches:
    if allow_funnel.get(hp) is True:
        print("REFUSE:funnel")
        sys.exit(0)
    handlers = (entry or {}).get("Handlers") or {}
    root = handlers.get("/") or {}
    proxy = root.get("Proxy") or ""
    if not re.match(r"^http://127\.0\.0\.1:77[0-9]{2}$", proxy):
        print(f"REFUSE:proxy={proxy}")
        sys.exit(0)
    if len(handlers) != 1:
        print("REFUSE:extra_handlers")
        sys.exit(0)
print("OWNED")
PY
  )"
  case "$verdict" in
    OWNED)
      if "$TAILSCALE_BIN" serve --https="$ts_port" off >/dev/null 2>&1; then
        meta_set "$slug" tailnet_port ""
        meta_set "$slug" tailnet_url ""
        return 0
      else
        echo "WARNING: tailscale serve --https=$ts_port off failed for $slug" >&2
        return 1
      fi
      ;;
    GONE)
      meta_set "$slug" tailnet_port ""
      meta_set "$slug" tailnet_url ""
      return 0
      ;;
    REFUSE:*)
      echo "REFUSED: tailscale listener :$ts_port not owned by ps-commu ($verdict)" >&2
      return 1
      ;;
    *)
      echo "WARNING: invalid tailscale serve status JSON for $slug" >&2
      return 1
      ;;
  esac
}
