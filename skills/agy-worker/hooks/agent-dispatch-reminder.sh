#!/usr/bin/env bash
# agent-dispatch-reminder.sh — PreToolUse / BeforeTool hook for Claude (`Agent`/`Task`)
# and Antigravity (`invoke_subagent`/`delegate_task`).
#
# 1. When a subagent brief looks like read-only scouting/lookup, remind the caller to use
#    Haiku / Flash with low/medium effort (`dispatch-worker --scout --effort low`).
# 2. When a subagent brief looks like bulk mechanical work, inject ONE line reminding the
#    model of the `dispatch-worker` command (respecting the Claude > AGY > Codex waterfall
#    with the >= 60% Codex guard).
# 3. When Claude weekly quota is in the Yellow/Red zone (< 50% remaining), ALSO remind
#    on reviewer / audit / verification / builder subagents so multi-reviewer fan-out
#    is offloaded to Antigravity (`gemini-4-argon-medium` for review/judge,
#    `gemini-3.8-flash-high` for build/test).
# 4. High-confidence System-1 (Jev) classification: when ~/ps-skills/bin/jev-gate is available,
#    appends a calibrated tier recommendation (conf >= 0.85, risky-surface guard).
#
# Contract: ADVISORY ONLY. Never blocks, never denies, never changes the tool input.
# Exit 0 on every path; malformed JSON, wrong types, empty stdin or a missing jq all
# mean "say nothing".
# Disable without editing settings.json: export AGENT_DISPATCH_REMINDER=off

[ "${AGENT_DISPATCH_REMINDER:-on}" = "off" ] && exit 0
command -v jq >/dev/null 2>&1 || exit 0

