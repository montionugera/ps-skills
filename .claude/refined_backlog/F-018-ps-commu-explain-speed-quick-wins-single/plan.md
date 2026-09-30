# F-018 ps-commu-explain speed quick wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Speed up ps-commu-explain generation by moving mechanical work out of the model and into scripts, with less LLM bottleneck. User's words, verbatim: "want to speed up ps-commu generation, any builtin claude ability we can use, any room for improve, program so it need less LLM bottleneck".

**Architecture:** Extend the existing bash + embedded-python3 scripts in `skills/ps-commu-explain/scripts/`. No new do-everything script. `verify.sh` does one Chrome load per cycle and writes `page-text.txt`, and a new `--reader-prompt` mode builds the reader-gate prompt from it. The new `skeleton.sh` and `handoff.sh` scripts, a components index and a `log_timing` helper take mechanical text off the model. SKILL.md shrinks to at most 110 lines and routes check subagents to cheaper models.

**Tech Stack:** bash 3.2 (macOS `/usr/bin/env bash`: no `mapfile`, no `${x,,}`), python3 stdlib, headless Google Chrome (already required), the existing `tests/lifecycle_test.sh` harness.

**Spec:** `.claude/refined_backlog/F-018-ps-commu-explain-speed-quick-wins-single/spec.md`

## Global Constraints

