#!/usr/bin/env bash
# SessionStart hook: print a reminder of the current ps-release-workflow state
# if cwd is inside an opted-in repo. Silent otherwise.

set -e

# Walk up to find .release.json.
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

REL_JSON="$REPO_ROOT/.release.json"
CLAIMS="$REPO_ROOT/.claude/state/claims.json"

VERSION=$(python3 -c "import json,sys; print(json.load(open('$REL_JSON'))['version'])" 2>/dev/null || echo "?")
IN_PROGRESS=$(python3 -c "import json,sys; print(json.load(open('$REL_JSON')).get('in_progress', False))" 2>/dev/null || echo "False")

echo "🚨 ps-release-workflow active in this repo ($REPO_ROOT)"
if [ "$IN_PROGRESS" = "True" ]; then
  echo "   Active release: $VERSION (in progress)"
  if [ -f "$CLAIMS" ]; then
    SESSION="${CLAUDE_SESSION_ID:-}"
    OWNED_FEATURE=$(python3 -c "
import json, os
claims = json.load(open('$CLAIMS'))
me = os.environ.get('CLAUDE_SESSION_ID','')
mine = [f for f, c in claims.items() if c.get('owner') == me]
print(','.join(mine) if mine else 'none')
" 2>/dev/null)
    if [ -n "$OWNED_FEATURE" ] && [ "$OWNED_FEATURE" != "none" ]; then
      echo "   Your active claim(s): $OWNED_FEATURE"
    else
      echo "   No claim — run /ps-release-workflow:claim --next"
    fi
  fi
else
  echo "   No release in progress — run /ps-release-workflow:new-release to start"
fi