# Prints "<remaining_percent> <age_seconds>" from the first source with a usable weekly window,
# or nothing. $1 = max data age in seconds; windows whose resets_at has passed are ignored
# (2026-11-10: a stale ~/.claude.json cache from the previous week read as "2% remaining").
_read_weekly_rem() {
  local max_age="$1" now qf val; shift
  now="$(date +%s)"
  for qf in "$@"; do
    [ -n "$qf" ] && [ -f "$qf" ] || continue
    val="$(jq -r --argjson now "$now" --argjson max "$max_age" '
      def live: (.resets_at == null) or ((.resets_at | tonumber? // 0) > $now);
      def epoch: if type == "string" then (.[0:19] + "Z" | fromdateiso8601) else . end;
      def rem: .remaining_percent // (if .used_percent != null then (100 - .used_percent) else empty end);
      (.snapshot // .) as $s
      | ([($s.windows // [])[] | select(.kind == "weekly" and live)]
         # top-level windows are empty when the last statusline writer had no rate_limits;
         # every live session window is the same week, so the lowest remaining is the latest.
         | if length == 0 then [($s.session_windows // {})[][]? | select(.kind == "weekly" and live)] else . end
         | map(rem) | min) as $wrem
      | (if $wrem != null then [$wrem, $s.fetched_at_unix]
         elif (.payload.rate_limits.seven_day.used_percentage != null) and (.payload.rate_limits.seven_day | live) then
           [100 - .payload.rate_limits.seven_day.used_percentage, $s.fetched_at_unix]
         elif .cachedUsageUtilization.utilization.seven_day.utilization != null then
           .cachedUsageUtilization as $c
           | if (($c.utilization.seven_day.resets_at // null | epoch) // 0) > $now
             then [100 - $c.utilization.seven_day.utilization, (($c.fetchedAtMs // 0) / 1000 | floor)] else empty end
         else empty end)
      | select(.[1] != null and ($now - .[1]) <= $max)
      | "\(.[0]) \($now - .[1])"
    ' "$qf" 2>/dev/null)"
    if [ -n "$val" ]; then
      printf '%s' "$val"
      return 0
    fi
  done
}

_read_five_hour_rem() {
  local qf
  for qf in "$@"; do
    [ -n "$qf" ] && [ -f "$qf" ] || continue
    local val
    val="$(jq -r '
      ((.snapshot // .) | .windows // [])
      | map(select(.kind == "five_hour") | (.remaining_percent // (if .used_percent != null then (100 - .used_percent) else empty end)))
      | first // empty
    ' "$qf" 2>/dev/null)"
    if [ -n "$val" ]; then
      printf '%s' "$val"
      return 0
    fi
  done
}

CLAUDE_WEEKLY_REM="$(_read_weekly_rem "${CLAUDE_QUOTA_MAX_AGE_S:-21600}" \
  "${CLAUDE_QUOTA_STATE_FILE:-}" \
  "$HOME/.local/state/herdr/plugins/herdr-agent-quota/claude-statusline.observation.json" \
  "$HOME/.local/state/herdr/plugins/herdr-agent-quota/claude-statusline.json" \
  "$HOME/.local/state/herdr/plugins/herdr-agent-quota/claude.json" \
  "$HOME/.claude.json")"

AGY_WEEKLY_REM="$(_read_weekly_rem 999999999 \
  "${AGY_QUOTA_STATE_FILE:-}" \
  "$HOME/.local/state/herdr/plugins/herdr-agent-quota/agy-statusline.observation.json" \
  "$HOME/.local/state/herdr/plugins/herdr-agent-quota/agy-statusline.json")"

CODEX_WEEKLY_REM="$(_read_weekly_rem 999999999 \
  "${CODEX_QUOTA_STATE_FILE:-}" \
  "$HOME/.local/state/herdr/plugins/herdr-agent-quota/codex-app-server.json" \
  "$HOME/.local/state/herdr/plugins/herdr-agent-quota/codex.json")"

CODEX_5H_REM="$(_read_five_hour_rem \
  "${CODEX_QUOTA_STATE_FILE:-}" \
  "$HOME/.local/state/herdr/plugins/herdr-agent-quota/codex-app-server.json" \
  "$HOME/.local/state/herdr/plugins/herdr-agent-quota/codex.json")"

INPUT_JSON="$(head -c 262144 2>/dev/null || true)"
[ -z "$INPUT_JSON" ] && exit 0

JEV_HINT=""
if [ "${JEV_DISPATCH_GATE:-on}" != "off" ] && [ -x "$HOME/ps-skills/bin/jev-gate" ]; then
  PROMPT_SNIPPET="$(printf '%s' "$INPUT_JSON" | jq -r '
    if (.tool_name == "Agent" or .tool_name == "Task") then
      ((.tool_input.description // "") + "\n" + ((.tool_input.prompt // "") | .[0:4000]))
    elif (.tool_name == "invoke_subagent") then
      (((.tool_input.Subagents // []) | map((.Role // "") + ": " + (.Prompt // "")) | join("\n")) | .[0:4000])
    elif (.tool_name == "delegate_task") then
      ((.tool_input.task // "") | .[0:4000])
    else empty end
  ' 2>/dev/null || true)"
  if [ -n "$PROMPT_SNIPPET" ]; then
    JEV_HINT="$("$HOME/ps-skills/bin/jev-gate" classify-task --prompt "$PROMPT_SNIPPET" --hook-line --timeout 2.0 2>/dev/null || true)"
  fi
fi

ADVISORY="$(printf '%s' "$INPUT_JSON" | jq -c \
  --arg weekly "${CLAUDE_WEEKLY_REM%% *}" \
  --arg weekly_age "${CLAUDE_WEEKLY_REM#* }" \
  --arg agy_w "${AGY_WEEKLY_REM%% *}" \
  --arg codex_w "${CODEX_WEEKLY_REM%% *}" \
  --arg codex_5h "${CODEX_5H_REM:-0}" \
  --arg jev "$JEV_HINT" '
  def s: if type == "string" then . else "" end;
  (($weekly | tonumber?) // null) as $wk
  | (($weekly_age | tonumber? // 0) / 60 | floor) as $wage_min
  | ($wk != null and $wk < 50) as $w_low
  | ($agy_w | tonumber? // 100) as $aw
  | ($codex_w | tonumber? // 0) as $cw
  | ($codex_5h | tonumber? // 0) as $c5
  | (($aw < 30) and ($c5 > 80) and ($cw >= 60)) as $prefer_codex
  | (if ($jev | length) > 0 then " " + $jev else "" end) as $jnote

  | (.tool_name | s) as $tool
  | (if $tool == "invoke_subagent" then ((.tool_input.Subagents[0].TypeName // "") | s)
     else (.tool_input.subagent_type | s) end) as $subtype
  | (if $tool == "invoke_subagent" then ((.tool_input.Subagents[0].Model // "") | s)
     else (.tool_input.model | s) end) as $model
  | (if $tool == "invoke_subagent" then ((.tool_input.Subagents[0].Role // "") | s | ascii_downcase)
     else (.tool_input.description | s | ascii_downcase) end) as $desc
  | (if $tool == "invoke_subagent" then
       ($desc + " " + (((.tool_input.Subagents // []) | map(.Prompt // "") | join(" ")) | s | .[0:6000] | ascii_downcase))
     elif $tool == "delegate_task" then
       ((.tool_input.task // "") | s | .[0:6000] | ascii_downcase)
     else
       ($desc + " " + (.tool_input.prompt | s | .[0:6000] | ascii_downcase))
     end) as $text

  | select($tool == "Agent" or $tool == "Task" or $tool == "invoke_subagent" or $tool == "delegate_task")
  | select($subtype | test("^claude-code-guide$|^statusline-setup$") | not)
  | select($text | test("claude-in-chrome|browser|screenshot|chrome tab|mcp__|mcp connector|this conversation") | not)

  | (($subtype | test("^Explore$|^research$")) or (($text | test("scout|read-only|locate (all )?files|find where|trace the call|list all callers|do not (edit|modify)")) and (($text | test("implement|refactor|write (code|tests)|fix the bug|commit")) | not))) as $is_scout
  | ($text | test("implement (task|phase|slice|step)|implementer|bulk|sweep|rename|migrat|replace (all|every)|across (all|[0-9]+) (files|packages|modules|repos)|in (all|every) (file|package|module)|fix-?up pass|apply (the |all )?(review )?(fixes|findings)|redraw|regenerate|codemod|search-and-replace|sed-style|mechanical|boilerplate|run the (full |whole )?(test )?suite|update (all|every) ")) as $is_bulk
  | (($subtype | test("reviewer|aios-|verifier|falsifier|silent-failures|builder|test-writer|remediator")) or ($desc | test("review|audit|critique|grill|verify|falsif|silent.?fail"))) as $is_review_or_aios

  | select($is_scout or $is_bulk or ($is_review_or_aios and ($wk == null or $w_low)))

  | (if $model == "opus" then " (this call is on Opus -> maps to gemini-4-argon-medium)"
     elif $model == "sonnet" then " (this call is on Sonnet -> maps to gemini-3.8-flash-high)"
     elif $model == "" then " (no model set: inherits parent)"
     else "" end) as $note

  | (if $prefer_codex then
       "dispatch-worker --agent codex --model gpt-6.1-terra --effort medium"
     else
       "dispatch-worker --agent agy --model gemini-3.8-flash-high"
     end) as $worker_cmd

  | if ($is_scout and ($is_review_or_aios | not) and ($is_bulk | not)) then
      {hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext:
        ("Scouting tier check" + $note + ": read-only scouting/lookup tasks should use Haiku (`model: \"haiku\"` with `effort: low`, or `medium` for multi-file call-chain tracing) or `dispatch-worker --scout --cwd \"<worktree>\" --task \"<scout brief>\"` (routes to Haiku/3.8-Flash with low/medium effort and --no-verify)." + $jnote)}}
    elif ($is_review_or_aios and $wk == null and ($is_bulk | not)) then
      {hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext:
        ("Quota-aware dispatch check: Claude weekly quota unknown (no live weekly window in data newer than 6h); no offload advice." + $jnote)}}
    elif ($w_low and $is_review_or_aios and ($is_bulk | not)) then
      {hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext:
        ("Quota-aware dispatch check (Claude weekly quota: " + ($wk|tostring) + "% remaining / " + ((100 - $wk)|tostring) + "% used, data " + ($wage_min|tostring) + " min old; yellow zone is < 50% remaining)" + $note
         + ": native Claude review/AIOS subagents cost ~47k Turn-1 cache tokens each. Prefer offloading independent review/judge passes to Antigravity via dispatch-thinker --agent agy --model gemini-4-argon-medium --cwd \"<worktree>\" --task \"<review brief>\" or worker passes via " + $worker_cmd + ", or cap native parallel reviewers to 1 combined pass." + $jnote)}}
    else
      {hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext:
        ("Rule 8 dispatch check: this Agent brief looks like bulk mechanical work" + $note
         + ". If it is more than 5 tool calls or 3 files and needs no browser/MCP, send it to a worker instead: "
         + $worker_cmd + " --cwd \"<worktree>\" --task \"<goal + files>\" "
         + "--acceptance \"<criteria>\" --verify-cmd \"<cmd>\" --timeout <seconds> --detach ; then dispatch-worker --wait <job-id>. "
         + "Advisory only: proceed with Agent if the task needs judgment or this session'\''s tools." + $jnote)}}
    end
' 2>/dev/null | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null || true)"

CONTRACT='Subagent budget (Rule 12, applies to this dispatch): the brief must say — never poll (no sleep/until/tail loops; ONE blocking wait); stop at ~120 tool calls or ~250K context and hand back a partial report; if the repo has a `graft/` index, run `graft ask "<query>" --source` or `graft skeleton <file>` before grepping or reading whole files; read excerpts (grep -n, then <=250-line ranges), <=2 screenshots; return <=15 lines. Review sizing (Rule 7): label every reviewer brief RISK: R0|R1|R2. R2 -> one consolidated reviewer; R1+/prod -> code-reviewer + language reviewer, ONE fix round. Fresh agent per fix round; do not continue a finished agent.'
printf '%s' "$INPUT_JSON" | jq -c --arg contract "$CONTRACT" --arg advisory "${ADVISORY:-}" '
  def s: if type == "string" then . else "" end;
  (.tool_name | s) as $tool
  | (if $tool == "invoke_subagent" then ((.tool_input.Subagents[0].TypeName // "") | s) else (.tool_input.subagent_type | s) end) as $subtype
  | (if $tool == "invoke_subagent" then (((.tool_input.Subagents // []) | map(.Prompt // "") | join(" ")) | s)
     elif $tool == "delegate_task" then ((.tool_input.task // "") | s)
     else (.tool_input.prompt | s) end) as $brief
  | select($tool == "Agent" or $tool == "Task" or $tool == "invoke_subagent" or $tool == "delegate_task")
  | select($subtype | test("^Explore$|^claude-code-guide$|^statusline-setup$") | not)
  | (if ($brief | test("Subagent budget|Worker budget|never poll"; "i")) then "" else $contract end) as $c
  | (($c + (if ($advisory | length) > 0 then (if ($c | length) > 0 then " " else "" end) + $advisory else "" end))) as $ctx
  | select(($ctx | length) > 0)
  | {hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $ctx}}
' 2>/dev/null || true
exit 0
