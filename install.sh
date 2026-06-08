#!/usr/bin/env bash
# install.sh — install the ps-* skills (and the release-workflow engine) into ~/.claude.
#
# Usage:
#   ./install.sh                 # symlink skills (edits in the repo take effect live)
#   ./install.sh --copy          # copy instead of symlink (snapshot, no live link)
#   CLAUDE_HOME=/path ./install.sh   # install into a non-default Claude home
#
# What it does:
#   skills/ps-*            -> $CLAUDE_HOME/skills/ps-*
#   engine/ps-release-workflow -> $CLAUDE_HOME/ps-release-workflow
#     (the 9 ps-release-workflow-* skills call scripts in that engine dir; without
#      it they install but fail at runtime.)
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
MODE="symlink"
[[ "${1:-}" == "--copy" ]] && MODE="copy"
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { grep '^#' "$0" | cut -c3-; exit 0; }

mkdir -p "$CLAUDE_HOME/skills"

link() {  # src dest
  local src="$1" dest="$2"
  if [[ -e "$dest" && ! -L "$dest" ]]; then
    echo "skip (exists, not a symlink): $dest" >&2; return
  fi
  rm -f "$dest"
  if [[ "$MODE" == "symlink" ]]; then ln -s "$src" "$dest"; else cp -R "$src" "$dest"; fi
  echo "$MODE: $dest"
}

for d in "$REPO"/skills/*/; do
  link "${d%/}" "$CLAUDE_HOME/skills/$(basename "$d")"
done
link "$REPO/engine/ps-release-workflow" "$CLAUDE_HOME/ps-release-workflow"

echo
echo "Installed into $CLAUDE_HOME. Restart your Claude Code session to pick up new skills."
echo "ps-commu-explain is self-contained; ps-release-workflow-* use $CLAUDE_HOME/ps-release-workflow."
