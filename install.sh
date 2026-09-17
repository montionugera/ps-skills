#!/usr/bin/env bash
# install.sh — install ps-* skills for Claude and Codex.
#
# Usage:
#   ./install.sh                 # symlink skills (edits in the repo take effect live)
#   ./install.sh --copy          # copy instead of symlink (snapshot, no live link)
#   ./install.sh --force         # replace foreign symlinks or existing destinations
#   ./install.sh --copy --force  # refresh existing copied destinations
#   ./install.sh --parity        # reconcile parity from Claude into Gemini
#   CLAUDE_HOME=/path AGENTS_HOME=/path GEMINI_HOME=/path ./install.sh
#
# Existing files, directories, and foreign symlinks are preserved unless --force is set.
#
# What it does:
#   skills/ps-*            -> $CLAUDE_HOME/skills/ps-*
#   skills/ps-*            -> $AGENTS_HOME/skills/ps-*
#   skills/ps-*            -> $GEMINI_HOME/skills/ps-*
#   skills/*/hooks/*       -> $CLAUDE_HOME/hooks/*   (hook scripts; register them in settings.json)
#   bin/ps-skills-sync     -> $HOME/.local/bin/ps-skills-sync
#   engine/ps-release-workflow -> $CLAUDE_HOME/ps-release-workflow
#     (the ps-release-workflow-* skills call scripts in that engine dir; without
#      it they install but fail at runtime.)
#   --parity:
#     Reconciles $GEMINI_HOME/skills to mirror $CLAUDE_HOME/skills via symlinks,
#     replaces diverged directories (e.g. test-driven-development) with symlinks,
#     and archives unparsed junk folders (superpowers/, nested skills/).
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
AGENTS_HOME="${AGENTS_HOME:-$HOME/.agents}"
GEMINI_HOME="${GEMINI_HOME:-$HOME/.gemini/config}"
CURSOR_HOME="${CURSOR_HOME:-$HOME/.cursor}"
BIN_HOME="${BIN_HOME:-$HOME/.local/bin}"
MODE="symlink"
FORCE="false"
PARITY="false"
NON_INTERACTIVE="false"

usage() {
  sed -n '2,/^set -euo pipefail$/s/^# \{0,1\}//p' "$0"
}

while (($#)); do
  case "$1" in
    --copy) MODE="copy" ;;
    --force) FORCE="true" ;;
    --parity) PARITY="true" ;;
    -y|--yes|--non-interactive) NON_INTERACTIVE="true" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

mkdir -p "$CLAUDE_HOME/skills" "$CLAUDE_HOME/hooks" "$AGENTS_HOME/skills" "$GEMINI_HOME/skills" "$CURSOR_HOME/skills" "$BIN_HOME"

replace_destination() {  # dest
  local dest="$1"
  case "$dest" in
    "$CLAUDE_HOME/skills/"*|"$AGENTS_HOME/skills/"*|"$GEMINI_HOME/skills/"*|"$CURSOR_HOME/skills/"*|"$CLAUDE_HOME/hooks/"*|"$CLAUDE_HOME/ps-release-workflow"|"$BIN_HOME/ps-skills-sync"|"$BIN_HOME/dispatch-agy-worker"|"$BIN_HOME/dispatch-codex-worker"|"$BIN_HOME/dispatch-cursor-worker"|"$BIN_HOME/dispatch-worker"|"$BIN_HOME/ps-plugin-bridge") ;;
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
  link "${d%/}" "$GEMINI_HOME/skills/$(basename "$d")"
  link "${d%/}" "$CURSOR_HOME/skills/$(basename "$d")"
