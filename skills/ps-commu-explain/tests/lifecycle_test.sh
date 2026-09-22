#!/usr/bin/env bash
# Lifecycle tests for ps-commu-explain scripts. Run directly; exits non-zero on failure.
# Uses slugs prefixed "t-" and cleans them up.
set -uo pipefail
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
S="$SKILL_DIR/scripts"
PASS=0; FAIL=0; SKIP=0
ok()   { echo "PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "FAIL: $1"; FAIL=$((FAIL+1)); }
skip() { echo "SKIP: $1"; SKIP=$((SKIP+1)); }
CHECK_LOG="$(mktemp)"
check(){               # on FAIL, show the test's output so CI logs say why
  local name="$1"; shift
  if "$@" >"$CHECK_LOG" 2>&1; then ok "$name"; else bad "$name"; tail -n 25 "$CHECK_LOG" | sed 's/^/    /'; fi
}
check_or_skip(){       # like check, but exit code 2 = visible SKIP (e.g. no Chrome) — never a pass
  local name="$1"; shift; local rc
  "$@" >"$CHECK_LOG" 2>&1; rc=$?
  if (( rc == 0 )); then ok "$name"
  elif (( rc == 2 )); then skip "$name — $(grep -m1 '^SKIP' "$CHECK_LOG" || head -n1 "$CHECK_LOG")"
  else bad "$name"; tail -n 25 "$CHECK_LOG" | sed 's/^/    /'; fi
}

# --- common.sh ---
source "$S/common.sh"

cleanup_tests() {
  for d in /tmp/ps-commu/t-*/; do
    [[ -d "$d" ]] || continue
    local s p; s="$(basename "$d")"; p="$(meta_get "$s" pid 2>/dev/null)"
    [[ -n "$p" ]] && pid_has_marker "$p" "$s" && kill "$p" 2>/dev/null
  done
  rm -rf /tmp/ps-commu/t-* "$CHECK_LOG" 2>/dev/null
}
trap cleanup_tests EXIT

test_marker_refusal() {            # an unrelated PID must never verify
  sleep 300 & local p=$!
  if pid_has_marker "$p" "t-x"; then kill $p; return 1; fi
  kill $p; return 0
}
test_realpath_refusal() { ! validate_workspace_path "$HOME"; }
test_realpath_accepts() {
  mkdir -p /tmp/ps-commu/t-rp
  validate_workspace_path /tmp/ps-commu/t-rp | grep -q '^/tmp/ps-commu/t-rp$'
}
test_meta_roundtrip() {
  mkdir -p /tmp/ps-commu/t-meta
  meta_set t-meta pid 12345
  [[ "$(meta_get t-meta pid)" == "12345" ]]
}
test_duration_parse() {
  [[ "$(parse_duration 24h)" == 86400 ]] || return 1
  [[ "$(parse_duration 90m)" == 5400   ]] || return 1
  [[ "$(parse_duration 10s)" == 10     ]] || return 1
  [[ "$(parse_duration 60)"  == 60     ]] || return 1
  ! parse_duration xh      2>/dev/null   || return 1
  ! parse_duration 1h30m   2>/dev/null   || return 1
}

check marker_refusal   test_marker_refusal
check realpath_refusal test_realpath_refusal
check realpath_accepts test_realpath_accepts
check meta_roundtrip   test_meta_roundtrip
check duration_parse   test_duration_parse

# --- init.sh ---
test_init_creates() {
  "$S/init.sh" t-init --tier html >/dev/null
  [[ -d /tmp/ps-commu/t-init ]] &&
  [[ "$(stat -f %Lp /tmp/ps-commu)" == "700" ]] &&
  [[ "$(meta_get t-init tier)" == "html" ]] &&
  [[ "$(meta_get t-init port)" =~ ^77[0-9][0-9]$ ]]
}
test_init_bad_slug() {
  ! "$S/init.sh" "Bad Slug!" 2>/dev/null &&
  ! "$S/init.sh" "trailing-" 2>/dev/null &&
  ! "$S/init.sh" t-ok --tier vue 2>/dev/null &&
  ! "$S/init.sh" t-ok --tier 2>/dev/null
}
test_sweep_old_dead() {                 # >3d old, no server → swept
  mkdir -p /tmp/ps-commu/t-old
  touch -t 202601010000 /tmp/ps-commu/t-old
  "$S/init.sh" t-sweeptrigger >/dev/null
  [[ ! -d /tmp/ps-commu/t-old ]]
}
test_sweep_spares_live() {              # >3d old but live marker-verified server → spared
  mkdir -p /tmp/ps-commu/t-oldlive
  python3 -m http.server 7798 --bind 127.0.0.1 --directory /tmp/ps-commu/t-oldlive >/dev/null 2>&1 &
  local pid=$!
  sleep 1
  meta_set t-oldlive pid "$pid"
  touch -t 202601010000 /tmp/ps-commu/t-oldlive
  "$S/init.sh" t-sweeptrigger2 >/dev/null
  local alive=0; [[ -d /tmp/ps-commu/t-oldlive ]] && alive=1
  kill "$pid" 2>/dev/null
  (( alive ))
}

test_init_writes_workspace_files() {  # Task 4: 00-brief/01-facts/02-storyboard skeletons
  "$S/init.sh" t-wsfiles --tier html >/dev/null
  [[ -f /tmp/ps-commu/t-wsfiles/00-brief.md ]] &&
  [[ -f /tmp/ps-commu/t-wsfiles/01-facts.md ]] &&
  [[ -f /tmp/ps-commu/t-wsfiles/02-storyboard.md ]]
}

check init_creates     test_init_creates
check init_bad_slug    test_init_bad_slug
check sweep_old_dead   test_sweep_old_dead
check sweep_spares_live test_sweep_spares_live
check init_writes_workspace_files test_init_writes_workspace_files

# --- serve.sh / stop.sh ---
# NOTE on --tier html + --no-lint below: serve.sh now runs scripts/lint.sh
# before serving (Task 4). These tests exercise HTTP/process mechanics only —
# they overwrite app/index.html directly and never author 00-brief.md /
# 01-facts.md / 02-storyboard.md — so they use --tier html (accurate for what
# they test) and --no-lint (the authoring chain is out of scope for them).
test_serve_html() {
  "$S/init.sh" t-serve --tier html >/dev/null
  echo '<h1>hello t-serve</h1>' > /tmp/ps-commu/t-serve/app/index.html
  "$S/serve.sh" t-serve --no-lint >/dev/null
  local port; port="$(meta_get t-serve port)"
  curl -sf "http://127.0.0.1:$port/" | grep -q 'hello t-serve'
}
test_serve_no_lint_warns() {  # --no-lint must print a warning line (stderr)
  "$S/init.sh" t-nolint-warn --tier html >/dev/null
  echo ok > /tmp/ps-commu/t-nolint-warn/app/index.html
  local out; out="$("$S/serve.sh" t-nolint-warn --no-lint 2>&1 >/dev/null)"
  "$S/stop.sh" t-nolint-warn >/dev/null 2>&1
  grep -qi 'WARNING' <<<"$out"
}
test_marker_visible() {     # server argv must contain the workspace path (D7)
  local pid; pid="$(meta_get t-serve pid)"
  pid_has_marker "$pid" t-serve
}
test_bind_localhost_only() { # D9: listening on 127.0.0.1, not *
  local port; port="$(meta_get t-serve port)"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN | grep -q '127\.0\.0\.1' &&
  ! lsof -nP -iTCP:"$port" -sTCP:LISTEN | grep -q '\*:'
}
test_port_retry() {          # D3: occupied candidate port → next one taken
  "$S/init.sh" t-retry --tier html >/dev/null
  meta_set t-retry port "$(meta_get t-serve port)"   # force collision
  echo ok > /tmp/ps-commu/t-retry/app/index.html
  "$S/serve.sh" t-retry --no-lint >/dev/null
  [[ "$(meta_get t-retry port)" != "$(meta_get t-serve port)" ]] &&
  curl -sf "http://127.0.0.1:$(meta_get t-retry port)/" >/dev/null
}
test_watchdog_fires() {      # D6 with marker check
  "$S/init.sh" t-watch --tier html >/dev/null
  echo ok > /tmp/ps-commu/t-watch/app/index.html
  "$S/serve.sh" t-watch --no-lint --keep-alive 3s >/dev/null
  local pid; pid="$(meta_get t-watch pid)"
  kill -0 "$pid" 2>/dev/null || return 1   # alive now
  for _ in $(seq 1 16); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.5
  done
  return 1
}
test_stop() {
  local pid; pid="$(meta_get t-serve pid)"
  "$S/stop.sh" t-serve >/dev/null
  ! kill -0 "$pid" 2>/dev/null && [[ -z "$(meta_get t-serve pid)" ]]
}
test_stop_refuses_foreign_pid() {  # PID-reuse safety: markerless pid never killed
  sleep 300 & local p=$!
  mkdir -p /tmp/ps-commu/t-foreign
  meta_set t-foreign pid "$p"
  "$S/stop.sh" t-foreign >/dev/null
  local alive=0; kill -0 "$p" 2>/dev/null && alive=1
  kill "$p" 2>/dev/null
  (( alive ))
}
test_serve_refuses_unlinted() {  # Task 4: serve.sh refuses to serve a workspace whose
  "$S/init.sh" t-lintgate --tier html >/dev/null      # authoring docs fail scripts/lint.sh
  echo ok > /tmp/ps-commu/t-lintgate/app/index.html
  local out rc
  out="$("$S/serve.sh" t-lintgate 2>&1)"; rc=$?
  (( rc != 0 )) && grep -q '00-brief.md' <<<"$out"
}

# NOTE: marker_visible, bind_localhost_only, port_retry and stop all depend on
# serve_html having started the t-serve server. Keep registration order.
check serve_html          test_serve_html
check serve_no_lint_warns test_serve_no_lint_warns
check marker_visible      test_marker_visible
check bind_localhost_only test_bind_localhost_only
check port_retry          test_port_retry
check watchdog_fires      test_watchdog_fires
check stop                test_stop
check stop_refuses_foreign_pid test_stop_refuses_foreign_pid
check serve_refuses_unlinted   test_serve_refuses_unlinted

# --- lint.sh (authoring-chain gate) ---
_lint_valid_brief_facts_storyboard() {  # slug — writes a fully-filled valid chain
  local ws="/tmp/ps-commu/$1"
  cat > "$ws/00-brief.md" <<'EOF'
# Brief

Q1: What is X?
Q2: Why does X matter?
Q3: How do I use X?

Section budget: 5
EOF
  cat > "$ws/01-facts.md" <<'EOF'
# Facts

| id | statement | source |
| --- | --- | --- |
| F1 | X does the thing | user said |
EOF
  cat > "$ws/02-storyboard.md" <<'EOF'
# Storyboard

| section | question | facts |
| --- | --- | --- |
| 1 | Q1 | F1 |
| 2 | Q2 | F1 |
| 3 | Q3 | F1 |
EOF
}
test_lint_passes_starter() {   # a fully-filled, valid authoring chain lints clean
  "$S/init.sh" t-lint-ok --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-ok
  "$S/lint.sh" t-lint-ok
}
test_lint_fails_unlabeled_edge() {  # content.md: bare --> flowchart edge with no label
  "$S/init.sh" t-lint-edge --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-edge
  mkdir -p /tmp/ps-commu/t-lint-edge/app
  cat > /tmp/ps-commu/t-lint-edge/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A --> B
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-edge 2>&1)"; rc=$?
  (( rc == 1 )) && grep -qi 'no label' <<<"$out"
}
test_lint_fails_uncited_fact() {  # storyboard row citing no existing F<n>
  "$S/init.sh" t-lint-fact --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-fact
  cat > /tmp/ps-commu/t-lint-fact/02-storyboard.md <<'EOF'
# Storyboard

| section | question | facts |
| --- | --- | --- |
| 1 | Q1 |  |
| 2 | Q2 | F1 |
| 3 | Q3 | F1 |
EOF
  local out rc; out="$("$S/lint.sh" t-lint-fact 2>&1)"; rc=$?
  (( rc == 1 )) && grep -qi 'cites no existing' <<<"$out"
}
test_lint_fails_chained_edge_tail() {  # regression: A --> B --> C must catch the TAIL edge
  "$S/init.sh" t-lint-chain --tier html >/dev/null                 # too (a combined src-op-dst
  _lint_valid_brief_facts_storyboard t-lint-chain                  # regex previously consumed B
  mkdir -p /tmp/ps-commu/t-lint-chain/app                          # as the first edge's dst,
  cat > /tmp/ps-commu/t-lint-chain/app/content.md <<'EOF'          # leaving nothing to anchor
See F1 for details.                                                # the second arrow's src on)

```mermaid
flowchart LR
  A[a] -->|start| B --> C
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-chain 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "'B --> C' has no label" <<<"$out"
}
test_lint_fails_node_cap_standalone() {  # regression: standalone "ID[label]" declarations
  "$S/init.sh" t-lint-nodecap --tier html >/dev/null               # (no edge at all) must still
  _lint_valid_brief_facts_storyboard t-lint-nodecap                # count toward the <=7 node cap
  mkdir -p /tmp/ps-commu/t-lint-nodecap/app
  cat > /tmp/ps-commu/t-lint-nodecap/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A[a]
  B[b]
  C[c]
  D[d]
  E[e]
  F[f]
  G[g]
  H[h]
  A -->|link| B
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-nodecap 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q '8 nodes (max 7)' <<<"$out"
}
test_lint_fails_alt_arrow_unlabeled() {  # regression: dotted (-.->) and thick (==>) arrows
  "$S/init.sh" t-lint-altarrow --tier html >/dev/null              # must be checked too, not just
  _lint_valid_brief_facts_storyboard t-lint-altarrow                # plain --> (they were invisible
  mkdir -p /tmp/ps-commu/t-lint-altarrow/app                        # to both checks before)
  cat > /tmp/ps-commu/t-lint-altarrow/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A -.-> B
  B ==> C
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-altarrow 2>&1)"; rc=$?
  (( rc == 1 )) &&
  grep -q "'A -.-> B' has no label" <<<"$out" &&
  grep -q "'B ==> C' has no label" <<<"$out"
}
test_lint_passes_labeled_chain_and_alt_arrows() {  # a LEGITIMATE diagram using chained edges,
  "$S/init.sh" t-lint-goodflow --tier html >/dev/null              # dotted/thick links and exactly
  _lint_valid_brief_facts_storyboard t-lint-goodflow                # 7 nodes, all correctly labeled,
  mkdir -p /tmp/ps-commu/t-lint-goodflow/app                        # must still pass (no false
  cat > /tmp/ps-commu/t-lint-goodflow/app/content.md <<'EOF'         # positives from the fix above)
See F1 for details.

```mermaid
flowchart LR
  A[a] -->|start| B --> |middle| C
  C -.->|dotted ok| D
  D ==>|thick ok| E
  E -- also ok --> F
  F --x|x-end ok| G
```
EOF
  # Assert rc==0 AND empty output, not just a zero exit code: fix round 1's
  # version of this fixture (the "B --> |middle| C" line, a space before the
  # pipe) passed VACUOUSLY — the pre-round-2 parser silently dropped that
  # whole line from both checks (bail-out bug), so this test happened to
  # still exit 0 without ever actually verifying that edge's label. Now that
  # an unclassifiable statement is a reported defect (fail closed) rather
  # than a silent skip, a regression back to that bug would make this FAIL
  # (non-empty output), which is what makes this assertion non-vacuous.
  local out rc; out="$("$S/lint.sh" t-lint-goodflow 2>&1)"; rc=$?
  (( rc == 0 )) && [[ -z "$out" ]]
}
test_lint_fails_semicolon_edges() {  # regression: ";"-terminated edges must be fully
  "$S/init.sh" t-lint-semi --tier html >/dev/null                  # checked, not dropped (Mermaid's
  _lint_valid_brief_facts_storyboard t-lint-semi                    # own docs use this style)
  mkdir -p /tmp/ps-commu/t-lint-semi/app
  cat > /tmp/ps-commu/t-lint-semi/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A --> B;
  B --> C;
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-semi 2>&1)"; rc=$?
  (( rc == 1 )) &&
  grep -q "'A --> B' has no label" <<<"$out" &&
  grep -q "'B --> C' has no label" <<<"$out" &&
  ! grep -qi 'not understood' <<<"$out"
}
test_lint_fails_inline_comment_edge() {  # regression: a trailing "%% note" on an edge
  "$S/init.sh" t-lint-comment --tier html >/dev/null                # line must not hide that edge
  _lint_valid_brief_facts_storyboard t-lint-comment                  # from the label check
  mkdir -p /tmp/ps-commu/t-lint-comment/app
  cat > /tmp/ps-commu/t-lint-comment/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A --> B %% some note
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-comment 2>&1)"; rc=$?
  (( rc == 1 )) &&
  grep -q "'A --> B' has no label" <<<"$out" &&
  ! grep -qi 'not understood' <<<"$out"
}
test_lint_fails_fanout_edges() {  # regression: "A --> B & C" fan-out must check
  "$S/init.sh" t-lint-fanout --tier html >/dev/null                 # BOTH targets, not bail out
  _lint_valid_brief_facts_storyboard t-lint-fanout
  mkdir -p /tmp/ps-commu/t-lint-fanout/app
  cat > /tmp/ps-commu/t-lint-fanout/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A --> B & C
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-fanout 2>&1)"; rc=$?
  (( rc == 1 )) &&
  grep -q "'A --> B' has no label" <<<"$out" &&
  grep -q "'A --> C' has no label" <<<"$out" &&
  ! grep -qi 'not understood' <<<"$out"
}
# regression: proves a spaced "--> |x|" labeled edge is genuinely PARSED
# (not silently dropped) alongside a real unlabeled edge in the same
# diagram. If the spaced form were ever bailed-out again, that line would
# surface as an EXTRA "not understood" defect, making the exact-one-defect
# assertion below fail.
test_lint_fails_only_expected_edge_with_spaced_pipe() {
  "$S/init.sh" t-lint-spacedpipe --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-spacedpipe
  mkdir -p /tmp/ps-commu/t-lint-spacedpipe/app
  cat > /tmp/ps-commu/t-lint-spacedpipe/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A --> |mid| B
  B --> C
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-spacedpipe 2>&1)"; rc=$?
  local n; n="$(grep -c ':' <<<"$out")"
  (( rc == 1 )) && (( n == 1 )) && grep -q "'B --> C' has no label" <<<"$out"
}
test_lint_passes_class_shorthand_not_counted_as_node() {  # regression: ":::hot" on 7
  "$S/init.sh" t-lint-classshort --tier html >/dev/null             # real, distinct nodes must not
  _lint_valid_brief_facts_storyboard t-lint-classshort                # add a phantom 8th "hot" node
  mkdir -p /tmp/ps-commu/t-lint-classshort/app                        # and trip the >7 cap
  cat > /tmp/ps-commu/t-lint-classshort/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A[a]:::hot
  B[b]:::hot
  C[c]:::hot
  D[d]:::hot
  E[e]:::hot
  F[f]:::hot
  G[g]:::hot
  A -->|x| B
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-classshort 2>&1)"; rc=$?
  (( rc == 0 )) && [[ -z "$out" ]]
}
test_lint_flags_unverifiable_q_coverage_when_brief_missing() {  # regression: an empty
  "$S/init.sh" t-lint-nobrief --tier html >/dev/null              # q_ids (brief missing) must
  _lint_valid_brief_facts_storyboard t-lint-nobrief                 # report "cannot verify", not
  rm -f /tmp/ps-commu/t-lint-nobrief/00-brief.md                    # silently skip Q-coverage
  local out rc; out="$("$S/lint.sh" t-lint-nobrief 2>&1)"; rc=$?
  (( rc == 1 )) && grep -qi 'cannot verify' <<<"$out"
}
# regression: a label containing a literal ";" must NOT be torn apart by the
# statement splitter — round 2's naive ";"/"%%" split did this (fix round 3).
test_lint_fails_bracket_label_with_semicolon_not_torn() {
  "$S/init.sh" t-lint-semilabel --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-semilabel
  mkdir -p /tmp/ps-commu/t-lint-semilabel/app
  cat > /tmp/ps-commu/t-lint-semilabel/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A["one; two"] --> B
```
EOF
  # The genuine defect (A --> B unlabeled) must be reported, and there must
  # be NO "not understood" noise — proving the ";" inside the quoted label
  # was recognized as label content, not a statement separator.
  local out rc; out="$("$S/lint.sh" t-lint-semilabel 2>&1)"; rc=$?
  (( rc == 1 )) &&
  grep -q "'A --> B' has no label" <<<"$out" &&
  ! grep -qi 'not understood' <<<"$out"
}
# regression: an inline dash-label containing ";" ("-- yes; no -->") must
# also survive intact (no brackets/quotes involved at all here).
test_lint_passes_dash_label_with_semicolon_not_torn() {
  "$S/init.sh" t-lint-semidash --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-semidash
  mkdir -p /tmp/ps-commu/t-lint-semidash/app
  cat > /tmp/ps-commu/t-lint-semidash/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A -- yes; then no --> B
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-semidash 2>&1)"; rc=$?
  (( rc == 0 )) && [[ -z "$out" ]]
}
# regression: a node genuinely named "Direction"/"Style" (capitalized) must
# NOT be silently swallowed by the FLOW_KEYWORDS check — Mermaid's actual
# directive keywords are lowercase-only, so capitalized node ids are legal
# and distinct. Round 2's case-insensitive keyword match dropped these
# entirely (fix round 3).
test_lint_fails_capitalized_keyword_lookalike_nodes() {
  "$S/init.sh" t-lint-kwnode --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-kwnode
  mkdir -p /tmp/ps-commu/t-lint-kwnode/app
  cat > /tmp/ps-commu/t-lint-kwnode/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  Direction --> A
  Style --> B
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-kwnode 2>&1)"; rc=$?
  (( rc == 1 )) &&
  grep -q "'Direction --> A' has no label" <<<"$out" &&
  grep -q "'Style --> B' has no label" <<<"$out"
}
# Minor: positive test for the fail-closed "not understood" path — every
# other assertion about it so far has been negative (absence). Feed genuinely
# unparseable syntax and assert the defect actually fires, with a line
# number pointing at the real source line.
test_lint_fails_unparseable_statement_with_line_number() {
  "$S/init.sh" t-lint-garbled --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-garbled
  mkdir -p /tmp/ps-commu/t-lint-garbled/app
  cat > /tmp/ps-commu/t-lint-garbled/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A --> B
  A --> B{weird[nested syntax}}
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-garbled 2>&1)"; rc=$?
  (( rc == 1 )) &&
  grep -qi "not understood" <<<"$out" &&
  grep -q "line 3" <<<"$out" &&
  grep -q "B{weird\[nested syntax}}" <<<"$out"
}
# Required combined regression matrix (fix round 3): every form named across
# all three fix rounds, exercised TOGETHER in one diagram — chained edges,
# >7 nodes (via a mix of standalone + edge-declared ids), -.->/==> arrows,
# a ";"-terminated statement, an inline "%%" comment, "&" fan-out, a
# ":::class" shorthand assignment, a pipe label containing a literal ";", a
# bracket label containing a literal "%%", a capitalized keyword-lookalike
# node, and legitimate classDef/class directive lines — all in one file, so
# a fix for one round's finding that breaks another round's fix is caught
# here rather than only in isolated single-purpose fixtures.
test_lint_combined_regression_matrix() {
  "$S/init.sh" t-lint-matrix --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-matrix
  mkdir -p /tmp/ps-commu/t-lint-matrix/app
  cat > /tmp/ps-commu/t-lint-matrix/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A[a]:::hot -->|start; ok| B --> C
  C -.-> D
  D ==> E %% inline comment here
  E --> F & G;
  Style[note %% not a comment] --> H
  classDef hot fill:#f00
  class A hot
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-matrix 2>&1)"; rc=$?
  (( rc == 1 )) &&
  ! grep -qi 'not understood' <<<"$out" &&
  ! grep -q "'A --> B' has no label" <<<"$out" &&
  grep -q "'B --> C' has no label" <<<"$out" &&
  grep -q "'C -.-> D' has no label" <<<"$out" &&
  grep -q "'D ==> E' has no label" <<<"$out" &&
  grep -q "'E --> F' has no label" <<<"$out" &&
  grep -q "'E --> G' has no label" <<<"$out" &&
  grep -q "'Style --> H' has no label" <<<"$out" &&
  grep -q '9 nodes (max 7)' <<<"$out"
}

