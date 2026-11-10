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
  --mode <code|plan>          Handoff type (claude: code->sonnet, plan->default; agy: code->gemini-3.8-flash-high, plan->gemini-4-argon-medium)
  --model <name>              Explicit model for claude, codex, or agy; overrides --mode
  --effort <level>            Reasoning effort for codex (low, medium, high; default: medium)
  --cloud / --no-cloud        Force or disable claude --cloud (default: auto; checks free credit > $0 first, then requires Jev cloud_compatible >= 0.85 & read-only review/research)
  --jev / --no-jev            Enable or disable TypeSafe Jev System-1 task routing assist (default: auto)
  --no-quota-switch           Do not auto-switch low-quota claude handoffs to cloud/codex/agy
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
CODEX_EFFORT="${HERDR_HANDOFF_EFFORT:-medium}"
CLAUDE_CLOUD="${HERDR_HANDOFF_CLOUD:-auto}"
JEV_ASSIST="${HERDR_HANDOFF_JEV:-auto}"
CLOUD_CREDIT_DOLLARS=""
CLOUD_CREDIT_BUCKET=""
JEV_INFO=""
FALLBACK_KIND=""
FALLBACK_MODEL=""
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
    --effort)
      CODEX_EFFORT="$2"
      shift 2
      ;;
    --cloud)
      CLAUDE_CLOUD="true"
      shift
      ;;
    --no-cloud)
      CLAUDE_CLOUD="false"
      shift
      ;;
    --jev)
      JEV_ASSIST="true"
      shift
      ;;
    --no-jev)
      JEV_ASSIST="false"
      shift
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
# Free-credit, low-quota & Jev System-1 auto-routing:
# 1. Uses TypeSafe Jev System-1 (`jev-gate classify-task`) on the handoff doc
#    and prompt to classify whether the work is normal coding (`agy_flash`,
#    low reviewer/risk probability -> mode=code) or complex/review/architecture
#    (`agy_argon` / `claude_opus` or reviewer/risky -> mode=plan).
# 2. Automatically inspects ~/.claude.json (or $CLAUDE_CONFIG_FILE) for free
#    Anthropic Cloud Session Credits (iguana_necktie / cinder_cove / wattle_ember /
#    promo_credits with remaining_dollars > 0 and unexpired resets_at).
# 3. Inspects herdr-agent-quota state for local Claude weekly/5h quota and
#    Codex 5h/weekly quota.
# 4. Routing priority:
#    - Tier 1 (Free Cloud Session Credit > $0 on Claude, or --cloud): route to
#      `claude --cloud` (`CCR_ENABLE_BUNDLE=1`), with Jev picking `sonnet` (for
#      coding, fallback `codex/gpt-6.1-terra`) vs `opus` (for complex/review,
#      fallback `agy/gemini-4-argon-medium`).
#    - Tier 2 (Coding task + High Codex quota 5h >= 50%, wk >= 30% when local
#      Claude quota is low or handing off from AGY without --model): auto-switch
#      to `codex` (`gpt-6.1-terra`, effort: medium).
#    - Tier 3 (Local Claude quota low <= 10%): auto-switch to `agy`
#      (`gemini-3.8-flash-high` for code, `gemini-4-argon-medium` for plan).
# --------------------------------------------------------------------------
if [[ ( "$AGENT_KIND" == "claude" || "$AGENT_KIND" == "agy" || "$AGENT_KIND" == "gemini" ) && ( "$QUOTA_SWITCH" != "false" && "$QUOTA_SWITCH" != "0" || "$CLAUDE_CLOUD" == "true" || "$JEV_ASSIST" == "true" ) ]]; then
  QUOTA_PROBE_OUT=$(HANDOFF_DOC_FILE="$HANDOFF_PATH" HANDOFF_CUSTOM_PROMPT="$CUSTOM_PROMPT" JEV_ASSIST_MODE="$JEV_ASSIST" python3 -c '
import json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

def is_future_reset(ra, now_ts):
    if ra is None:
        return True
    if isinstance(ra, (int, float)):
        return ra <= 0 or ra > now_ts
    if isinstance(ra, str) and ra.strip():
        try:
            dt = datetime.fromisoformat(ra.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp() > now_ts
        except Exception:
            return True
    return True

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

cfg_env = os.environ.get("CLAUDE_CONFIG_FILE", "").strip()
if cfg_env:
    claude_cfg = Path(cfg_env).expanduser()
elif os.environ.get("FAKE_LOG"):
    claude_cfg = None
else:
    claude_cfg = Path.home() / ".claude.json"

thr = 10.0
quota_disabled = False
env_thr = os.environ.get("CLAUDE_LOW_QUOTA_THRESHOLD", "").strip()
if env_thr:
    if env_thr.lower() in ("off", "false", "0", "none"):
        quota_disabled = True
    else:
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
        if not raw or raw.lower() in ("off", "false", "0", "none"):
            # "off" in low-quota-alert only mutes the Herdr UI banner; keep thr=10.0
            continue
        try:
            thr = float(raw)
            break
        except ValueError:
            pass

now_ts = int(time.time())
low_quota_info = ""
if not quota_disabled:
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
                    low_quota_info = f"{min_rem:g}:{thr:g}:{kind}"
                break
        if low_quota_info:
            break

cloud_credit_str = ""
if claude_cfg and claude_cfg.is_file():
    try:
        cdata = json.loads(claude_cfg.read_text())
        util = (cdata.get("cachedUsageUtilization") or {}).get("utilization") or {}
        if isinstance(util, dict):
            credit_keys = ["iguana_necktie", "cinder_cove", "wattle_ember", "promo_credits", "omelette_promotional"]
            best_d = 0.0
            best_k = ""
            for k in list(credit_keys) + [k for k in util.keys() if k not in credit_keys]:
                v = util.get(k)
                if not isinstance(v, dict) or "remaining_dollars" not in v:
                    continue
                if v.get("locked_reason"):
                    continue
                if not is_future_reset(v.get("resets_at"), now_ts):
                    continue
                rem_d = float(v.get("remaining_dollars") or 0.0)
                if rem_d > best_d:
                    best_d = rem_d
                    best_k = k
            if best_d > 0:
                cloud_credit_str = f"{best_d:g}:{best_k}"
            if not low_quota_info and not quota_disabled:
                rems = []
                for k, kind_name in (("five_hour", "5h"), ("seven_day", "weekly")):
                    w = util.get(k)
                    if isinstance(w, dict) and isinstance(w.get("utilization"), (int, float)):
                        if is_future_reset(w.get("resets_at"), now_ts):
                            rems.append((max(0.0, 100.0 - float(w["utilization"])), kind_name))
                if rems:
                    min_rem, kind = min(rems, key=lambda x: x[0])
                    if min_rem <= thr:
                        low_quota_info = f"{min_rem:g}:{thr:g}:{kind}"
    except Exception:
        pass

codex_high_info = ""
for d in dirs:
    for name in ("codex-app-server.json", "codex.json"):
        p = d / name
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        snap = data.get("snapshot") if isinstance(data, dict) and isinstance(data.get("snapshot"), dict) else data
        windows = snap.get("windows") if isinstance(snap, dict) else None
        if not isinstance(windows, list) or not windows:
            continue
        r5, rw = None, None
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
                k = str(w.get("kind") or "")
                if k in ("five_hour", "5h"):
                    r5 = float(rem)
                elif k in ("weekly", "7d", "seven_day"):
                    rw = float(rem)
        if r5 is not None and rw is not None:
            if r5 > 80.0 and rw >= 60.0:
                codex_high_info = f"5h={r5:g}%,wk={rw:g}%"
            break
    if codex_high_info:
        break

agy_status = "unknown"
for d in dirs:
    for name in ("agy-statusline.observation.json", "agy.json", "agy-statusline.json"):
        p = d / name
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        snap = data.get("snapshot") if isinstance(data, dict) and isinstance(data.get("snapshot"), dict) else data
        windows = snap.get("windows") if isinstance(snap, dict) else None
        r5_a, rw_a = None, None
        if isinstance(windows, list):
            for w in windows:
                if not isinstance(w, dict):
                    continue
                rem = w.get("remaining_percent")
                if rem is None and isinstance(w.get("used_percent"), (int, float)):
                    rem = max(0.0, 100.0 - float(w["used_percent"]))
                if isinstance(rem, (int, float)):
                    k = str(w.get("kind") or "")
                    if k in ("five_hour", "5h"):
                        r5_a = float(rem)
                    elif k in ("weekly", "7d", "seven_day"):
                        rw_a = float(rem)
        elif isinstance(snap, dict) and isinstance(snap.get("quota"), dict):
            q = snap["quota"]
            if "gemini-5h" in q:
                r5_a = float(q["gemini-5h"].get("remaining_fraction", 0.0)) * 100.0
            if "gemini-weekly" in q:
                rw_a = float(q["gemini-weekly"].get("remaining_fraction", 0.0)) * 100.0
        if rw_a is not None:
            if (r5_a is None or r5_a >= 30.0) and rw_a >= 30.0:
                agy_status = "high"
            else:
                agy_status = "low"
            break
    if agy_status != "unknown":
        break

jev_str = ""
jev_mode = os.environ.get("JEV_ASSIST_MODE", "auto").strip().lower()
jev_bin_env = os.environ.get("JEV_GATE_BIN", "").strip()
run_jev = (jev_mode == "true") or (jev_mode == "auto" and (bool(jev_bin_env) or not os.environ.get("FAKE_LOG")))
if run_jev:
    doc_path = os.environ.get("HANDOFF_DOC_FILE", "")
    custom_p = os.environ.get("HANDOFF_CUSTOM_PROMPT", "")
    text_parts = []
    if custom_p:
        text_parts.append(custom_p)
    if doc_path and Path(doc_path).is_file():
        try:
            text_parts.append(Path(doc_path).read_text(errors="ignore")[:8000])
        except Exception:
            pass
    full_text = "\n\n".join(text_parts).strip()
    jev_bin = Path(jev_bin_env) if jev_bin_env else (Path.home() / "ps-skills" / "bin" / "jev-gate")
    if full_text and jev_bin.is_file():
        py_exe = "/opt/homebrew/bin/python3" if Path("/opt/homebrew/bin/python3").is_file() else sys.executable
        cmd = [str(jev_bin), "classify-task", "--prompt", full_text] if jev_bin_env else [py_exe, str(jev_bin), "classify-task", "--prompt", full_text]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            if proc.returncode == 0 and proc.stdout.strip():
                jdata = json.loads(proc.stdout.strip())
                if isinstance(jdata, dict) and "raw_route" in jdata and not jdata.get("fallback"):
                    raw_r = str(jdata.get("raw_route") or "")
                    eff_r = str(jdata.get("route") or raw_r)
                    conf = float(jdata.get("route_confidence") or 0.0)
                    rev_p = float(jdata.get("is_reviewer_prob") or 0.0)
                    risk_p = float(jdata.get("risky_surface_prob") or 0.0)
                    comp = float(jdata.get("complexity_score") or 0.0)
                    cloud_p = float(jdata.get("cloud_compatible_prob") or 0.0)
                    import re
                    if re.search(r"(\.superpowers/|orbstack|kubectl|deploy-local|shoot\.mjs|psrw\s+ship|dispatch-worker|\.claude/worktrees/)", full_text):
                        cloud_p = min(cloud_p, 0.05)
                    if raw_r in ("agy_argon", "claude_opus") or rev_p >= 0.50 or risk_p >= 0.35:
                        jtier = "plan"
                    else:
                        jtier = "code"
                    jev_str = f"{jtier}:{raw_r}:{conf:.2f}:{rev_p:.2f}:{risk_p:.2f}:{comp:.2f}:{cloud_p:.2f}"
        except Exception:
            pass
    if not jev_str and full_text:
        import re
        if re.search(
            r"\b(code[- ]review|spec[- ]review|spec[- ]audit|self-grill-audit|security[- ]audit|"
            r"review[- ]chain|aios[- ]review|falsif(?:y|ier|ication)|audit\b.*\bvulnerabilit|"
            r"root[- ]cause\s+analysis|architectural\s+(?:design|review|audit))\b",
            full_text, re.IGNORECASE
        ):
            jev_str = "plan:agy_argon:0.85:0.85:0.50:2.00:0.00"
        else:
            jev_str = "code:agy_flash:0.80:0.05:0.05:1.20:0.00"

print(f"{low_quota_info}|{cloud_credit_str}|{codex_high_info}|{jev_str}|{agy_status}")
' 2>/dev/null || true)

  IFS='|' read -r LOW_QUOTA_INFO CLOUD_CREDIT_INFO CODEX_HIGH_INFO JEV_INFO AGY_STATUS <<<"$QUOTA_PROBE_OUT"
  if [[ -n "$CLOUD_CREDIT_INFO" ]]; then
    CLOUD_CREDIT_DOLLARS="${CLOUD_CREDIT_INFO%%:*}"
    CLOUD_CREDIT_BUCKET="${CLOUD_CREDIT_INFO#*:}"
  fi

  JEV_CLOUD_OK="false"
  if [[ -n "$JEV_INFO" ]]; then
    IFS=':' read -r JEV_TIER JEV_RAW_ROUTE JEV_CONF JEV_REV JEV_RISK JEV_COMP JEV_CLOUD <<<"$JEV_INFO"
    if python3 -c "import sys; rev=float(sys.argv[1] or 0); cld=float(sys.argv[2] or 0); sys.exit(0 if (cld >= 0.85 and rev >= 0.50) else 1)" "${JEV_REV:-0}" "${JEV_CLOUD:-0}" 2>/dev/null; then
      JEV_CLOUD_OK="true"
    fi
    if [[ "$JEV_TIER" == "plan" && "$HANDOFF_MODE" != "plan" ]]; then
      HANDOFF_MODE="plan"
      echo "🧭 Jev System-1 assist: route=$JEV_RAW_ROUTE (conf=$JEV_CONF, rev=$JEV_REV, risk=$JEV_RISK, complexity=$JEV_COMP, cloud=${JEV_CLOUD:-0.00}) -> escalating mode to plan"
    elif [[ "$JEV_TIER" == "code" && -z "$HANDOFF_MODE" ]]; then
      HANDOFF_MODE="code"
      echo "🧭 Jev System-1 assist: route=$JEV_RAW_ROUTE (conf=$JEV_CONF, rev=$JEV_REV, risk=$JEV_RISK, complexity=$JEV_COMP, cloud=${JEV_CLOUD:-0.00}) -> auto-selecting mode=code"
    else
      echo "🧭 Jev System-1 assist: route=$JEV_RAW_ROUTE (conf=$JEV_CONF, rev=$JEV_REV, risk=$JEV_RISK, complexity=$JEV_COMP, cloud=${JEV_CLOUD:-0.00}) -> confirmed mode=${HANDOFF_MODE:-$JEV_TIER}"
    fi
  fi

  if [[ "$AGENT_KIND" == "claude" ]]; then
    if [[ "$CLAUDE_CLOUD" == "true" || ( "$CLAUDE_CLOUD" == "auto" && -n "$CLOUD_CREDIT_DOLLARS" && "$JEV_CLOUD_OK" == "true" ) ]]; then
      CLAUDE_CLOUD="true"
      if [[ "$HANDOFF_MODE" == "plan" && -z "$CLAUDE_MODEL" && -n "$JEV_INFO" ]]; then
        CLAUDE_MODEL="opus"
      fi
      if [[ "$HANDOFF_MODE" != "plan" && "$AGY_STATUS" != "high" && -n "$CODEX_HIGH_INFO" ]]; then
        FALLBACK_KIND="codex"
        FALLBACK_MODEL="gpt-6.1-terra"
      elif [[ "$HANDOFF_MODE" != "plan" ]]; then
        FALLBACK_KIND="agy"
        FALLBACK_MODEL="gemini-3.8-flash-high"
      else
        FALLBACK_KIND="agy"
        FALLBACK_MODEL="gemini-4-argon-medium"
      fi
      if [[ -n "$LOW_QUOTA_INFO" && -n "$CLOUD_CREDIT_DOLLARS" ]]; then
        echo "☁️  Claude quota low ($LOW_QUOTA_INFO), free Cloud Session Credit available (\$$CLOUD_CREDIT_DOLLARS left in $CLOUD_CREDIT_BUCKET) — Auto-switching handoff to claude --cloud (fallback: $FALLBACK_KIND/$FALLBACK_MODEL)"
      elif [[ -n "$CLOUD_CREDIT_DOLLARS" ]]; then
        echo "☁️  Free Claude Cloud Session Credit available (\$$CLOUD_CREDIT_DOLLARS left in $CLOUD_CREDIT_BUCKET) — Auto-routing handoff to claude --cloud (fallback: $FALLBACK_KIND/$FALLBACK_MODEL)"
      else
        echo "☁️  Routing handoff to claude --cloud (fallback: $FALLBACK_KIND/$FALLBACK_MODEL)"
      fi
    elif [[ -n "$LOW_QUOTA_INFO" && "$QUOTA_SWITCH" != "false" && "$QUOTA_SWITCH" != "0" ]]; then
      # Priority waterfall: Claude > AGY (if 7d >= 30%) > Codex (if code & AGY 7d < 30% & Codex 5h > 80%, 7d >= 60%)
      if [[ "$HANDOFF_MODE" != "plan" && "$AGY_STATUS" != "high" && -n "$CODEX_HIGH_INFO" && "$CLAUDE_MODEL" != "opus" && "$CLAUDE_MODEL" != claude-opus* && "$CLAUDE_MODEL" != "argon" && "$CLAUDE_MODEL" != gemini-4-argon* && ( -z "$CLAUDE_MODEL" || "$CLAUDE_MODEL" == "sonnet" || "$CLAUDE_MODEL" == claude-* ) ]]; then
        AGENT_KIND="codex"
        YOLO=true
        CLAUDE_MODEL="gpt-6.1-terra"
        echo "⚡ Claude quota low ($LOW_QUOTA_INFO), AGY low/unavailable & Codex quota high ($CODEX_HIGH_INFO) — Auto-switching code handoff to codex (yolo, model: $CLAUDE_MODEL, effort: $CODEX_EFFORT)"
      else
        AGENT_KIND="agy"
        YOLO=true
        if [[ "$CLAUDE_MODEL" == "sonnet" || "$CLAUDE_MODEL" == claude-sonnet* ]]; then
          CLAUDE_MODEL="gemini-3.8-flash-high"
        elif [[ "$CLAUDE_MODEL" == "opus" || "$CLAUDE_MODEL" == claude-opus* ]]; then
          CLAUDE_MODEL="gemini-4-argon-medium"
        elif [[ -z "$CLAUDE_MODEL" || "$CLAUDE_MODEL" == claude-* ]]; then
          if [[ "$HANDOFF_MODE" == "plan" ]]; then
            CLAUDE_MODEL="gemini-4-argon-medium"
          else
            CLAUDE_MODEL="gemini-3.8-flash-high"
          fi
        fi
        echo "⚡ Claude quota low ($LOW_QUOTA_INFO) — Auto-switching handoff to agy (yolo, model: $CLAUDE_MODEL)"
      fi
    fi
  elif [[ ( "$AGENT_KIND" == "agy" || "$AGENT_KIND" == "gemini" ) && "$QUOTA_SWITCH" != "false" && "$QUOTA_SWITCH" != "0" ]]; then
    if [[ "$HANDOFF_MODE" != "plan" && "$AGY_STATUS" != "high" && -n "$CODEX_HIGH_INFO" && -z "$CLAUDE_MODEL" ]]; then
      AGENT_KIND="codex"
      YOLO=true
      CLAUDE_MODEL="gpt-6.1-terra"
      echo "⚡ Jev classified as coding, AGY 7d low & Codex quota high ($CODEX_HIGH_INFO) — Auto-switching handoff to codex (yolo, model: $CLAUDE_MODEL, effort: $CODEX_EFFORT)"
    fi
  fi
fi

# Model routing for claude, codex, and agy handoffs:
# - claude: code -> sonnet, plan -> default
# - codex: default -> gpt-6.1-terra (effort: medium)
# - agy/gemini: code/default -> gemini-3.8-flash-high, plan -> gemini-4-argon-medium, --model argon -> gemini-4-argon-medium
# An explicit --model always wins.
if [[ "$AGENT_KIND" == "claude" ]]; then
  case "$HANDOFF_MODE" in
    code) CLAUDE_MODEL="${CLAUDE_MODEL:-sonnet}" ;;
    plan|"") ;;
  esac
  if [[ -z "$HANDOFF_MODE" && -z "$CLAUDE_MODEL" ]]; then
    echo "⚠️  No --mode given; claude will start on the default model. Pass --mode code for Sonnet." >&2
  fi