- Exit codes for every new or changed script: 0 = success, 1 = a defect (listed), 2 = a precondition is missing (no workspace, no Chrome, no server, no `page-text.txt`). Callers treat 2 as SKIP, never as a pass.
- `--help` for every script comes from its header comment (`usage() { grep '^#' "$0" | cut -c3-; ... }`). A new flag or behaviour is documented there first.
- No new dependencies: bash, python3 stdlib, and the Chrome that `verify.sh` already finds.
- Every change is R2 and revertable with git. Make a new commit per task. Never `git commit --amend`.
- The live skill `~/.claude/skills/ps-commu-explain` is a symlink to the MAIN checkout (`/Users/pasitnusso/ps-skills/skills/ps-commu-explain`). Nothing here goes live until release 1.9 is promoted to main, so every test and timing run uses the feature worktree's scripts, never `~/.claude/skills/...` (except the Task 0 baseline, which deliberately measures the live skill).
- Scope is the spec and nothing more. Not added: a PostToolUse auto-lint hook (the spec's batch-grill rejected it, even though the feature title still names it), a diagram DSL (I-019), the declarative renderer, html/react authoring changes, or facts-subagent changes.

## Conventions used by every task

- `WT` = the feature worktree that `psrw claim F-018` creates. The expected path is `/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single`. If claim prints a different path, use that one. `SK` = `$WT/skills/ps-commu-explain`. Shell state does not persist between tool calls, so start every command with `WT=...; SK=$WT/skills/ps-commu-explain;`.
- The test harness registers tests explicitly (`check <name> <fn>` or `check_or_skip <name> <fn>`); there is no auto-discovery. A new test only runs once it is registered. Real-Chrome tests take about 45 s each, and a full run takes about 10 min. Task 1 adds an `ONLY=<regex>` filter so each TDD step can run just its own tests.
- New F-018 tests go in one block headed `# --- F-018: speed quick wins ---`. It sits immediately before `# --- list.sh / clean.sh ---`, because the clean tests wipe `/tmp/ps-commu` and must stay last. Each task appends its tests and its `check` lines to the end of that block.
- A task's commit is `git -C "$WT" add <files> && git -C "$WT" commit -m "<msg>"`, and every message ends with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Phase gate** (rule 7, runs automatically, not a permission stop): (1) verify: the task's `ONLY=` run plus `bash -n` on each touched script; (2) review: dispatch the `code-reviewer` agent on the task diff (`git -C "$WT" diff HEAD~N`), plus `python-reviewer` when a python heredoc changed; (3) run `/simplify` on the diff and apply its fixes; (4) re-verify: rerun step 1. Fix every finding before moving on, and commit the fixes as new commits.

---

## Task 0: Baseline timing (before any code change)

**Files:**
- Create: `$WT/.claude/refined_backlog/F-018-ps-commu-explain-speed-quick-wins-single/verification.md`

**Interfaces:**
- Consumes: the live skill `~/.claude/skills/ps-commu-explain/` (the MAIN checkout; on 2026-09-30 its `skills/ps-commu-explain` tree matched `release/1.9` exactly, per `git diff --stat main release/1.9 -- skills/ps-commu-explain`).
- Produces: `verification.md` with a `## Baseline (before)` table. Task 9 appends `## After` and `## Comparison`.

**Fixed topic (use it for both runs):** "How ps-commu-explain's `stop.sh` decides whether it may kill a server" (sources: `scripts/stop.sh`, `scripts/common.sh` `pid_has_marker`). Baseline slug: `f018-bench-before`. Task 9 slug: `f018-bench-after`.

- [ ] **Step 1: Create a Chrome launch counter (a wrapper around the real Chrome).**

```bash
SCR=/private/tmp/f018-bench; mkdir -p "$SCR"; : > "$SCR/chrome-launches.log"
REAL="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
cat > "$SCR/chrome-count" <<EOF
#!/usr/bin/env bash
echo "\$(date +%s) \$*" >> "$SCR/chrome-launches.log"
exec "$REAL" "\$@"
EOF
chmod +x "$SCR/chrome-count"
```

- [ ] **Step 2: Run one full explainer with the LIVE skill and time each script by hand.** Follow `~/.claude/skills/ps-commu-explain/SKILL.md` exactly as it is today: brief, then facts (subagent), then storyboard, then author (replace the exemplar content.md), then verify, then the reader gate, then handoff. Record the wall-clock start first. Prefix every script call with `time` and `CHROME_BIN=$SCR/chrome-count`:

```bash
date +%s > /private/tmp/f018-bench/before.start
L=~/.claude/skills/ps-commu-explain/scripts
time "$L/init.sh" f018-bench-before
# ... model authors 00-brief/01-facts/02-storyboard/app/content.md per SKILL.md ...
time "$L/lint.sh" f018-bench-before
time "$L/serve.sh" f018-bench-before
time CHROME_BIN=/private/tmp/f018-bench/chrome-count "$L/verify.sh" f018-bench-before
time CHROME_BIN=/private/tmp/f018-bench/chrome-count "$L/verify.sh" f018-bench-before --dump-text > /private/tmp/f018-bench/before-page.txt
# ... reader-gate subagent, fix cycles (repeat the verify pair per cycle) ...
date +%s > /private/tmp/f018-bench/before.end
wc -l < /private/tmp/f018-bench/chrome-launches.log
```

- [ ] **Step 3: Write `verification.md`.** Record the real numbers from Step 2:

```markdown
# F-018 verification notes

## Baseline (before), 2026-MM-DD, live skill (main checkout @ <git -C /Users/pasitnusso/ps-skills rev-parse --short HEAD>)

Topic: How ps-commu-explain's `stop.sh` decides whether it may kill a server. Slug: f018-bench-before.
Timed by hand with `time`; timings.log does not exist yet.

| step | real (s) | runs |
| --- | --- | --- |
| init.sh | | 1 |
| lint.sh | | |
| serve.sh | | |
| verify.sh (asserts) | | |
| verify.sh --dump-text | | |
| fix cycles | | |
| **total wall clock (end - start)** | | |
| Chrome launches (chrome-launches.log lines) | | per cycle: |
```

- [ ] **Step 4: Commit.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single
git -C "$WT" add .claude/refined_backlog/F-018-ps-commu-explain-speed-quick-wins-single/verification.md
git -C "$WT" commit -m "docs(F-018): baseline timing of one live-skill explainer run

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 1: `log_timing` helper, its calls, and the `ONLY` test filter

**Files:**
- Modify: `$SK/scripts/common.sh` (append after `parse_duration`, currently L58-70)
- Modify: `$SK/scripts/init.sh` (after L66-67 `ws=...; mkdir -p "$ws"`)
- Modify: `$SK/scripts/serve.sh` (after L33, the `[[ -d "$ws" ]]` check)
- Modify: `$SK/scripts/verify.sh` (after L107, the `[[ -d "$ws/app" ]]` check)
- Modify: `$SK/tests/lifecycle_test.sh` (`check()` L12-15, `check_or_skip()` L16-22; new F-018 block before `# --- list.sh / clean.sh ---`, ~L1654)

**Interfaces:**
- Produces: `log_timing <script> <seconds>` in `common.sh`. It appends one line, `<ISO-8601 UTC> <script> <seconds>`, to `$ws/timings.log`, where `$ws` is the calling script's workspace variable (all scripts already name it `ws`). With `$ws` unset or not a directory it does nothing. It never fails the caller.
- Produces: each script sets `trap 'log_timing <name>.sh "$SECONDS"' EXIT` right after its workspace check, so every call that reaches its workspace writes exactly one line, whatever the exit path.
- Produces (tests): `_stub_chrome <dir> page|fail`, a fake Chrome at `<dir>/chrome` that appends one line to `<dir>/launches` per launch and prints either a canned rendered page or nothing. `_vstub_ws` gives a served `init.sh --example` workspace `t-vstub`. The `ONLY` env filter picks tests by name regex.

- [ ] **Step 1: Add the `ONLY` filter to the harness** (test infrastructure only; with `ONLY` unset, nothing changes). In `lifecycle_test.sh`, add above `check(){` and put a guard at the top of both runners:

```bash
_selected() { [[ -z "${ONLY:-}" || "$1" =~ $ONLY ]]; }   # ONLY=<regex>: run only matching test names
check(){               # on FAIL, show the test's output so CI logs say why
  _selected "$1" || return 0
  local name="$1"; shift
  if "$@" >"$CHECK_LOG" 2>&1; then ok "$name"; else bad "$name"; tail -n 25 "$CHECK_LOG" | sed 's/^/    /'; fi
}
check_or_skip(){       # like check, but exit code 2 = visible SKIP (e.g. no Chrome) — never a pass
  _selected "$1" || return 0
  local name="$1"; shift; local rc
  ...unchanged...
```

- [ ] **Step 2: Write the failing tests.** Add the F-018 block:

```bash
# --- F-018: speed quick wins ---
_stub_chrome() {  # dir page|fail — fake Chrome at $dir/chrome; one line in $dir/launches per launch
  local dir="$1" mode="$2"
  mkdir -p "$dir"; : > "$dir/launches"
  if [[ "$mode" == page ]]; then
    printf '%s\n' '<html><body class="is-ready"><div class="cherry-previewer"><p>Stub page text for F-018.</p></div></body></html>' > "$dir/page.html"
  else
    : > "$dir/page.html"          # a failed load: no DOM at all
  fi
  cat > "$dir/chrome" <<EOF
#!/usr/bin/env bash
echo launch >> "$dir/launches"
cat "$dir/page.html"
EOF
  chmod +x "$dir/chrome"
}
_vstub_ws() {  # a served, lint-clean infographic workspace t-vstub (reused by F-018 verify tests)
  [[ -f /tmp/ps-commu/t-vstub/meta.json ]] || "$S/init.sh" t-vstub --example >/dev/null || return 1
  local pid; pid="$(meta_get t-vstub pid)"
  [[ -n "$pid" ]] && pid_has_marker "$pid" t-vstub && return 0
  "$S/serve.sh" t-vstub >/dev/null
}
test_log_timing_appends() {
  mkdir -p /tmp/ps-commu/t-timing; rm -f /tmp/ps-commu/t-timing/timings.log
  ( ws=/tmp/ps-commu/t-timing; log_timing demo.sh 3; log_timing demo.sh 4 )
  [[ "$(wc -l < /tmp/ps-commu/t-timing/timings.log | tr -d ' ')" == 2 ]] &&
  grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z demo\.sh 3$' /tmp/ps-commu/t-timing/timings.log
}
test_log_timing_noop_without_workspace() { ( unset ws; log_timing demo.sh 1 ) && ( ws=/nonexistent/x; log_timing demo.sh 1 ); }
test_scripts_log_timing() {  # init, serve and verify each add exactly one line per call
  rm -rf /tmp/ps-commu/t-timelog
  local d=/tmp/ps-commu/t-stub-timelog log=/tmp/ps-commu/t-timelog/timings.log
  _stub_chrome "$d" fail
  "$S/init.sh" t-timelog --example >/dev/null &&
  "$S/serve.sh" t-timelog >/dev/null || return 1
  CHROME_BIN="$d/chrome" "$S/verify.sh" t-timelog >/dev/null 2>&1   # fails fast on the empty DOM; still logged
  "$S/stop.sh" t-timelog >/dev/null
  cat "$log"
  [[ "$(grep -cE ' init\.sh [0-9]+$' "$log")" == 1 ]] &&
  [[ "$(grep -cE ' serve\.sh [0-9]+$' "$log")" == 1 ]] &&
  [[ "$(grep -cE ' verify\.sh [0-9]+$' "$log")" == 1 ]]
}
check log_timing_appends              test_log_timing_appends
check log_timing_noop_without_workspace test_log_timing_noop_without_workspace
check scripts_log_timing              test_scripts_log_timing
```

- [ ] **Step 3: Run the tests and confirm they FAIL.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
ONLY='log_timing|scripts_log_timing' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(PASS|FAIL|SKIP):|^-----' | tail -n 8
```
Expected: `FAIL: log_timing_appends`, `FAIL: scripts_log_timing` (`log_timing: command not found`), and `----- 0 passed, 2 failed` or `1 passed` (the no-op test may pass vacuously while the function is missing; the other two must fail).

- [ ] **Step 4: Implement.** Append to `common.sh`:

```bash
# Timing log (F-018): append "<ISO-8601 UTC> <script> <seconds>" to <workspace>/timings.log.
# The workspace is the caller's $ws (every ps-commu script names it that). Script time only —
# model time shows up as the gaps between entries. Never fails the caller.
log_timing() {  # script seconds
  [[ -n "${ws:-}" && -d "${ws:-}" ]] || return 0
  printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" >>"$ws/timings.log" 2>/dev/null || true
}
```

In `init.sh`, after `mkdir -p "$ws"` (L67):

```bash
trap 'log_timing init.sh "$SECONDS"' EXIT
```

In `serve.sh`, after L33 (`[[ -d "$ws" ]] || { ... }`):

```bash
trap 'log_timing serve.sh "$SECONDS"' EXIT
```

In `verify.sh`, after L107 (`[[ -d "$ws/app" ]] || { ... }`):

```bash
trap 'log_timing verify.sh "$SECONDS"' EXIT
```

- [ ] **Step 5: Run the tests and confirm they PASS, and that the existing init/serve tests still pass.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
ONLY='log_timing|scripts_log_timing|^init_|^serve_|marker_visible|bind_localhost|port_retry|watchdog|^stop' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(FAIL|SKIP):|^-----'
```
Expected: no `FAIL:` lines, and `----- N passed, 0 failed`. If `scripts_log_timing` shows 2 serve lines, the watchdog subshell inherited the trap. In that case add `trap - EXIT` as the first line inside serve.sh's backgrounded `( ... ) &` subshell (~L143) and re-run.

- [ ] **Step 6: Commit.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single
git -C "$WT" add skills/ps-commu-explain/scripts/common.sh skills/ps-commu-explain/scripts/init.sh skills/ps-commu-explain/scripts/serve.sh skills/ps-commu-explain/scripts/verify.sh skills/ps-commu-explain/tests/lifecycle_test.sh
git -C "$WT" commit -m "feat(ps-commu-explain): per-script timings.log via log_timing; ONLY= test filter (F-018)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Phase gate** (verify, then code-reviewer, then `/simplify`, then re-verify; see Conventions).

---

## Task 2: `verify.sh`: one Chrome load writes `page-text.txt`; `--dump-text` reuses it; stale and `--url` guards

**Files:**
- Modify: `$SK/scripts/verify.sh`: header L3 and L74-80 (`--dump-text` text); arg parse L92-104; after the Task 1 trap (~L108); the python invocation L227 (`python3 - "$chrome" "$url" "$fences" "$dump_text" "$tier" <<'PY'`) and its argv line L230; extraction L369-378 (KEEP L368 `pv = Preview(); pv.feed(dom)`).
- Modify: `$SK/tests/lifecycle_test.sh`: `test_verify_dump_text` (~L1202-1210), the F-018 block.

**Interfaces:**
- Produces: `<workspace>/page-text.txt` (`/tmp/ps-commu/<slug>/page-text.txt`, the workspace root, never served). It holds the exact reader-visible text that `Preview()` extracts, written only when that text is non-empty and `--url` was NOT passed. It is deleted at the start of every `verify.sh` run except `--reader-prompt` (Task 3).
- Unchanged: `--dump-text` stdout and exit codes (0 with text, 1 with no `.cherry-previewer`, 2 with no Chrome, no server, or the html tier). It now also writes `page-text.txt` through the same code path.
- Consumes: the Task 1 helpers `_stub_chrome` and `_vstub_ws`.

- [ ] **Step 1: Write the failing tests** (append to the F-018 block):

```bash
test_verify_one_load_writes_page_text() {  # asserts + page-text.txt from ONE Chrome launch
  _vstub_ws || return 1
  local d=/tmp/ps-commu/t-stub-one pt=/tmp/ps-commu/t-vstub/page-text.txt out
  _stub_chrome "$d" page; rm -f "$pt"
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub)"   # rc 1 expected: the stub page has no diagram
  echo "$out"
  [[ "$(wc -l < "$d/launches" | tr -d ' ')" == 1 ]] &&
  grep -q '^PASS: 2 ' <<<"$out" && grep -q '^PASS: 3 ' <<<"$out" && grep -q '^PASS: 8 ' <<<"$out" &&
  grep -q '^PASS: 6 ' <<<"$out" &&
  [[ "$(cat "$pt")" == "Stub page text for F-018." ]]
}
test_verify_dump_text_same_path() {  # --dump-text: one launch, stdout == page-text.txt
  _vstub_ws || return 1
  local d=/tmp/ps-commu/t-stub-dump pt=/tmp/ps-commu/t-vstub/page-text.txt out rc
  _stub_chrome "$d" page; rm -f "$pt"
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub --dump-text)"; rc=$?
  (( rc == 0 )) && [[ "$(wc -l < "$d/launches" | tr -d ' ')" == 1 ]] &&
  [[ "$out" == "Stub page text for F-018." ]] && [[ "$out" == "$(cat "$pt")" ]]
}
test_verify_failed_load_leaves_no_page_text() {  # stale copy from an earlier run must not survive
  _vstub_ws || return 1
  local d=/tmp/ps-commu/t-stub-fail pt=/tmp/ps-commu/t-vstub/page-text.txt rc
  _stub_chrome "$d" fail; echo STALE > "$pt"
  CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub >/dev/null 2>&1; rc=$?
  (( rc == 1 )) && [[ ! -e "$pt" ]]
}
test_verify_url_writes_no_page_text() {  # --url may load another doc: never written, stale copy removed
  _vstub_ws || return 1
  local d=/tmp/ps-commu/t-stub-url pt=/tmp/ps-commu/t-vstub/page-text.txt port out
  _stub_chrome "$d" page; echo STALE > "$pt"; port="$(meta_get t-vstub port)"
  CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub --url "http://127.0.0.1:$port/" >/dev/null 2>&1
  [[ ! -e "$pt" ]] || return 1
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub --url "http://127.0.0.1:$port/" --dump-text)" &&
  [[ "$out" == "Stub page text for F-018." ]] && [[ ! -e "$pt" ]]
}
check verify_one_load_writes_page_text        test_verify_one_load_writes_page_text
check verify_dump_text_same_path              test_verify_dump_text_same_path
check verify_failed_load_leaves_no_page_text  test_verify_failed_load_leaves_no_page_text
check verify_url_writes_no_page_text          test_verify_url_writes_no_page_text
```

Also extend the real-Chrome `test_verify_dump_text` (~L1202) so the real page proves the same equality. Add before its final condition chain:

```bash
  [[ "$out" == "$(cat /tmp/ps-commu/t-verify/page-text.txt 2>/dev/null)" ]] || { echo "stdout != page-text.txt"; return 1; }
```

- [ ] **Step 2: Run and confirm FAIL.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
ONLY='^verify_(one_load|dump_text_same|failed_load|url_writes)' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(PASS|FAIL|SKIP):|^-----'
```
Expected: `FAIL: verify_one_load_writes_page_text` and `FAIL: verify_dump_text_same_path` (no `page-text.txt`), and `FAIL: verify_failed_load_leaves_no_page_text` and `FAIL: verify_url_writes_no_page_text` (the STALE file survives).

- [ ] **Step 3: Implement.** Arg parse (L92-104): track whether `--url` was given.

```bash
slug="" url="" url_given=0 dump_text=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) [[ $# -ge 2 ]] || { echo "--url requires a value" >&2; exit 1; }
           url="$2"; url_given=1; shift ;;
```

After the Task 1 `trap` line:

```bash
# page-text.txt (F-018) is the reader gate's input, written by the SAME Chrome load as
# the asserts. Delete it up front so a failed load, a missing Chrome, the html tier or a
# --url run (which may load a different doc) can never leave a stale copy behind. The
# python block rewrites it only after extracting non-empty text on a non---url run.
page_text="$ws/page-text.txt"
rm -f "$page_text"
text_out="$page_text"; [[ "$url_given" == 1 ]] && text_out=""
```

Python invocation (L227) and argv (L231):

```bash
python3 - "$chrome" "$url" "$fences" "$dump_text" "$tier" "$text_out" <<'PY'
```
```python
chrome, url, fences, dump_text, tier, text_out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4] == "1", sys.argv[5], sys.argv[6]
```

Replace L369-378 of the extraction block with the snippet below. **Keep L368 `pv = Preview(); pv.feed(dom)` untouched.** Deleting it makes every infographic run fail with a NameError on `pv`.

```python
text, prose = "".join(pv.text), "".join(pv.prose)
no_preview_msg = "no .cherry-previewer subtree in the dump (page did not render)"
# One extraction feeds all three consumers: page-text.txt, --dump-text and asserts 2/3/8.
if dump_text and text.strip() and text_out:
    with open(text_out, "w", encoding="utf-8") as f:
        f.write(text)
if dump_text:
    # Backward-compatible text-export mode: same load, same extraction, same file.
    if not pv.text:
        sys.stderr.write(f"FAIL: {no_preview_msg}\n")
        sys.exit(1)
    sys.stdout.write(text)
    sys.exit(0)
```

In the assert run, `page-text.txt` must come only from a run that passed, so a partial render never reaches the reader gate. Directly before the final `sys.exit(1 if failed else 0)` (verify.sh L426), add:

```python
if not failed and text.strip() and text_out:
    with open(text_out, "w", encoding="utf-8") as f:
        f.write(text)
```

Add to `test_verify_failed_load_leaves_no_page_text`, or a sibling stub test, a case where the stub DOM renders but an assert FAILs (e.g. an `explainer-error` body). Expected: no `page-text.txt`.

Header comment: change L3 to `# Usage: verify.sh <slug> [--url URL] [--dump-text] [--reader-prompt]`. Replace the `--dump-text` paragraph (L74-80) with:

```bash
#   page-text.txt  every infographic run (asserts or --dump-text) also writes the
#          clean, reader-visible page text to /tmp/ps-commu/<slug>/page-text.txt
#          from the SAME Chrome load: one load per verify cycle. It is deleted at
#          the start of every run and written only when the extracted text is
#          non-empty, never under --url (which may load a different doc).
#   --dump-text  skip the PASS/FAIL asserts; print that same page text to stdout
#          and exit 0 (kept for backward compatibility; a plain run already writes
#          page-text.txt). It reuses the .cherry-previewer extractor the asserts
#          use, never a raw --dump-dom (that holds toolbar/source-pane copies, raw
#          data-nav markup and unrendered ```drawio fences). Exit 1 if the page
#          never rendered a .cherry-previewer subtree; 2 if Chrome/server is
#          unavailable, same as the normal run.
```

- [ ] **Step 4: Run and confirm PASS, including the real-Chrome regression tests.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
ONLY='^verify_' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(PASS|FAIL|SKIP):|^-----'
```
Expected: all four new tests PASS. The existing `verify_*` tests PASS, or SKIP visibly when Chrome is absent. No `FAIL:`. (Until Task 4, `verify_passes_template` still uses the plain init plus `--no-lint`, and it still passes.)

