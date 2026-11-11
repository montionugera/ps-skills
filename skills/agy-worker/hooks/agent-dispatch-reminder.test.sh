#!/usr/bin/env bash
# Regression check for the Claude weekly-quota reading in agent-dispatch-reminder.sh.
# Runs the hook against a fake $HOME with fixture quota files. Usage: bash agent-dispatch-reminder.test.sh
set -u
HOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/agent-dispatch-reminder.sh"
NOW="$(date +%s)"; FUTURE=$((NOW + 86400)); PAST=$((NOW - 86400))
PAYLOAD='{"tool_name":"Agent","tool_input":{"subagent_type":"code-reviewer","model":"opus","description":"Review the diff","prompt":"Review it. never poll."}}'
fail=0

run_case() { # name, setup-fn, expected-substring, forbidden-substring
  local name="$1" setup="$2" want="$3" deny="$4" h out
  h="$(mktemp -d)"; mkdir -p "$h/.local/state/herdr/plugins/herdr-agent-quota"
  "$setup" "$h/.local/state/herdr/plugins/herdr-agent-quota" "$h"
  out="$(printf '%s' "$PAYLOAD" | HOME="$h" JEV_DISPATCH_GATE=off bash "$HOOK" | jq -r '.hookSpecificOutput.additionalContext // ""')"
  if { [ -z "$want" ] || [[ "$out" == *"$want"* ]]; } && { [ -z "$deny" ] || [[ "$out" != *"$deny"* ]]; }; then
    echo "PASS $name"
  else
    echo "FAIL $name"; echo "  got: ${out:0:300}"; fail=1
  fi
  rm -rf "$h"
}

statusline() { # dir, fetched_at, windows-json, session-windows-json
  printf '{"fetched_at_unix":%s,"windows":%s,"session_windows":%s}' "$2" "$3" "$4" > "$1/claude-statusline.json"
}
# The 2026-11-10 bug: live statusline has no weekly window, ~/.claude.json holds last week's 98%-used cache.
stale_cache()    { statusline "$1" "$NOW" '[]' '{}'
                   printf '{"cachedUsageUtilization":{"fetchedAtMs":%s000,"utilization":{"seven_day":{"utilization":98,"resets_at":"2026-01-01T19:00:00.865977+00:00"}}}}' "$PAST" > "$2/.claude.json"; }
missing()        { :; }
old_file()       { statusline "$1" $((NOW - 30000)) "[{\"kind\":\"weekly\",\"used_percent\":90,\"resets_at\":$FUTURE}]" '{}'; }
expired_window() { statusline "$1" "$NOW" "[{\"kind\":\"weekly\",\"used_percent\":98,\"resets_at\":$PAST}]" '{}'; }
fresh_low()      { statusline "$1" "$NOW" "[{\"kind\":\"weekly\",\"used_percent\":70.0,\"remaining_percent\":30.0,\"resets_at\":$FUTURE}]" '{}'; }
fresh_high()     { statusline "$1" "$NOW" "[{\"kind\":\"weekly\",\"used_percent\":2.0,\"remaining_percent\":98.0,\"resets_at\":$FUTURE}]" '{}'; }
session_only()   { statusline "$1" "$NOW" '[]' "{\"a\":[{\"kind\":\"weekly\",\"used_percent\":60,\"resets_at\":$FUTURE}],\"b\":[{\"kind\":\"weekly\",\"used_percent\":95,\"resets_at\":$PAST}]}"; }

run_case "stale ~/.claude.json cache -> unknown, no advice"      stale_cache    "quota unknown" "dispatch-thinker"
run_case "no source -> unknown, no advice"                       missing        "quota unknown" "dispatch-thinker"
run_case "statusline older than 6h -> unknown"                   old_file       "quota unknown" "dispatch-thinker"
run_case "expired weekly window -> unknown"                      expired_window "quota unknown" "dispatch-thinker"
run_case "fresh 30% remaining -> advice with used/remaining/age" fresh_low      "30.0% remaining / 70% used, data 0 min old" ""
run_case "fresh 98% remaining -> no quota advice"                fresh_high     "" "Quota-aware"
run_case "session_windows fallback, live only -> 40% remaining"  session_only   "40% remaining / 60% used" ""
exit "$fail"