done
for h in "$REPO"/skills/*/hooks/*; do
  if [[ -f "$h" ]]; then link "$h" "$CLAUDE_HOME/hooks/$(basename "$h")"; fi
done
link "$REPO/engine/ps-release-workflow" "$CLAUDE_HOME/ps-release-workflow"
link "$REPO/bin/ps-skills-sync" "$BIN_HOME/ps-skills-sync"
link "$REPO/bin/dispatch-agy-worker" "$BIN_HOME/dispatch-agy-worker"
link "$REPO/bin/dispatch-codex-worker" "$BIN_HOME/dispatch-codex-worker"
link "$REPO/bin/dispatch-cursor-worker" "$BIN_HOME/dispatch-cursor-worker"
link "$REPO/bin/dispatch-worker" "$BIN_HOME/dispatch-worker"
link "$REPO/bin/ps-plugin-bridge" "$BIN_HOME/ps-plugin-bridge"

reconcile_parity() {
  echo
  echo "Reconciling skills parity ($CLAUDE_HOME -> $GEMINI_HOME)..."
  local archive_date
  archive_date="$(date +%Y-%m-%d)"
  local gemini_archive="$GEMINI_HOME/skills-archive-$archive_date"

  # Archive known junk directories in GEMINI_HOME/skills
  for junk in "superpowers" "skills"; do
    if [[ -d "$GEMINI_HOME/skills/$junk" && ! -L "$GEMINI_HOME/skills/$junk" ]]; then
      mkdir -p "$gemini_archive"
      echo "archive junk: $GEMINI_HOME/skills/$junk -> $gemini_archive/$junk"
      mv "$GEMINI_HOME/skills/$junk" "$gemini_archive/"
    fi
  done

  # Reconcile diverged test-driven-development directory
  if [[ -d "$GEMINI_HOME/skills/test-driven-development" && ! -L "$GEMINI_HOME/skills/test-driven-development" ]]; then
    echo "reconcile diverged copy: $GEMINI_HOME/skills/test-driven-development -> $CLAUDE_HOME/skills/test-driven-development"
    rm -rf "$GEMINI_HOME/skills/test-driven-development"
    ln -s "$CLAUDE_HOME/skills/test-driven-development" "$GEMINI_HOME/skills/test-driven-development"
  fi

  # Symlink all canonical skills from CLAUDE_HOME/skills into GEMINI_HOME/skills
  for item in "$CLAUDE_HOME/skills"/*; do
    [[ -e "$item" || -L "$item" ]] || continue
    local name
    name="$(basename "$item")"
    case "$name" in
      .*|capture-inbox.md|synced|skills|superpowers|*.bak) continue ;;
    esac

    local dest="$GEMINI_HOME/skills/$name"
    if [[ -L "$dest" ]]; then
      # If link is broken, refresh it
      if [[ ! -e "$dest" ]]; then
        echo "refresh broken symlink: $dest -> $item"
        rm -f "$dest"
        ln -s "$item" "$dest"
      fi
    elif [[ -d "$dest" ]]; then
      if [[ "$FORCE" == "true" ]]; then
        echo "replace diverged directory (--force): $dest -> $item"
        rm -rf "$dest"
        ln -s "$item" "$dest"
      else
        echo "preserve (existing directory): $dest" >&2
      fi
    elif [[ ! -e "$dest" ]]; then
      ln -s "$item" "$dest"
      echo "symlink (parity): $dest -> $item"
    fi
  done
}

if [[ "$PARITY" == "true" ]]; then
  reconcile_parity
fi

configure_dispatch() {
  # If running non-interactively or stdin is not a terminal, skip prompt
  if [[ ! -t 0 || "$NON_INTERACTIVE" == "true" || "${CI:-false}" == "true" ]]; then
    return 0
  fi

  local config_dir="$HOME/.config/dispatch"
  local config_file="$config_dir/config.env"
  mkdir -p "$config_dir"

  echo
  echo "============================================================"
  echo " Multi-Agent Worker Setup (dispatch-worker)                "
  echo "============================================================"
  echo "Choose your default routing preference chain:"
  echo "  1) auto [Default] (Dynamic runway across flat subscriptions: agy > codex)"
  echo "  2) cursor:gemini-3.8-flash > agy > codex (Cursor Flash On-Demand first)"
  echo "  3) cursor:gemini-3.8-flash > codex:gpt-5.6-terra"
  echo "  4) agy > codex (Strict flat subscriptions only, zero on-demand)"
  echo "  5) Custom priority chain"
  echo "  6) Keep existing configuration / Skip"
  echo
  read -r -p "Enter selection [1-6] (default: 1): " choice
  choice="${choice:-1}"

  local pref=""
  local allow_on_demand="0"

  case "$choice" in
    1)
      pref="auto"
      ;;
    2)
      pref="cursor:gemini-3.8-flash > agy > codex"
      ;;
    3)
      pref="cursor:gemini-3.8-flash > codex:gpt-5.6-terra"
      ;;
    4)
      pref="agy > codex"
      ;;
    5)
      read -r -p "Enter custom chain (e.g. 'cursor:gemini-3.8-flash > codex:terra'): " custom_pref
      pref="${custom_pref:-auto}"
      ;;
    6)
      echo "Keeping existing dispatch configuration."
      return 0
      ;;
    *)
      pref="auto"
      ;;
  esac

  if [[ "$pref" == *"cursor"* ]]; then
    echo
    read -r -p "Allow Cursor on-demand metered billing by default? [y/N]: " od_resp
    case "${od_resp:-n}" in
      [yY]|[yY][eE][sS]) allow_on_demand="1" ;;
      *) allow_on_demand="0" ;;
    esac
  fi

  cat > "$config_file" <<EOF
# Generated by ps-skills install.sh on $(date '+%Y-%m-%d %H:%M:%S')
DISPATCH_ROUTING_PREFERENCE="$pref"
DISPATCH_ALLOW_ON_DEMAND="$allow_on_demand"
EOF

  echo "Saved dispatch preferences to $config_file"
  echo "  DISPATCH_ROUTING_PREFERENCE=\"$pref\""
  echo "  DISPATCH_ALLOW_ON_DEMAND=\"$allow_on_demand\""
}

configure_dispatch

echo
echo "Installed into $CLAUDE_HOME, $AGENTS_HOME, $GEMINI_HOME, and $CURSOR_HOME. Restart Claude Code, Codex, Cursor, and Antigravity to pick up new skills."
echo "ps-commu-explain is self-contained; ps-release-workflow-* use $CLAUDE_HOME/ps-release-workflow."


