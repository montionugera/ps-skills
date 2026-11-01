#!/usr/bin/env bash
set -euo pipefail

# herdr-handoff.sh — Create a new tab in Herdr (or open/launch in T3 Code),
# start a coding agent, and deliver a handoff prompt.
#
# Usage:
#   herdr-handoff.sh <handoff-markdown-path> [options]
#
# Options:
#   --kind <agent-kind>         Agent kind (agy, gemini, claude, codex, opencode, cursor, t3code)
#   --multiplexer <mux>         Multiplexer/launcher target: herdr, t3 (or t3code), auto (default: auto)
#   --label <tab-label>         Exact tab label (default: "<project> · <topic> #N")
#   --topic <text>              2-5 words on what the new session does next
#   --cwd <dir>                 Working directory (default: the doc's Worktree/Repo, else $PWD)
#   --prompt <text>             Custom prompt override
#   --mode <code|plan>          Handoff type. For --kind claude: code -> Sonnet,
#                               plan -> the default model (unset: default + warning)
#   --model <name>              Explicit Claude model; overrides --mode
#   --no-agent                  Only open a shell tab without starting an agent
#   --no-focus                  Never switch focus (default: follow only if you are on this tab)
#   --use-agent-manager         Try `herdr agent start` first (direct interactive launch is default)
#   --running <N>               How many background agents this session still has running.
#                               0 implies --close-source; N>0 keeps this tab open (the banner
#                               says so, and this tab relays their results). Omitted: the
#                               banner says the count is unknown.
#   --close-source              After the new agent is CONFIRMED running, close the
#                               tab this script was run from ($HERDR_TAB_ID) after a grace period.
#   --dry-run                   Validate arguments, formulate prompt, and print target plan without launching
#   --help, -h                  Show usage information

usage() {
  cat <<'EOF'
Usage: herdr-handoff.sh <handoff-markdown-path> [options]

Options:
  --kind <agent-kind>         Agent kind: agy, gemini, claude, codex, opencode, cursor, t3code
  --multiplexer <mux>         Multiplexer target: herdr, t3 (or t3code), auto (default: auto)
  --label <tab-label>         Exact tab label (default: "<project> · <topic> #N")
  --topic <text>              2-5 words on what the new session does next
  --cwd <dir>                 Working directory (default: the doc's Worktree/Repo, else $PWD)
  --prompt <text>             Custom prompt override
  --mode <code|plan>          Handoff type (claude: code->sonnet, plan->default; agy: code->gemini-4-argon-medium, plan->gemini-4-argon-high)
  --model <name>              Explicit model for claude or agy; overrides --mode
  --no-quota-switch           Do not auto-switch low-quota claude handoffs to agy yolo with argon
  --no-agent                  Only open a shell tab without starting an agent
  --no-focus                  Never switch focus (default: follow only if you are on this tab)
  --use-agent-manager         Try `herdr agent start` first
  --running <N>               Background agents this session still has running (0 = close this
                              tab after the handoff; N>0 = keep it open and relay their results)
  --close-source              Close source Herdr tab ($HERDR_TAB_ID) after confirming agent alive
  --yolo / --no-yolo          Enable/disable permission-skipping flag (default: --yolo)
  --dry-run                   Print resolved multiplexer, agent kind, and prompt file without launching
  --help, -h                  Show this help message
EOF
}

HANDOFF_PATH=""
# Auto-detect current calling agent by environment, or fall back to sensible default:
DETECTED_KIND="opencode"
if [[ -n "${T3CODE_PROJECT_ID:-}" || "${TERM_PROGRAM:-}" == "t3code" ]]; then
  DETECTED_KIND="t3code"
elif [[ -n "${ANTIGRAVITY_AGENT:-}" || -n "${ANTIGRAVITY_APP_DATA_DIR:-}" || -n "${ANTIGRAVITY_AGENTAPI_EXE:-}" || -n "${GEMINI_AI_STUDIO_API_KEY:-}" ]]; then
  DETECTED_KIND="agy"
elif [[ -n "${CODEX_HOME:-}" || -n "${CODEX_CLI_PATH:-}" || -n "${CODEX_SANDBOX:-}" ]]; then
  DETECTED_KIND="codex"
elif [[ -n "${CLAUDE_CODE_ENTRYPOINT:-}" || -n "${CLAUDE_CODE_MAX_RETRIES:-}" || -n "${CLAUDE_SESSION_ID:-}" ]]; then
  DETECTED_KIND="claude"
elif [[ -n "${OPENCODE_SESSION_ID:-}" ]]; then
  DETECTED_KIND="opencode"
elif [[ -n "${CURSOR_AGENT:-}" ]]; then
  DETECTED_KIND="cursor"
fi

AGENT_KIND="${HERDR_HANDOFF_AGENT_KIND:-$DETECTED_KIND}"
MULTIPLEXER="${HERDR_HANDOFF_MULTIPLEXER:-auto}"
TAB_LABEL=""
TAB_TOPIC=""
TARGET_CWD="$PWD"
CWD_EXPLICIT=false
CUSTOM_PROMPT=""
HANDOFF_MODE=""
CLAUDE_MODEL=""
START_AGENT=true
FOCUS_FLAG="--focus"
USE_AGENT_MANAGER=false
CLOSE_SOURCE=false
CLOSE_GRACE_SECONDS=20
RUNNING=""
# Stays under the 120s default of an agent's Bash tool; real claims take 5-15s.
CONFIRM_TIMEOUT="${HERDR_HANDOFF_CONFIRM_TIMEOUT:-90}"
[[ "$CONFIRM_TIMEOUT" =~ ^[1-9][0-9]{0,3}$ ]] || CONFIRM_TIMEOUT=90
YOLO=true
QUOTA_SWITCH="${HERDR_HANDOFF_QUOTA_SWITCH:-true}"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --kind)
      AGENT_KIND="$2"
      shift 2
      ;;
    --multiplexer|--mux)
      MULTIPLEXER="$2"
      shift 2
      ;;
    --label)
      TAB_LABEL="$2"
      shift 2
      ;;
    --topic)
      TAB_TOPIC="$2"
      shift 2
      ;;
    --cwd)
      TARGET_CWD="$2"
      CWD_EXPLICIT=true
      shift 2
      ;;
    --prompt)
      CUSTOM_PROMPT="$2"
      shift 2
      ;;
    --mode)
      HANDOFF_MODE="$2"
      shift 2
      ;;
    --model)
      CLAUDE_MODEL="$2"
      shift 2
      ;;
    --no-agent)
      START_AGENT=false
      shift
      ;;
    --no-focus)
      FOCUS_FLAG="--no-focus"
      shift
      ;;
    --use-agent-manager)
      USE_AGENT_MANAGER=true
      shift
      ;;
    --running)
      RUNNING="${2:-}"
      if [[ ! "$RUNNING" =~ ^[0-9]{1,4}$ ]]; then
        echo "Error: --running needs a whole number of up to 4 digits (got '$RUNNING')." >&2
        exit 1
      fi
      RUNNING=$((10#$RUNNING))  # "08" is eight, not a bad octal
      shift 2
      ;;
    --close-source)
      CLOSE_SOURCE=true
      shift
      ;;
    --yolo)
      YOLO=true
      shift
      ;;
    --no-yolo)
      YOLO=false
      shift
      ;;
    --no-quota-switch)
      QUOTA_SWITCH=false
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      if [[ -z "$HANDOFF_PATH" ]]; then
        HANDOFF_PATH="$1"
      elif [[ -z "$CUSTOM_PROMPT" ]]; then
        CUSTOM_PROMPT="$1"
      fi
      shift
      ;;
  esac
