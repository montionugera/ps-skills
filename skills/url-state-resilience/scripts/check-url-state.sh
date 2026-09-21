#!/usr/bin/env bash
# check-url-state.sh: Static linter for URL-as-State compliance and E2E reload resilience.
# Zero-cost ($0), deterministic (~0.1s runtime).
set -euo pipefail

TARGET_DIR="${1:-.}"
echo "==> [URL-as-State Gate] Verifying state resilience in: $TARGET_DIR"

ERRORS=0

# Check 1: E2E Reload Invariance Assertion
if [ -d "$TARGET_DIR/tests/e2e" ] || [ -d "$TARGET_DIR/e2e" ]; then
    SPEC_DIR="$TARGET_DIR/tests/e2e"
    [ -d "$SPEC_DIR" ] || SPEC_DIR="$TARGET_DIR/e2e"

    FILTER_SPECS=$(grep -rnE "(filter|search|screener|pagination|sort)" "$SPEC_DIR" 2>/dev/null | grep -v "node_modules" || true)
    if [ -n "$FILTER_SPECS" ]; then
        RELOAD_ASSERT=$(grep -rnE "(page\.reload\(\)|cy\.reload\(\))" "$SPEC_DIR" 2>/dev/null | grep -v "node_modules" || true)
        if [ -z "$RELOAD_ASSERT" ]; then
            echo "❌ [ERROR] Filter/search E2E tests exist but have no reload resilience assertions ('page.reload()')."
            echo "           All UI selection state must survive page refresh (URL-as-State)."
            ERRORS=$((ERRORS + 1))
        else
            echo "✓ E2E reload resilience assertions verified."
        fi
    fi
fi

if [ $ERRORS -gt 0 ]; then
    echo "❌ [URL-as-State Gate] Failed with $ERRORS error(s)."
    exit 1
fi

echo "✅ [URL-as-State Gate] Passed cleanly."
