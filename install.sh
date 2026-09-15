#!/usr/bin/env bash
# install.sh — install ps-* skills for Claude and Codex.
#
# Usage:
#   ./install.sh                 # symlink skills (edits in the repo take effect live)
#   ./install.sh --copy          # copy instead of symlink (snapshot, no live link)
#   ./install.sh --force         # replace foreign symlinks or existing destinations
#   ./install.sh --copy --force  # refresh existing copied destinations
#   CLAUDE_HOME=/path AGENTS_HOME=/path ./install.sh
#
# Existing files, directories, and foreign symlinks are preserved unless --force is set.
#
# What it does:
#   skills/ps-*            -> $CLAUDE_HOME/skills/ps-*
#   skills/ps-*            -> $AGENTS_HOME/skills/ps-*
#   skills/*/hooks/*       -> $CLAUDE_HOME/hooks/*   (hook scripts; register them in settings.json)
#   bin/ps-skills-sync     -> $HOME/.local/bin/ps-skills-sync
#   engine/ps-release-workflow -> $CLAUDE_HOME/ps-release-workflow
#     (the ps-release-workflow-* skills call scripts in that engine dir; without
#      it they install but fail at runtime.)
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
AGENTS_HOME="${AGENTS_HOME:-$HOME/.agents}"
BIN_HOME="${BIN_HOME:-$HOME/.local/bin}"
MODE="symlink"
FORCE="false"

usage() {
  sed -n '2,/^set -euo pipefail$/s/^# \{0,1\}//p' "$0"
}

while (($#)); do
  case "$1" in
    --copy) MODE="copy" ;;
    --force) FORCE="true" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

mkdir -p "$CLAUDE_HOME/skills" "$CLAUDE_HOME/hooks" "$AGENTS_HOME/skills" "$BIN_HOME"

replace_destination() {  # dest
  local dest="$1"
  case "$dest" in
    "$CLAUDE_HOME/skills/"*|"$AGENTS_HOME/skills/"*|"$CLAUDE_HOME/hooks/"*|"$CLAUDE_HOME/ps-release-workflow"|"$BIN_HOME/ps-skills-sync") ;;
    *) echo "refuse unsafe destination: $dest" >&2; return 1 ;;
  esac
  rm -rf -- "$dest"
}

link() {  # src dest
  local src="$1" dest="$2"
  if [[ -L "$dest" ]]; then
    if [[ "$dest" -ef "$src" ]]; then
      rm -f -- "$dest"
    elif [[ "$FORCE" == "true" ]]; then
      replace_destination "$dest"
    else
      echo "preserve (foreign symlink): $dest" >&2
      return
    fi
  elif [[ -e "$dest" ]]; then
    if [[ "$FORCE" == "true" ]]; then
      replace_destination "$dest"
    else
      echo "preserve (existing path): $dest" >&2
      return
    fi
  fi
  if [[ "$MODE" == "symlink" ]]; then ln -s "$src" "$dest"; else cp -R "$src" "$dest"; fi
  echo "$MODE: $dest"
}

for d in "$REPO"/skills/*/; do
  link "${d%/}" "$CLAUDE_HOME/skills/$(basename "$d")"
  link "${d%/}" "$AGENTS_HOME/skills/$(basename "$d")"
done
for h in "$REPO"/skills/*/hooks/*; do
  if [[ -f "$h" ]]; then link "$h" "$CLAUDE_HOME/hooks/$(basename "$h")"; fi
done
link "$REPO/engine/ps-release-workflow" "$CLAUDE_HOME/ps-release-workflow"
link "$REPO/bin/ps-skills-sync" "$BIN_HOME/ps-skills-sync"

echo
echo "Installed into $CLAUDE_HOME and $AGENTS_HOME. Restart Claude Code and Codex to pick up new skills."
echo "ps-commu-explain is self-contained; ps-release-workflow-* use $CLAUDE_HOME/ps-release-workflow."