check lint_passes_starter       test_lint_passes_starter
check lint_fails_unlabeled_edge test_lint_fails_unlabeled_edge
check lint_fails_uncited_fact   test_lint_fails_uncited_fact
check lint_fails_chained_edge_tail  test_lint_fails_chained_edge_tail
check lint_fails_node_cap_standalone test_lint_fails_node_cap_standalone
check lint_fails_alt_arrow_unlabeled test_lint_fails_alt_arrow_unlabeled
check lint_passes_labeled_chain_and_alt_arrows test_lint_passes_labeled_chain_and_alt_arrows
check lint_fails_semicolon_edges  test_lint_fails_semicolon_edges
check lint_fails_inline_comment_edge test_lint_fails_inline_comment_edge
check lint_fails_fanout_edges     test_lint_fails_fanout_edges
check lint_fails_only_expected_edge_with_spaced_pipe test_lint_fails_only_expected_edge_with_spaced_pipe
check lint_passes_class_shorthand_not_counted_as_node test_lint_passes_class_shorthand_not_counted_as_node
check lint_flags_unverifiable_q_coverage_when_brief_missing test_lint_flags_unverifiable_q_coverage_when_brief_missing
check lint_fails_bracket_label_with_semicolon_not_torn test_lint_fails_bracket_label_with_semicolon_not_torn
check lint_passes_dash_label_with_semicolon_not_torn test_lint_passes_dash_label_with_semicolon_not_torn
check lint_fails_capitalized_keyword_lookalike_nodes test_lint_fails_capitalized_keyword_lookalike_nodes
check lint_fails_unparseable_statement_with_line_number test_lint_fails_unparseable_statement_with_line_number
check lint_combined_regression_matrix test_lint_combined_regression_matrix

