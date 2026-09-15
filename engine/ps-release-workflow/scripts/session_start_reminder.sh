#!/usr/bin/env bash
# SessionStart hook: print a brief ps-release-workflow status if cwd is inside
# an opted-in repo. Silent otherwise. Spawns python3 at most ONCE (status.py
# --brief does all the work); must always exit 0 and never break a session.

# Cheap bash fast-exit: walk up to find .release.json — no python spawn when absent.
dir="$PWD"
while [ "$dir" != "/" ]; do
  if [ -f "$dir/.release.json" ]; then
    REPO_ROOT="$dir"
    break
  fi
  dir="$(dirname "$dir")"
done

if [ -z "${REPO_ROOT:-}" ]; then
  exit 0  # not in a workflow repo
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Single python spawn. status.py itself always exits 0 and degrades gracefully;
# the guards here cover a missing/broken python3 as well.
python3 "$SCRIPT_DIR/status.py" --repo "$REPO_ROOT" --brief 2>/dev/null || true
exit 0
