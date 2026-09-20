#!/usr/bin/env bash
set -euo pipefail

# herdr-handoff.sh — Create a new tab in Herdr, start a coding agent, and deliver a handoff prompt.
#
# Usage:
#   herdr-handoff.sh <handoff-markdown-path> [options]
#
# Options:
#   --kind <agent-kind>    Agent kind (opencode, claude, codex, gemini, agy; default: opencode)
#   --label <tab-label>    Tab label (default: "Handoff: <slug>")
#   --cwd <dir>            Working directory (default: $PWD)
#   --prompt <text>        Custom prompt override
#   --mode <code|plan>     Handoff type. For --kind claude: code -> Sonnet,
#                          plan -> the default model (unset: default + warning)
#   --model <name>         Explicit Claude model; overrides --mode
#   --no-agent            Only open a shell tab without starting an agent
#   --no-focus             Do not switch focus to the new tab
#   --use-agent-manager    Try `herdr agent start` first (currently unreliable;
#                          direct interactive launch is the default)
#   --close-source         After the new agent is CONFIRMED running, close the
#                          tab this script was run from ($HERDR_TAB_ID) after a
#                          short grace period. Pass ONLY when the calling session
#                          has no background agents/tasks still running — the
#                          script cannot see those, the caller must check.

HANDOFF_PATH=""
AGENT_KIND="opencode"
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
YOLO=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kind)
      AGENT_KIND="$2"
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

if [[ -z "$HANDOFF_PATH" ]]; then
  echo "Error: Handoff file path is required." >&2
  echo "Usage: herdr-handoff.sh <handoff-markdown-path> [--kind <agent>] [--prompt <text>]" >&2
  exit 1
fi

if [[ ! -f "$HANDOFF_PATH" ]]; then
  echo "Error: Handoff file '$HANDOFF_PATH' does not exist." >&2
  exit 1
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

# Check if herdr CLI exists
if ! command -v herdr >/dev/null 2>&1; then
  echo "⚠️  herdr CLI not found. Handoff file created at: $HANDOFF_PATH"
  exit 0
fi

# Check if herdr server is running
HERDR_STATUS=$(herdr status server 2>&1 || true)
if [[ "$HERDR_STATUS" != *"status: running"* && "$HERDR_STATUS" != *"running"* ]]; then
  echo "⚠️  Herdr server is not currently running."
  echo "📁 Handoff file is ready at: $HANDOFF_PATH"
  echo "💡 Start Herdr or launch manually: $AGENT_KIND"
  exit 0
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
# close the source tab after a grace period. "Launched" is not "running":
# a pane can accept `pane run` and the agent can still die at startup.
# --------------------------------------------------------------------------
finish_handoff() {
  local alive=false pane_json agent status
  for _ in $(seq 1 60); do
    pane_json=$(herdr pane get "$ROOT_PANE" 2>/dev/null || true)
    agent=$(echo "$pane_json" | jq -r '.result.pane.agent // empty' 2>/dev/null || true)
    status=$(echo "$pane_json" | jq -r '.result.pane.agent_status // empty' 2>/dev/null || true)
    if [[ -n "$agent" && "$status" != "" && "$status" != "exited" && "$status" != "dead" ]]; then
      alive=true
      break
    fi
    sleep 1
  done

  local source_tab="${HERDR_TAB_ID:-}"
  echo
  echo "════════════════════════════════════════════════════════════"
  if [[ "$alive" != "true" ]]; then
    echo "⛔  DO NOT CLOSE THIS TAB — new agent NOT confirmed running"
    echo "    in tab $TAB_ID (pane $ROOT_PANE) after 60s."
    echo "    Handoff file: $HANDOFF_PATH"
    echo "════════════════════════════════════════════════════════════"
    return 1
  fi
  echo "✅  HANDOFF CONFIRMED — $agent is $status in tab $TAB_ID"
  if [[ "$CLOSE_SOURCE" == "true" && -n "$source_tab" && "$source_tab" != "$TAB_ID" ]]; then
    echo "🚪  Closing THIS tab ($source_tab) in ${CLOSE_GRACE_SECONDS}s."
    echo "════════════════════════════════════════════════════════════"
    nohup sh -c "sleep $CLOSE_GRACE_SECONDS; herdr tab close '$source_tab'" >/dev/null 2>&1 &
  else
    echo "🟢  SAFE TO CLOSE THIS TAB${source_tab:+ ($source_tab)} — unless the"
    echo "    session says background agents are still running."
    echo "════════════════════════════════════════════════════════════"
  fi
  return 0
}

# Formulate prompt for incoming agent
FINAL_PROMPT="Please read the handoff document at $HANDOFF_PATH and execute the 'Immediate Next Action' directly. Do NOT conduct historical audits, search other worktrees, or read past review logs inline — stay a thin orchestrator and begin the immediate action."
if [[ -n "$CUSTOM_PROMPT" ]]; then
  FINAL_PROMPT="Please read the handoff document at $HANDOFF_PATH and execute: $CUSTOM_PROMPT. Do NOT conduct historical audits or read past review logs inline — begin the immediate action."
fi

