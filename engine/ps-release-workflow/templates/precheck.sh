#!/usr/bin/env bash
# Gate 1 (precheck) - fast checks, no external services.
# Stamped by `psrw init`. `psrw ship` runs it before merging a feature into the release.
#
# Each slot_* function below is a labelled slot. To FILL a slot, replace its
# `unfilled` line with the real commands. If a slot truly does not apply to this
# repo, keep `unfilled` and add one comment line above it inside the function:
#     # n/a: the reason, in plain words
# An unfilled slot is reported loudly here and FAILS Gate 2 (integration.sh).
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
cd "$(dirname "$SELF")/.."

UNFILLED_IS_FAILURE=0

# ---- slot runner (leave as is) ----------------------------------------------
FAILED=0
UNFILLED=0
UNFILLED_RC=64

unfilled() { echo "UNFILLED GATE SLOT: $SLOT"; return "$UNFILLED_RC"; }

na_reason() {  # prints the reason when slot $1 carries a real "# n/a: ..." marker
  sed -n "/^slot_$1() {/,/^}/p" "$SELF" \
    | sed -n 's/^[[:space:]]*# n\/a: \([^<[:space:]].*\)$/\1/p' | head -n 1
}

run_slot() {
  SLOT=$1
  reason=$(na_reason "$SLOT")
  if [ -n "$reason" ]; then
    echo "-- $SLOT: n/a ($reason)"
    return 0
  fi
  echo "== $SLOT"
  # Subshell with its own `set -e`, called outside any `if`, so the slot stops at
  # its FIRST failing command instead of reporting only the last one.
  set +e
  ( set -e; "slot_$SLOT" )
  rc=$?
  set -e
  if [ "$rc" -eq "$UNFILLED_RC" ]; then
    UNFILLED=$((UNFILLED + 1))
    [ "$UNFILLED_IS_FAILURE" -eq 0 ] && return 0
  fi
  if [ "$rc" -ne 0 ]; then
    echo "FAILED: $SLOT"
    FAILED=$((FAILED + 1))
  fi
}

# ---- slots -------------------------------------------------------------------

# SLOT 1 - build / typecheck (e.g. `pnpm build && pnpm check`, `go vet ./...`, `mypy app`)
slot_build_typecheck() {
  unfilled
}

# SLOT 2 - unit tests (e.g. `pnpm test:unit`, `pytest -q`, `go test ./...`)
slot_unit_tests() {
  unfilled
}

# SLOT 3 - fast static UI checks: lint for controls that cannot be clicked
# (handlers missing, unclosed containers, overlays covering buttons), e.g.
# `pnpm lint`, svelte-check, an antislop script. No browser here - that is Gate 2.
slot_static_ui_checks() {
  unfilled
}

for slot in build_typecheck unit_tests static_ui_checks; do
  run_slot "$slot"
done

if [ "$FAILED" -gt 0 ]; then
  echo "Gate 1: $FAILED slot(s) failed"
  exit 1
fi
if [ "$UNFILLED" -gt 0 ]; then
  echo "Gate 1: passed, but $UNFILLED slot(s) are UNFILLED and checked nothing"
else
  echo "Gate 1: ok"
fi
