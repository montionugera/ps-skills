#!/usr/bin/env bash
# Lifecycle tests for ps-commu-explain scripts. Run directly; exits non-zero on failure.
# Uses slugs prefixed "t-" and cleans them up.
set -uo pipefail
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
S="$SKILL_DIR/scripts"
PASS=0; FAIL=0
ok()   { echo "PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "FAIL: $1"; FAIL=$((FAIL+1)); }
check(){ local name="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi; }

# --- common.sh ---
source "$S/common.sh"

cleanup_tests() {
  for d in /tmp/ps-commu/t-*/; do
    [[ -d "$d" ]] || continue
    local s p; s="$(basename "$d")"; p="$(meta_get "$s" pid 2>/dev/null)"
    [[ -n "$p" ]] && pid_has_marker "$p" "$s" && kill "$p" 2>/dev/null
  done
  rm -rf /tmp/ps-commu/t-* 2>/dev/null
}
trap cleanup_tests EXIT

test_marker_refusal() {            # an unrelated PID must never verify
  sleep 300 & local p=$!
  if pid_has_marker "$p" "t-x"; then kill $p; return 1; fi
  kill $p; return 0
}
test_realpath_refusal() { ! validate_workspace_path "$HOME"; }
test_realpath_accepts() {
  mkdir -p /tmp/ps-commu/t-rp
  validate_workspace_path /tmp/ps-commu/t-rp | grep -q '^/tmp/ps-commu/t-rp$'
}
test_meta_roundtrip() {
  mkdir -p /tmp/ps-commu/t-meta
  meta_set t-meta pid 12345
  [[ "$(meta_get t-meta pid)" == "12345" ]]
}
test_duration_parse() {
  [[ "$(parse_duration 24h)" == 86400 ]] || return 1
  [[ "$(parse_duration 90m)" == 5400   ]] || return 1
  [[ "$(parse_duration 10s)" == 10     ]] || return 1
  [[ "$(parse_duration 60)"  == 60     ]] || return 1
  ! parse_duration xh      2>/dev/null   || return 1
  ! parse_duration 1h30m   2>/dev/null   || return 1
}

check marker_refusal   test_marker_refusal
check realpath_refusal test_realpath_refusal
check realpath_accepts test_realpath_accepts
check meta_roundtrip   test_meta_roundtrip
check duration_parse   test_duration_parse

# --- init.sh ---
test_init_creates() {
  "$S/init.sh" t-init --tier html >/dev/null
  [[ -d /tmp/ps-commu/t-init ]] &&
  [[ "$(stat -f %Lp /tmp/ps-commu)" == "700" ]] &&
  [[ "$(meta_get t-init tier)" == "html" ]] &&
  [[ "$(meta_get t-init port)" =~ ^77[0-9][0-9]$ ]]
}
test_init_bad_slug() {
  ! "$S/init.sh" "Bad Slug!" 2>/dev/null &&
  ! "$S/init.sh" "trailing-" 2>/dev/null &&
  ! "$S/init.sh" t-ok --tier vue 2>/dev/null &&
  ! "$S/init.sh" t-ok --tier 2>/dev/null
}
test_sweep_old_dead() {                 # >3d old, no server → swept
  mkdir -p /tmp/ps-commu/t-old
  touch -t 202601010000 /tmp/ps-commu/t-old
  "$S/init.sh" t-sweeptrigger >/dev/null
  [[ ! -d /tmp/ps-commu/t-old ]]
}
test_sweep_spares_live() {              # >3d old but live marker-verified server → spared
  mkdir -p /tmp/ps-commu/t-oldlive
  python3 -m http.server 7798 --bind 127.0.0.1 --directory /tmp/ps-commu/t-oldlive >/dev/null 2>&1 &
  local pid=$!
  sleep 1
  meta_set t-oldlive pid "$pid"
  touch -t 202601010000 /tmp/ps-commu/t-oldlive
  "$S/init.sh" t-sweeptrigger2 >/dev/null
  local alive=0; [[ -d /tmp/ps-commu/t-oldlive ]] && alive=1
  kill "$pid" 2>/dev/null
  (( alive ))
}

check init_creates     test_init_creates
check init_bad_slug    test_init_bad_slug
check sweep_old_dead   test_sweep_old_dead
check sweep_spares_live test_sweep_spares_live

# --- serve.sh / stop.sh ---
test_serve_html() {
  "$S/init.sh" t-serve >/dev/null
  echo '<h1>hello t-serve</h1>' > /tmp/ps-commu/t-serve/index.html
  "$S/serve.sh" t-serve >/dev/null
  local port; port="$(meta_get t-serve port)"
  curl -sf "http://127.0.0.1:$port/" | grep -q 'hello t-serve'
}
test_marker_visible() {     # server argv must contain the workspace path (D7)
  local pid; pid="$(meta_get t-serve pid)"
  pid_has_marker "$pid" t-serve
}
test_bind_localhost_only() { # D9: listening on 127.0.0.1, not *
  local port; port="$(meta_get t-serve port)"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN | grep -q '127\.0\.0\.1' &&
  ! lsof -nP -iTCP:"$port" -sTCP:LISTEN | grep -q '\*:'
}
test_port_retry() {          # D3: occupied candidate port → next one taken
  "$S/init.sh" t-retry >/dev/null
  meta_set t-retry port "$(meta_get t-serve port)"   # force collision
  echo ok > /tmp/ps-commu/t-retry/index.html
  "$S/serve.sh" t-retry >/dev/null
  [[ "$(meta_get t-retry port)" != "$(meta_get t-serve port)" ]] &&
  curl -sf "http://127.0.0.1:$(meta_get t-retry port)/" >/dev/null
}
test_watchdog_fires() {      # D6 with marker check
  "$S/init.sh" t-watch >/dev/null
  echo ok > /tmp/ps-commu/t-watch/index.html
  "$S/serve.sh" t-watch --keep-alive 3s >/dev/null
  local pid; pid="$(meta_get t-watch pid)"
  kill -0 "$pid" 2>/dev/null || return 1   # alive now
  for _ in $(seq 1 16); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.5
  done
  return 1
}
test_stop() {
  local pid; pid="$(meta_get t-serve pid)"
  "$S/stop.sh" t-serve >/dev/null
  ! kill -0 "$pid" 2>/dev/null && [[ -z "$(meta_get t-serve pid)" ]]
}
test_stop_refuses_foreign_pid() {  # PID-reuse safety: markerless pid never killed
  sleep 300 & local p=$!
  mkdir -p /tmp/ps-commu/t-foreign
  meta_set t-foreign pid "$p"
  "$S/stop.sh" t-foreign >/dev/null
  local alive=0; kill -0 "$p" 2>/dev/null && alive=1
  kill "$p" 2>/dev/null
  (( alive ))
}

# NOTE: marker_visible, bind_localhost_only, port_retry and stop all depend on
# serve_html having started the t-serve server. Keep registration order.
check serve_html          test_serve_html
check marker_visible      test_marker_visible
check bind_localhost_only test_bind_localhost_only
check port_retry          test_port_retry
check watchdog_fires      test_watchdog_fires
check stop                test_stop
check stop_refuses_foreign_pid test_stop_refuses_foreign_pid

# --- list.sh / clean.sh ---
# NOTE: clean tests wipe /tmp/ps-commu entirely — keep them registered last.
test_list_shows_running_and_stopped() {
  "$S/init.sh" t-list >/dev/null
  echo ok > /tmp/ps-commu/t-list/index.html
  "$S/serve.sh" t-list >/dev/null
  local out; out="$("$S/list.sh")"
  echo "$out" | grep -E 't-list .*running .*http://localhost:' >/dev/null &&
  { "$S/stop.sh" t-list >/dev/null; "$S/list.sh" | grep -E 't-list .*stopped' >/dev/null; }
}
test_clean_refuses_symlink_escape() {   # D8: realpath guard on wipe
  mkdir -p /tmp/ps-commu-outside-canary
  ln -sfn /tmp/ps-commu-outside-canary /tmp/ps-commu/t-evil
  "$S/clean.sh" >/dev/null 2>&1
  local survived=0; [[ -d /tmp/ps-commu-outside-canary ]] && survived=1
  rm -rf /tmp/ps-commu-outside-canary /tmp/ps-commu/t-evil 2>/dev/null
  (( survived ))
}
test_clean_removes_dangling_link() {
  mkdir -p "$PS_COMMU_ROOT"
  ln -sfn /tmp/nonexistent-target-xyz /tmp/ps-commu/t-dangle
  "$S/clean.sh" >/dev/null 2>&1
  [[ ! -L /tmp/ps-commu/t-dangle ]]
}
test_clean_wipes_and_kills() {
  "$S/init.sh" t-clean >/dev/null
  echo ok > /tmp/ps-commu/t-clean/index.html
  "$S/serve.sh" t-clean >/dev/null
  local pid; pid="$(meta_get t-clean pid)"
  "$S/clean.sh" >/dev/null
  ! kill -0 "$pid" 2>/dev/null && [[ ! -d /tmp/ps-commu/t-clean ]]
}

check list_running_stopped     test_list_shows_running_and_stopped
check clean_refuses_symlink    test_clean_refuses_symlink_escape
check clean_removes_dangling   test_clean_removes_dangling_link
check clean_wipes_and_kills    test_clean_wipes_and_kills

echo "----- $PASS passed, $FAIL failed"
exit $(( FAIL > 0 ))
