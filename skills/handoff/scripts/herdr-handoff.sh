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
#   --label <tab-label>         Tab label (default: "Handoff: <slug>")
#   --cwd <dir>                 Working directory (default: $PWD)
#   --prompt <text>             Custom prompt override
#   --mode <code|plan>          Handoff type. For --kind claude: code -> Sonnet,
#                               plan -> the default model (unset: default + warning)
#   --model <name>              Explicit Claude model; overrides --mode
#   --no-agent                  Only open a shell tab without starting an agent
#   --no-focus                  Do not switch focus to the new tab
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
  --label <tab-label>         Tab label (default: "Handoff: <slug>")
  --cwd <dir>                 Working directory (default: $PWD)
  --prompt <text>             Custom prompt override
  --mode <code|plan>          Handoff type for --kind claude (code -> sonnet, plan -> default)
  --model <name>              Explicit Claude model; overrides --mode
  --no-agent                  Only open a shell tab without starting an agent
  --no-focus                  Do not switch focus to the new tab
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
TARGET_CWD="$PWD"
CUSTOM_PROMPT=""
HANDOFF_MODE=""
CLAUDE_MODEL=""
START_AGENT=true
FOCUS_FLAG="--focus"
USE_AGENT_MANAGER=false
CLOSE_SOURCE=false
CLOSE_GRACE_SECONDS=20
RUNNING=""
CONFIRM_TIMEOUT="${HERDR_HANDOFF_CONFIRM_TIMEOUT:-60}"
[[ "$CONFIRM_TIMEOUT" =~ ^[1-9][0-9]{0,3}$ ]] || CONFIRM_TIMEOUT=60
YOLO=true
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
    --cwd)
      TARGET_CWD="$2"
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

# Model routing for claude handoffs: coding work goes to Sonnet, planning
# work keeps the default model. An explicit --model always wins.
case "$HANDOFF_MODE" in
  code) CLAUDE_MODEL="${CLAUDE_MODEL:-sonnet}" ;;
  plan|"") ;;
  *)
    echo "Error: --mode must be 'code' or 'plan' (got '$HANDOFF_MODE')." >&2
    exit 1
    ;;
esac
if [[ "$AGENT_KIND" == "claude" && -z "$HANDOFF_MODE" && -z "$CLAUDE_MODEL" ]]; then
  echo "⚠️  No --mode given; claude will start on the default model. Pass --mode code for Sonnet." >&2