- [ ] **Step 5: Commit.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single
git -C "$WT" add skills/ps-commu-explain/scripts/verify.sh skills/ps-commu-explain/tests/lifecycle_test.sh
git -C "$WT" commit -m "perf(ps-commu-explain): one Chrome load per verify cycle writes page-text.txt (F-018)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(Phase gate shared with Task 3.)

---

## Task 3: `verify.sh --reader-prompt`

**Files:**
- Modify: `$SK/scripts/verify.sh`: header (add the `--reader-prompt` paragraph after the `--dump-text` one); arg parse; a new branch placed AFTER the Task 1 trap and BEFORE the Task 2 `rm -f "$page_text"`.
- Modify: `$SK/tests/lifecycle_test.sh`: the F-018 block.

**Interfaces:**
- Consumes: `/tmp/ps-commu/<slug>/page-text.txt` (Task 2) and `/tmp/ps-commu/<slug>/00-brief.md` (the `Reader:` line and `Q1:`-`Q3:` lines, HTML comments stripped the same way `lint.sh` strips them).
- Produces on stdout: first line exactly `Agent model: sonnet`, then the reader-gate prompt. The prompt is SKILL.md L76-105's verbatim text with two changes: the `PAGE TEXT (from <URL>)` block becomes an instruction to read one file by its absolute path, and the brackets are filled. Exit 0. Exit 2 when `page-text.txt` is missing or empty (`run verify.sh <slug> first`), or when the brief lacks a filled `Reader:` line or Q1-Q3. It never launches Chrome and never deletes `page-text.txt`.
- The verbatim prompt now lives only here. SKILL.md drops its copy in Task 8.

- [ ] **Step 1: Write the failing tests** (append to the F-018 block):

```bash
test_reader_prompt_needs_page_text() {
  _vstub_ws || return 1
  rm -f /tmp/ps-commu/t-vstub/page-text.txt
  local out rc; out="$("$S/verify.sh" t-vstub --reader-prompt 2>&1)"; rc=$?
  echo "$out"
  (( rc == 2 )) && grep -qF 'run verify.sh t-vstub first' <<<"$out"
}
test_reader_prompt_fills_brief_and_path() {  # path, not contents; no Chrome; Sonnet first line
  _vstub_ws || return 1
  local d=/tmp/ps-commu/t-stub-rp ws=/tmp/ps-commu/t-vstub out rc q
  _stub_chrome "$d" page
  printf 'PAGE BODY SENTINEL 7f3a\n' > "$ws/page-text.txt"
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub --reader-prompt)"; rc=$?
  echo "$out" | head -n 12
  (( rc == 0 )) || return 1
  [[ "$(head -n1 <<<"$out")" == "Agent model: sonnet" ]] || return 1
  grep -qF "THE PAGE'S INTENDED READER: $(sed -n 's/^Reader:[[:space:]]*//p' "$ws/00-brief.md")" <<<"$out" || return 1
  for q in Q1 Q2 Q3; do grep -qF "$(grep "^$q:" "$ws/00-brief.md")" <<<"$out" || return 1; done
  grep -qxF "$ws/page-text.txt" <<<"$out" &&
  ! grep -q 'SENTINEL 7f3a' <<<"$out" &&
  [[ ! -s "$d/launches" ]] &&
  [[ -f "$ws/page-text.txt" ]]          # --reader-prompt must not delete its own input
}
check reader_prompt_needs_page_text      test_reader_prompt_needs_page_text
check reader_prompt_fills_brief_and_path test_reader_prompt_fills_brief_and_path
```

- [ ] **Step 2: Run and confirm FAIL.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
ONLY='^reader_prompt_' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(PASS|FAIL|SKIP):|^-----'
```
Expected: both FAIL. `--reader-prompt` is not parsed yet (it falls into `*) slug=...`), so the run becomes a normal verify.

- [ ] **Step 3: Implement.** Arg parse: add `reader_prompt=0` to the init line and a case:

```bash
    --reader-prompt) reader_prompt=1 ;;
```

The new branch, after the trap and before `page_text=...; rm -f`:

```bash
# --reader-prompt (F-018): print the reader-gate prompt, filled from 00-brief.md, pointing
# at page-text.txt by ABSOLUTE PATH (the reader subagent reads it itself, so the main
# model never re-types the page). No Chrome; never deletes page-text.txt.
if [[ "$reader_prompt" == 1 ]]; then
  [[ -s "$ws/page-text.txt" ]] || { echo "no page text at $ws/page-text.txt: run verify.sh $slug first" >&2; exit 2; }
  [[ "$ws/app/content.md" -nt "$ws/page-text.txt" ]] && { echo "stale page text: app/content.md changed after the last verify; run verify.sh $slug again" >&2; exit 2; }
  python3 - "$ws/00-brief.md" "$ws/page-text.txt" <<'PY'
import re, sys
brief_path, page_text = sys.argv[1], sys.argv[2]
try:
    with open(brief_path, encoding="utf-8") as f:
        brief = re.sub(r"<!--.*?-->", "", f.read(), flags=re.S)
except OSError as e:
    sys.stderr.write(f"cannot read {brief_path}: {e}\n"); sys.exit(2)
reader = re.search(r"(?mi)^Reader:[ \t]*(\S.*)$", brief)
qs = dict(re.findall(r"(?m)^Q([1-3]):[ \t]*(\S.*)$", brief))
if not reader or sorted(qs) != ["1", "2", "3"]:
    sys.stderr.write(f"{brief_path}: needs a filled Reader: line and Q1-Q3 (run lint.sh)\n"); sys.exit(2)
print(f"""Agent model: sonnet
You are an independent reader. You have NOT seen this project's 00-brief.md, 01-facts.md,
02-storyboard.md, or any source file — only the page text in the ONE file named below, exactly
as a browser would render it. Do not use outside knowledge, do not guess, do not infer from a
file you were not given.

THE PAGE'S INTENDED READER: {reader.group(1).strip()}
Read as that person — you know nothing beyond what they know.

PAGE TEXT: read this one file with the Read tool, and no other file:
{page_text}

Answer these three questions using ONLY that page text:
Q1: {qs["1"].strip()}
Q2: {qs["2"].strip()}
Q3: {qs["3"].strip()}

For each: give a 1-3 sentence answer, then cite the F<n> id(s) the page itself attributes to
that claim. Never invent a citation. If the text doesn't answer a question, write UNANSWERABLE
and name what's missing.

Then list every term, acronym, ID, or codename the page uses BEFORE (or without) explaining it
in plain words, as that reader would stumble on it. F<n> citation markers don't count.

Return exactly this, nothing else:
Q1: <answer> — F<n>[, F<n>...]
Q2: <answer> — F<n>[, F<n>...]
Q3: <answer> — F<n>[, F<n>...]
Unexplained terms: <comma-separated list, or "none">
Verdict: PASS (all three answered with real citations AND no unexplained terms) | FAIL (name which failed and why)""")
PY
  exit $?
