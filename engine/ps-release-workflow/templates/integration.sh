#!/usr/bin/env bash
# Gate 2 (integration) - real services, real browser, real data.
# Stamped by `psrw init`. `psrw promote` runs it before the release goes to main.
#
# Each slot_* function below is a labelled slot. To FILL a slot, replace its
# `unfilled` line with the real commands. If a slot truly does not apply to this
# repo, keep `unfilled` and add one comment line above it inside the function:
#     # n/a: the reason, in plain words
# Here an unfilled slot is a FAILURE: an empty template must never pass.
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
cd "$(dirname "$SELF")/.."

UNFILLED_IS_FAILURE=1

# Name of the env var that points at the REAL datastore (not a mock, not sqlite).
DATASTORE_ENV_VAR="DATABASE_URL"

# ---- slot runner (leave as is) ----------------------------------------------
FAILED=0
UNFILLED=0

unfilled() { return 1; }   # placeholder body; run_slot detects it from the source

slot_body() { sed -n "/^slot_$1() {/,/^}/p" "$SELF"; }

is_unfilled() { slot_body "$1" | grep -Eq '^[[:space:]]*unfilled[[:space:]]*$'; }

na_reason() {  # prints the reason when slot $1 carries a real "# n/a: ..." marker
  slot_body "$1" \
    | sed -n 's/^[[:space:]]*# n\/a: \([^<[:space:]].*\)$/\1/p' | head -n 1
}

run_slot() {
  SLOT=$1
  reason=$(na_reason "$SLOT")
  if [ -n "$reason" ]; then
    echo "-- $SLOT: n/a ($reason)"
    return 0
  fi
  # Unfilled is decided from the slot's SOURCE (it still holds the `unfilled`
  # line), never from an exit code a real tool could also return.
  if is_unfilled "$SLOT"; then
    echo "UNFILLED GATE SLOT: $SLOT"
    UNFILLED=$((UNFILLED + 1))
    if [ "$UNFILLED_IS_FAILURE" -ne 0 ]; then
      echo "FAILED: $SLOT"
      FAILED=$((FAILED + 1))
    fi
    return 0
  fi
  echo "== $SLOT"
  # Subshell with its own `set -e`, called outside any `if`, so the slot stops at
  # its FIRST failing command instead of reporting only the last one.
  set +e
  ( set -e; "slot_$SLOT" )
  rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    echo "FAILED: $SLOT"
    FAILED=$((FAILED + 1))
  fi
}

require_env() {  # FAIL, never skip, when the real datastore is not configured
  if [ -z "${!1:-}" ]; then
    echo "$1 is not set - integration tests need the REAL datastore; refusing to skip"
    return 1
  fi
}

# ---- slots -------------------------------------------------------------------

# SLOT 1 - integration tests against the REAL datastore (run migrations, then the
# integration suite against $DATASTORE_ENV_VAR). Keep the require_env line.
slot_integration_real_datastore() {
  require_env "$DATASTORE_ENV_VAR"
  unfilled
}

# SLOT 2 - browser smoke: click every primary control, fail on any page error
# (console error, uncaught exception, failed request), e.g. a Playwright spec.
slot_browser_smoke() {
  unfilled
}

# SLOT 3 - data reconciliation: row count out == row count in; no hardcoded LIMIT.
# Run the pipeline on a known input, compare counts, and grep the query code for
# literal LIMIT / head(N) / slice(0, N) caps that silently trim data.
slot_data_reconciliation() {
  unfilled
}

for slot in integration_real_datastore browser_smoke data_reconciliation; do
  run_slot "$slot"
done

if [ "$FAILED" -gt 0 ]; then
  echo "Gate 2: $FAILED slot(s) failed"
  exit 1
fi
if [ "$UNFILLED" -gt 0 ]; then
  echo "Gate 2: passed, but $UNFILLED slot(s) are UNFILLED and checked nothing"
else
  echo "Gate 2: ok"
fi
