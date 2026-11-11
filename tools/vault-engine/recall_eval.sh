#!/usr/bin/env bash
# Scores retrieval against a private prompt set. Each line: {"prompt": "...", "expected_id": "..."}
# An empty expected_id marks a prompt that must inject nothing (precision check).
# Usage: recall_eval.sh <set.jsonl> [min_hits]   (VAULT_ENGINE overrides the binary)
set -euo pipefail
SET="${1:?usage: recall_eval.sh <set.jsonl> [min_hits]}"
MIN="${2:-16}"
ENGINE="${VAULT_ENGINE:-vault-engine}"
hits=0
total=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  prompt=$(printf '%s' "$line" | python3 -c 'import json,sys; print(json.load(sys.stdin)["prompt"])')
  want=$(printf '%s' "$line" | python3 -c 'import json,sys; print(json.load(sys.stdin)["expected_id"])')
  total=$((total + 1))
  out=$("$ENGINE" context --query "$prompt" --limit 2)
  # An empty expected_id means the prompt must inject nothing.
  if { [ -z "$want" ] && [ -z "$out" ]; } || { [ -n "$want" ] && printf '%s' "$out" | grep -qF -- "- $want |"; }; then
    hits=$((hits + 1))
  else
    echo "MISS: $want <- $prompt"
  fi
done < "$SET"
echo "recall: $hits/$total (min $MIN)"
[ "$hits" -ge "$MIN" ]