elif [[ "$AGENT_KIND" == "codex" ]]; then
  if [[ -z "$CLAUDE_MODEL" || "$CLAUDE_MODEL" == "sonnet" || "$CLAUDE_MODEL" == claude-* ]]; then
    CLAUDE_MODEL="gpt-6.1-terra"
  fi
elif [[ "$AGENT_KIND" == "agy" || "$AGENT_KIND" == "gemini" ]]; then
  if [[ "$CLAUDE_MODEL" == "argon" || "$CLAUDE_MODEL" == "opus" || "$CLAUDE_MODEL" == claude-opus* ]]; then
    CLAUDE_MODEL="gemini-4-argon-medium"
  elif [[ "$CLAUDE_MODEL" == "sonnet" || "$CLAUDE_MODEL" == claude-sonnet* ]]; then
    CLAUDE_MODEL="gemini-3.8-flash-high"
  elif [[ -z "$CLAUDE_MODEL" ]]; then
    case "$HANDOFF_MODE" in
      plan) CLAUDE_MODEL="gemini-4-argon-medium" ;;
      code|"") CLAUDE_MODEL="gemini-3.8-flash-high" ;;
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
if [[ "$HANDOFF_CONTENT" != *"$CLAIM_DIR"* ]]; then
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
    --max "${HERDR_HANDOFF_LABEL_MAX:-16}" 2>/dev/null || true)
  TAB_LABEL="${TAB_LABEL:-$PROJECT}"