done

# Running agents hold this tab open whatever else was asked; none running closes it.
if [[ -n "$RUNNING" ]]; then
  if (( RUNNING > 0 )); then CLOSE_SOURCE=false; else CLOSE_SOURCE=true; fi
fi

if [[ -z "$HANDOFF_PATH" ]]; then
  echo "Error: Handoff file path is required." >&2
  echo "Usage: herdr-handoff.sh <handoff-markdown-path> [--kind <agent>] [--multiplexer <herdr|t3|auto>] [--prompt <text>]" >&2
  exit 1
fi

if [[ ! -f "$HANDOFF_PATH" ]]; then
  echo "Error: Handoff file '$HANDOFF_PATH' does not exist." >&2
  exit 1
fi
[[ "$HANDOFF_PATH" == /* ]] || HANDOFF_PATH="$PWD/$HANDOFF_PATH"
CLAIM_DIR="$HANDOFF_PATH.claim"
SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# A claimed doc already has an owner; a second spawn could only race it.
if [[ -d "$CLAIM_DIR" && "$DRY_RUN" != "true" && "$START_AGENT" == "true" ]]; then
  echo "❌ Handoff already claimed by: $(cat "$CLAIM_DIR/owner" 2>/dev/null || echo unknown)" >&2
  echo "   To spawn it again on purpose: rm -r '$CLAIM_DIR'" >&2
  exit 1
fi

case "$MULTIPLEXER" in
  herdr|t3|t3code|auto) ;;
  *)
    echo "Error: --multiplexer must be 'herdr', 't3', 't3code', or 'auto' (got '$MULTIPLEXER')." >&2
    exit 1
    ;;
esac

if [[ "$MULTIPLEXER" == "t3code" ]]; then
  MULTIPLEXER="t3"
fi
if [[ "$AGENT_KIND" == "t3code" && "$MULTIPLEXER" == "auto" ]]; then
  MULTIPLEXER="t3"
fi

case "$HANDOFF_MODE" in
  code|plan|"") ;;
  *)
    echo "Error: --mode must be 'code' or 'plan' (got '$HANDOFF_MODE')." >&2
    exit 1
    ;;
esac

# --------------------------------------------------------------------------
# Low-quota auto-switch: when handing off to Claude and Claude's quota is low
# (<= CLAUDE_LOW_QUOTA_THRESHOLD or herdr-agent-quota low-quota-alert, default 10%),
# automatically switch to agy in YOLO mode with the Argon model.
# --------------------------------------------------------------------------
if [[ "$AGENT_KIND" == "claude" && "$QUOTA_SWITCH" != "false" && "$QUOTA_SWITCH" != "0" ]]; then
  LOW_QUOTA_INFO=$(python3 -c '
import json, os, sys, time
from pathlib import Path
custom = os.environ.get("HERDR_PLUGIN_STATE_DIR", "").strip()
if custom:
    dirs = [Path(custom).expanduser()]
elif os.environ.get("FAKE_LOG"):
    dirs = []
else:
    h = Path.home()
    dirs = [
        h / ".local/state/herdr/plugins/herdr-agent-quota",
        h / "Library/Application Support/dev.herdr.herdr-agent-quota",
    ]
thr = 10.0
env_thr = os.environ.get("CLAUDE_LOW_QUOTA_THRESHOLD", "").strip()
if env_thr:
    if env_thr.lower() in ("off", "false", "0", "none"):
        sys.exit(0)
    try:
        thr = float(env_thr)
    except ValueError:
        pass
else:
    for d in dirs:
        p = d / "low-quota-alert"
        try:
            raw = p.read_text().strip()
        except OSError:
            continue
        if not raw:
            continue
        if raw.lower() in ("off", "false", "0", "none"):
            sys.exit(0)
        try:
            thr = float(raw)
            break
        except ValueError:
            pass
now_ts = int(time.time())
for d in dirs:
    for name in ("claude-statusline.json", "claude.json", "claude-statusline.observation.json"):
        p = d / name
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        snap = data.get("snapshot") if isinstance(data, dict) and isinstance(data.get("snapshot"), dict) else data
        windows = snap.get("windows") if isinstance(snap, dict) else None
        if not isinstance(windows, list) or not windows:
            continue
        rems = []
        for w in windows:
            if not isinstance(w, dict):
                continue
            ra = w.get("resets_at")
            if isinstance(ra, (int, float)) and 0 < ra <= now_ts:
                continue
            rem = w.get("remaining_percent")
            if rem is None and isinstance(w.get("used_percent"), (int, float)):
                rem = max(0.0, 100.0 - float(w["used_percent"]))
            if isinstance(rem, (int, float)):
                rems.append((float(rem), str(w.get("kind") or "quota")))
        if rems:
            min_rem, kind = min(rems, key=lambda x: x[0])
            if min_rem <= thr:
                print(f"{min_rem:g}:{thr:g}:{kind}")
            sys.exit(0)
' 2>/dev/null || true)
  if [[ -n "$LOW_QUOTA_INFO" ]]; then
    AGENT_KIND="agy"
    YOLO=true
    if [[ "$CLAUDE_MODEL" == "sonnet" || "$CLAUDE_MODEL" == claude-sonnet* ]]; then
      CLAUDE_MODEL="gemini-3.8-flash-high"
    elif [[ "$CLAUDE_MODEL" == "opus" || "$CLAUDE_MODEL" == claude-opus* ]]; then
      CLAUDE_MODEL="gemini-4-argon-medium"
    elif [[ -z "$CLAUDE_MODEL" || "$CLAUDE_MODEL" == claude-* ]]; then
      if [[ "$HANDOFF_MODE" == "code" ]]; then
        CLAUDE_MODEL="gemini-3.8-flash-high"
      else
        CLAUDE_MODEL="gemini-4-argon-medium"
      fi
    fi
    echo "⚡ Claude quota low ($LOW_QUOTA_INFO) — Auto-switching handoff to agy (yolo, model: $CLAUDE_MODEL)"
  fi
fi

# Model routing for claude and agy handoffs:
# - claude: code -> sonnet, plan -> default
# - agy/gemini: code -> gemini-4-argon-medium, plan -> gemini-4-argon-high, --model argon -> gemini-4-argon-high
# An explicit --model always wins.
if [[ "$AGENT_KIND" == "claude" ]]; then
  case "$HANDOFF_MODE" in
    code) CLAUDE_MODEL="${CLAUDE_MODEL:-sonnet}" ;;
    plan|"") ;;
  esac
  if [[ -z "$HANDOFF_MODE" && -z "$CLAUDE_MODEL" ]]; then
    echo "⚠️  No --mode given; claude will start on the default model. Pass --mode code for Sonnet." >&2
  fi
elif [[ "$AGENT_KIND" == "agy" || "$AGENT_KIND" == "gemini" ]]; then
  if [[ "$CLAUDE_MODEL" == "argon" || "$CLAUDE_MODEL" == "opus" || "$CLAUDE_MODEL" == claude-opus* ]]; then
    CLAUDE_MODEL="gemini-4-argon-medium"
  elif [[ "$CLAUDE_MODEL" == "sonnet" || "$CLAUDE_MODEL" == claude-sonnet* ]]; then
    CLAUDE_MODEL="gemini-3.8-flash-high"
  elif [[ -z "$CLAUDE_MODEL" ]]; then
    case "$HANDOFF_MODE" in
      code) CLAUDE_MODEL="gemini-3.8-flash-high" ;;
      plan) CLAUDE_MODEL="gemini-4-argon-medium" ;;
      "") ;;
    esac
  fi
fi
CLAUDE_MODEL_FLAG=""
if [[ -n "$CLAUDE_MODEL" ]]; then
  if [[ ! "$CLAUDE_MODEL" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Error: invalid --model '$CLAUDE_MODEL'." >&2
    exit 1
  fi
  CLAUDE_MODEL_FLAG="--model $CLAUDE_MODEL "
fi

# The doc says where the work lives; the calling shell may be somewhere else.
if [[ "$CWD_EXPLICIT" != "true" ]]; then
  DOC_CWD=$(sed -n '1,3p' "$HANDOFF_PATH" | sed -nE 's/.*\*\*(Worktree|Repo):\*\* `([^`]+)`.*/\2/p' | sed -n '1p')
  if [[ -n "$DOC_CWD" && -d "$DOC_CWD" && "$DOC_CWD" != "$TARGET_CWD" ]]; then
    echo "📂 Using the doc's directory: $DOC_CWD"
    TARGET_CWD="$DOC_CWD"
  fi
fi

# The script owns the claim path, so a doc can never reach an agent without one.
claim_section() {
  cat <<EOF

## 0. Claim This Handoff (run this FIRST, before reading further)
\`\`\`bash
mkdir "$CLAIM_DIR" 2>/dev/null && echo "\$(whoami) pid \$\$ \$(date -Iseconds)" > "$CLAIM_DIR/owner" && echo CLAIMED || { echo "ALREADY CLAIMED by:"; cat "$CLAIM_DIR/owner"; }
\`\`\`
If it prints \`ALREADY CLAIMED\`: STOP. Another agent already owns this handoff. Do not read further or dispatch anything; tell the user two sessions raced this handoff, and end your turn.
If it prints \`CLAIMED\`: proceed to section 1.
EOF
}

# Formulate prompt for incoming agent and write sidecar file before mux dispatch.
# Inline the full handoff markdown directly into PROMPT_FILE so the receiving agent
# starts with the complete Main Context (Objective, Governing Spec/Plan, User Decisions,
# and Live Frontier) already in Turn 0 without losing the big picture.
ORIGINAL_CONTENT="$(cat "$HANDOFF_PATH")"
CLAIM_PLACEHOLDER="<this-file's-own-absolute-path>"
HANDOFF_CONTENT=${ORIGINAL_CONTENT//"$CLAIM_PLACEHOLDER"/"$HANDOFF_PATH"}
if [[ "$HANDOFF_CONTENT" != *".claim"* ]]; then
  DOC_FIRST_LINE="${HANDOFF_CONTENT%%$'\n'*}"
  DOC_REST=""
  [[ "$HANDOFF_CONTENT" == *$'\n'* ]] && DOC_REST="${HANDOFF_CONTENT#*$'\n'}"
  HANDOFF_CONTENT="$DOC_FIRST_LINE
$(claim_section)

$DOC_REST"
fi
if [[ "$HANDOFF_CONTENT" != "$ORIGINAL_CONTENT" && "$DRY_RUN" != "true" ]]; then
  printf '%s\n' "$HANDOFF_CONTENT" > "$HANDOFF_PATH"
fi
if [[ "$DRY_RUN" != "true" ]]; then
  grep -q '^## 1' "$HANDOFF_PATH" || echo "⚠️  Handoff doc has no '## 1' (Main Context) section." >&2
  grep -q '^## 4' "$HANDOFF_PATH" || echo "⚠️  Handoff doc has no '## 4' (Immediate Next Action) section." >&2
  DOC_BYTES=$(wc -c < "$HANDOFF_PATH" | tr -d ' ')
  if (( DOC_BYTES > 12288 )); then
    echo "⚠️  Handoff doc is $DOC_BYTES bytes; the new session pays for all of it in turn 0." >&2
  fi
fi
if [[ -n "$CUSTOM_PROMPT" ]]; then
  FINAL_PROMPT="Handoff file: $HANDOFF_PATH
Task override / focus: $CUSTOM_PROMPT

Instructions:
1. Run the Section 0 Claim command first.
2. Internalize Section 1 (Main Context: Original User Objective, Governing Spec/Plan/Epic, and Key User Decisions/Constraints) so you preserve the full big picture.
3. Execute Section 4 (Immediate Next Action) and continue driving toward the Section 1 objective (consulting the Governing Spec/Plan file when transitioning between steps, without doing unfocused historical audits).

--- BEGIN HANDOFF DOCUMENT ($HANDOFF_PATH) ---
$HANDOFF_CONTENT
--- END HANDOFF DOCUMENT ---"
else
  FINAL_PROMPT="Handoff file: $HANDOFF_PATH

Instructions:
1. Run the Section 0 Claim command first.
2. Internalize Section 1 (Main Context: Original User Objective, Governing Spec/Plan/Epic, and Key User Decisions/Constraints) so you preserve the full big picture.
3. Execute Section 4 (Immediate Next Action) and continue driving toward the Section 1 objective (consulting the Governing Spec/Plan file when transitioning between steps, without doing unfocused historical audits).

--- BEGIN HANDOFF DOCUMENT ($HANDOFF_PATH) ---
$HANDOFF_CONTENT
--- END HANDOFF DOCUMENT ---"
fi
PROMPT_FILE="${HANDOFF_PATH%.md}.prompt.txt"
printf '%s\n' "$FINAL_PROMPT" > "$PROMPT_FILE"

# Ensure Graft context graph is seeded if TARGET_CWD is a worktree or repo
if [[ "$DRY_RUN" != "true" ]] && command -v graft >/dev/null 2>&1; then
  if git -C "$TARGET_CWD" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    _git_common="$(git -C "$TARGET_CWD" rev-parse --git-common-dir 2>/dev/null || true)"
    if [[ -n "$_git_common" && ! -d "$TARGET_CWD/graft" ]]; then
      _main_repo="$(cd "$TARGET_CWD" && cd "$_git_common/.." 2>/dev/null && pwd)"
      if [[ -d "$_main_repo/graft" ]]; then
        echo "🌱 Seeding graft context graph for worktree from $(basename "$_main_repo") in the background..."
        (cd "$TARGET_CWD" && nohup graft build </dev/null >/dev/null 2>&1 &)
      fi
    fi
  fi
fi

# Detect Herdr & T3Code availability
HERDR_AVAILABLE=false
if command -v herdr >/dev/null 2>&1; then
  HERDR_STATUS=$(herdr status server 2>&1 || true)
  # An exact line: a stopped server prints "status: not running".
  if grep -qE '^[[:space:]]*status: running[[:space:]]*$' <<<"$HERDR_STATUS"; then
    HERDR_AVAILABLE=true
  fi
fi

T3_AVAILABLE=false
T3_RUNTIME_FILE="${T3CODE_HOME:-$HOME/.t3}/userdata/server-runtime.json"
if command -v t3 >/dev/null 2>&1 || [[ -f "$T3_RUNTIME_FILE" ]]; then
  T3_AVAILABLE=true
fi

RESOLVED_MUX="$MULTIPLEXER"
if [[ "$RESOLVED_MUX" == "auto" ]]; then
  if [[ -n "${T3CODE_PROJECT_ID:-}" || "${TERM_PROGRAM:-}" == "t3code" || "${__CFBundleIdentifier:-}" == "com.t3tools.t3code" || -n "${T3CODE_CLI_PATH:-}" ]]; then
    RESOLVED_MUX="t3"
  elif [[ "$HERDR_AVAILABLE" == "true" ]]; then
    RESOLVED_MUX="herdr"
  elif [[ "$T3_AVAILABLE" == "true" ]]; then
    RESOLVED_MUX="t3"
  else
    RESOLVED_MUX="none"
  fi
fi

# Who is calling. `pane current` resolves HERDR_PANE_ID live, so it stays right
# after a pane moves; the inherited HERDR_WORKSPACE_ID and HERDR_TAB_ID do not.
CALLER_WORKSPACE="${HERDR_WORKSPACE_ID:-}"
SOURCE_TAB="${HERDR_TAB_ID:-}"
SOURCE_LABEL=""
if [[ "$RESOLVED_MUX" == "herdr" && "$HERDR_AVAILABLE" == "true" ]]; then
  if [[ -n "${HERDR_PANE_ID:-}" ]]; then
    CALLER_JSON=$(herdr pane current 2>/dev/null || true)
    LIVE_WORKSPACE=$(jq -r '.result.pane.workspace_id // empty' <<<"$CALLER_JSON" 2>/dev/null || true)
    LIVE_TAB=$(jq -r '.result.pane.tab_id // empty' <<<"$CALLER_JSON" 2>/dev/null || true)
    CALLER_WORKSPACE="${LIVE_WORKSPACE:-$CALLER_WORKSPACE}"
    SOURCE_TAB="${LIVE_TAB:-$SOURCE_TAB}"
  fi
  if [[ -n "$SOURCE_TAB" ]]; then
    SOURCE_JSON=$(herdr tab get "$SOURCE_TAB" 2>/dev/null || true)
    SOURCE_LABEL=$(jq -r '.result.tab.label // empty' <<<"$SOURCE_JSON" 2>/dev/null || true)
    # Not `// empty`: jq treats false as missing.
    SOURCE_FOCUSED=$(jq -r '.result.tab.focused | tostring' <<<"$SOURCE_JSON" 2>/dev/null || true)
    # Follow the handoff only if the user is on the parent; never pull them off other work.
    [[ "$SOURCE_FOCUSED" == "false" ]] && FOCUS_FLAG="--no-focus"
  fi
fi

if [[ -z "$TAB_LABEL" ]]; then
  BASENAME=$(basename "$HANDOFF_PATH" .md)
  SLUG=$(echo "$BASENAME" | sed -E 's/handoff(-[0-9_-]+)?-//; s/^[0-9_-]+//')
  [[ "$SLUG" == "$BASENAME" ]] && SLUG=""
  DOC_TITLE=$(sed -n '1s/^# *Handoff: *//p' "$HANDOFF_PATH")
  GIT_COMMON=$(git -C "$TARGET_CWD" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
  if [[ -n "$GIT_COMMON" ]]; then
    PROJECT=$(basename "$(dirname "$GIT_COMMON")")
  else
    PROJECT=$(basename "$TARGET_CWD")
  fi
  TAB_LABEL=$(python3 "$SCRIPT_DIR/handoff_label.py" --cwd-project "$PROJECT" --topic "$TAB_TOPIC" \
    --title "$DOC_TITLE" --slug "$SLUG" --source-label "$SOURCE_LABEL" \
    --max "${HERDR_HANDOFF_LABEL_MAX:-36}" 2>/dev/null || true)
  TAB_LABEL="${TAB_LABEL:-$PROJECT}"
fi

if [[ "$DRY_RUN" == "true" ]]; then
  echo "DRY_RUN=true"
  echo "RESOLVED_MUX=$RESOLVED_MUX"
  echo "AGENT_KIND=$AGENT_KIND"
  echo "TARGET_CWD=$TARGET_CWD"
  echo "HANDOFF_PATH=$HANDOFF_PATH"
  echo "PROMPT_FILE=$PROMPT_FILE"
  echo "TAB_LABEL=$TAB_LABEL"
  echo "TARGET_WORKSPACE=$CALLER_WORKSPACE"
  exit 0
fi

# The installed skill is a checkout: a fix merged upstream does nothing until it lands here.
DRIFT=$(git -C "$SCRIPT_DIR" rev-list --count HEAD..origin/main -- .. 2>/dev/null || true)
if [[ "$DRIFT" =~ ^[1-9][0-9]*$ ]]; then
  echo "⚠️  This handoff skill is $DRIFT commit(s) behind origin/main ($SCRIPT_DIR): merged fixes are not active."
fi

# --------------------------------------------------------------------------
# T3 Code (t3) Multiplexer / Launcher Path
# --------------------------------------------------------------------------
launch_t3_handoff() {
  echo "🚀 Routing handoff to T3 Code (t3) for workspace '$TARGET_CWD'..."
  if command -v pbcopy >/dev/null 2>&1; then
    printf '%s' "$FINAL_PROMPT" | pbcopy || true
    echo "📋 Copied handoff bootstrap prompt to macOS clipboard (pbcopy)."
  fi
  if command -v t3 >/dev/null 2>&1; then
    t3 project add "$TARGET_CWD" >/dev/null 2>&1 || true
    if [[ "$FOCUS_FLAG" != "--no-focus" ]]; then
      t3 app "$TARGET_CWD" >/dev/null 2>&1 || true
    fi
    echo "✅ Opened project '$TARGET_CWD' in T3 Code."
  else
    echo "ℹ️  T3 Code runtime detected ($T3_RUNTIME_FILE), CLI binary not in PATH."
  fi
  echo "📁 Handoff file:   $HANDOFF_PATH"
  echo "📝 Prompt sidecar: $PROMPT_FILE"
  echo "⚠️  NO THREAD WAS STARTED: a shell script cannot create T3 threads."
  echo "👉 AGENT ACTION REQUIRED: call the t3_thread_launch MCP tool now with message = contents of $PROMPT_FILE"
  local t3_model_hint=""
  if [[ "$AGENT_KIND" == "agy" || "$AGENT_KIND" == "gemini" ]]; then
    t3_model_hint=", provider 'antigravity', model '${CLAUDE_MODEL:-gemini-4-argon-medium}'"
  elif [[ -n "$CLAUDE_MODEL" ]]; then
    t3_model_hint=", model '$CLAUDE_MODEL'"
  fi
  if [[ "$YOLO" == "true" ]]; then
    echo "   (title '$TAB_LABEL', runtimeMode 'full-access', interactionMode 'default'${t3_model_hint}, workspaceStrategy matching this checkout)."
    echo "   Never interactionMode 'plan': a plan-mode thread and its subagents refuse every edit."
  else
    echo "   (title '$TAB_LABEL', runtimeMode 'approval-required' (--no-yolo), interactionMode 'default'${t3_model_hint}, workspaceStrategy matching this checkout)."
  fi
  echo "   Fallback for a human: paste (⌘V) into a new T3 Code thread."
  exit 0
}

if [[ "$RESOLVED_MUX" == "t3" ]]; then
  launch_t3_handoff
fi

if [[ "$RESOLVED_MUX" == "none" || "$HERDR_AVAILABLE" != "true" ]]; then
  if [[ "$T3_AVAILABLE" == "true" ]]; then
    launch_t3_handoff
  fi
  echo "⚠️  Neither Herdr server nor T3 Code is currently running."
  echo "📁 Handoff file is ready at: $HANDOFF_PATH"
  echo "📝 Prompt sidecar is ready at: $PROMPT_FILE"
  echo "💡 Start Herdr / T3 Code or launch manually: $AGENT_KIND"
  exit 0
fi

# Pin the new tab to the caller's workspace. Without --workspace herdr uses the
# workspace the user is looking at, and handoffs often fire while they are elsewhere.
WORKSPACE_ARGS=()
if [[ -n "$CALLER_WORKSPACE" ]]; then
  WORKSPACE_ARGS=(--workspace "$CALLER_WORKSPACE")
fi

echo "🚀 Creating Herdr tab in '$TARGET_CWD'${CALLER_WORKSPACE:+ (workspace $CALLER_WORKSPACE)}..."
CREATE_RES=$(herdr tab create ${WORKSPACE_ARGS[@]+"${WORKSPACE_ARGS[@]}"} --cwd "$TARGET_CWD" --label "$TAB_LABEL" "$FOCUS_FLAG" 2>&1 || true)
if [[ -n "$CALLER_WORKSPACE" && "$CREATE_RES" == *workspace_not_found* ]]; then
  echo "⚠️  Workspace $CALLER_WORKSPACE no longer exists; opening the tab in the focused workspace."
  CREATE_RES=$(herdr tab create --cwd "$TARGET_CWD" --label "$TAB_LABEL" "$FOCUS_FLAG" 2>&1 || true)
fi
TAB_ID=$(jq -r '.result.tab.tab_id // .result.tab_id // empty' <<<"$CREATE_RES" 2>/dev/null || true)
ROOT_PANE=$(jq -r '.result.root_pane.pane_id // .result.pane_id // empty' <<<"$CREATE_RES" 2>/dev/null || true)
ACTUAL_WORKSPACE=$(jq -r '.result.tab.workspace_id // empty' <<<"$CREATE_RES" 2>/dev/null || true)

if [[ -z "$TAB_ID" || -z "$ROOT_PANE" ]]; then
  echo "❌ Failed to create Herdr tab. Response: $CREATE_RES" >&2
  echo "📁 Handoff file is ready at: $HANDOFF_PATH — launch manually: $AGENT_KIND" >&2
  exit 1
fi

if [[ -n "$CALLER_WORKSPACE" && -n "$ACTUAL_WORKSPACE" && "$ACTUAL_WORKSPACE" != "$CALLER_WORKSPACE" ]]; then
  echo "⚠️  Tab opened in workspace $ACTUAL_WORKSPACE, expected $CALLER_WORKSPACE."
elif [[ -n "$ACTUAL_WORKSPACE" ]]; then
  echo "📍 Workspace: $ACTUAL_WORKSPACE"
fi
echo "✅ Created tab: $TAB_ID (Pane: $ROOT_PANE, Label: '$TAB_LABEL')"

if [[ "$START_AGENT" == "false" ]]; then
  echo "ℹ️  Shell ready in Herdr tab $TAB_ID. Handoff file: $HANDOFF_PATH"
  exit 0
fi

# --------------------------------------------------------------------------
# finish_handoff: confirm the new agent really took the work, print the big
# close / don't-close banner, and (only if --close-source and confirmed)
# close the source tab after a grace period.
#
# Only the claim confirms. It means the agent got its prompt and ran the first
# command. An agent that is merely present can be stuck on a dialog.
# --------------------------------------------------------------------------
write_ledger() {
  local path="${HERDR_HANDOFF_LEDGER:-${XDG_STATE_HOME:-$HOME/.local/state}/handoff/ledger.jsonl}"
  {
    mkdir -p "$(dirname "$path")" &&
      jq -nc --arg ts "$(date -Iseconds)" --arg doc "$HANDOFF_PATH" --arg label "$TAB_LABEL" \
        --arg kind "$AGENT_KIND" --arg model "$CLAUDE_MODEL" --arg cwd "$TARGET_CWD" \
        --arg source_tab "$SOURCE_TAB" --arg tab "$TAB_ID" \
        --arg workspace_expected "$CALLER_WORKSPACE" --arg workspace_actual "$ACTUAL_WORKSPACE" \
        --argjson confirm_secs "$2" --arg outcome "$1" \
        '$ARGS.named' >> "$path"
  } 2>/dev/null || true
}

finish_handoff() {
  local claimed=false pane_json agent="" status="" started=$SECONDS waited
  while :; do
    pane_json=$(herdr pane get "$ROOT_PANE" 2>/dev/null || true)
    agent=$(jq -r '.result.pane.agent // empty' <<<"$pane_json" 2>/dev/null || true)
    status=$(jq -r '.result.pane.agent_status // empty' <<<"$pane_json" 2>/dev/null || true)
    if [[ -d "$CLAIM_DIR" ]]; then
      claimed=true
      break
    fi
    [[ "$status" == "exited" || "$status" == "dead" ]] && break
    (( SECONDS - started >= CONFIRM_TIMEOUT )) && break
    sleep 0.5
  done
  waited=$((SECONDS - started))

  local source_tab="$SOURCE_TAB"
  echo
  echo "════════════════════════════════════════════════════════════"
  if [[ "$claimed" != "true" ]]; then
    write_ledger unclaimed "$waited"
    if [[ -n "$agent" && "$status" != "exited" && "$status" != "dead" ]]; then
      echo "⚠️   new tab started, status unknown — check it before closing this one"
      echo "    (agent is ${status:-unknown} but has not claimed the handoff; it may be on a dialog)"
    else
      echo "⛔  DO NOT CLOSE THIS TAB — new agent NOT confirmed running"
    fi
    echo "    in tab $TAB_ID (pane $ROOT_PANE) after ${waited}s."
    echo "    Handoff file: $HANDOFF_PATH"
    echo "════════════════════════════════════════════════════════════"
    return 1
  fi
  write_ledger claimed "$waited"
  [[ "$agent" =~ ^[A-Za-z0-9_]+$ ]] || agent="$AGENT_KIND"
  [[ "$status" =~ ^[A-Za-z0-9_]+$ && "$status" != "unknown" ]] || status="claimed"
  echo "✅  HANDOFF CONFIRMED — $agent is $status in tab $TAB_ID (claimed in ${waited}s)"
  if [[ -n "$RUNNING" ]] && (( RUNNING > 0 )); then
    echo "⛔  KEEP THIS TAB OPEN — $RUNNING agents still running"
    echo "    Relay each report to tab $TAB_ID (SendMessage) and append it to"
    echo "    $HANDOFF_PATH under \"Late results\"; say it is fine to close after the last."
    if [[ -n "$source_tab" ]]; then
      herdr tab rename "$source_tab" "⏳ relay → $TAB_LABEL" >/dev/null 2>&1 || true
    fi
  elif [[ "$CLOSE_SOURCE" == "true" && -n "$source_tab" && "$source_tab" != "$TAB_ID" ]]; then
    echo "🚪  Closing THIS tab ($source_tab) in ${CLOSE_GRACE_SECONDS}s (0 agents running)."
    python3 -c 'import subprocess, sys; subprocess.Popen(["sh", "-c", "sleep \"$1\"; herdr tab close \"$2\"", "_", sys.argv[1], sys.argv[2]], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)' "$CLOSE_GRACE_SECONDS" "$source_tab"
  elif [[ -n "$RUNNING" ]]; then
    echo "🟢  SAFE TO CLOSE THIS TAB${source_tab:+ ($source_tab)} — 0 agents running."
  else
    echo "⚠️   agents running: count unknown (no --running given) — close this tab"
    echo "    only if your own check found 0 agents running."
  fi
  echo "════════════════════════════════════════════════════════════"
  return 0
}

for _ in $(seq 1 20); do
  if herdr pane list 2>/dev/null \
      | jq -e --arg p "$ROOT_PANE" '[.result.panes[]? | select(.pane_id == $p)] | length > 0' \
        >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
# Wait for the shell's first output (0.4s on a normal zsh) instead of a blind sleep.
herdr pane wait-output "$ROOT_PANE" --regex '\S' --timeout 5000 >/dev/null 2>&1 || true

TIMESTAMP=$(date +%s)
SHORT_ID=$(echo "$ROOT_PANE" | tr ':' '_' | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9_')
AGENT_NAME="next_${SHORT_ID}_${TIMESTAMP: -4}"

if [[ "$USE_AGENT_MANAGER" == "true" ]]; then
  echo "🤖 Starting managed agent '$AGENT_NAME' (kind: $AGENT_KIND) in pane $ROOT_PANE..."
  AGENT_START_OUT=""
  AGENT_START_OK=false
  if AGENT_START_OUT=$(herdr agent start "$AGENT_NAME" --kind "$AGENT_KIND" --pane "$ROOT_PANE" 2>&1); then
    if ! echo "$AGENT_START_OUT" | jq -e '.error' >/dev/null 2>&1; then
      AGENT_START_OK=true
    fi
  fi
  if [[ "$AGENT_START_OK" == "true" ]] && herdr agent prompt "$AGENT_NAME" "$FINAL_PROMPT" --wait; then
    echo "✨ Handoff delivered to managed agent $AGENT_NAME in Herdr tab $TAB_ID!"
    finish_handoff
    exit $?
  fi
  echo "⚠️  Managed path failed (${AGENT_START_OUT:-prompt delivery failed}); using direct launch." >&2
  if ! herdr pane list 2>/dev/null | jq -e --arg p "$ROOT_PANE" \
        '[.result.panes[]? | select(.pane_id == $p)] | length > 0' >/dev/null 2>&1; then
    echo "❌ Pane $ROOT_PANE no longer exists (the managed agent took the tab with it)." >&2
    echo "📁 Handoff file is ready at: $HANDOFF_PATH — launch manually." >&2
    exit 1
  fi
fi

echo "⚡ Launching $AGENT_KIND interactively in pane $ROOT_PANE..."
YOLO_FLAG=""
if [[ "$YOLO" == "true" ]]; then
  YOLO_FLAG="--dangerously-skip-permissions "
fi
QUOTED_PROMPT_FILE=$(printf '%q' "$PROMPT_FILE")

if [[ "$AGENT_KIND" == "opencode" ]]; then
  LAUNCH_CMD="opencode --prompt \"\$(cat $QUOTED_PROMPT_FILE)\""
elif [[ "$AGENT_KIND" == "claude" ]]; then
  echo "🧠 Claude model: ${CLAUDE_MODEL:-default}"
  LAUNCH_CMD="claude ${YOLO_FLAG}${CLAUDE_MODEL_FLAG}--name $(printf '%q' "$TAB_LABEL") \"\$(cat $QUOTED_PROMPT_FILE)\""
elif [[ "$AGENT_KIND" == "agy" || "$AGENT_KIND" == "gemini" ]]; then
  echo "🧠 AGY model: ${CLAUDE_MODEL:-default}"
  LAUNCH_CMD="agy ${YOLO_FLAG}${CLAUDE_MODEL_FLAG}-i \"\$(cat $QUOTED_PROMPT_FILE)\""
else
  LAUNCH_CMD="$AGENT_KIND"
fi
if ! herdr pane run "$ROOT_PANE" "$LAUNCH_CMD"; then
  echo "❌ Could not start $AGENT_KIND in pane $ROOT_PANE (tab $TAB_ID)." >&2
  echo "📁 Handoff file is ready at: $HANDOFF_PATH — launch manually: $AGENT_KIND" >&2
  exit 1
fi
echo "✨ Agent launched INTERACTIVELY in Herdr tab $TAB_ID with handoff context."
if [[ "$AGENT_KIND" == "claude" || "$AGENT_KIND" == "opencode" || "$AGENT_KIND" == "agy" || "$AGENT_KIND" == "gemini" ]]; then
  finish_handoff
  exit $?
fi
echo "ℹ️  Agent kind '$AGENT_KIND' starts without a prompt; not auto-verified — check tab $TAB_ID before closing this one."