fi
```

Header comment, after the `--dump-text` paragraph:

```bash
#   --reader-prompt  print the reader-gate prompt (the single source of its text):
#          line 1 is "Agent model: sonnet" (pass it as the Agent tool's model),
#          the rest is the prompt to paste verbatim, filled with 00-brief.md's
#          Reader: line and Q1-Q3 and the ABSOLUTE path to page-text.txt (never
#          its contents; the subagent reads that one file itself). Starts no
#          Chrome. Exit 2 if page-text.txt is missing (run verify.sh <slug>
#          first) or the brief lacks Reader:/Q1-Q3.
```

- [ ] **Step 4: Run and confirm PASS.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
ONLY='^reader_prompt_|^verify_(one_load|dump_text_same|failed_load|url_writes)|verify_help' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(PASS|FAIL|SKIP):|^-----'
```
Expected: 7 PASS, 0 failed.

- [ ] **Step 5: Commit.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single
git -C "$WT" add skills/ps-commu-explain/scripts/verify.sh skills/ps-commu-explain/tests/lifecycle_test.sh
git -C "$WT" commit -m "feat(ps-commu-explain): verify.sh --reader-prompt prints the filled reader-gate prompt (F-018)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Phase gate for Tasks 2-3** (verify.sh diff since the Task 1 commit): the `ONLY='^verify_|^reader_prompt_'` run and `bash -n "$SK/scripts/verify.sh"`, then `code-reviewer` plus `python-reviewer` (the heredocs changed), then `/simplify`, then re-verify.

---

## Task 4: `init.sh` moves the exemplar aside; `lint.sh` flags a missing `content.md` and `TODO(` lines on the infographic tier; two tests switch to `--example`

**Files:**
- Modify: `$SK/scripts/init.sh`: header L6-16; scaffold block L74-79.
- Modify: `$SK/scripts/lint.sh`: the python invocation L57 (`python3 - "$ws" <<'PY'`); argv L60-61; after `content = read(content_path)` L84; header L4 and L19-36 (the stale Mermaid-scanner text; the whole header rewrite is done here so `--help` is right from this task on).
- Modify: `$SK/tests/lifecycle_test.sh`: `test_verify_passes_template` L1177-1200; the F-018 block.

**Interfaces:**
- Produces: plain `init.sh <slug>` on the infographic tier leaves `app/example-content.md` (a byte-copy of `assets/template-infographic/content.md`) and NO `app/content.md`. `init.sh --example <slug>` is unchanged (`app/content.md` is the exemplar).
- Produces (lint, infographic tier only, tier read via `meta_get <slug> tier`): the defect `missing app/content.md: run skeleton.sh <slug>` when `app/content.md` is absent, and `app/content.md: unfilled skeleton line: <line>` for every line that contains `TODO(`. html/react behaviour is unchanged.

- [ ] **Step 1: Write the failing tests** (append to the F-018 block):

```bash
test_init_default_moves_exemplar() {
  rm -rf /tmp/ps-commu/t-initex
  "$S/init.sh" t-initex >/dev/null &&
  [[ ! -e /tmp/ps-commu/t-initex/app/content.md ]] &&
  cmp -s /tmp/ps-commu/t-initex/app/example-content.md "$SKILL_DIR/assets/template-infographic/content.md"
}
test_lint_flags_missing_content_infographic() {
  rm -rf /tmp/ps-commu/t-lint-nocontent
  "$S/init.sh" t-lint-nocontent >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-nocontent
  local out; out="$("$S/lint.sh" t-lint-nocontent)" && return 1
  echo "$out"
  grep -qxF 'missing app/content.md: run skeleton.sh t-lint-nocontent' <<<"$out"
}
test_lint_rejects_todo_line_infographic() {
  rm -rf /tmp/ps-commu/t-lint-todo
  "$S/init.sh" t-lint-todo >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-todo
  printf 'Intro (F1).\n\nTODO(Q1; F1): 1\n' > /tmp/ps-commu/t-lint-todo/app/content.md
  local out; out="$("$S/lint.sh" t-lint-todo)" && return 1
  echo "$out"
  grep -qxF 'app/content.md: unfilled skeleton line: TODO(Q1; F1): 1' <<<"$out" || return 1
  printf 'Intro (F1).\n\nFilled in plain words (F1).\n' > /tmp/ps-commu/t-lint-todo/app/content.md
  "$S/lint.sh" t-lint-todo
}
test_lint_help_describes_drawio_not_mermaid_scanner() {
  local h; h="$("$S/lint.sh" --help)"
  ! grep -q 'Mermaid flowchart edges' <<<"$h" && ! grep -q 'sequenceDiagram' <<<"$h" &&
  grep -q 'drawio' <<<"$h" && grep -qF 'TODO(' <<<"$h" && grep -q 'skeleton.sh' <<<"$h"
}
check init_default_moves_exemplar                  test_init_default_moves_exemplar
check lint_flags_missing_content_infographic       test_lint_flags_missing_content_infographic
check lint_rejects_todo_line_infographic           test_lint_rejects_todo_line_infographic
check lint_help_describes_drawio_not_mermaid       test_lint_help_describes_drawio_not_mermaid_scanner
```

Switch `test_verify_passes_template` (L1177-1200) to `--example`. Replace its first comment block and its two setup lines with:

```bash
test_verify_passes_template() {
  # --example pairs the shipped exemplar content.md with its matching filled
  # 00-brief/01-facts/02-storyboard, so it lints clean and serves through the
  # real lint gate (F-018: a plain init no longer ships app/content.md).
  rm -rf /tmp/ps-commu/t-verify
  "$S/init.sh" t-verify --example >/dev/null
  "$S/serve.sh" t-verify >/dev/null
```

(Keep the rest of the function. Also add after its `(( rc == 2 )) && return 2` line: `[[ -s /tmp/ps-commu/t-verify/page-text.txt ]] || { echo "no page-text.txt after a real run"; return 1; }`.) `test_verify_dump_text` reuses `t-verify`, so it inherits `--example` and needs no setup change.

- [ ] **Step 2: Run and confirm FAIL.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
ONLY='init_default_moves|lint_flags_missing_content|lint_rejects_todo|lint_help_describes' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(PASS|FAIL|SKIP):|^-----'
```
Expected: all 4 FAIL (content.md is still copied; lint treats a missing content.md as fine and ignores TODO(; the header still describes the Mermaid scanner).

- [ ] **Step 3: Implement `init.sh`.** Replace L74-79:

```bash
tpl="$(cd "$(dirname "$0")/.." && pwd)/assets/template-$tier"
if [[ -d "$tpl" && ! -e "$ws/app/index.html" ]]; then
  mkdir -p "$ws/app"
  cp -R "$tpl"/. "$ws/app"/
  # F-018: the model should not start by reading and deleting a 281-line exemplar.
  # A plain infographic init keeps it at app/example-content.md; skeleton.sh writes
  # app/content.md from the storyboard. --example keeps the exemplar AS content.md.
  if [[ "$tier" == "infographic" && "$example" == 0 && -f "$ws/app/content.md" ]]; then
    mv "$ws/app/content.md" "$ws/app/example-content.md"
  fi
  echo "scaffolded app/ from template-$tier"
fi
```

Header L6-7 and L10-16 become:

```bash
#              infographic  cream Markdown-driven explainer (cherry-markdown);
#                           author app/content.md: fill the chain, then run
#                           skeleton.sh <slug> to draft it. The exemplar ships
#                           at app/example-content.md (read-only reference).
#   --example  scaffold the filled exemplar chain instead of empty skeletons:
#              assets/workspace/example/'s filled 00-brief.md/01-facts.md/
#              02-storyboard.md, plus the exemplar as app/content.md (not
#              moved to example-content.md). Forces --tier infographic
#              (errors if combined with another --tier).
#              `init.sh --example <slug> && serve.sh <slug>` passes lint.sh
#              and verify.sh out of the box — no authoring required.
```

- [ ] **Step 4: Implement `lint.sh`.** Pass the tier into python (L57):

```bash
python3 - "$ws" "$(meta_get "$slug" tier)" <<'PY'
```

After `ws = sys.argv[1]` add `tier = sys.argv[2]` and `slug = os.path.basename(ws.rstrip('/'))`. After `content = read(content_path)` (L84) add:

```python
# Infographic tier (F-018): content.md is required, and an unfilled skeleton.sh
# placeholder (a TODO( line) is a defect, so the serve.sh lint gate enforces it.
if tier == 'infographic':
    if content is None:
        defects.append(f"missing app/content.md: run skeleton.sh {slug}")
    else:
        for ln in content.splitlines():
            if ln.startswith('TODO('):  # line-start only: skeleton.sh always emits it there; code samples mentioning TODO( stay legal
                defects.append(f"app/content.md: unfilled skeleton line: {ln.strip()[:120]}")
```

Header: L4 becomes `#   Checks the workspace's authoring docs and app/content.md (required on the` / `#   infographic tier; checked only if present on html/react).` Replace L19-36 (from `#     app/content.md (only checked if present):` through `#                       (fail closed) — never silently skipped.`) with:

