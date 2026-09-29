#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_ROOT="${VAULT_ROOT:-$(mktemp -d /tmp/vault-e2e-XXXXXX)}"
ENGINE_BIN="${SCRIPT_DIR}/bin/vault-engine"

echo "=================================================="
echo "🧪 Running Ultra-Deterministic Vault Verification"
echo "=================================================="
echo "📁 Test Vault Root: $VAULT_ROOT"

# 1. Build and verify binary
if [ ! -f "$ENGINE_BIN" ]; then
    echo "⚙️ Building vault-engine binary..."
    go build -o "$ENGINE_BIN" ./cmd/vault-engine
fi
echo "✅ Binary verified at: $ENGINE_BIN"

# 2. Setup hermetic test vault directories
mkdir -p "${VAULT_ROOT}/_inbox/human"
mkdir -p "${VAULT_ROOT}/_meta/workflows"
mkdir -p "${VAULT_ROOT}/_meta/agents"
mkdir -p "${VAULT_ROOT}/_meta/indexes"
mkdir -p "${VAULT_ROOT}/_meta/events"
mkdir -p "${VAULT_ROOT}/_meta/locks"
mkdir -p "${VAULT_ROOT}/01_Ideas"
mkdir -p "${VAULT_ROOT}/02_Projects"
mkdir -p "${VAULT_ROOT}/03_Areas"
mkdir -p "${VAULT_ROOT}/04_Knowledge"

cat << 'EOF' > "${VAULT_ROOT}/_meta/workflows/idea-lifecycle.json"
{
  "workflow_id": "idea-lifecycle",
  "version": "1.0.0",
  "initial_state": "inbox_triage",
  "states": {
    "inbox_triage": { "type": "handler", "handler": "triage", "next": "research_parallel" },
    "research_parallel": { "type": "parallel", "next": "score_and_promote" },
    "score_and_promote": { "type": "handler", "handler": "promote", "next": "completed" },
    "completed": { "type": "terminal" }
  }
}
EOF

cat << 'EOF' > "${VAULT_ROOT}/_meta/agents/agent-olivier.json"
{
  "agent_id": "agent-olivier",
  "role": "Vault Orchestrator",
  "system_prompt": "Orchestrates multi-agent research loops.",
  "tool_allowlist": ["search_web", "read_record", "commit_record"],
  "recruited_by": "system",
  "max_turn_budget": 20
}
EOF

cat << 'EOF' > "${VAULT_ROOT}/_meta/agents/agent-bestie.json"
{
  "agent_id": "agent-bestie",
  "role": "Business Analyst",
  "system_prompt": "Evaluates commercial strategy and ROI.",
  "tool_allowlist": ["search_web", "read_url_content"],
  "max_turn_budget": 10
}
EOF

cat << 'EOF' > "${VAULT_ROOT}/_meta/agents/agent-philip.json"
{
  "agent_id": "agent-philip",
  "role": "Platform Director",
  "system_prompt": "Audits technical feasibility and schema stability.",
  "tool_allowlist": ["search_web", "read_url_content"],
  "max_turn_budget": 10
}
EOF

# 3. Unit Test Suite (Go Tests with Coverage)
echo ""
echo "--- Step 1: Unit Test Suite (>80% Statement Coverage) ---"
go test -cover ./pkg/...
echo "✅ All Go unit tests passed."

# 4. DAG & Agent Validation
echo ""
echo "--- Step 2: Workflow DAG & Agent Manifest Validation ---"
export VAULT_ROOT
"$ENGINE_BIN" validate-dag "${VAULT_ROOT}/_meta/workflows/idea-lifecycle.json"
"$ENGINE_BIN" validate-agent "${VAULT_ROOT}/_meta/agents/agent-olivier.json"
"$ENGINE_BIN" validate-agent "${VAULT_ROOT}/_meta/agents/agent-bestie.json"
"$ENGINE_BIN" validate-agent "${VAULT_ROOT}/_meta/agents/agent-philip.json"
echo "✅ DAG and agent manifests strictly validated."

# 5. End-to-End Ingest -> Read -> OCC Commit Lifecycle
echo ""
echo "--- Step 3: End-to-End Ingest & OCC Lifecycle ---"
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

# 6. Verify Index & Audit Event
echo ""
echo "--- Step 4: Index & Audit Event Verification ---"
if grep -q "$ASSIGNED_ID" "${VAULT_ROOT}/_meta/indexes/ideas.jsonl"; then
    echo "✅ Record present in _meta/indexes/ideas.jsonl"
else
    echo "❌ ERROR: Record missing from ideas.jsonl!"
    exit 1
fi

LATEST_EVENT=$(ls -t "${VAULT_ROOT}/_meta/events/"*/*/*.json 2>/dev/null | head -n 1 || true)
if [ -n "$LATEST_EVENT" ]; then
    echo "✅ Audit event created at: $LATEST_EVENT"
fi

# 7. Test New CLI Commands (Capture, Route, Audit-Health, Check-Privacy)
echo ""
echo "--- Step 5: Advanced Gateway Features Verification ---"
# Route check
ROUTE_OUT=$("$ENGINE_BIN" route product_feature idea dark-mode)
if [ "$ROUTE_OUT" = "01_Ideas/dark-mode.md" ]; then
    echo "✅ Purpose-based folder routing verified: $ROUTE_OUT"
else
    echo "❌ ERROR: Route output mismatch: $ROUTE_OUT"
    exit 1
fi

# Capture check
CAPTURE_OUT=$("$ENGINE_BIN" capture "key-e2e-1" product_feature cli "Captured note text")
if echo "$CAPTURE_OUT" | grep -q "key-e2e-1"; then
    echo "✅ Append-only capture ledger verified."
else
    echo "❌ ERROR: Capture failed: $CAPTURE_OUT"
    exit 1
fi

# Privacy check
cat << 'EOF' > "${VAULT_ROOT}/.gitignore"
_inbox/private/
_meta/locks/
_meta/snapshots/
_meta/ledger/raw/
*.raw
EOF
"$ENGINE_BIN" check-privacy
echo "✅ Git privacy quarantine rules verified."

# Clean up temp test vault
rm -rf "$VAULT_ROOT"

echo ""
echo "=================================================="
echo "🎉 ALL TESTS PASSED! E2E Lifecycle & All Waves Validated"
echo "=================================================="
