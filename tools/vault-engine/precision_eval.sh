#!/usr/bin/env bash
# Scores injection precision against a private labelled set. Each line: {"prompt": "...", "relevant_ids": ["..."]}
# An injected note counts as relevant only when its id is in relevant_ids, so a note nobody labelled is off topic.
# Usage: precision_eval.sh <set.jsonl> [min_percent]   (VAULT_ENGINE overrides the binary)
set -euo pipefail
SET="${1:?usage: precision_eval.sh <set.jsonl> [min_percent]}"
exec python3 - "$SET" "${2:-80}" "${VAULT_ENGINE:-vault-engine}" <<'PY'
import json, subprocess, sys

path, minimum, engine = sys.argv[1], float(sys.argv[2]), sys.argv[3]
injected = relevant = 0
for line in open(path):
    if not line.strip():
        continue
    row = json.loads(line)
    # The hook sends the first 2,000 characters and injects at most 2 notes.
    out = subprocess.run([engine, "context", "--query", row["prompt"][:2000], "--limit", "2"],
                         capture_output=True, text=True, check=True).stdout
    ids = [l[2:].split(" | ", 1)[0] for l in out.splitlines() if l.startswith("- ") and " | " in l]
    injected += len(ids)
    relevant += sum(i in row["relevant_ids"] for i in ids)
pct = 100 * relevant / injected if injected else 0
print(f"precision: {relevant}/{injected} = {pct:.1f}% (min {minimum:g}%)")
sys.exit(0 if injected and pct >= minimum else 1)
PY