```bash
#     app/content.md:   every F<n> mentioned exists in 01-facts.md; forbidden
#                       classes absent (stat-grid, stat-tile, meter, cat-*,
#                       metric-grid, card-grid); every ```drawio fence (and any
#                       fence whose body starts with <mxGraphModel, mirroring
#                       cherry-setup.js) is parsed as mxGraph XML: well-formed,
#                       both root cells, unique ids, vertex/edge exclusivity,
#                       every edge labelled, <=7 vertices, no overlapping or
#                       out-of-bounds vertices, no literal '<' or '&' in a
#                       label (&lt;br&gt; is the one allowed break), and
#                       role=accent|pitfall|check instead of raw hex colours.
#     infographic tier only: app/content.md must exist ("missing
#                       app/content.md: run skeleton.sh <slug>") and must hold
#                       no line containing TODO( (an unfilled skeleton.sh
#                       placeholder). html/react: content.md is optional.
```

- [ ] **Step 5: Run and confirm PASS, plus every existing lint and init test and the two switched verify tests.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
ONLY='^init_|^lint_|serve_refuses_unlinted|verify_passes_template|verify_dump_text$' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(FAIL|SKIP):|^-----'
```
Expected: no `FAIL:` (the two verify tests may SKIP only when Chrome is absent), and `----- N passed, 0 failed`.

- [ ] **Step 6: Commit.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single
git -C "$WT" add skills/ps-commu-explain/scripts/init.sh skills/ps-commu-explain/scripts/lint.sh skills/ps-commu-explain/tests/lifecycle_test.sh
git -C "$WT" commit -m "feat(ps-commu-explain): exemplar moves to example-content.md; lint requires content.md and rejects TODO( on infographic (F-018)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Phase gate** (init/lint diff): verify, then `code-reviewer` plus `python-reviewer`, then `/simplify`, then re-verify.

---

## Task 5: `scripts/skeleton.sh`

**Files:**
- Create: `$SK/scripts/skeleton.sh` (chmod +x)
- Modify: `$SK/tests/lifecycle_test.sh`: the F-018 block.

**Interfaces:**
- Consumes: `00-brief.md` (Q1-Q3), `01-facts.md` (rows `F<n> | statement | source`, parsed with the same regex as lint.sh), `02-storyboard.md` (rows `section | question | facts`, skipping the header, the separator and any row containing `(...)`), all with `<!-- -->` stripped; `meta_get <slug> tier`.
- Produces: `app/content.md` with (a) a `reader-questions` block holding Q1-Q3; (b) per storyboard row, a `section-head` block (`data-nav=<title>`, `data-nav-icon="hash"`, which is cherry-setup.js's own default icon, `id=<alnum title>`) followed by exactly one plain-Markdown line `TODO(<questions>; <facts>): <storyboard section cell>`, e.g. `TODO(Q1; F1,F2): 1 Overview`; (c) a `receipts` footer, one `<li><span class="receipts-fact">F<n></span> <source> — <statement></li>` per distinct cited fact in numeric order. It never emits `<!--`. It logs through `log_timing skeleton.sh`.
- Exit: 0 written; 1 refused (content.md exists and no `--force`) or no filled storyboard rows; 2 no workspace or `app/`, tier is not infographic, or a chain file is missing.

- [ ] **Step 1: Write the failing tests** (append to the F-018 block):

```bash
_skel_ws() {  # t-skel: the filled --example chain with NO app/content.md
  rm -rf /tmp/ps-commu/t-skel
  "$S/init.sh" t-skel --example >/dev/null && rm -f /tmp/ps-commu/t-skel/app/content.md
}
test_skeleton_writes_todo_per_row() {
  _skel_ws || return 1
  "$S/skeleton.sh" t-skel || return 1
  local c=/tmp/ps-commu/t-skel/app/content.md rows
  rows="$(grep -cE '^\| *[0-9]' /tmp/ps-commu/t-skel/02-storyboard.md)"
  (( rows == 7 )) && [[ "$(grep -c '^TODO(' "$c")" == "$rows" ]] &&
  grep -qxF 'TODO(Q1; F1,F2): 1 Overview' "$c" &&
  ! grep -qF '<!--' "$c" &&
  grep -q 'class="reader-questions"' "$c" &&
  grep -qF '<span class="receipts-fact">F19</span>' "$c" &&
  [[ "$(grep -cE ' skeleton\.sh [0-9]+$' /tmp/ps-commu/t-skel/timings.log)" == 1 ]]
}
test_skeleton_lint_gate() {  # unfilled: lint rejects; every TODO( replaced with cited prose: lint accepts
  _skel_ws && "$S/skeleton.sh" t-skel >/dev/null || return 1
  local c=/tmp/ps-commu/t-skel/app/content.md out
  out="$("$S/lint.sh" t-skel)" && return 1
  [[ "$(grep -c 'unfilled skeleton line' <<<"$out")" == 7 ]] || { echo "$out"; return 1; }
  sed -i.bak -E 's/^TODO\(.*$/This section is explained in plain words (F1)./' "$c" && rm -f "$c.bak"
  "$S/lint.sh" t-skel
}
test_skeleton_refuses_overwrite() {
  _skel_ws || return 1
  local c=/tmp/ps-commu/t-skel/app/content.md rc
  echo 'authored work' > "$c"
  "$S/skeleton.sh" t-skel 2>/dev/null; rc=$?
  (( rc == 1 )) && grep -qx 'authored work' "$c" &&
  "$S/skeleton.sh" t-skel --force >/dev/null && grep -q '^TODO(' "$c"
}
test_skeleton_preconditions() {  # exit 2: no workspace; non-infographic tier
  local rc
  "$S/skeleton.sh" t-no-such-ws-xyz 2>/dev/null; rc=$?; (( rc == 2 )) || return 1
  rm -rf /tmp/ps-commu/t-skel-html; "$S/init.sh" t-skel-html --tier html >/dev/null
  "$S/skeleton.sh" t-skel-html 2>/dev/null; rc=$?; (( rc == 2 )) &&
  "$S/skeleton.sh" --help | grep -q 'Usage: skeleton.sh'
}
check skeleton_writes_todo_per_row test_skeleton_writes_todo_per_row
check skeleton_lint_gate           test_skeleton_lint_gate
check skeleton_refuses_overwrite   test_skeleton_refuses_overwrite
check skeleton_preconditions       test_skeleton_preconditions
```

- [ ] **Step 2: Run and confirm FAIL.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
ONLY='^skeleton_' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(PASS|FAIL|SKIP):|^-----'
```
Expected: all 4 FAIL (`skeleton.sh: No such file or directory`).

- [ ] **Step 3: Implement `$SK/scripts/skeleton.sh`:**

```bash
#!/usr/bin/env bash
# skeleton.sh — draft app/content.md from the authoring chain (infographic tier).
# Usage: skeleton.sh <slug> [--force]
#   Reads 00-brief.md (Q1-Q3), 01-facts.md (F<n> rows) and 02-storyboard.md
#   (one row per section) and writes app/content.md:
#     - the reader-questions block (the brief's Q1-Q3)
#     - per storyboard row: a section-head block, then ONE placeholder line
#         TODO(<questions>; <facts>): <storyboard section text>
#       Plain Markdown, never an HTML comment (Cherry renders `<!--` as literal
#       page text). lint.sh rejects any remaining TODO( line on the
#       infographic tier, so an unfilled skeleton cannot be served. Replace
#       each one with prose that cites its facts.
#     - a Receipts footer: every fact the storyboard cites, with its source.
#   --force  overwrite an existing app/content.md (default: refuse, so authored
#            work is never destroyed).
# Exit 0 = written; 1 = refused (content.md exists) or no filled storyboard
# rows; 2 = cannot run (no workspace, not the infographic tier, a chain file
# missing).
set -uo pipefail
source "$(dirname "$0")/common.sh"

usage() { grep '^#' "$0" | cut -c3-; exit "${1:-0}"; }
slug="" force=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) force=1 ;;
    -h|--help) usage ;;
    *) slug="$1" ;;
  esac
  shift
done
[[ -n "$slug" ]] || usage 1
ws="$PS_COMMU_ROOT/$slug"
[[ -d "$ws/app" ]] || { echo "no workspace app dir: $ws/app (run init.sh first)" >&2; exit 2; }
trap 'log_timing skeleton.sh "$SECONDS"' EXIT
tier="$(meta_get "$slug" tier)"
[[ "$tier" == "infographic" ]] || { echo "skeleton.sh is infographic-tier only (tier='$tier')" >&2; exit 2; }
for f in 00-brief.md 01-facts.md 02-storyboard.md; do
  [[ -f "$ws/$f" ]] || { echo "missing $ws/$f (run init.sh, then fill it)" >&2; exit 2; }
done
if [[ -e "$ws/app/content.md" && "$force" != 1 ]]; then
  echo "refusing to overwrite $ws/app/content.md (pass --force to replace it)" >&2
  exit 1
fi

python3 - "$ws" <<'PY'
import html, os, re, sys

ws = sys.argv[1]


def read(name):
    with open(os.path.join(ws, name), encoding="utf-8") as f:
        return re.sub(r"<!--.*?-->", "", f.read(), flags=re.S)


def esc(s):
    return html.escape(s, quote=False)


brief, facts, story = read("00-brief.md"), read("01-facts.md"), read("02-storyboard.md")
qs = dict(re.findall(r"(?m)^Q([1-3]):[ \t]*(\S.*)$", brief))
fact_rows = {
    f"F{n}": (stmt.strip(), src.strip())
    for n, stmt, src in re.findall(r"(?m)^\s*\|?\s*F(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|?\s*$", facts)
}
rows = []
for sec, q, fc in re.findall(r"(?m)^\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$", story):
    if re.fullmatch(r"-{2,}", sec) or sec.lower() == "section" or "(...)" in sec + q + fc:
        continue
    rows.append((sec, re.sub(r"\s+", "", q), re.sub(r"\s+", "", fc)))
if not rows:
    sys.stderr.write("02-storyboard.md: no filled rows (fill it and run lint.sh first)\n")
    sys.exit(1)

out = ['<div class="reader-questions">',
       '  <div class="rq-kicker"><i data-lucide="help-circle"></i> This explainer answers</div>',
       '  <div class="rq-list">']
for n in ("1", "2", "3"):
    out.append(f'    <div class="rq-q"><span class="rq-num">{n}</span>'
               f'<span class="rq-text">{esc(qs.get(n, "").strip())}</span></div>')
out += ["  </div>", "</div>", ""]

ids, cited = set(), []
for i, (sec, q, fc) in enumerate(rows, 1):
    title = re.sub(r"^\d+[.)]?\s*", "", sec) or f"Section {i}"
    sid = re.sub(r"[^a-z0-9]", "", title.lower()) or f"s{i}"
    while sid in ids:
        sid += "x"
    ids.add(sid)
    out += [f'<div class="section-head" data-nav="{html.escape(title)}" data-nav-icon="hash" id="{sid}">',
            '  <span class="icon-chip lg"><i data-lucide="hash"></i></span>',
            '  <div class="sh-text">',
            f'    <span class="sh-kicker">{i}</span>',
            f'    <div class="sh-title">{esc(title)}</div>',
            "  </div>", "</div>", "",
            f"TODO({q}; {fc}): {sec}", ""]
    for fid in re.findall(r"F\d+", fc):
        if fid not in cited:
            cited.append(fid)