fi

if [[ "$DRY_RUN" == "true" ]]; then
  echo "DRY_RUN=true"
  echo "RESOLVED_MUX=$RESOLVED_MUX"
  echo "AGENT_KIND=$AGENT_KIND"
  echo "CLAUDE_CLOUD=$CLAUDE_CLOUD"
  echo "CLOUD_CREDIT_DOLLARS=${CLOUD_CREDIT_DOLLARS:-0}"
  echo "RESOLVED_MODEL=${CLAUDE_MODEL:-default}"
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

# Herdr appends new tabs at the end. Put this one right after its parent, so it
# takes the parent's place when the parent closes. Same workspace only.
place_next_to_source() {
  [[ -n "$SOURCE_TAB" && "$SOURCE_TAB" != "$TAB_ID" ]] || return 0
  local ws="${ACTUAL_WORKSPACE:-$CALLER_WORKSPACE}" list src_idx new_idx target err
  [[ -n "$ws" ]] || return 0
  list=$(herdr tab list --workspace "$ws" 2>/dev/null || true)
  src_idx=$(jq -r --arg t "$SOURCE_TAB" '[.result.tabs[]?.tab_id] | index($t) // empty' <<<"$list" 2>/dev/null || true)
  new_idx=$(jq -r --arg t "$TAB_ID" '[.result.tabs[]?.tab_id] | index($t) // empty' <<<"$list" 2>/dev/null || true)
  [[ "$src_idx" =~ ^[0-9]+$ && "$new_idx" =~ ^[0-9]+$ ]] || return 0  # parent is in another workspace
  (( new_idx == src_idx + 1 )) && return 0
  # insert_index is the tab's final slot: coming from in front, the parent shifts left by one.
  target=$((src_idx + 1))
  (( new_idx < src_idx )) && target=$src_idx
  if [[ -z "${HERDR_SOCKET_PATH:-}" ]]; then
    echo "⚠️  Tab left at the end: HERDR_SOCKET_PATH is not set."
    return 0
  fi
  if err=$(python3 "$SCRIPT_DIR/herdr_tab_move.py" --socket "$HERDR_SOCKET_PATH" --tab "$TAB_ID" --index "$target" 2>&1); then
    echo "↔️  Placed next to the parent tab ($SOURCE_TAB)."
  else
    echo "⚠️  Tab left at the end: tab.move failed (${err:-no reply})."
  fi
}
place_next_to_source

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
# Quote TAB_LABEL with shlex, not printf %q: macOS bash 3.2 %q splits multibyte
# characters such as "…" into invalid UTF-8, and herdr then rejects the command.
QUOTED_TAB_LABEL=$(python3 -I -c 'import shlex,sys; print(shlex.quote(sys.argv[1]))' "$TAB_LABEL")

