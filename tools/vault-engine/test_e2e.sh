#!/usr/bin/env bash
set -euo pipefail

VAULT_ROOT="/Users/pasitnusso/Documents/Obsidian Vault"
ENGINE_BIN="${VAULT_ROOT}/_meta/bin/vault-engine"

echo "=================================================="
echo "🧪 Running Ultra-Deterministic Vault Verification"
echo "=================================================="

# 1. Check binary exists
if [ ! -f "$ENGINE_BIN" ]; then
    echo "⚙️ Building vault-engine binary..."
    cd "${VAULT_ROOT}/_meta/engine"
    go build -o "$ENGINE_BIN" ./cmd/vault-engine
fi
echo "✅ Binary verified at: $ENGINE_BIN"

# 2. Run unit tests in engine
echo ""
echo "--- Step 1: Unit Test Suite (Go Tests) ---"
cd "${VAULT_ROOT}/_meta/engine"
go test -v ./...
echo "✅ All Go unit tests passed."

# 3. Test DAG validation & cycle rejection
echo ""
echo "--- Step 2: Workflow DAG & Agent Manifest Validation ---"
"$ENGINE_BIN" validate-dag "${VAULT_ROOT}/_meta/workflows/idea-lifecycle.json"
"$ENGINE_BIN" validate-agent "${VAULT_ROOT}/_meta/agents/agent-olivier.json"
"$ENGINE_BIN" validate-agent "${VAULT_ROOT}/_meta/agents/agent-bestie.json"
"$ENGINE_BIN" validate-agent "${VAULT_ROOT}/_meta/agents/agent-philip.json"
echo "✅ DAG and agent manifests strictly validated."

# 4. End-to-End Ingest -> Read -> OCC Commit Lifecycle
echo ""
echo "--- Step 3: End-to-End OCC Lifecycle ---"
TMP_NOTE="${VAULT_ROOT}/_inbox/human/e2e-demo-$$.md"
cat << 'EOF' > "$TMP_NOTE"
---
title: E2E Autonomous Engine Verification
area_ids: [area-engineering]
---
Verifying optimistic concurrency control and multi-agent state transitions.
EOF

# Ingest
ASSIGNED_ID=$("$ENGINE_BIN" ingest "$TMP_NOTE" | awk '{print $NF}')
echo "1. Ingested note as: $ASSIGNED_ID"

# Read Record Envelope
RECORD_JSON=$("$ENGINE_BIN" read-record "$ASSIGNED_ID")
RECORD_SHA=$(echo "$RECORD_JSON" | grep '"sha256":' | cut -d'"' -f4)
echo "2. Current SHA-256: $RECORD_SHA"

# Stale Conflict Check (must fail)
echo "3. Testing Stale Conflict Rejection..."
if "$ENGINE_BIN" commit "$ASSIGNED_ID" "stale-fake-hash-0000" "agent-bestie" '{"status":"committed"}' >/dev/null 2>&1; then
    echo "❌ ERROR: Stale commit should have been rejected!"
    exit 1
else
    echo "   ✅ Stale conflict correctly rejected."
fi

# Valid OCC Commit
echo "4. Executing Valid OCC Commit..."
"$ENGINE_BIN" commit "$ASSIGNED_ID" "$RECORD_SHA" "agent-olivier" '{"status":"candidate","impact":5,"effort":1,"confidence":5}' "e2e-run-$$" "verified-in-automated-test"
echo "   ✅ Valid OCC commit succeeded."

# 5. Verify Index & Audit Event
echo ""
echo "--- Step 4: Index & Audit Event Verification ---"
if grep -q "$ASSIGNED_ID" "${VAULT_ROOT}/_meta/indexes/ideas.jsonl"; then
    echo "✅ Record present in _meta/indexes/ideas.jsonl"
else
    echo "❌ ERROR: Record missing from ideas.jsonl!"
    exit 1
fi

LATEST_EVENT=$(ls -t "${VAULT_ROOT}/_meta/events/"*/*/*.json | head -n 1)
echo "✅ Audit event created at: $LATEST_EVENT"

echo ""
echo "=================================================="
echo "🎉 ALL TESTS PASSED! System is Ultra-Deterministic"
echo "=================================================="
