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
link "$REPO/bin/mesh" "$BIN_HOME/mesh"
link "$REPO/bin/mesh-run" "$BIN_HOME/mesh-run"
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
  local config_dir="$HOME/.config/dispatch"
  local config_file="$config_dir/config.env"
  mkdir -p "$config_dir"

  # If running non-interactively or stdin is not a terminal, write safe default if missing and skip prompt
  if [[ ! -t 0 || "$NON_INTERACTIVE" == "true" || "${CI:-false}" == "true" ]]; then
    if [[ ! -f "$config_file" ]]; then
      cat > "$config_file" <<EOF
# Generated by ps-skills install.sh on $(date '+%Y-%m-%d %H:%M:%S')
AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_MODE="subscription_quota_remaining"
AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_ROUTING_PREFERENCE="auto"
AI_AGENT_AUTO_DISPATCH_TIMEOUT="900"

# Backward compatibility aliases
DISPATCH_MODE="subscription_quota_remaining"
DISPATCH_ROUTING_PREFERENCE="auto"
DISPATCH_ALLOW_ON_DEMAND="0"
DISPATCH_TIMEOUT="900"
EOF
    fi
    return 0
  fi

  echo
  echo "============================================================"
  echo " Multi-Agent Environment Discovery                          "
  echo "============================================================"

  # Auto-detect available CLI agents and models via python helper
  local discovery_json
  discovery_json=$(python3 - <<'PY'
import json, os, shutil, subprocess

data = {"agy": None, "codex": None, "cursor": None}

if shutil.which("agy"):
    try:
        res = subprocess.run(["agy", "models"], capture_output=True, text=True, timeout=3)
        models = [line.split()[0] for line in res.stdout.splitlines() if line.strip() and not line.startswith("⠋") and not line.startswith("Fetching")]
        data["agy"] = models[:4] if models else ["gemini-3.8-flash-high", "gemini-3.1-pro-high"]
    except Exception:
        data["agy"] = ["gemini-3.8-flash-high", "gemini-3.1-pro-high"]

if shutil.which("codex"):
    data["codex"] = ["gpt-5.6-terra"]

cursor_bin = shutil.which("cursor-agent") or os.path.expanduser("~/.local/bin/cursor-agent")
if os.path.exists(cursor_bin):
    try:
        res = subprocess.run([cursor_bin, "--list-models"], capture_output=True, text=True, timeout=3)
        out = res.stdout.strip()
        if "No models" not in out and out:
            data["cursor"] = [line.strip() for line in out.splitlines() if line.strip()][:4]
        else:
            data["cursor"] = ["(installed; login via cursor-agent login)"]
    except Exception:
        data["cursor"] = ["(installed; login via cursor-agent login)"]

print(json.dumps(data))
PY
)

  local agy_model=""
  local codex_model="gpt-5.6-terra"
  local cursor_info=""

  if [[ $(echo "$discovery_json" | python3 -c 'import sys, json; print(bool(json.load(sys.stdin).get("agy")))') == "True" ]]; then
    agy_model=$(echo "$discovery_json" | python3 -c 'import sys, json; print(json.load(sys.stdin)["agy"][0])')
    echo "  ✔ Antigravity CLI (agy): Available (detected model: $agy_model)"
  else
    echo "  ✖ Antigravity CLI (agy): Not found in PATH"
  fi

  if [[ $(echo "$discovery_json" | python3 -c 'import sys, json; print(bool(json.load(sys.stdin).get("codex")))') == "True" ]]; then
    echo "  ✔ OpenAI Codex (codex):  Available (detected model: $codex_model)"
  else
    echo "  ✖ OpenAI Codex (codex):  Not found in PATH"
  fi

  if [[ $(echo "$discovery_json" | python3 -c 'import sys, json; print(bool(json.load(sys.stdin).get("cursor")))') == "True" ]]; then
    cursor_info=$(echo "$discovery_json" | python3 -c 'import sys, json; print(json.load(sys.stdin)["cursor"][0])')
    echo "  ✔ Cursor CLI (cursor):   Available ($cursor_info)"
  else
    echo "  ✖ Cursor CLI (cursor):   Not found in PATH"
  fi

  echo "============================================================"
  echo "Configure your Multi-Agent Dispatch preferences:"
  echo "  1) Step-by-Step Setup Wizard (Mode -> Tool 1 -> Model -> Tool 2 -> Model ... -> Done) [Recommended]"
  if [[ -n "$agy_model" ]]; then
    echo "  2) Quick Preset: Flat Subscriptions (agy:$agy_model > codex:$codex_model)"
  else
    echo "  2) Quick Preset: Flat Subscriptions (agy > codex)"
  fi
  echo "  3) Dynamic Runway Auto Mode (balanced across agy and codex)"
  echo "  4) Enter Custom Priority String directly"
  echo "  5) Keep existing configuration / Skip"
  echo
  read -r -p "Enter selection [1-5] (default: 1): " choice
  choice="${choice:-1}"

  local pref=""
  local allow_on_demand="0"
  local mode_str="subscription_quota_remaining"

  case "$choice" in
    1)
      echo
      echo "--- [1/3] Billing & On-Demand Policy ---"
      echo "  1) Strict Subscriptions Only (Flat rate, \$0 extra billing) [Default]"
      echo "  2) Allow On-Demand Metered Billing (Enable Cursor Business pay-as-you-go)"
      read -r -p "Select billing mode [1-2] (default: 1): " b_choice
      if [[ "$b_choice" == "2" ]]; then
        mode_str="on_demand"
        allow_on_demand="1"
      else
        mode_str="subscription_quota_remaining"
        allow_on_demand="0"
      fi

      echo
      echo "--- [2/3] Primary Tool (#1 Preference) ---"
      echo "  1) Antigravity CLI (agy)"
      echo "  2) OpenAI Codex (codex)"
      echo "  3) Cursor CLI (cursor)"
      read -r -p "Select primary tool [1-3] (default: 1): " t1_choice
      t1_choice="${t1_choice:-1}"

      local tool1="agy"
      local default_m1="$agy_model"
      if [[ "$t1_choice" == "2" ]]; then
        tool1="codex"
        default_m1="$codex_model"
      elif [[ "$t1_choice" == "3" ]]; then
        tool1="cursor"
        default_m1="gemini-3.8-flash"
      fi

      read -r -p "Enter model for $tool1 (default: $default_m1): " m1_choice
      m1_choice="${m1_choice:-$default_m1}"
      local seg1="${tool1}:${m1_choice}"

      echo
      echo "--- [3/3] Secondary Tool (#2 Fallback) ---"
      echo "When $tool1 is busy or low on quota, route to:"
      local t2_opts=()
      for t in "agy" "codex" "cursor"; do
        if [[ "$t" != "$tool1" ]]; then
          t2_opts+=("$t")
        fi
      done
      echo "  1) ${t2_opts[0]}"
      echo "  2) ${t2_opts[1]}"
      echo "  3) None (Stop here)"
      read -r -p "Select secondary tool [1-3] (default: 1): " t2_choice
      t2_choice="${t2_choice:-1}"

      if [[ "$t2_choice" == "1" || "$t2_choice" == "2" ]]; then
        local idx=$((t2_choice - 1))
        local tool2="${t2_opts[$idx]}"
        local default_m2=""
        if [[ "$tool2" == "agy" ]]; then default_m2="$agy_model"; fi
        if [[ "$tool2" == "codex" ]]; then default_m2="$codex_model"; fi
        if [[ "$tool2" == "cursor" ]]; then default_m2="gemini-3.8-flash"; fi

        read -r -p "Enter model for $tool2 (default: $default_m2): " m2_choice
        m2_choice="${m2_choice:-$default_m2}"
        local seg2="${tool2}:${m2_choice}"

        # Check for remaining tool 3
        local tool3=""
        for t in "agy" "codex" "cursor"; do
          if [[ "$t" != "$tool1" && "$t" != "$tool2" ]]; then
            tool3="$t"
          fi
        done
        echo
        read -r -p "Add $tool3 as final fallback? [Y/n]: " add_t3
        case "${add_t3:-y}" in
          [yY]|[yY][eE][sS])
            local default_m3=""
            if [[ "$tool3" == "agy" ]]; then default_m3="$agy_model"; fi
            if [[ "$tool3" == "codex" ]]; then default_m3="$codex_model"; fi
            if [[ "$tool3" == "cursor" ]]; then default_m3="gemini-3.8-flash"; fi
            read -r -p "Enter model for $tool3 (default: $default_m3): " m3_choice
            m3_choice="${m3_choice:-$default_m3}"
            pref="${seg1} > ${seg2} > ${tool3}:${m3_choice}"
            ;;
          *)
            pref="${seg1} > ${seg2}"
            ;;
        esac
      else
        pref="$seg1"
      fi
      ;;
    2)
      if [[ -n "$agy_model" ]]; then
        pref="agy:$agy_model > codex:$codex_model"
      else
        pref="agy > codex"
      fi
      ;;
    3)
      pref="auto"
      ;;
    4)
      read -r -p "Enter custom chain (e.g. 'cursor:gemini-3.8-flash > codex:terra'): " custom_pref
      pref="${custom_pref:-auto}"
      ;;
    5)
      echo "Keeping existing dispatch configuration."
      return 0
      ;;
    *)
      pref="auto"
      ;;
  esac

  cat > "$config_file" <<EOF
# Generated by ps-skills install.sh on $(date '+%Y-%m-%d %H:%M:%S')
AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_MODE="$mode_str"
AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_ROUTING_PREFERENCE="$pref"
AI_AGENT_AUTO_DISPATCH_TIMEOUT="900"

# Backward compatibility aliases
DISPATCH_MODE="$mode_str"
DISPATCH_ROUTING_PREFERENCE="$pref"
DISPATCH_ALLOW_ON_DEMAND="$allow_on_demand"
DISPATCH_TIMEOUT="900"
EOF

  echo "Saved dispatch preferences to $config_file"
  echo "  AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_MODE=\"$mode_str\""
  echo "  AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_ROUTING_PREFERENCE=\"$pref\""
  echo "  AI_AGENT_AUTO_DISPATCH_TIMEOUT=\"900\""
}

configure_dispatch

echo
echo "Installed into $CLAUDE_HOME, $AGENTS_HOME, $GEMINI_HOME, and $CURSOR_HOME. Restart Claude Code, Codex, Cursor, and Antigravity to pick up new skills."
echo "ps-commu-explain is self-contained; ps-release-workflow-* use $CLAUDE_HOME/ps-release-workflow."


