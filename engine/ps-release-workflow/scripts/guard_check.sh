#!/usr/bin/env bash
# Fast-path PreToolUse wrapper around guard_check.py.
#
# Rationale: the hook fires on EVERY Edit/Write/MultiEdit/NotebookEdit in every
# repo, and a python spawn costs ~60ms. Most edits are in repos that never
# opted into ps-release-workflow (no .release.json anywhere up the tree), so
# decide that cheap case in bash + jq and only spawn python when it matters.
#
# Correctness rules:
# - On ANY doubt (jq missing, unparseable input, empty path, relative path),
#   fall through to python — never skip the real guard because of uncertainty.
# - A target that doesn't exist yet (Write of a new file) walks up from the
#   nearest EXISTING ancestor.
# - Exit code is python's exit code whenever python runs (0 allow, 2 block).
#
# PS_GUARD_PYTHON overrides the python interpreter (used by tests).
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="${PS_GUARD_PYTHON:-/usr/local/bin/python3}"
if [ ! -x "$PYTHON" ]; then
    PYTHON="$(command -v python3 || true)"
fi

# Buffer ALL of stdin so it can be re-fed to python if needed.
INPUT="$(cat)"

run_python() {
    if [ -z "$PYTHON" ]; then
        # No interpreter anywhere: the guard is effectively dead on this machine.
        # Never brick every edit (exit 0), but SCREAM so it gets fixed.
        {
            echo "⚠️⚠️⚠️  guard_check.sh: NO python3 INTERPRETER FOUND."
            echo "⚠️  The ps-release-workflow PreToolUse guard is DISABLED MACHINE-WIDE:"
            echo "⚠️  edits on main of opted-in repos will NOT be blocked."
            echo "⚠️  Install python3 (or set PS_GUARD_PYTHON) to restore the guard."
        } >&2
        exit 0
    fi
    printf '%s' "$INPUT" | "$PYTHON" "$SCRIPT_DIR/guard_check.py"
    exit $?
}

JQ="/usr/local/bin/jq"
if [ ! -x "$JQ" ]; then
    JQ="$(command -v jq || true)"
fi
[ -z "$JQ" ] && run_python

# One jq spawn for both fields (tool name + target path), tab-separated.
EXTRACT="$(printf '%s' "$INPUT" | "$JQ" -r \
    '[(.tool_name // ""), (.tool_input.file_path // .tool_input.notebook_path // "")] | @tsv' \
    2>/dev/null)" || run_python

# B2: @tsv escapes tab/newline/backslash (\t, \n, \\), so an extraction that
# contains ANY backslash no longer names a real filesystem path — the walk
# below would silently miss the repo. Backslash = doubt = run python.
case "$EXTRACT" in
    *\\*) run_python ;;
esac

TOOL="${EXTRACT%%$'\t'*}"
FP="${EXTRACT#*$'\t'}"

case "$TOOL" in
    Edit|Write|MultiEdit|NotebookEdit|write_file|replace) ;;  # mutating tool (Claude + Gemini names): keep checking
    "") run_python ;;                       # missing/unparseable: let python decide
    *) exit 0 ;;                            # non-mutating tool: allow fast
esac

[ -z "$FP" ] && run_python
case "$FP" in
    /*) ;;             # absolute: safe to walk
    *) run_python ;;   # relative/odd: don't guess in bash
esac

# Nearest existing ancestor directory of the target (pure-bash, no dirname
# spawns). A Write target may not exist yet, so trim path components until
# an existing directory is found.
DIR="$FP"
[ -d "$DIR" ] || DIR="${DIR%/*}"
while [ -n "$DIR" ] && [ ! -d "$DIR" ]; do
    DIR="${DIR%/*}"
done
[ -z "$DIR" ] && DIR="/"

# B1: physically resolve the starting directory (pwd -P) before walking. A
# target reached via a symlinked dir (link -> repo/src) has no .release.json
# on its LITERAL ancestor chain, so a string-walk would skip the real guard
# while guard_check.py (which .resolve()s) would have blocked. If resolution
# fails for any reason, fall through to python — never decide on doubt.
DIR="$(cd "$DIR" 2>/dev/null && pwd -P)" || run_python
[ -z "$DIR" ] && run_python

# Walk up looking for a workflow opt-in marker. Linked worktrees carry the
# committed .release.json in their checkout (and toolkit worktrees live under
# <repo>/.claude/worktrees/, i.e. beneath the opted-in root anyway).
CUR="$DIR"
while :; do
    [ -f "$CUR/.release.json" ] && run_python
    [ "$CUR" = "/" ] && break
    CUR="${CUR%/*}"
    [ -z "$CUR" ] && CUR="/"
done

# No .release.json anywhere up to / — not a ps-release-workflow repo. Allow.
exit 0
