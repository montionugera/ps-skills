#!/usr/bin/env bash
# Builds a throwaway shared copy ("hub") and two test places from a small
# synthetic fixture. It never reads or writes a real vault.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REAL_VAULT="$HOME/workspace/agentic-vault"
# VAULT_HARNESS_EXTRA_GUARDED_DIR names one additional guarded directory (for
# tests); it never replaces the real-vault guard.
EXTRA_GUARDED_DIR="${VAULT_HARNESS_EXTRA_GUARDED_DIR:-}"

usage() {
    echo "usage: sync-harness.sh setup <empty-dir> <engine-binary> | run" >&2
    exit 2
}

# Runs git in <dir> for the fixture. Like a place (gitLocationVars in
# pkg/vaultsync/repo.go), it does not pass on the variables with which a
# caller points git at another repository, and git may not look above <dir>.
fixture_git() { # <dir> <git arguments...>
    local dir=$1
    shift
    env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_COMMON_DIR \
        -u GIT_OBJECT_DIRECTORY -u GIT_ALTERNATE_OBJECT_DIRECTORIES -u GIT_QUARANTINE_PATH \
        -u GIT_NAMESPACE -u GIT_PREFIX -u GIT_IMPLICIT_WORK_TREE -u GIT_SHALLOW_FILE \
        -u GIT_GRAFT_FILE -u GIT_REPLACE_REF_BASE \
        GIT_CEILING_DIRECTORIES="$(dirname "$dir")" \
        git -C "$dir" -c user.name=fixture -c user.email=fixture@test.invalid -c commit.gpgsign=false "$@"
}

write_idea() { # <dir> <number> <title>
    cat > "$1/01_Ideas/IDEA-2026-00000$2--fixture-idea-$2.md" <<EOF
---
schema: idea/v1
id: IDEA-2026-00000$2
kind: idea
title: $3
status: triage
impact: 3
effort: 3
created: "2026-10-10"
updated: "2026-10-10T00:00:00Z"
tags: [idea]
---
Synthetic note number $2 for the sync tests. It holds no real content.
EOF
}

write_fixture() { # <dir>
    local d=$1
    mkdir -p "$d/01_Ideas" "$d/02_Projects" "$d/03_Areas" "$d/04_Knowledge" "$d/_archive/ideas" \
        "$d/_inbox/human" "$d/_inbox/agent/agent-olivier" "$d/_inbox/agent/agent-bestie" \
        "$d/_meta/events" "$d/_meta/ledger" "$d/_meta/agents"
    for keep in 02_Projects 03_Areas 04_Knowledge _archive/ideas _inbox/human \
        _inbox/agent/agent-olivier _inbox/agent/agent-bestie _meta/events _meta/ledger; do
        : > "$d/$keep/.gitkeep"
    done
    cat > "$d/.gitignore" <<'EOF'
.DS_Store
.obsidian/
_tmp/
_quarantine/
graft/
_meta/bin/
_meta/locks/
_meta/guards/
_meta/logs/
_meta/indexes/
_meta/instances/
_meta/snapshots/
_meta/ledger/raw/
_inbox/private/
*.raw
*.tmp
*.tmp.*
EOF
    cat > "$d/_meta/agents/agent-olivier.json" <<'EOF'
{
  "agent_id": "agent-olivier",
  "role": "Vault Orchestrator",
  "system_prompt": "Synthetic fixture agent.",
  "tool_allowlist": ["read_record", "commit_record"],
  "recruited_by": "system",
  "max_turn_budget": 20
}
EOF
    write_idea "$d" 1 "Fixture idea one"
    write_idea "$d" 2 "Fixture idea two"
    { printf '# Agent rules for this folder\n\n'; cat "$ENGINE_DIR/templates/vault-rules/AGENTS.section.md"; } > "$d/AGENTS.md"
    cp "$ENGINE_DIR/templates/vault-rules/CLAUDE.md" "$d/CLAUDE.md"
    cp "$ENGINE_DIR/templates/vault-rules/GEMINI.md" "$d/GEMINI.md"
}

make_place() { # <root> <place> <engine-binary>
    git clone --quiet "$1/hub.git" "$1/$2"
    mkdir -p "$1/$2/_meta/bin"
    cp "$3" "$1/$2/_meta/bin/vault-engine"
    printf '{"place":"%s","poll_interval_ms":%s,"inbox_quiet_ms":%s}\n' \
        "$2" "${POLL_MS:-3000}" "${QUIET_MS:-3000}" > "$1/$2/_meta/bin/sync.json"
}

# True when <physical-dir> equals or lies under <guarded>, by its given name or
# its symlink-resolved name (only the name is resolved, nothing is read).
under_guarded() { # <physical-dir> <guarded>
    local phys
    phys="$(cd "$2" 2>/dev/null && pwd -P)" || phys=""
    case "$1/" in "$2"/*) return 0 ;; esac
    [ -z "$phys" ] || case "$1/" in "$phys"/*) return 0 ;; esac
    return 1
}

in_real_vault() { # <physical-dir>
    under_guarded "$1" "$REAL_VAULT" || { [ -n "$EXTRA_GUARDED_DIR" ] && under_guarded "$1" "$EXTRA_GUARDED_DIR"; }
}

setup() { # <empty-dir> <engine-binary>
    local root engine
    root="$(cd "$1" 2>/dev/null && pwd -P)" || { echo "sync-harness: target folder $1 does not exist" >&2; exit 1; }
    engine="$2"
    ! in_real_vault "$root" || { echo "sync-harness: refusing to work inside the real vault" >&2; exit 1; }
    [ -z "$(ls -A "$root")" ] || { echo "sync-harness: $root is not empty" >&2; exit 1; }
    for v in POLL_MS QUIET_MS; do
        case "${!v:-3000}" in
            ''|*[!0-9]*|0|0[0-9]*) echo "sync-harness: $v must be a positive whole number, got '${!v}'" >&2; exit 2 ;;
        esac
    done
    [ -x "$engine" ] || { echo "sync-harness: engine binary $engine not found" >&2; exit 1; }

    sh "$ENGINE_DIR/hub/create-hub.sh" "$root/hub.git" "$engine" >/dev/null
    mkdir "$root/seed"
    write_fixture "$root/seed"
    fixture_git "$root/seed" init --quiet --initial-branch=main
    fixture_git "$root/seed" add -A
    fixture_git "$root/seed" commit --quiet -m "fixture: synthetic seed"
    env VAULT_HUB_PLACE=seed git -C "$root/seed" push --quiet "$root/hub.git" HEAD:refs/heads/main
    make_place "$root" mac-test "$engine"
    make_place "$root" srv-test "$engine"
    echo "hub=$root/hub.git"
    echo "mac-test=$root/mac-test"
    echo "srv-test=$root/srv-test"
}

run() {
    cd "$ENGINE_DIR"
    mkdir -p bin
    go build -o bin/vault-engine ./cmd/vault-engine
    echo "--- all packages, short rounds ---"
    go test ./... -count=1 2>&1 | tail -n 12
    echo "--- sync scenarios, full rounds (100 / 100 / 100 / 1000 / 50) ---"
    VAULT_SYNC_ROUNDS=full go test ./pkg/vaultsync/ -run 'TestScenario' -count=1 -timeout 90m -v 2>&1 \
        | grep -E '^(--- |ok|FAIL|LATENCY|KILLS|panic)'
}

case "${1:-}" in
    setup) [ $# -eq 3 ] || usage; setup "$2" "$3" ;;
    run) [ $# -eq 1 ] || usage; run ;;
    *) usage ;;
esac