out += ['<div class="receipts">',
        '  <div class="receipts-label"><i data-lucide="receipt"></i> Receipts</div>',
        '  <ul class="receipts-list">']
for fid in sorted(cited, key=lambda f: int(f[1:])):
    stmt, src = fact_rows.get(fid, ("(missing from 01-facts.md)", "?"))
    out.append(f'    <li><span class="receipts-fact">{fid}</span> {esc(src)} — {esc(stmt)}</li>')
out += ["  </ul>", "</div>", ""]

path = os.path.join(ws, "app", "content.md")
with open(path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"wrote {path}: {len(rows)} sections, {len(cited)} receipts. "
      "Replace every TODO( line with cited prose, then serve.sh.")
PY
```

```bash
chmod +x "$SK/scripts/skeleton.sh"
```

- [ ] **Step 4: Run and confirm PASS.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
bash -n "$SK/scripts/skeleton.sh" && ONLY='^skeleton_' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(PASS|FAIL|SKIP):|^-----'
```
Expected: 4 PASS, 0 failed.

- [ ] **Step 5: Commit.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single
git -C "$WT" add skills/ps-commu-explain/scripts/skeleton.sh skills/ps-commu-explain/tests/lifecycle_test.sh
git -C "$WT" commit -m "feat(ps-commu-explain): skeleton.sh drafts content.md from the storyboard (F-018)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Phase gate** (skeleton.sh): verify, then `code-reviewer` plus `python-reviewer`, then `/simplify`, then re-verify.

---

## Task 6: `components-index.md` and its drift test

**Files:**
- Create: `$SK/assets/template-infographic/components-index.md` (≤40 lines; `init.sh`'s `cp -R` copies it to `app/components-index.md`)
- Modify: `$SK/tests/lifecycle_test.sh`: the F-018 block.

**Interfaces:**
- Consumes: the `section-head` blocks in `assets/template-infographic/components.md`. There are 13 today (L10, 20, 40, 75, 163, 247, 288, 317, 350, 416, 451, 484, 518). Match `class="section-head[^"]*"[^>]*id="…"`, NOT a bare `id=`, which also matches the mxCell ids inside the drawio samples.
- Produces: one index row per section, holding the literal `id="<id>"` grep string, the section name, and the classes or fences it shows.

- [ ] **Step 1: Write the failing test** (append to the F-018 block):

```bash
test_components_index_covers_every_section() {
  local a="$SKILL_DIR/assets/template-infographic" ids id rc=0
  [[ -f "$a/components-index.md" ]] || { echo "no components-index.md"; return 1; }
  (( $(wc -l < "$a/components-index.md") <= 40 )) || { echo "index over 40 lines"; return 1; }
  ids="$(grep -oE 'class="section-head[^"]*"[^>]*id="[^"]+"' "$a/components.md" | sed -E 's/.*id="([^"]+)"$/\1/')"
  [[ -n "$ids" ]] || { echo "no section ids parsed from components.md"; return 1; }
  for id in $ids; do
    grep -qF "id=\"$id\"" "$a/components-index.md" || { echo "index misses section: $id"; rc=1; }
  done
  return $rc
}
check components_index_covers_every_section test_components_index_covers_every_section
```

- [ ] **Step 2: Run and confirm FAIL.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
ONLY='^components_index' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(PASS|FAIL|SKIP):|^-----'
```
Expected: `FAIL: components_index_covers_every_section` (`no components-index.md`).

- [ ] **Step 3: Create `components-index.md`** (the class lists were extracted from components.md on 2026-09-30; re-check each row against its section while writing):

```markdown
# Components index

One row per section of `components.md` (the full gallery, served beside
content.md). Read this first, then open only the section you need:
`grep -n 'id="<id>"' app/components.md` and read about 40 lines from there.

| grep for | section | classes / fences it shows |
| --- | --- | --- |
| `id="overview"` | Overview | gallery intro, no component |
| `id="sectionhead"` | Section header | section-head, bookend, icon-chip lg, sh-text, sh-kicker, sh-title |
| `id="readerquestions"` | Reader questions | reader-questions (data-nav-title, data-nav-sub), rq-kicker, rq-list, rq-q, rq-num, rq-text |
| `id="mechanism"` | Mechanism diagrams | drawio fence: mxGraphModel, labelled edges, role=accent/pitfall/check |
| `id="authoringskeleton"` | Authoring skeleton | drawio running-cursor layout, schematic, wrong-without, callout note |
| `id="workedexample"` | Worked example | worked-example, we-flow, we-stage, we-stage-k, we-stage-v, we-arrow, we-label |
| `id="claims"` | Claims | claim-card, claim-text, claim-meta, claim-fact, claim-source, claim-check |
| `id="wrongwithout"` | Wrong without | wrong-without, ww-ico, ww-title, ww-body |
| `id="beforeafter"` | Before / after | before-after, ba-panel, ba-label, ba-value, ba-arrow, compare, compare-panel, cmp-head, cmp-body, sm |
| `id="callouts"` | Callouts | `::: callout note`, `::: callout check`, `::: callout pitfall` |
| `id="steps"` | Steps | steps, step, step-num, step-title, step-body |
| `id="badges"` | Badges | badge, dot, chip-row, topic-chip, legend, legend-item, legend-swatch |
| `id="receipts"` | Receipts | receipts, receipts-label, receipts-list, receipts-fact |

gallery-item, gallery-body and gallery-label only frame each sample in this
gallery: do not copy them into content.md.
Removed (lint.sh rejects): stat-grid, stat-tile, meter, cat-*, metric-grid, card-grid.
```

- [ ] **Step 4: Run and confirm PASS.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
ONLY='^components_index' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(PASS|FAIL|SKIP):|^-----'; wc -l < "$SK/assets/template-infographic/components-index.md"
```
Expected: `PASS: components_index_covers_every_section` and a line count ≤ 40 (about 22).

- [ ] **Step 5: Commit.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single
git -C "$WT" add skills/ps-commu-explain/assets/template-infographic/components-index.md skills/ps-commu-explain/tests/lifecycle_test.sh
git -C "$WT" commit -m "feat(ps-commu-explain): 20-line components index with a drift test (F-018)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(Phase gate shared with Task 7: both are small new files.)

---

## Task 7: `scripts/handoff.sh`

**Files:**
- Create: `$SK/scripts/handoff.sh` (chmod +x)
- Modify: `$SK/tests/lifecycle_test.sh`: the F-018 block.

**Interfaces:**
- Consumes: `meta.json` (`port`, `pid`, marker-verified with `pid_has_marker`), `00-brief.md` (Q1-Q3), `list.sh`.
- Produces on stdout, in order: `URL: http://localhost:<port>` (or `URL: none, no live server (run <dir>/serve.sh <slug>)`); `Reader questions:` followed by the `Q1:`-`Q3:` lines; `Reader-gate answers: (add ...)`, the only part the model fills in; `Apps (list.sh):` followed by the `list.sh` output; `Cleanup: <dir>/stop.sh <slug> (this app) or <dir>/clean.sh (wipes ALL apps)`; `Re-serve: <dir>/serve.sh <slug>`. `<dir>` is the absolute scripts directory. It logs through `log_timing handoff.sh`.
- Exit: 0 printed with a live URL; 1 printed but no live server; 2 no workspace or no `00-brief.md`.

- [ ] **Step 1: Write the failing tests** (append to the F-018 block):

```bash
test_handoff_prints_everything() {
  _vstub_ws || return 1
  rm -f /tmp/ps-commu/t-vstub/timings.log
  local port out; port="$(meta_get t-vstub port)"
  out="$("$S/handoff.sh" t-vstub)" || { echo "$out"; return 1; }
  echo "$out"
  grep -qxF "URL: http://localhost:$port" <<<"$out" &&
  grep -q '^Q1: ' <<<"$out" && grep -q '^Q2: ' <<<"$out" && grep -q '^Q3: ' <<<"$out" &&
  grep -q '^Reader-gate answers:' <<<"$out" &&
  grep -qE '^SLUG +TIER' <<<"$out" && grep -qE '^t-vstub +infographic .*running' <<<"$out" &&
  grep -qF "$S/stop.sh t-vstub" <<<"$out" && grep -qF "$S/clean.sh" <<<"$out" &&
  grep -qxF "Re-serve: $S/serve.sh t-vstub" <<<"$out" &&
  [[ "$(grep -cE ' handoff\.sh [0-9]+$' /tmp/ps-commu/t-vstub/timings.log)" == 1 ]]
}
test_handoff_without_server_or_workspace() {
  rm -rf /tmp/ps-commu/t-hoff; "$S/init.sh" t-hoff --example >/dev/null
  local out rc
  out="$("$S/handoff.sh" t-hoff)"; rc=$?
  (( rc == 1 )) && grep -q '^URL: none, no live server' <<<"$out" || return 1
  "$S/handoff.sh" t-no-such-ws-xyz >/dev/null 2>&1; rc=$?
  (( rc == 2 )) && "$S/handoff.sh" --help | grep -q 'Usage: handoff.sh'
}
check handoff_prints_everything           test_handoff_prints_everything
check handoff_without_server_or_workspace test_handoff_without_server_or_workspace
```

- [ ] **Step 2: Run and confirm FAIL.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
ONLY='^handoff_' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(PASS|FAIL|SKIP):|^-----'
```
Expected: both FAIL (`handoff.sh: No such file or directory`).

- [ ] **Step 3: Implement `$SK/scripts/handoff.sh`:**

```bash
#!/usr/bin/env bash
# handoff.sh — print the Stage 6 handoff for a ps-commu workspace.
# Usage: handoff.sh <slug>
#   Prints, in order: the page URL (live marker-verified server only), the
#   brief's Q1-Q3, a "Reader-gate answers:" line (the one part you fill in,
#   from the reader subagent's reply), list.sh output, the cleanup hint and
#   the re-serve command. Commands are printed with absolute paths.
# Exit 0 = printed with a live URL; 1 = printed, but no live server (no URL to
# hand over: run serve.sh <slug> first); 2 = no workspace / no 00-brief.md.
set -uo pipefail
source "$(dirname "$0")/common.sh"

usage() { grep '^#' "$0" | cut -c3-; exit "${1:-0}"; }
case "${1:-}" in -h|--help) usage ;; "") usage 1 ;; esac
slug="$1"
dir="$(cd "$(dirname "$0")" && pwd)"
ws="$PS_COMMU_ROOT/$slug"
[[ -f "$ws/00-brief.md" ]] || { echo "no $ws/00-brief.md (run init.sh first)" >&2; exit 2; }
trap 'log_timing handoff.sh "$SECONDS"' EXIT