fi
CLAUDE_MODEL_FLAG=""
if [[ -n "$CLAUDE_MODEL" ]]; then
  if [[ ! "$CLAUDE_MODEL" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Error: invalid --model '$CLAUDE_MODEL'." >&2
    exit 1
  fi
  CLAUDE_MODEL_FLAG="--model $CLAUDE_MODEL "
fi

# Determine default label
if [[ -z "$TAB_LABEL" ]]; then
  BASENAME=$(basename "$HANDOFF_PATH" .md)
  SLUG=$(echo "$BASENAME" | sed -E 's/handoff(-[0-9_-]+)?-//; s/^[0-9_-]+//')
  if [[ -n "$SLUG" && "$SLUG" != "$BASENAME" ]]; then
    TAB_LABEL="Handoff: $SLUG"
  else
    TAB_LABEL="Handoff: $(basename "$TARGET_CWD")"
  fi
fi

# Formulate prompt for incoming agent and write sidecar file before mux dispatch.
# Inline the full handoff markdown directly into PROMPT_FILE so the receiving agent
# starts with the complete Main Context (Objective, Governing Spec/Plan, User Decisions,
# and Live Frontier) already in Turn 0 without losing the big picture.
HANDOFF_CONTENT="$(cat "$HANDOFF_PATH")"
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
        echo "🌱 Seeding graft context graph for worktree from $(basename "$_main_repo")..."
        (cd "$TARGET_CWD" && graft build >/dev/null 2>&1 || true)
      fi
    fi
  fi
fi

# Detect Herdr & T3Code availability
HERDR_AVAILABLE=false
if command -v herdr >/dev/null 2>&1; then
  HERDR_STATUS=$(herdr status server 2>&1 || true)
  if [[ "$HERDR_STATUS" == *"status: running"* || "$HERDR_STATUS" == *"running"* ]]; then
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

if [[ "$DRY_RUN" == "true" ]]; then
  echo "DRY_RUN=true"
  echo "RESOLVED_MUX=$RESOLVED_MUX"
  echo "AGENT_KIND=$AGENT_KIND"
  echo "TARGET_CWD=$TARGET_CWD"
  echo "HANDOFF_PATH=$HANDOFF_PATH"
  echo "PROMPT_FILE=$PROMPT_FILE"
  exit 0
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
  if [[ "$YOLO" == "true" ]]; then
    echo "   (title 'Handoff: <slug>', runtimeMode 'full-access', interactionMode 'default', workspaceStrategy matching this checkout)."
    echo "   Never interactionMode 'plan': a plan-mode thread and its subagents refuse every edit."
  else
    echo "   (title 'Handoff: <slug>', runtimeMode 'approval-required' (--no-yolo), interactionMode 'default', workspaceStrategy matching this checkout)."
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

echo "🚀 Creating Herdr tab in '$TARGET_CWD'..."
CREATE_RES=$(herdr tab create --cwd "$TARGET_CWD" --label "$TAB_LABEL" "$FOCUS_FLAG")
TAB_ID=$(echo "$CREATE_RES" | jq -r '.result.tab.tab_id // .result.tab_id // empty')
ROOT_PANE=$(echo "$CREATE_RES" | jq -r '.result.root_pane.pane_id // .result.pane_id // empty')

if [[ -z "$TAB_ID" || -z "$ROOT_PANE" ]]; then
  echo "❌ Failed to create Herdr tab. Response: $CREATE_RES" >&2
  exit 1
fi

echo "✅ Created tab: $TAB_ID (Pane: $ROOT_PANE, Label: '$TAB_LABEL')"

if [[ "$START_AGENT" == "false" ]]; then
  echo "ℹ️  Shell ready in Herdr tab $TAB_ID. Handoff file: $HANDOFF_PATH"
  exit 0
fi

# --------------------------------------------------------------------------
# finish_handoff: confirm the new agent is really alive, print the big
# close / don't-close banner, and (only if --close-source and confirmed)
# close the source tab after a grace period.
# --------------------------------------------------------------------------
finish_handoff() {
  local alive=false pane_json agent="" status=""
  for _ in $(seq 1 "$CONFIRM_TIMEOUT"); do
    pane_json=$(herdr pane get "$ROOT_PANE" 2>/dev/null || true)
    agent=$(echo "$pane_json" | jq -r '.result.pane.agent // empty' 2>/dev/null || true)
    status=$(echo "$pane_json" | jq -r '.result.pane.agent_status // empty' 2>/dev/null || true)
    # Only a status that shows a live agent confirms; "unknown" and the rest keep polling.
    if [[ -n "$agent" && ( "$status" == "working" || "$status" == "idle" || "$status" == "blocked" ) ]]; then
      alive=true
      break
    fi
    sleep 1
  done

  local source_tab="${HERDR_TAB_ID:-}"
  echo
  echo "════════════════════════════════════════════════════════════"
  if [[ "$alive" != "true" ]]; then
    if [[ -n "$agent" && "$status" != "exited" && "$status" != "dead" ]]; then
      echo "⚠️   new tab started, status unknown — check it before closing this one"
    else
      echo "⛔  DO NOT CLOSE THIS TAB — new agent NOT confirmed running"
    fi
    echo "    in tab $TAB_ID (pane $ROOT_PANE) after ${CONFIRM_TIMEOUT}s."
    echo "    Handoff file: $HANDOFF_PATH"
    echo "════════════════════════════════════════════════════════════"
    return 1
  fi
  echo "✅  HANDOFF CONFIRMED — $agent is $status in tab $TAB_ID"
  if [[ -n "$RUNNING" ]] && (( RUNNING > 0 )); then
    echo "⛔  KEEP THIS TAB OPEN — $RUNNING agents still running"
    echo "    Relay each report to tab $TAB_ID (SendMessage) and append it to"
    echo "    $HANDOFF_PATH under \"Late results\"; say it is fine to close after the last."
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
sleep 1

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
  herdr pane run "$ROOT_PANE" "opencode --prompt \"\$(cat $QUOTED_PROMPT_FILE)\""
elif [[ "$AGENT_KIND" == "claude" ]]; then
  echo "🧠 Claude model: ${CLAUDE_MODEL:-default}"
  herdr pane run "$ROOT_PANE" "claude ${YOLO_FLAG}${CLAUDE_MODEL_FLAG}\"\$(cat $QUOTED_PROMPT_FILE)\""
elif [[ "$AGENT_KIND" == "agy" || "$AGENT_KIND" == "gemini" ]]; then
  herdr pane run "$ROOT_PANE" "agy ${YOLO_FLAG}-i \"\$(cat $QUOTED_PROMPT_FILE)\""
else
  herdr pane run "$ROOT_PANE" "$AGENT_KIND"
fi
echo "✨ Agent launched INTERACTIVELY in Herdr tab $TAB_ID with handoff context."
if [[ "$AGENT_KIND" == "claude" || "$AGENT_KIND" == "opencode" || "$AGENT_KIND" == "agy" || "$AGENT_KIND" == "gemini" ]]; then
  finish_handoff
  exit $?
fi
echo "ℹ️  Agent kind '$AGENT_KIND' starts without a prompt; not auto-verified — check tab $TAB_ID before closing this one."