# --- verify.sh (render gate; needs Google Chrome — SKIPs visibly without it) ---
# A verify run is ~45s on macOS (Chrome start + CDN load + Mermaid render).
verify_run() {           # args... → verify.sh output on stdout; rc 2 = cannot run (Chrome/server)
  if command -v timeout >/dev/null; then timeout 150 "$S/verify.sh" "$@"; else "$S/verify.sh" "$@"; fi
}
test_verify_passes_template() {
  # --no-lint: deliberate deviation from --no-lint's "html/react dev loop
  # only" framing in serve.sh's usage text. This tier must stay infographic
  # (needs the real cherry-markdown + Mermaid template), but the stock
  # template-infographic/content.md still contains forbidden classes
  # (stat-grid, stat-tile, cat-*) that scripts/lint.sh correctly rejects —
  # making that template lint-clean is Task 6/7 scope, not this batch's.
  "$S/init.sh" t-verify >/dev/null
  "$S/serve.sh" t-verify --no-lint >/dev/null
  local out rc; out="$(verify_run t-verify)"; rc=$?
  echo "$out"
  (( rc == 2 )) && return 2
  (( rc == 0 )) &&
  grep -q '^PASS: 1 mermaid svg=2 fences=2' <<<"$out" &&
  ! grep -q '^FAIL' <<<"$out"
}
test_verify_fails_on_leak() {  # literal ~~CODE$ in prose + a Mermaid fence that cannot render
  local port; port="$(meta_get t-verify port)"
  cat > /tmp/ps-commu/t-verify/app/leak.md <<'MD'
<div class="section-head cat-coral" data-nav="Intro" data-cat="coral" id="intro">
<h2>Intro</h2>
</div>

A literal ~~CODE$ placeholder stays in prose.

```mermaid
flowchart LR
  A --> B --> (((
```
MD
  local out rc; out="$(verify_run t-verify --url "http://127.0.0.1:$port/?doc=leak.md")"; rc=$?
  echo "$out"
  (( rc == 2 )) && return 2
  (( rc == 1 )) &&
  grep -q '^FAIL: 1 mermaid svg=0 fences=1' <<<"$out" &&
  grep -q '^FAIL: 2 ~~CODE placeholder LEAKED' <<<"$out"
}
test_verify_help() { "$S/verify.sh" --help | grep -q 'Usage: verify.sh' && ! "$S/verify.sh" >/dev/null 2>&1; }