if [[ "$AGENT_KIND" == "opencode" ]]; then
  LAUNCH_CMD="opencode --prompt \"\$(cat $QUOTED_PROMPT_FILE)\""
elif [[ "$AGENT_KIND" == "claude" ]]; then
  if [[ "$CLAUDE_CLOUD" == "true" ]]; then
    echo "☁️  Claude Cloud model: ${CLAUDE_MODEL:-default} (credit: \$${CLOUD_CREDIT_DOLLARS:-auto})"
    QUOTED_CLAIM_DIR=$(printf '%q' "$CLAIM_DIR")
    if [[ "${FALLBACK_KIND:-agy}" == "codex" ]]; then
      FALLBACK_CMD="codex --dangerously-bypass-approvals-and-sandbox -c model=\"${FALLBACK_MODEL:-gpt-6.1-terra}\" -c model_reasoning_effort=\"${CODEX_EFFORT:-medium}\" \"\$(cat $QUOTED_PROMPT_FILE)\""
    else
      FALLBACK_CMD="agy ${YOLO_FLAG}--model ${FALLBACK_MODEL:-gemini-4-argon-medium} -i \"\$(cat $QUOTED_PROMPT_FILE)\""
    fi
    CLOUD_LOG="${HANDOFF_PATH%.md}.cloud.log"
    QUOTED_CLOUD_LOG=$(printf '%q' "$CLOUD_LOG")
    LAUNCH_CMD="if CCR_ENABLE_BUNDLE=1 claude ${YOLO_FLAG}${CLAUDE_MODEL_FLAG}--name $QUOTED_TAB_LABEL --forward-home-settings true --cloud \"\$(cat $QUOTED_PROMPT_FILE)\" 2>&1 | tee $QUOTED_CLOUD_LOG; then mkdir -p $QUOTED_CLAIM_DIR 2>/dev/null && echo \"claude-cloud \$(date -Iseconds)\" > $QUOTED_CLAIM_DIR/owner; _sid=\$(grep -Eo 'session_[A-Za-z0-9]+' $QUOTED_CLOUD_LOG | head -n 1); if [[ -n \"\$_sid\" ]]; then claude --teleport \"\$_sid\"; fi; else echo \"⚠️ claude --cloud failed; falling back to local ${FALLBACK_KIND:-agy} (${FALLBACK_MODEL:-gemini-4-argon-medium})...\" >&2; $FALLBACK_CMD; fi"
  else
    echo "🧠 Claude model: ${CLAUDE_MODEL:-default}"
    LAUNCH_CMD="claude ${YOLO_FLAG}${CLAUDE_MODEL_FLAG}--name $QUOTED_TAB_LABEL \"\$(cat $QUOTED_PROMPT_FILE)\""
  fi
elif [[ "$AGENT_KIND" == "codex" ]]; then
  CODEX_YOLO_FLAG=""
  if [[ "$YOLO" == "true" ]]; then
    CODEX_YOLO_FLAG="--dangerously-bypass-approvals-and-sandbox "
  fi
  echo "🧠 Codex model: ${CLAUDE_MODEL:-gpt-6.1-terra} (effort: ${CODEX_EFFORT:-medium})"
  LAUNCH_CMD="codex ${CODEX_YOLO_FLAG}-c model=\"${CLAUDE_MODEL:-gpt-6.1-terra}\" -c model_reasoning_effort=\"${CODEX_EFFORT:-medium}\" \"\$(cat $QUOTED_PROMPT_FILE)\""
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
if [[ "$AGENT_KIND" == "claude" || "$AGENT_KIND" == "codex" || "$AGENT_KIND" == "opencode" || "$AGENT_KIND" == "agy" || "$AGENT_KIND" == "gemini" ]]; then
  finish_handoff
  exit $?
fi
echo "ℹ️  Agent kind '$AGENT_KIND' starts without a prompt; not auto-verified — check tab $TAB_ID before closing this one."