port="$(meta_get "$slug" port)"; pid="$(meta_get "$slug" pid)"
rc=0
if [[ -n "$pid" ]] && pid_has_marker "$pid" "$slug"; then
  echo "URL: http://localhost:$port"
else
  echo "URL: none, no live server (run $dir/serve.sh $slug)"; rc=1
fi
echo
echo "Reader questions:"
sed -n 's/^\(Q[1-3]:\)[[:space:]]*/\1 /p' "$ws/00-brief.md"
echo
echo "Reader-gate answers: (add the reader subagent's Q1-Q3 lines and its Verdict here)"
echo
echo "Apps (list.sh):"
"$dir/list.sh"
echo
echo "Cleanup: $dir/stop.sh $slug (this app) or $dir/clean.sh (wipes ALL apps)"
echo "Re-serve: $dir/serve.sh $slug"
exit "$rc"
```

```bash
chmod +x "$SK/scripts/handoff.sh"
```

- [ ] **Step 4: Run and confirm PASS.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
bash -n "$SK/scripts/handoff.sh" && ONLY='^handoff_' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(PASS|FAIL|SKIP):|^-----'
```
Expected: 2 PASS, 0 failed.

- [ ] **Step 5: Commit.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single
git -C "$WT" add skills/ps-commu-explain/scripts/handoff.sh skills/ps-commu-explain/tests/lifecycle_test.sh
git -C "$WT" commit -m "feat(ps-commu-explain): handoff.sh prints the Stage 6 handoff (F-018)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Phase gate for Tasks 6-7:** verify (`ONLY='^components_index|^handoff_'`), then `code-reviewer`, then `/simplify`, then re-verify.

---

## Task 8: SKILL.md trim (≤110 lines), model routing, main-thread verify, stale comments, README

**Files:**
- Modify: `$SK/SKILL.md`: L18, L46-48, L63-64, L67-106 (replaced), L110, L129-130.
- Modify: `$SK/scripts/serve.sh`: header L6-11.
- Modify: `$WT/README.md`: the ps-commu-explain row (L11) and the usage bullet (~L168-176).
- Modify: `$SK/tests/lifecycle_test.sh`: the F-018 block.
- (The `lint.sh` header was already fixed in Task 4.)

**Interfaces:**
- Consumes: `verify.sh --reader-prompt` (Task 3), `skeleton.sh` (Task 5), `app/components-index.md` (Task 6), `handoff.sh` (Task 7).
- Produces: SKILL.md at most 110 lines. The infographic `verify.sh` runs in the main thread; html/react screenshot and console subagents use `model: haiku`; the reader gate uses `model: sonnet`, with its prompt from `--reader-prompt`. Every rule the lint and verify gates enforce is still stated, and the verbatim prompt is removed.

- [ ] **Step 1: Write the failing tests** (append to the F-018 block):

```bash
test_skill_md_budget_and_routing() {
  local m="$SKILL_DIR/SKILL.md"
  (( $(wc -l < "$m") <= 110 )) || { echo "SKILL.md is $(wc -l < "$m") lines"; return 1; }
  grep -qF 'model: haiku' "$m" && grep -qF 'model: sonnet' "$m" &&
  grep -qF -- '--reader-prompt' "$m" && grep -qF 'skeleton.sh' "$m" &&
  grep -qF 'handoff.sh' "$m" && grep -qF 'components-index.md' "$m" &&
  grep -qi 'main thread' "$m" &&
  ! grep -qF 'You are an independent reader' "$m" &&        # verbatim prompt lives in verify.sh now
  grep -qF 'You are an independent reader' "$S/verify.sh" &&
  grep -qF 'TODO(' "$m" && grep -qF 'role=accent' "$m" && grep -qF 'scroll-behavior' "$m"
}
test_serve_help_not_stale() { ! "$S/serve.sh" --help | grep -q 'Task 6/7'; }
test_readme_mentions_new_scripts() {
  local r="$SKILL_DIR/../../README.md"
  grep -F 'ps-commu-explain' "$r" | grep -qF 'skeleton.sh' &&
  grep -qF 'handoff.sh' "$r" && grep -qF -- '--reader-prompt' "$r"
}
check skill_md_budget_and_routing test_skill_md_budget_and_routing
check serve_help_not_stale        test_serve_help_not_stale
check readme_mentions_new_scripts test_readme_mentions_new_scripts
```

- [ ] **Step 2: Run and confirm FAIL.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
ONLY='skill_md_budget|serve_help_not_stale|readme_mentions' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(PASS|FAIL|SKIP):|^-----'
```
Expected: 3 FAIL (138 lines; `Task 6/7` still in serve.sh; README has no `skeleton.sh`).

- [ ] **Step 3: Edit SKILL.md** (exact replacements):

L18: replace `Component cheat-sheet ships live at \`app/components.md\` (served alongside).` with:
```
Components: read `app/components-index.md` first (one line per section), then `grep -n 'id="<id>"' app/components.md` for only the section you need.
```

L46 (Stage 4 row): replace the Output cell, from `` `app/content.md` — **ships pre-filled`` up to `(cheat-sheet live at \`app/components.md\`)`, with:
```
`app/content.md` — once the storyboard lints, run `scripts/skeleton.sh <slug>`: it writes the reader-questions block, one section per storyboard row with a `TODO(Q<n>; F<n>,...): <section>` line for you to replace with cited prose, and a Receipts footer (refuses to overwrite without `--force`). The exemplar sits at `app/example-content.md`; `init.sh --example <slug>` uses it as content.md with a matching filled chain. Components: `app/components-index.md`
```
and put this at the start of its "Checked by" cell: ``(infographic) `lint.sh` rejects a missing `content.md` and any remaining `TODO(` line; it also rejects `` (the rest of the cell is unchanged).

L47 (Stage 5 row), Output cell:
```
render gate (`verify.sh <slug>`, **infographic tier only**, main thread; the same Chrome load writes `page-text.txt`) then reader gate (`model: sonnet` subagent, prompt from `verify.sh <slug> --reader-prompt`)
```

L48 (Stage 6 row): `| 6 | Handoff | \`scripts/handoff.sh <slug>\` output + the reader gate's answers | prose |`

L63-64 become:
```
- **Authoring cycles (Stage 4):** you author `content.md` in the main thread. The infographic render gate (`verify.sh <slug>`, ~8 PASS/FAIL lines) also runs in the main thread: a subagent would add latency and save nothing. Every html/react render check (Chrome load, screenshot, console read) runs in a `model: haiku` subagent that returns ≤15 lines. Screenshots are never taken inline in the main thread.
- **Reader gate (Stage 5):** always a fresh `model: sonnet` subagent, prompted with the output of `verify.sh <slug> --reader-prompt`. It reads only `page-text.txt`, never the brief/facts/storyboard files.
```

L67-106 (the whole `## Verify: render gate + reader gate` section, including `### Reader-gate prompt` and its fenced prompt) become:
```
## Verify: render gate + reader gate

- **Infographic render gate:** `scripts/verify.sh <slug>` in the main thread: one headless-Chrome load, 8 PASS/FAIL/SKIP asserts (drawio render count and non-empty shapes, no `~~CODE` leak, no raw `data-nav` text, zero page-origin console errors, nav click (permanent SKIP), no `scroll-behavior` in explainer.css, drawio pan/zoom initialized on every diagram, no literal `<br>` text). Detail: `verify.sh --help`. Exit 0 = pass; 1 = defects; 2 = no Chrome/no server (a SKIP, never a pass; the `scroll-behavior` check still runs without Chrome). The same load writes the reader-visible text to `/tmp/ps-commu/<slug>/page-text.txt`.
- **html:** verify.sh runs `html-1` (no `explainer-error` on body) and `html-2` (svg count == `.mermaid` div count); `lint.sh` runs every `.mermaid` block through `mmdc` (missing mmdc warns and skips; `EXPLAINER_STRICT_MERMAID=1` fails). **react:** verify.sh reports `FAIL: doc not found`; the render check is a `model: haiku` subagent Chrome load (console + screenshot, ≤15 lines).
- **Reader gate:** a clean render gate is necessary, not sufficient. Run `scripts/verify.sh <slug> --reader-prompt` (exit 2 = no `page-text.txt` yet: run `verify.sh <slug>` first). Its first line, `Agent model: sonnet`, is the Agent tool's `model`; paste the rest verbatim as the prompt, and never paste page text yourself. The subagent must answer Q1-Q3 with `F<n>` citations from the page's Receipts footer, list unexplained terms, and return `Verdict: PASS` before the page counts as done.
```

L110 (Handoff body):
```
Run `scripts/handoff.sh <slug>`: it prints the URL, the brief's 3 questions, `list.sh` output, the cleanup hint and the re-serve command. Relay it and add the reader gate's answers with citations. Offer an artifact copy-out. Explainers stay under `/tmp`, never committed.
```

L129: `- \`content.md\` still holding a \`TODO(\` line, or citing an \`F<n>\` with no matching row in \`01-facts.md\` (lint catches both; if it didn't, lint wasn't run)`

L130: `- A screenshot, or an html/react Chrome check, run inline in the main thread instead of a \`model: haiku\` subagent (the infographic \`verify.sh\` text run is the one main-thread Chrome check)`

- [ ] **Step 4: Fix the stale `serve.sh` header** (L6-11):

```bash
#   --no-lint     Skip the scripts/lint.sh authoring-chain gate before serving.
#                 Intended for the html/react tiers' dev loops and this repo's
#                 own server-mechanics tests. Prints a warning. Without it,
#                 serve.sh refuses (exit 1, printing the lint output) when
#                 scripts/lint.sh <slug> fails.
```