check_or_skip verify_passes_template test_verify_passes_template
check_or_skip verify_fails_on_leak   test_verify_fails_on_leak
check verify_help                     test_verify_help
"$S/stop.sh" t-verify >/dev/null 2>&1

# --- list.sh / clean.sh ---
# NOTE: clean tests wipe /tmp/ps-commu entirely — keep them registered last.
test_list_shows_running_and_stopped() {
  "$S/init.sh" t-list --tier html >/dev/null
  echo ok > /tmp/ps-commu/t-list/app/index.html
  "$S/serve.sh" t-list --no-lint >/dev/null
  local out; out="$("$S/list.sh")"
  echo "$out" | grep -E 't-list .*running .*http://localhost:' >/dev/null &&
  { "$S/stop.sh" t-list >/dev/null; "$S/list.sh" | grep -E 't-list .*stopped' >/dev/null; }
}
test_clean_refuses_symlink_escape() {   # D8: realpath guard on wipe
  mkdir -p /tmp/ps-commu-outside-canary
  ln -sfn /tmp/ps-commu-outside-canary /tmp/ps-commu/t-evil
  "$S/clean.sh" >/dev/null 2>&1
  local survived=0; [[ -d /tmp/ps-commu-outside-canary ]] && survived=1
  rm -rf /tmp/ps-commu-outside-canary /tmp/ps-commu/t-evil 2>/dev/null
  (( survived ))
}
test_clean_removes_dangling_link() {
  mkdir -p "$PS_COMMU_ROOT"
  ln -sfn /tmp/nonexistent-target-xyz /tmp/ps-commu/t-dangle
  "$S/clean.sh" >/dev/null 2>&1
  [[ ! -L /tmp/ps-commu/t-dangle ]]
}
test_clean_wipes_and_kills() {
  "$S/init.sh" t-clean --tier html >/dev/null
  echo ok > /tmp/ps-commu/t-clean/app/index.html
  "$S/serve.sh" t-clean --no-lint >/dev/null
  local pid; pid="$(meta_get t-clean pid)"
  "$S/clean.sh" >/dev/null
  ! kill -0 "$pid" 2>/dev/null && [[ ! -d /tmp/ps-commu/t-clean ]]
}

check list_running_stopped     test_list_shows_running_and_stopped
check clean_refuses_symlink    test_clean_refuses_symlink_escape
check clean_removes_dangling   test_clean_removes_dangling_link
check clean_wipes_and_kills    test_clean_wipes_and_kills

echo "----- $PASS passed, $FAIL failed, $SKIP skipped"
exit $(( FAIL > 0 ))
