#!/usr/bin/env bash
# init.sh — create a ps-commu workspace (sweeps stale ones first).
# Usage: init.sh <slug> [--tier infographic|html|react] [--example]
#   slug       kebab-case topic id, e.g. jwt-refresh-rotation
#   --tier     infographic (default) | html | react
#              infographic  cream Markdown-driven explainer (cherry-markdown);
#                           author app/content.md
#              html         classic bespoke hand-written HTML; edit app/index.html
#              react        interactive React+TS tier
#   --example  scaffold the filled exemplar chain instead of empty skeletons:
#              assets/workspace/example/'s filled 00-brief.md/01-facts.md/
#              02-storyboard.md, plus the infographic tier's shipped
#              app/content.md (itself that same exemplar). Forces --tier
#              infographic (errors if combined with another --tier).
#              `init.sh --example <slug> && serve.sh <slug>` passes lint.sh
#              and verify.sh out of the box — no authoring required.
# Also scaffolds the authoring-chain docs (00-brief.md, 01-facts.md,
# 02-storyboard.md) from assets/workspace/ into the workspace root, sibling
# to app/ — never served. scripts/lint.sh gates them; serve.sh runs it
# before serving (see serve.sh --no-lint).
# Sweep rule (spec D5): delete workspaces >3 days old AND with no live
# marker-verified server. Port pick here is advisory; serve.sh binding is
# authoritative (spec D3).
set -euo pipefail
source "$(dirname "$0")/common.sh"

usage() { grep '^#' "$0" | cut -c3-; exit "${1:-0}"; }
slug="" tier="infographic" example=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tier) [[ $# -ge 2 ]] || { echo "--tier requires a value" >&2; exit 1; }
            tier="$2"; shift ;;
    --example) example=1 ;;
    -h|--help) usage ;;
    *) slug="$1" ;;
  esac
  shift
done
[[ "$slug" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || { echo "bad slug: '$slug' (use kebab-case)" >&2; exit 1; }
[[ "$tier" == "infographic" || "$tier" == "html" || "$tier" == "react" ]] || { echo "bad tier: '$tier'" >&2; exit 1; }
if [[ "$example" == 1 && "$tier" != "infographic" ]]; then
  echo "--example only supports the infographic tier (got --tier $tier)" >&2
  exit 1
fi

mkdir -p "$PS_COMMU_ROOT"
chmod 700 "$PS_COMMU_ROOT"   # spec D2: fact sheets may contain private code

# --- sweep ---
now="$(date +%s)"
for ws in "$PS_COMMU_ROOT"/*/; do
  [[ -d "$ws" ]] || continue
  s="$(basename "$ws")"
  pid="$(meta_get "$s" pid)"
  if [[ -n "$pid" ]] && pid_has_marker "$pid" "$s"; then
    continue                                   # live server — never sweep
  fi
  mtime="$(stat -f %m "$ws" 2>/dev/null || stat -c %Y "$ws" 2>/dev/null || echo "$now")"
  if (( now - mtime > 259200 )); then          # 3 days
    target="$(validate_workspace_path "$ws")" || continue
    rm -rf "$target" && echo "swept: $s"
  fi
done

# --- workspace ---
ws="$PS_COMMU_ROOT/$slug"
mkdir -p "$ws"

# --- scaffold app/ from the tier template ---
# Copy the template (incl. mermaid.min.js for the HTML tier) so the agent edits
# app/index.html IN PLACE. Writing app/index.html from scratch loses the diagram
# library and mermaid blocks render as raw text. Idempotent: never clobbers an
# existing app/index.html, so re-running init on a live slug is safe.
tpl="$(cd "$(dirname "$0")/.." && pwd)/assets/template-$tier"
if [[ -d "$tpl" && ! -e "$ws/app/index.html" ]]; then
  mkdir -p "$ws/app"
  cp -R "$tpl"/. "$ws/app"/
  echo "scaffolded app/ from template-$tier"
fi

# --- scaffold authoring-chain docs from assets/workspace/ (workspace root,
# sibling to app/ — never served, so the reader-facing tree stays free of
# authoring docs). Idempotent: never clobbers an existing file. --example
# sources the already-filled chain from assets/workspace/example/ instead of
# the empty skeleton, so it lints clean immediately (paired with the
# infographic tier's shipped app/content.md, which is that same exemplar). ---
wtpl="$(cd "$(dirname "$0")/.." && pwd)/assets/workspace"
[[ "$example" == 1 ]] && wtpl="$wtpl/example"
if [[ -d "$wtpl" ]]; then
  for f in "$wtpl"/*; do
    [[ -f "$f" ]] || continue   # skip subdirs (e.g. assets/workspace/example/)
    name="$(basename "$f")"
    [[ -e "$ws/$name" ]] || cp "$f" "$ws/$name"
  done
fi

# --- advisory free port ---
port=7700
while (( port <= 7799 )); do
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 || break
  port=$((port+1))
done
(( port <= 7799 )) || { echo "no free port in 7700-7799 — run clean.sh" >&2; exit 1; }

python3 - "$ws/meta.json" "$slug" "$tier" "$port" <<'PY'
import json, os, sys, tempfile
path, slug, tier, port = sys.argv[1:5]
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
with os.fdopen(fd, "w") as f:
    json.dump({"slug": slug, "tier": tier, "port": int(port), "pid": "", "started_at": ""}, f, indent=1)
os.replace(tmp, path)
PY
echo "workspace: $ws (tier=$tier, candidate port=$port)"
