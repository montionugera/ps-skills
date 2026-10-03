#!/usr/bin/env bash
# render-spec-md.sh — render a markdown spec/brainstorm/decision doc to
# dark-theme HTML (with Mermaid) and open in Chrome.
#
# Two invocation modes:
#   1. PostToolUse hook: reads tool payload JSON from stdin, extracts
#      tool_input.file_path, only proceeds for .md files under the
#      whitelisted spec/research/docs paths.
#   2. CLI / slash skill: pass the markdown path as $1, no stdin.
#
# Exit silently (0) when the input isn't something we want to render,
# so the hook never blocks tool calls.

set -euo pipefail

STYLE_HEADER="$HOME/.claude/spec-style.html"
SUPPRESS_FLAG="${QUANT_RENDER_SUPPRESS:-0}"

# --- Loud failure contract -------------------------------------------------
# Intentional skips (suppress flag, non-.md, non-whitelisted hook path) stay silent.
# Every REAL problem (missing tool, pandoc error, leaked HTML, broken/unvalidated
# mermaid) is: printed to stderr, appended to a log, and ends in a NON-ZERO exit
# (2 in hook mode so PostToolUse feeds stderr to Claude; 1 in CLI mode).
trap 'rm -rf "${_mmd_dir:-}" "${_src:-}"' EXIT
LOG_FILE="$HOME/.claude/logs/render-spec.log"
PROBLEMS=0
_fail_code=2; [[ $# -ge 1 && -n "${1:-}" ]] && _fail_code=1
problem() {
  PROBLEMS=$((PROBLEMS+1))
  echo "render-spec: ❌ $*" >&2
  mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
  printf '%s %s\n' "$(date -Iseconds)" "$*" >> "$LOG_FILE" 2>/dev/null || true
}
finish_if_problems() {
  if [[ "$PROBLEMS" -gt 0 ]]; then
    echo "render-spec: ❌ ${PROBLEMS} problem(s) — render is NOT trustworthy. Log: $LOG_FILE" >&2
    exit "$_fail_code"
  fi
}

[[ "$SUPPRESS_FLAG" == "1" ]] && exit 0
[[ -f "$STYLE_HEADER" ]] || { problem "missing style header $STYLE_HEADER"; finish_if_problems; }
command -v pandoc >/dev/null 2>&1 || { problem "pandoc not on PATH (brew install pandoc)"; finish_if_problems; }

file_path=""
explicit=0

if [[ $# -ge 1 && -n "${1:-}" ]]; then
  # CLI mode
  file_path="$1"
  explicit=1
else
  # Hook mode — parse stdin
  command -v jq >/dev/null 2>&1 || { problem "jq not on PATH (brew install jq) — hook render skipped"; finish_if_problems; }
  payload="$(cat || true)"
  [[ -z "$payload" ]] && exit 0
  file_path="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')" \
    || { problem "unparseable hook payload"; finish_if_problems; }
fi

# Hook mode skips non-targets silently; an EXPLICIT path that can't render is an error.
if [[ "$explicit" == "1" ]]; then
  [[ -f "$file_path" ]] || { problem "no such file: $file_path"; finish_if_problems; }
  [[ "$file_path" == *.md ]] || { problem "not a .md file: $file_path"; finish_if_problems; }
fi
[[ -z "$file_path" ]] && exit 0
[[ "$file_path" != *.md ]] && exit 0
[[ ! -f "$file_path" ]] && exit 0

# Path whitelist — only the auto-fire HOOK is restricted; an explicit CLI path always renders.
if [[ "$explicit" == "0" ]]; then
case "$file_path" in
  */docs/superpowers/specs/*) ;;
  */docs/superpowers/plans/*) ;;
  */docs/superpowers/decisions/*) ;;
  */docs/superpowers/brainstorms/*) ;;
  */docs/superpowers/runbooks/*) ;;
  */docs/superpowers/research/*) ;;
  */research/*) ;;
  *) exit 0 ;;
esac
fi

# Filename blacklist — don't render index / config / memory files even if
# they live under a whitelisted path.
basename="$(basename "$file_path")"
if [[ "$explicit" == "0" ]]; then
case "$basename" in
  MEMORY.md|CLAUDE.md|GEMINI.md|AGENTS.md|README.md|CHANGELOG.md) exit 0 ;;
esac
fi

html_path="${file_path%.md}.html"

# Mermaid validation (best-effort): the HTML renders Mermaid client-side, so a
# bad diagram silently shows "Syntax error in text" to the reader. If mmdc
# (@mermaid-js/mermaid-cli) is installed, validate each ```mermaid block here
# and WARN loudly to stderr. Never blocks the render (always falls through).
if command -v mmdc >/dev/null 2>&1 && command -v awk >/dev/null 2>&1; then
  # Use the installed system Chrome (mmdc's bundled puppeteer pins a Chrome version that is often not in the cache).
  _mmd_pp=""; [[ -f "$HOME/.claude/puppeteer-mmdc.json" ]] && _mmd_pp="$HOME/.claude/puppeteer-mmdc.json"
  _mmd_dir="$(mktemp -d 2>/dev/null || echo '')"
  if [[ -n "$_mmd_dir" ]]; then
    awk -v dir="$_mmd_dir" '
      /^```mermaid/ {inblk=1; n++; fn=sprintf("%s/blk_%03d.mmd", dir, n); next}
      /^```/ {inblk=0; next}
      inblk {print > fn}
    ' "$file_path" 2>/dev/null
    _mmd_fail=0
    for _blk in "$_mmd_dir"/blk_*.mmd; do
      [[ -e "$_blk" ]] || continue
      _mmd_err="$(mmdc ${_mmd_pp:+-p "$_mmd_pp"} -i "$_blk" -o "$_blk.svg" 2>&1)" && continue
      if printf '%s' "$_mmd_err" | grep -q "Could not find Chrome"; then
        problem "mermaid validation UNAVAILABLE — mmdc cannot launch Chrome (fix: check ~/.claude/puppeteer-mmdc.json executablePath points at an installed Chrome). Diagrams are UNVERIFIED."
        break
      fi
      if true; then
        _mmd_fail=$((_mmd_fail+1))
        _num="$(basename "$_blk" .mmd | sed 's/blk_0*//')"
        problem "MERMAID SYNTAX ERROR — $(basename "$file_path") block #${_num} will render as 'Syntax error in text'."
      fi
    done
    rm -rf "$_mmd_dir"
    [[ "$_mmd_fail" -gt 0 ]] && echo "render-spec: hint — quote labels; no { } ( ) inside labels." >&2
  fi
fi

# Pandoc treats any 4+-space-indented line as an indented CODE BLOCK, so nested
# raw-HTML (metric-tile > metric-label, callouts, row layouts) renders as literal
# "<div class=...>" text. Dedent lines that start with an HTML tag, outside
# fenced code. (pandoc has no markdown-indented_code_blocks switch.)
_src="$(mktemp "${TMPDIR:-/tmp}/render-spec-XXXXXX")"
awk '/^[ \t]*```/ {f=!f} { if (!f && $0 ~ /^[ \t]+<\/?[A-Za-z]/) sub(/^[ \t]+/, ""); print }' "$file_path" > "$_src"
pandoc "$_src" -s --toc --toc-depth=2 -H "$STYLE_HEADER" -o "$html_path" >/dev/null 2>&1 || {
  rm -f "$_src"
  problem "pandoc failed on $file_path"
  finish_if_problems
}

# Leak guard (source-level, fence-aware): after the dedent above, any remaining
# unfenced line indented 4+ spaces/tab that contains HTML would still become a
# literal code block. Fenced examples of HTML are legitimate and NOT flagged.
_leak="$(awk '/^[ \t]*```/ {f=!f; next} !f && /^( {4}|\t)/ && /<\/?(div|span|table|details|section)/ {print NR": "$0}' "$_src" | head -3 || true)"
if [[ -n "$_leak" ]]; then
  problem "RAW-HTML LEAK — $(basename "$file_path") has indented HTML pandoc will render as code: ${_leak//$'\n'/ | }"
fi
rm -f "$_src"

finish_if_problems

# Auto-open in Chrome disabled (2026-05-30) — was annoying when running
# multiple Edit calls on the same spec (each opened a new tab). The HTML
# is still rendered silently in place; Claude reports the file:// URL
# back to the user in chat when the work is at a checkpoint. If you want
# the old behavior, set QUANT_RENDER_AUTO_OPEN=1 in your environment.
if [[ "${QUANT_RENDER_AUTO_OPEN:-0}" == "1" ]]; then
  if [[ "$(uname)" == "Darwin" ]] && [[ -d "/Applications/Google Chrome.app" ]]; then
    open -a "Google Chrome" "file://$html_path" >/dev/null 2>&1 || true
  fi
fi

# CLI mode prints the rendered path for human feedback.
if [[ $# -ge 1 && -n "${1:-}" ]]; then
  echo "rendered: $html_path"
fi