# Wait for the new pane's shell to actually come up before starting an agent
# in it. A flat `sleep 0.5` was a race: `herdr agent start` then failed with
# "agent target pane ... is not an available shell", the script fell through
# to the fallback, and the fallback's `claude -p` printed one reply and
# exited — a dead tab. Poll instead of guessing.
for _ in $(seq 1 20); do
  if herdr pane list 2>/dev/null \
      | jq -e --arg p "$ROOT_PANE" '[.result.panes[]? | select(.pane_id == $p)] | length > 0' \
        >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
sleep 1

# Generate unique valid agent name [a-z][a-z0-9_-]{0,31}
TIMESTAMP=$(date +%s)
# MUST be lowercased. herdr rejects the name otherwise with
# invalid_agent_name ("must start with a lowercase letter and contain only
# lowercase letters, digits, '-' or '_'"). Pane ids are mixed case (w6:pZ),
# so the old 'a-zA-Z0-9_' class preserved an uppercase letter and EVERY
# `herdr agent start` failed — silently, because stderr was discarded — which
# is what pushed this script into its broken `claude -p` fallback every time.
SHORT_ID=$(echo "$ROOT_PANE" | tr ':' '_' | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9_')
AGENT_NAME="next_${SHORT_ID}_${TIMESTAMP: -4}"

# Keep the prompt OFF the command line entirely: write it to a sidecar file
# and have the remote shell read it back. Two earlier attempts failed here —
# \"$FINAL_PROMPT\" broke on embedded quotes, and `printf %q` mangled the
# em dash into escapes herdr rejected ("argument 4 is not valid UTF-8").
# Only the sidecar PATH (ASCII, no spaces) crosses the boundary, so prompt
# text can contain quotes, $, backticks, dashes or any UTF-8 safely.
PROMPT_FILE="${HANDOFF_PATH%.md}.prompt.txt"
printf '%s\n' "$FINAL_PROMPT" > "$PROMPT_FILE"

# --------------------------------------------------------------------------
# Launch strategy: DIRECT INTERACTIVE LAUNCH IS THE DEFAULT.
#
# `herdr agent start` was the old primary path. Measured 2026-09-13, it failed
# 4 out of 4 attempts, three different ways:
#   - invalid_agent_name  (name built from a mixed-case pane id; fixed above)
#   - agent_pane_busy     ("target pane is not an available shell")
#   - agent_not_running   started, then died instantly — AND TOOK THE WHOLE TAB
#                         WITH IT, so nothing was delivered and there was no
#                         pane left to fall back into.
# That last mode is the dangerous one: it reports success at start, fails at
# prompt delivery, and destroys the tab. A fallback placed after it cannot
# recover, because the pane is already gone.
#
# The direct launch has worked every time it was tried (verified: live
# interactive session with a real input prompt). So it goes FIRST. The managed
# path is available behind --use-agent-manager for when herdr fixes it.
# --------------------------------------------------------------------------
if [[ "$USE_AGENT_MANAGER" == "true" ]]; then
  echo "🤖 Starting managed agent '$AGENT_NAME' (kind: $AGENT_KIND) in pane $ROOT_PANE..."
  # `herdr agent start` can report failure in TWO ways — a non-zero exit, OR
  # exit 0 with a JSON {"error":...} payload on stdout. Check both; never
  # discard stderr (that is what made the original failure invisible).
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
  # The pane may have been destroyed along with the dead agent — re-check.
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

if [[ "$AGENT_KIND" == "opencode" ]]; then
  herdr pane run "$ROOT_PANE" "opencode --prompt \"\$(cat '$PROMPT_FILE')\""
elif [[ "$AGENT_KIND" == "claude" ]]; then
  # INTERACTIVE, not `claude -p`. `-p/--print` is one-shot: it prints a single
  # reply and EXITS, leaving a dead shell prompt with no session to continue
  # or resume — which is exactly what "it silently fails" looked like.
  # Passing the prompt positionally starts a normal interactive session seeded
  # with it, so the handoff can actually be worked in that tab.
  echo "🧠 Claude model: ${CLAUDE_MODEL:-default}"
  herdr pane run "$ROOT_PANE" "claude ${YOLO_FLAG}${CLAUDE_MODEL_FLAG}\"\$(cat '$PROMPT_FILE')\""
elif [[ "$AGENT_KIND" == "agy" || "$AGENT_KIND" == "gemini" ]]; then
  herdr pane run "$ROOT_PANE" "agy ${YOLO_FLAG}-i \"\$(cat '$PROMPT_FILE')\""
else
  herdr pane run "$ROOT_PANE" "$AGENT_KIND"
fi
echo "✨ Agent launched INTERACTIVELY in Herdr tab $TAB_ID with handoff context."
if [[ "$AGENT_KIND" == "claude" || "$AGENT_KIND" == "opencode" || "$AGENT_KIND" == "agy" || "$AGENT_KIND" == "gemini" ]]; then
  finish_handoff
  exit $?
fi
echo "ℹ️  Agent kind '$AGENT_KIND' starts without a prompt; not auto-verified — check tab $TAB_ID before closing this one."
