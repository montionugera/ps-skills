#!/bin/sh
# Creates the shared copy: a bare repository that only moves forward on one
# main line and checks every incoming file.
# usage: create-hub.sh <hub-dir> <engine-binary> [limits.json]
set -eu
[ $# -ge 2 ] || { echo "usage: create-hub.sh <hub-dir> <engine-binary> [limits.json]" >&2; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
HUB=$1
ENGINE=$2
LIMITS=${3:-$HERE/vault-limits.json}

[ ! -e "$HUB" ] || { echo "create-hub: $HUB already exists" >&2; exit 1; }
MAX_INPUT=$(sed -n 's/.*"max_input_bytes"[^0-9]*\([0-9][0-9]*\).*/\1/p' "$LIMITS")
[ -n "$MAX_INPUT" ] || { echo "create-hub: max_input_bytes not found in $LIMITS" >&2; exit 1; }

git init --quiet --bare --initial-branch=main "$HUB"
git -C "$HUB" config receive.denyNonFastForwards true
git -C "$HUB" config receive.denyDeletes true
git -C "$HUB" config receive.maxInputSize "$MAX_INPUT"
git -C "$HUB" config receive.fsckObjects true
cp "$ENGINE" "$HUB/hooks/vault-engine"
cp "$LIMITS" "$HUB/hooks/vault-limits.json"
cp "$HERE/pre-receive" "$HUB/hooks/pre-receive"
chmod +x "$HUB/hooks/vault-engine" "$HUB/hooks/pre-receive"
echo "created hub at $HUB (upload cut-off $MAX_INPUT bytes)"