- [ ] **Step 5: Update README.md.** In the row (L11), after `gated by \`scripts/lint.sh\` and \`scripts/verify.sh\`.` insert:
```
Mechanical steps are scripted so the model only does the judgment: `skeleton.sh` drafts `content.md` from the storyboard, `verify.sh` does one Chrome load per cycle and `verify.sh --reader-prompt` builds the reader-gate prompt, `handoff.sh` prints the handoff, and each script logs to the workspace's `timings.log`.
```
In the usage bullet (~L168-176), replace `` `scripts/verify.sh` is the render gate (headless
  Chrome asserts); a reader-gate subagent, given only the rendered page text, must then answer the
  brief's 3 questions with citations.`` with:
```
`scripts/skeleton.sh <slug>` drafts `app/content.md`
  (one `TODO(` line per storyboard row; lint rejects any left). `scripts/verify.sh` is the render gate
  (headless Chrome asserts, one load that also writes `page-text.txt`); `verify.sh <slug> --reader-prompt`
  prints the prompt for a Sonnet reader-gate subagent, which reads only that page text and must answer the
  brief's 3 questions with citations. `scripts/handoff.sh <slug>` prints the final handoff.
```

- [ ] **Step 6: Run and confirm PASS.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; SK=$WT/skills/ps-commu-explain
ONLY='skill_md_budget|serve_help_not_stale|readme_mentions|serve_no_lint_warns' bash "$SK/tests/lifecycle_test.sh" 2>&1 | grep -E '^(PASS|FAIL|SKIP):|^-----'; wc -l < "$SK/SKILL.md"
```
Expected: 4 PASS and a SKILL.md count ≤ 110 (about 106). If it is over 110, merge the two Handoff lines or drop blank lines inside the Verify bullets. Do not delete any gate rule.

- [ ] **Step 7: Commit.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single
git -C "$WT" add skills/ps-commu-explain/SKILL.md skills/ps-commu-explain/scripts/serve.sh README.md skills/ps-commu-explain/tests/lifecycle_test.sh
git -C "$WT" commit -m "docs(ps-commu-explain): SKILL.md to <=110 lines, haiku/sonnet check routing, main-thread verify; README (F-018)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 8: Phase gate** (docs diff): verify, then `code-reviewer`, which checks that every lint/verify rule from the old SKILL.md L46 and L69 is still stated somewhere in SKILL.md or in a script's `--help`, then `/simplify`, then re-verify.

---

## Task 9: After-run timing, before/after comparison, full test run

**Files:**
- Modify: `$WT/.claude/refined_backlog/F-018-ps-commu-explain-speed-quick-wins-single/verification.md` (append)

**Interfaces:**
- Consumes: the Task 0 baseline and `/tmp/ps-commu/f018-bench-after/timings.log`.
- Produces: the `## After` and `## Comparison` sections plus the full-suite result.

- [ ] **Step 1: Run the same topic with the FEATURE-WORKTREE skill** (the live symlink still points at main). Follow `$SK/SKILL.md` as it now reads: init, fill the chain, `skeleton.sh`, fill the TODO lines, `serve.sh`, `verify.sh` in the main thread, `--reader-prompt` into a `model: sonnet` subagent, then `handoff.sh`. Reuse the Task 0 Chrome counter:

```bash
SCR=/private/tmp/f018-bench; : > "$SCR/chrome-launches.log"; date +%s > "$SCR/after.start"
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single; W=$WT/skills/ps-commu-explain/scripts
"$W/init.sh" f018-bench-after
# ... model fills 00-brief/01-facts/02-storyboard ...
"$W/skeleton.sh" f018-bench-after
# ... model replaces each TODO( line ...
"$W/serve.sh" f018-bench-after
CHROME_BIN=$SCR/chrome-count "$W/verify.sh" f018-bench-after
"$W/verify.sh" f018-bench-after --reader-prompt     # paste into a model: sonnet Agent
# ... fix cycles: re-run verify.sh only ...
"$W/handoff.sh" f018-bench-after
date +%s > "$SCR/after.end"
cat /tmp/ps-commu/f018-bench-after/timings.log; wc -l < "$SCR/chrome-launches.log"
```

- [ ] **Step 2: Append to verification.md** with the real numbers:

```markdown
## After, 2026-MM-DD, feature worktree @ <git -C "$WT" rev-parse --short HEAD>

Topic: same as the baseline. Slug: f018-bench-after.

timings.log:
<paste /tmp/ps-commu/f018-bench-after/timings.log>

| metric | before | after | delta |
| --- | --- | --- | --- |
| total wall clock (s) | | | |
| verify cycles | | | |
| Chrome launches | | | |
| Chrome launches per cycle | 2 | 1 | -1 |
| verify.sh time per cycle (s) | | | |

## Comparison

<2-4 sentences: where the time went (script time vs gaps between timings.log entries = model time), and whether one Chrome launch per verify cycle held.>

## Full test suite

<paste the final `----- N passed, 0 failed, M skipped` line>
```

- [ ] **Step 3: Run the full suite** (about 10 min; run it in the background and wait):

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single
bash "$WT/skills/ps-commu-explain/tests/lifecycle_test.sh" 2>&1 | grep -E '^(FAIL|SKIP):|^-----'
```
Expected: no `FAIL:` lines, and `----- N passed, 0 failed, M skipped`. SKIPs are only the documented no-mmdc or no-Chrome cases.

- [ ] **Step 4: Clean up the bench workspaces:** `"$W/stop.sh" f018-bench-after; "$W/stop.sh" f018-bench-before`.

- [ ] **Step 5: Commit.**

```bash
WT=/Users/pasitnusso/ps-skills/.claude/worktrees/F-018-ps-commu-explain-speed-quick-wins-single
git -C "$WT" add .claude/refined_backlog/F-018-ps-commu-explain-speed-quick-wins-single/verification.md
git -C "$WT" commit -m "docs(F-018): after-run timing, before/after comparison, full suite green

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Final whole-branch gate:** run `code-reviewer` on `git -C "$WT" diff release/1.9...HEAD`, then `/simplify`, then rerun the full suite. After that, `psrw ship` (Gate 1).

---

## Self-review: spec coverage

| Spec acceptance criterion | Task(s) | Test(s) |
| --- | --- | --- |
| One `verify.sh <slug>` prints all asserts AND writes non-empty `page-text.txt` with one Chrome launch; `--dump-text` prints the same file via the same code path | 2 | `verify_one_load_writes_page_text`, `verify_dump_text_same_path`, extended `verify_dump_text` (real Chrome) |
| A failed Chrome load or a `--url` run leaves no `page-text.txt` | 2 | `verify_failed_load_leaves_no_page_text`, `verify_url_writes_no_page_text` |
| `--reader-prompt` prints the Reader line, Q1-Q3 and the absolute path (not the contents), starts no Chrome, exits 2 without `page-text.txt` | 3 | `reader_prompt_fills_brief_and_path`, `reader_prompt_needs_page_text` |
| `skeleton.sh` on the `--example` chain gives one `TODO(` per row; lint rejects until filled, then accepts; no `<!--`; refuses overwrite without `--force` | 4 (lint), 5 | `skeleton_writes_todo_per_row`, `skeleton_lint_gate`, `skeleton_refuses_overwrite`, `lint_rejects_todo_line_infographic` |
| Plain `init.sh` writes no `content.md` and puts the exemplar at `example-content.md`; `--example` unchanged; the two verify tests use `--example`; lint flags a missing content.md on infographic | 4 | `init_default_moves_exemplar`, `init_example_scaffolds_filled_chain` (existing), `lint_flags_missing_content_infographic`, switched `verify_passes_template` / `verify_dump_text` |
| `components-index.md` ≤40 lines and names every section | 6 | `components_index_covers_every_section` |
| `handoff.sh` prints URL, Q1-Q3, `list.sh`, cleanup hint and re-serve command | 7 | `handoff_prints_everything`, `handoff_without_server_or_workspace` |
| SKILL.md: infographic verify in the main thread, `model: haiku` for html/react checks, `model: sonnet` for the reader gate | 3 (prompt line), 8 | `skill_md_budget_and_routing` |
| SKILL.md ≤110 lines; `lint.sh --help` no longer describes the Mermaid scanner | 4 (lint header), 8 | `skill_md_budget_and_routing`, `lint_help_describes_drawio_not_mermaid`, `serve_help_not_stale` |
| `timings.log` gets one line per script call (init, serve, verify, skeleton, handoff) | 1, 5, 7 | `log_timing_appends`, `scripts_log_timing`, `skeleton_writes_todo_per_row`, `handoff_prints_everything` |
| Before/after evidence with `timings.log` and wall time; one Chrome launch per verify cycle after | 0, 9 | `verification.md` (hand-timed baseline plus the after run, both counted with the `chrome-count` wrapper) |
| `lifecycle_test.sh` passes in full; README row mentions the new scripts | 8, 9 | `readme_mentions_new_scripts`, the Task 9 full run |

Spec design items without their own acceptance line, also covered: the stale `serve.sh` comment (Task 8), the verbatim prompt moved to its single source (Tasks 3 and 8), and no auto-lint hook (Global Constraints).

Additions beyond the spec, all test-only or clarifying: the `ONLY=` filter in the test harness (Task 1), so TDD steps don't each need a 10-minute full run; and `log_timing` reads the caller's `$ws`, because the spec's two-argument signature `log_timing <script> <seconds>` does not name the workspace.


## Appendix: audit trail

- 2026-09-30 self-grill-audit (plan): verdict safe-with-fixes.
  - Corrected: Task 2 now keeps verify.sh L368 (`pv = Preview()`); the old wording would have deleted it (HIGH).
  - Corrected: in the assert run, `page-text.txt` is written only when no assert FAILs.
  - Corrected: `--reader-prompt` exits 2 when `app/content.md` is newer than `page-text.txt`, so it never serves stale text.
  - Corrected: the lint `TODO(` match is line-start only.
  - Corrected: argv line is L230.
- Notes for implementers (LOW, not rewritten above):
  - Task 1 Step 3: all 3 new tests FAIL, `log_timing_noop` with exit 127.
  - Task 3 Step 2: an unparsed `--reader-prompt` is taken as the slug, so the FAIL reason is "no workspace app dir". Still a FAIL, as expected.
  - Task 1 Step 5: the watchdog-subshell EXIT-trap contingency is moot.
  - A full lifecycle run takes about 3.5 min in CI, not 10.
- Blast radius: Task 4 means a plain `init.sh` no longer creates `content.md`, and Task 8 updates SKILL.md to match. Both ship in the same feature (F-018) and must never be split across promotes.
