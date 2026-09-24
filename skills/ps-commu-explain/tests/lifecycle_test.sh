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

test_init_example_scaffolds_filled_chain() {  # Task 7: --example sources the
  # filled assets/workspace/example/ chain instead of the empty skeleton, and
  # forces the infographic tier (whose shipped content.md is the exemplar).
  rm -rf /tmp/ps-commu/t-example
  "$S/init.sh" t-example --example >/dev/null &&
  [[ "$(meta_get t-example tier)" == "infographic" ]] &&
  [[ -f /tmp/ps-commu/t-example/app/content.md ]] &&
  ! grep -q '(\.\.\.)' /tmp/ps-commu/t-example/00-brief.md &&
  grep -q '^Q1:' /tmp/ps-commu/t-example/00-brief.md &&
  "$S/lint.sh" t-example    # the whole point: it must already lint clean
}

test_init_example_rejects_other_tier() {  # --example is infographic-only
  ! "$S/init.sh" t-example-bad --example --tier html 2>/dev/null
}

check init_creates     test_init_creates
check init_bad_slug    test_init_bad_slug
check sweep_old_dead   test_sweep_old_dead
check sweep_spares_live test_sweep_spares_live
check init_writes_workspace_files test_init_writes_workspace_files
check init_example_scaffolds_filled_chain test_init_example_scaffolds_filled_chain
check init_example_rejects_other_tier     test_init_example_rejects_other_tier

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
  # Fix round 4 additions: the brief is REMOVED so the q_ids "cannot verify
  # Q-coverage" branch runs in the same lint pass as the diagram checks (it
  # was previously only exercised in isolation); diagram #1 gains the
  # --x/--o/x--x/o--o/<-->/~~~ link families that round 3's matrix missed;
  # diagram #2 is a case-mismatched header ("Graph TD"), which Mermaid does
  # not detect as a diagram at all and which must therefore be REPORTED, not
  # silently left unchecked.
  rm -f /tmp/ps-commu/t-lint-matrix/00-brief.md
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
  A --x B; C --o D
  E x--x|both ends| F
  F o--o G
  G <--> H
  A ~~~ H
  classDef hot fill:#f00
  class A hot
```

```mermaid
Graph TD
  X --> Y
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-matrix 2>&1)"; rc=$?
  (( rc == 1 )) &&
  ! grep -qi 'not understood' <<<"$out" &&
  grep -qi 'cannot verify Q-coverage' <<<"$out" &&
  ! grep -q "'A --> B' has no label" <<<"$out" &&
  grep -q "'B --> C' has no label" <<<"$out" &&
  grep -q "'C -.-> D' has no label" <<<"$out" &&
  grep -q "'D ==> E' has no label" <<<"$out" &&
  grep -q "'E --> F' has no label" <<<"$out" &&
  grep -q "'E --> G' has no label" <<<"$out" &&
  grep -q "'Style --> H' has no label" <<<"$out" &&
  grep -q "'A --x B' has no label" <<<"$out" &&
  grep -q "'C --o D' has no label" <<<"$out" &&
  ! grep -q "'E x--x F' has no label" <<<"$out" &&
  grep -q "'F o--o G' has no label" <<<"$out" &&
  grep -q "'G <--> H' has no label" <<<"$out" &&
  ! grep -q "~~~" <<<"$out" &&
  grep -q '9 nodes (max 7)' <<<"$out" &&
  grep -q "diagram #2" <<<"$out" && grep -qi 'case-sensitive' <<<"$out"
}
# Fix round 4 (rereview-3 New-1): a bare --x/--o operator must not swallow a
# following ";"-separated statement or a "%%" comment up to the NEXT dashed
# operator on the line. Round 3 parsed "A --x B; C --> D" as ONE labeled edge
# A..D and reported nothing.
test_lint_fails_cross_circle_then_semicolon_stmt() {
  "$S/init.sh" t-lint-xo --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-xo
  mkdir -p /tmp/ps-commu/t-lint-xo/app
  cat > /tmp/ps-commu/t-lint-xo/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A --x B; C --> D
  E --o F; G --o H
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-xo 2>&1)"; rc=$?
  (( rc == 1 )) &&
  ! grep -qi 'not understood' <<<"$out" &&
  grep -q "'A --x B' has no label" <<<"$out" &&
  grep -q "'C --> D' has no label" <<<"$out" &&
  grep -q "'E --o F' has no label" <<<"$out" &&
  grep -q "'G --o H' has no label" <<<"$out" &&
  grep -q '8 nodes (max 7)' <<<"$out"
}
# Fix round 4 (rereview-3 New-2, corrected against Mermaid's own grammar):
# Mermaid's flowchart lexer is CASE-SENSITIVE (flow.jison has no
# case-insensitive option; verified by running Mermaid 11.15's parser):
# "Graph TD"/"Flowchart LR" are not detected as diagrams, "classdef"/
# "linkstyle" are parse errors, "End" is an ordinary node id and does NOT
# close a subgraph, and lowercase "end"/"style" cannot be node ids. The lint
# must REPORT each of these (fail closed), never skip the block or count a
# phantom, and never accept the lowercase form as a directive.
test_lint_fails_case_mismatched_header_not_skipped() {
  "$S/init.sh" t-lint-hdrcase --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-hdrcase
  mkdir -p /tmp/ps-commu/t-lint-hdrcase/app
  cat > /tmp/ps-commu/t-lint-hdrcase/app/content.md <<'EOF'
See F1 for details.

```mermaid
Graph TD
  A --> B
```

```mermaid
Flowchart LR
  C -->|x| D
```

```mermaid
SequenceDiagram
  A->>B: hi
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-hdrcase 2>&1)"; rc=$?
  (( rc == 1 )) &&
  grep -q "diagram #1" <<<"$out" && grep -q "diagram #2" <<<"$out" &&
  grep -q "diagram #3" <<<"$out" &&
  (( $(grep -ci 'case-sensitive' <<<"$out") == 3 ))
}
test_lint_fails_lowercase_keywords_and_End_node() {
  "$S/init.sh" t-lint-kwcase --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-kwcase
  mkdir -p /tmp/ps-commu/t-lint-kwcase/app
  cat > /tmp/ps-commu/t-lint-kwcase/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  subgraph one
    A -->|x| End
  End
  classdef hot fill:#f00
  linkstyle 0 stroke:#f00
```

```mermaid
flowchart LR
  A -->|x| end
  style --> B
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-kwcase 2>&1)"; rc=$?
  (( rc == 1 )) &&
  grep -q "diagram #1 .*subgraph.*never closed" <<<"$out" &&
  grep -q "diagram #1 line 5 not understood by lint: 'classdef hot fill:#f00'" <<<"$out" &&
  grep -q "diagram #1 line 6 not understood by lint: 'linkstyle 0 stroke:#f00'" <<<"$out" &&
  grep -q "diagram #2 line 2 .*reserved word 'end'" <<<"$out" &&
  grep -q "diagram #2 line 3 .*'style'" <<<"$out" &&
  ! grep -q "'style --> B' has no label" <<<"$out" &&
  ! grep -q "'A -->|x| End' has no label" <<<"$out"
}
# Fix round 4 (rereview-3 New-3, corrected against Mermaid): "--" inside a
# style/classDef/linkStyle argument list is a Mermaid parse error (Mermaid
# 11.15 rejects "style A fill:var(--a)" — its lexer reads "--" as a link),
# so the lint reports it with an accurate reason; but single dashes in CSS
# property names ("stroke-width") and "--" inside a quoted click URL are
# legal and must lint clean.
test_lint_flags_link_operator_in_style_args_only() {
  "$S/init.sh" t-lint-cssvar --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-cssvar
  mkdir -p /tmp/ps-commu/t-lint-cssvar/app
  cat > /tmp/ps-commu/t-lint-cssvar/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A -->|x| B
  style A fill:#f00,stroke:#333,stroke-width:2px
  classDef k fill:#0f0,stroke-dasharray:5 5
  linkStyle 0 stroke:#f00
  click A "http://x/a--o-b" "tip"
```

```mermaid
flowchart LR
  A -->|x| B
  style A fill:var(--a),stroke:var(--out)
  classDef k fill:var(--a),color:var(--xy)
  style A fill:#f00; B --> C
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-cssvar 2>&1)"; rc=$?
  (( rc == 1 )) &&
  ! grep -q "diagram #1" <<<"$out" &&
  (( $(grep -c "diagram #2 line [345] .*link operator" <<<"$out") == 3 ))
}
# Fix round 4 (rereview-3 New-4): byte-identical defect lines are printed once.
test_lint_dedupes_identical_defect_lines() {
  "$S/init.sh" t-lint-dedupe --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-dedupe
  mkdir -p /tmp/ps-commu/t-lint-dedupe/app
  cat > /tmp/ps-commu/t-lint-dedupe/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A --> B
  A --> B
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dedupe 2>&1)"; rc=$?
  (( rc == 1 )) && (( $(grep -c "'A --> B' has no label" <<<"$out") == 1 ))
}
# Fix round 4: a block whose first line is a %%{init}%% directive or a %%
# comment is still a flowchart and must be checked (the old first-line header
# match silently left such blocks entirely unvalidated).
test_lint_checks_block_behind_init_directive() {
  "$S/init.sh" t-lint-init --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-init
  mkdir -p /tmp/ps-commu/t-lint-init/app
  cat > /tmp/ps-commu/t-lint-init/app/content.md <<'EOF'
See F1 for details.

```mermaid
%%{init: {"theme": "dark"}}%%
%% a leading comment
flowchart LR
  A --> B
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-init 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "'A --> B' has no label" <<<"$out" &&
  ! grep -qi 'not understood' <<<"$out"
}
# Fix round 4 (oracle-backed): Mermaid only accepts %% comments on their own
# line; a trailing "%% note" after a statement is a parse error. The lint
# still validates the statement in front of it (so the edge defect is not
# masked) AND names the comment problem.
test_lint_flags_inline_comment_but_still_checks_edge() {
  "$S/init.sh" t-lint-inlcmt --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-inlcmt
  mkdir -p /tmp/ps-commu/t-lint-inlcmt/app
  cat > /tmp/ps-commu/t-lint-inlcmt/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  %% own-line comments are fine
  A --> B %% trailing comment
    %% indented own-line comment is fine too
  C -->|x| D
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-inlcmt 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "'A --> B' has no label" <<<"$out" &&
  (( $(grep -ci 'own line' <<<"$out") == 1 )) &&
  grep -q "line 3 .*own line" <<<"$out"
}
# Fix round 4 stress matrix (positive): every Mermaid flowchart link family,
# every node shape, edge ids, @{shape} data, unicode/dotted/dashed ids,
# a quoted label spanning lines, ";"-joined statements, a header on the same
# line as a statement, subgraph+direction, and every directive — all legal
# per Mermaid 11.15's own parser — lint CLEAN when every edge is labeled.
test_lint_passes_full_mermaid_vocabulary() {
  "$S/init.sh" t-lint-vocab --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-vocab
  mkdir -p /tmp/ps-commu/t-lint-vocab/app
  cat > /tmp/ps-commu/t-lint-vocab/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A -->|a| B ---|b| C -.->|c| D ==>|d| E --x|e| F --o|f| G
  A x--x|g| B
  A o--o|h| C
  A <-->|i| D
  A <-.->|j| E
  A <==>|k| F
  A -..->|l| G
  A ---->|m| B
  A ===|n| C
  A -.-|o| D
  A ~~~ E
  A -- p --> F
  A == q ==> G
  A -. r .-> B
  A -- s --x C
  A -- t ---- D
  A -- a-b --> E
  A -->|"quoted | pipe"| F
  A -->|has; semi and %% pct| G
  A e1@-->|u| B
```

```mermaid
graph TD;A-->|x|B
  C>odd] -->|x| D[/trap/] -->|x| E[\inv\] -->|x| F[/lean\]
  G(-ellipse-) -->|x| A([stadium]) -->|x| B[(cyl)] -->|x| C(((dc)))
  D[[sub]] -->|x| E{{hex}} -->|x| F((c)) -->|x| G(r)
  A{d} -->|x| B[s]:::hot -->|x| C@{ shape: circle, label: "a }b" }
  D["x ] y"] -->|x| E["`**md** text`"] -->|x| F["multi
  line"] -->|x| G[สวัสดี %% not; a comment]
  classDef hot fill:#f00
```

```mermaid
%%{init: {"theme": "dark"}}%%
flowchart TB
  accTitle: Title here
  accDescr: Description here
  subgraph grp["Group; title"]
    direction LR
    a.b -->|x| c-d; c-d -->|y| ก
  end
  subgraph plain
    n1 & n2 -->|z| n3 & ก
  end
  n3 -->|w| a.b & c-d
  n1:::hot -->|v| n2@{ shape: circle }
  class n1,n2 hot; classDef hot fill:#f00
  linkStyle default color:Sienna;
  style n3 fill:#0f0,stroke-width:2px
  click n1 "http://x/a--o-b" "tip" _blank
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-vocab 2>&1)"; rc=$?
  (( rc == 0 )) && [[ -z "$out" ]]
}
# Fix round 4 stress matrix (negative): every bare link family is reported
# unlabeled with its operator quoted as written; the invisible link "~~~"
# is the documented exception (it carries no information).
test_lint_fails_every_bare_operator() {
  "$S/init.sh" t-lint-bareops --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-bareops
  mkdir -p /tmp/ps-commu/t-lint-bareops/app
  cat > /tmp/ps-commu/t-lint-bareops/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A --> B
  A --- B
  A -.-> B
  A -.- B
  A ==> B
  A === B
  A --x B
  A --o B
  A x--x B
  A o--o B
  A <--> B
  A <-.-> B
  A <==> B
  A ---> B
  A -..-> B
  A ==o B
  C -->| | D
  A ~~~ B
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-bareops 2>&1)"; rc=$?
  (( rc == 1 )) && ! grep -qi 'not understood' <<<"$out" &&
  (( $(grep -c "has no label" <<<"$out") == 17 )) &&
  grep -qF "'C --> D' has no label" <<<"$out" &&
  for op in '-->' '---' '-.->' '-.-' '==>' '===' '--x' '--o' 'x--x' 'o--o' '<-->' '<-.->' '<==>' '--->' '-..->' '==o'; do
    grep -qF "'A $op B' has no label" <<<"$out" || return 1
  done
}
# Fix round 4 stress matrix (fail-closed): forms Mermaid itself rejects are
# each reported as a defect with a line number — never silently accepted,
# never allowed to mask a neighbouring edge's real defect.
test_lint_fails_closed_on_mermaid_rejected_forms() {
  "$S/init.sh" t-lint-rejects --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-rejects
  mkdir -p /tmp/ps-commu/t-lint-rejects/app
  cat > /tmp/ps-commu/t-lint-rejects/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  A --x --> B
  A --x B  C --o D
  A[a|b] -->|x| B
  A(text (nested) here) -->|x| B
  A [s] -->|x| B
  A -- t -->|u| B
  A:::hot:::cold -->|x| B
  A -->|x| B; end
  A -- --> B
  A -->|x| style
  Z -->|ok| Y
  W --> V
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-rejects 2>&1)"; rc=$?
  (( rc == 1 )) &&
  for ln in 2 3 4 5 6 7 8 9; do grep -q "line $ln " <<<"$out" || return 1; done &&
  grep -q "line 10 .*'-- -->'\|'A -- --> B' has no label" <<<"$out" &&
  grep -q "line 11 .*reserved word 'style'" <<<"$out" &&
  ! grep -q "line 12 " <<<"$out" &&
  grep -q "'W --> V' has no label" <<<"$out"
}
# Fix round 4 (block level, fail closed): a mermaid block whose first real
# line is not a Mermaid diagram type this lint knows (a typo such as
# "flowchat LR", or a body line before the header) must be REPORTED rather
# than silently left unchecked; a Mermaid "---" YAML front-matter block and
# %% lines before the header are skipped when finding it; and diagram types
# the lint has no rules for (classDiagram, pie, ...) still pass silently by
# design.
test_lint_reports_unknown_diagram_header_and_skips_frontmatter() {
  "$S/init.sh" t-lint-unkhdr --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-unkhdr
  mkdir -p /tmp/ps-commu/t-lint-unkhdr/app
  cat > /tmp/ps-commu/t-lint-unkhdr/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchat LR
  A --> B
```

```mermaid
accTitle: title first
flowchart LR
  C --> D
```

```mermaid
---
title: Front matter is legal
config:
  theme: dark
---
%% comment
flowchart LR
  E --> F
```

```mermaid
classDiagram
  Animal <|-- Duck
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-unkhdr 2>&1)"; rc=$?
  (( rc == 1 )) &&
  grep -q "diagram #1 header 'flowchat'" <<<"$out" &&
  grep -q "diagram #2 header 'accTitle:'" <<<"$out" &&
  grep -q "diagram #3 edge 'E --> F' has no label" <<<"$out" &&
  ! grep -q "diagram #4" <<<"$out" &&
  (( $(grep -c ':' <<<"$out") == 3 ))
}
# Fix round 4 (oracle-backed): Mermaid's lexer takes the WHOLE line holding
# "direction XX" as one token, so "direction LR; A --> B" parses fine in
# Mermaid but the edge never exists. Report it instead of mirroring the
# swallow; a plain "direction LR" line and a node named "direction" are fine.
test_lint_flags_text_swallowed_by_direction() {
  "$S/init.sh" t-lint-dirswallow --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-dirswallow
  mkdir -p /tmp/ps-commu/t-lint-dirswallow/app
  cat > /tmp/ps-commu/t-lint-dirswallow/app/content.md <<'EOF'
See F1 for details.

```mermaid
flowchart LR
  subgraph s
    direction LR
    direction -->|x| A
  end
  subgraph t
    direction TB; B --> C
  end
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dirswallow 2>&1)"; rc=$?
  (( rc == 1 )) && (( $(grep -c ':' <<<"$out") == 1 )) &&
  grep -q "line 7 .*'direction TB'.*ignores" <<<"$out"
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
check lint_fails_cross_circle_then_semicolon_stmt test_lint_fails_cross_circle_then_semicolon_stmt
check lint_fails_case_mismatched_header_not_skipped test_lint_fails_case_mismatched_header_not_skipped
check lint_fails_lowercase_keywords_and_End_node test_lint_fails_lowercase_keywords_and_End_node
check lint_flags_link_operator_in_style_args_only test_lint_flags_link_operator_in_style_args_only
check lint_dedupes_identical_defect_lines test_lint_dedupes_identical_defect_lines
check lint_checks_block_behind_init_directive test_lint_checks_block_behind_init_directive
check lint_flags_inline_comment_but_still_checks_edge test_lint_flags_inline_comment_but_still_checks_edge
check lint_passes_full_mermaid_vocabulary test_lint_passes_full_mermaid_vocabulary
check lint_fails_every_bare_operator test_lint_fails_every_bare_operator
check lint_fails_closed_on_mermaid_rejected_forms test_lint_fails_closed_on_mermaid_rejected_forms
check lint_reports_unknown_diagram_header_and_skips_frontmatter test_lint_reports_unknown_diagram_header_and_skips_frontmatter
check lint_flags_text_swallowed_by_direction test_lint_flags_text_swallowed_by_direction

# --- lint.sh (draw.io / mxGraph XML validator, Task 2) ---
# The ```drawio fence loop that replaced the Mermaid scanner above. These 9
# fixtures are the task's own required coverage; the bulk migration of the
# retired Mermaid tests above is a separate, later task.
test_lint_fails_drawio_malformed_xml() {  # unclosed XML tags -> ET.fromstring ParseError
  "$S/init.sh" t-lint-dmalformed --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-dmalformed
  mkdir -p /tmp/ps-commu/t-lint-dmalformed/app
  cat > /tmp/ps-commu/t-lint-dmalformed/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxGraphModel pageWidth="400" pageHeight="200">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0">
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dmalformed 2>&1)"; rc=$?
  (( rc == 1 )) && grep -qi 'unparseable' <<<"$out"
}
test_lint_fails_drawio_missing_root_cells() {  # valid XML missing id="1" parent="0"
  "$S/init.sh" t-lint-drootcells --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-drootcells
  mkdir -p /tmp/ps-commu/t-lint-drootcells/app
  cat > /tmp/ps-commu/t-lint-drootcells/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxGraphModel pageWidth="400" pageHeight="200">
  <root>
    <mxCell id="0" />
    <mxCell id="A" value="Solo" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="0">
      <mxGeometry x="40" y="40" width="120" height="60" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-drootcells 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q 'root mxCell id="1"' <<<"$out"
}
test_lint_fails_drawio_unlabeled_edge() {  # edge="1" cell with no value attribute
  "$S/init.sh" t-lint-dedge --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-dedge
  mkdir -p /tmp/ps-commu/t-lint-dedge/app
  cat > /tmp/ps-commu/t-lint-dedge/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxGraphModel pageWidth="800" pageHeight="300">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="Start" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="40" y="40" width="120" height="60" as="geometry" />
    </mxCell>
    <mxCell id="B" value="End" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="240" y="40" width="120" height="60" as="geometry" />
    </mxCell>
    <mxCell id="e1" style="html=1;" edge="1" parent="1" source="A" target="B">
      <mxGeometry relative="1" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dedge 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "edge 'e1' has no label" <<<"$out"
}
test_lint_fails_drawio_node_cap() {  # 8 vertex cells in one diagram -> over the 7-node cap
  "$S/init.sh" t-lint-dnodecap --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-dnodecap
  mkdir -p /tmp/ps-commu/t-lint-dnodecap/app
  {
    echo 'See F1 for details.'
    echo
    echo '```drawio'
    echo '<mxGraphModel pageWidth="1400" pageHeight="300">'
    echo '  <root>'
    echo '    <mxCell id="0" />'
    echo '    <mxCell id="1" parent="0" />'
    for i in 1 2 3 4 5 6 7 8; do
      local x=$(( (i - 1) * 150 ))
      printf '    <mxCell id="V%d" value="V%d" style="rounded=1;whiteSpace=wrap;html=1;role=accent;" vertex="1" parent="1">\n' "$i" "$i"
      printf '      <mxGeometry x="%d" y="40" width="120" height="60" as="geometry" />\n' "$x"
      echo '    </mxCell>'
    done
    echo '  </root>'
    echo '</mxGraphModel>'
    echo '```'
  } > /tmp/ps-commu/t-lint-dnodecap/app/content.md
  local out rc; out="$("$S/lint.sh" t-lint-dnodecap 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q '8 vertex cells (max 7)' <<<"$out"
}
test_lint_fails_drawio_overlap() {  # two vertex geometries with overlapping x/y/width/height
  "$S/init.sh" t-lint-doverlap --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-doverlap
  mkdir -p /tmp/ps-commu/t-lint-doverlap/app
  cat > /tmp/ps-commu/t-lint-doverlap/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxGraphModel pageWidth="800" pageHeight="600">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="A" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="40" y="40" width="120" height="60" as="geometry" />
    </mxCell>
    <mxCell id="B" value="B" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="100" y="60" width="120" height="60" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-doverlap 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "vertex 'A' overlaps vertex 'B'" <<<"$out"
}
test_lint_fails_drawio_out_of_bounds() {  # x+width exceeds the graph's declared pageWidth
  "$S/init.sh" t-lint-doob --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-doob
  mkdir -p /tmp/ps-commu/t-lint-doob/app
  cat > /tmp/ps-commu/t-lint-doob/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxGraphModel pageWidth="200" pageHeight="200">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="A" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="150" y="50" width="100" height="60" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-doob 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "extends beyond the declared page bounds" <<<"$out"
}
test_lint_fails_drawio_unescaped_label() {  # value="F<n> cites this" — a literal '<'
  "$S/init.sh" t-lint-dunesc --tier html >/dev/null                # surviving XML-decode, e.g. via
  _lint_valid_brief_facts_storyboard t-lint-dunesc                 # &lt;n&gt; — valid XML, but
  mkdir -p /tmp/ps-commu/t-lint-dunesc/app                          # corrupts the html=1 render
  cat > /tmp/ps-commu/t-lint-dunesc/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxGraphModel pageWidth="800" pageHeight="400">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="F&lt;n&gt; cites this"
        style="rounded=1;whiteSpace=wrap;html=1;role=accent;" vertex="1" parent="1">
      <mxGeometry x="40" y="40" width="160" height="60" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dunesc 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "literal '<' after XML-decoding" <<<"$out"
}
test_lint_fails_drawio_raw_hex() {  # style has fillColor=#1c4f8f instead of role=accent
  "$S/init.sh" t-lint-dhex --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-dhex
  mkdir -p /tmp/ps-commu/t-lint-dhex/app
  cat > /tmp/ps-commu/t-lint-dhex/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxGraphModel pageWidth="800" pageHeight="400">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="Plain label"
        style="rounded=1;whiteSpace=wrap;html=1;fillColor=#1c4f8f;" vertex="1" parent="1">
      <mxGeometry x="40" y="40" width="160" height="60" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dhex 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "raw hex color 'fillColor=#1c4f8f'" <<<"$out"
}
test_lint_passes_drawio_valid() {  # Task 0's final verified XML, wrapped in a ```drawio fence
  "$S/init.sh" t-lint-dvalid --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-dvalid
  mkdir -p /tmp/ps-commu/t-lint-dvalid/app
  cat > /tmp/ps-commu/t-lint-dvalid/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxGraphModel dx="800" dy="600" grid="1" gridSize="10" guides="1" tooltips="1"
    connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1400"
    pageHeight="400" math="0" shadow="0">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="init.sh" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="40" y="140" width="160" height="60" as="geometry" />
    </mxCell>
    <mxCell id="B" value="00-brief / 01-facts / 02-storyboard + app/"
        style="rounded=1;whiteSpace=wrap;html=1;role=accent;" vertex="1" parent="1">
      <mxGeometry x="240" y="140" width="200" height="60" as="geometry" />
    </mxCell>
    <mxCell id="C" value="serve.sh" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="480" y="140" width="160" height="60" as="geometry" />
    </mxCell>
    <mxCell id="D" value="lint clean?" style="rhombus;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="680" y="130" width="140" height="80" as="geometry" />
    </mxCell>
    <mxCell id="E" value="live at 127.0.0.1:PORT"
        style="rounded=1;whiteSpace=wrap;html=1;role=check;" vertex="1" parent="1">
      <mxGeometry x="860" y="140" width="200" height="60" as="geometry" />
    </mxCell>
    <mxCell id="F" value="6 PASS/FAIL/SKIP asserts"
        style="rounded=1;whiteSpace=wrap;html=1;role=check;" vertex="1" parent="1">
      <mxGeometry x="1100" y="140" width="220" height="60" as="geometry" />
    </mxCell>
    <mxCell id="e1" value="scaffold workspace + advisory port" style="html=1;"
        edge="1" parent="1" source="A" target="B">
      <mxGeometry relative="1" as="geometry">
        <mxPoint x="0" y="-24" as="offset" />
      </mxGeometry>
    </mxCell>
    <mxCell id="e2" value="author edits content.md" style="html=1;" edge="1" parent="1"
        source="B" target="C">
      <mxGeometry relative="1" as="geometry">
        <mxPoint x="0" y="-24" as="offset" />
      </mxGeometry>
    </mxCell>
    <mxCell id="e3" value="run lint.sh gate" style="html=1;" edge="1" parent="1"
        source="C" target="D">
      <mxGeometry relative="1" as="geometry">
        <mxPoint x="0" y="-24" as="offset" />
      </mxGeometry>
    </mxCell>
    <mxCell id="e4" value="no: exit 1" style="html=1;role=pitfall;" edge="1" parent="1"
        source="D" target="B">
      <mxGeometry relative="1" as="geometry">
        <Array as="points"><mxPoint x="750" y="60" /></Array>
      </mxGeometry>
    </mxCell>
    <mxCell id="e5" value="yes: bind 127.0.0.1 + watchdog" style="html=1;role=check;"
        edge="1" parent="1" source="D" target="E">
      <mxGeometry relative="1" as="geometry">
        <mxPoint x="0" y="-24" as="offset" />
      </mxGeometry>
    </mxCell>
    <mxCell id="e6" value="verify.sh: headless Chrome" style="html=1;" edge="1" parent="1"
        source="E" target="F">
      <mxGeometry relative="1" as="geometry">
        <mxPoint x="0" y="-24" as="offset" />
      </mxGeometry>
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  "$S/lint.sh" t-lint-dvalid
}

check lint_fails_drawio_malformed_xml      test_lint_fails_drawio_malformed_xml
check lint_fails_drawio_missing_root_cells test_lint_fails_drawio_missing_root_cells
check lint_fails_drawio_unlabeled_edge     test_lint_fails_drawio_unlabeled_edge
check lint_fails_drawio_node_cap           test_lint_fails_drawio_node_cap
check lint_fails_drawio_overlap            test_lint_fails_drawio_overlap
check lint_fails_drawio_out_of_bounds      test_lint_fails_drawio_out_of_bounds
check lint_fails_drawio_unescaped_label    test_lint_fails_drawio_unescaped_label
check lint_fails_drawio_raw_hex            test_lint_fails_drawio_raw_hex
check lint_passes_drawio_valid             test_lint_passes_drawio_valid

# --- cherry-setup.js drawio render pipeline (Task 1: frameAndRunDrawio) ---
# Needs Google Chrome (headless --dump-dom) — SKIPs visibly without it, same
# convention as the verify.sh tests below (rc 2 = cannot run, never a pass).
test_drawio_fence_detection_and_role_substitution() {
  local chrome="" c
  if [[ -n "${CHROME_BIN:-}" && -x "${CHROME_BIN:-}" ]]; then
    chrome="$CHROME_BIN"
  else
    for c in google-chrome google-chrome-stable chromium chromium-browser; do
      chrome="$(command -v "$c" 2>/dev/null)" && break
    done
    if [[ -z "$chrome" ]]; then
      c="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
      [[ -x "$c" ]] && chrome="$c"
    fi
  fi
  if [[ -z "$chrome" ]]; then echo "SKIP: no Google Chrome found (set CHROME_BIN)"; return 2; fi

  # Static HTML fixture: the real theme.css + cherry-setup.js (read-only
  # copies, never the workspace lifecycle machinery) plus the pinned draw.io
  # viewer CDN script, one <pre><code class="language-drawio"> block (exactly
  # what Cherry-Markdown's core build emits for a ```drawio fence) with a
  # role=accent; styled vertex, then a direct call to
  # frameAndRunDrawio(document.getElementById('root')) — no Cherry-Markdown
  # parsing in the loop, this isolates the render function itself.
  local d=/tmp/ps-commu/t-drawio-role
  mkdir -p "$d"
  cp "$SKILL_DIR/assets/template-infographic/cherry-setup.js" "$d/cherry-setup.js"
  cp "$SKILL_DIR/assets/template-infographic/theme.css" "$d/theme.css"

  # Expected hex read from the REAL theme.css at test time (never hardcoded)
  # so this test can't silently drift from F-011's own color rule.
  local accent_hex
  accent_hex="$(grep -oE -- '--accent:[[:space:]]*#[0-9a-fA-F]{6}' "$d/theme.css" | head -1 | grep -oE '#[0-9a-fA-F]{6}')"
  [[ -n "$accent_hex" ]] || { echo "FAIL: could not read --accent from theme.css"; return 1; }

  cat > "$d/fixture.html" <<'HTML'
<!DOCTYPE html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="./theme.css">
<script src="https://cdn.jsdelivr.net/gh/jgraph/drawio@v31.5.2/src/main/webapp/js/viewer-static.min.js"></script>
<script src="./cherry-setup.js"></script>
</head>
<body>
<div id="root"><pre><code class="language-drawio">&lt;mxGraphModel dx="400" dy="200" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="400" pageHeight="200" math="0" shadow="0"&gt;
  &lt;root&gt;
    &lt;mxCell id="0" /&gt;
    &lt;mxCell id="1" parent="0" /&gt;
    &lt;mxCell id="A" value="hi" style="rounded=1;whiteSpace=wrap;html=1;role=accent;" vertex="1" parent="1"&gt;
      &lt;mxGeometry x="40" y="40" width="120" height="40" as="geometry" /&gt;
    &lt;/mxCell&gt;
  &lt;/root&gt;
&lt;/mxGraphModel&gt;</code></pre></div>
<script>
  Promise.resolve(frameAndRunDrawio(document.getElementById('root'))).finally(function () {
    document.title = 'drawio-fixture-done';
  });
</script>
</body></html>
HTML

  python3 -m http.server 7699 --bind 127.0.0.1 --directory "$d" >/dev/null 2>&1 &
  local httpd=$!
  sleep 1

  # Mirrors verify.sh's own Chrome --dump-dom harness: this Chrome build
  # prints the DOM to stdout and then hangs on shutdown (does not exit on its
  # own), so a plain `timeout` wrapper is not enough — it only signals the
  # direct child, while helper/renderer processes still hold the stdout pipe
  # open, so a shell redirect never sees EOF. Read non-blockingly until
  # </html> appears, then SIGKILL the whole process group ourselves.
  local dump
  dump="$(python3 - "$chrome" "http://127.0.0.1:7699/fixture.html" <<'PY'
import os, select, shutil, signal, subprocess, sys, tempfile, time
chrome, url = sys.argv[1], sys.argv[2]
prof = tempfile.mkdtemp(prefix="ps-commu-drawio-test-")
proc = None
out = b""
try:
    cmd = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
           "--no-default-browser-check", "--disable-background-networking", "--disable-sync",
           "--disable-component-update", "--disable-extensions", "--window-size=1280,900",
           "--user-data-dir=" + prof, "--enable-logging=stderr", "--v=0",
           "--virtual-time-budget=8000", "--run-all-compositor-stages-before-draw",
           "--dump-dom", url]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    end = time.time() + 90
    fds = [proc.stdout, proc.stderr]
    while fds and time.time() < end and b"</html>" not in out:
        r, _, _ = select.select(fds, [], [], 0.5)
        for f in r:
            chunk = os.read(f.fileno(), 65536)
            if not chunk: fds.remove(f); continue
            if f is proc.stdout: out += chunk
finally:
    if proc is not None and proc.poll() is None:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    if proc is not None:
        try: proc.wait(timeout=5)
        except Exception: pass
    shutil.rmtree(prof, ignore_errors=True)
sys.stdout.write(out.decode("utf-8", "replace"))
PY
)"
  kill "$httpd" 2>/dev/null

  if [[ "$dump" != *"</html>"* ]]; then
    echo "FAIL: Chrome produced no complete DOM within 90s"; return 1
  fi
  if [[ "$dump" != *"drawio-fixture-done"* ]]; then
    echo "FAIL: page never reached document.title='drawio-fixture-done' — frameAndRunDrawio threw or never resolved"; return 1
  fi
  if [[ "$dump" != *"data-mxgraph"* ]]; then
    echo "FAIL: no data-mxgraph div found — fence was not detected/converted"; return 1
  fi
  if [[ "$dump" == *"role=accent"* ]]; then
    echo "FAIL: literal 'role=accent' token survived substitution"; return 1
  fi
  if [[ "$dump" != *"$accent_hex"* ]]; then
    echo "FAIL: substituted xml does not contain the real --accent hex ($accent_hex)"; return 1
  fi
  # The four checks above all pass on the data-mxgraph ATTRIBUTE alone, which
  # frameAndRunDrawio builds BEFORE calling GraphViewer.processElements() —
  # they'd stay green even if that call were silently removed. Assert the
  # diagram actually got RENDERED (an <svg> exists with the real stroke
  # color), so a regression that breaks the processElements() trigger itself
  # is caught here, not just the substitution logic upstream of it.
  if [[ "$dump" != *"<svg"* ]]; then
    echo "FAIL: no <svg> in the dump — GraphViewer never rendered the div (processElements() not called, or failed)"; return 1
  fi
  if [[ "$dump" != *"stroke=\"$accent_hex\""* ]]; then
    echo "FAIL: rendered <svg> has no stroke=\"$accent_hex\" — GraphViewer rendered, but not with the substituted color"; return 1
  fi
  return 0
}

check_or_skip drawio_fence_detection_and_role_substitution test_drawio_fence_detection_and_role_substitution

# --- verify.sh (render gate; needs Google Chrome — SKIPs visibly without it) ---
# A verify run is ~45s on macOS (Chrome start + CDN load + Mermaid render).
verify_run() {           # args... → verify.sh output on stdout; rc 2 = cannot run (Chrome/server)
  if command -v timeout >/dev/null; then timeout 150 "$S/verify.sh" "$@"; else "$S/verify.sh" "$@"; fi
}
test_verify_passes_template() {
  # --no-lint: deliberate deviation from --no-lint's "html/react dev loop
  # only" framing in serve.sh's usage text. This test scaffolds a PLAIN
  # (no --example) infographic workspace: app/content.md ships as the real,
  # lint-clean Task 7 exemplar (it cites F1-F19), but 01-facts.md/etc. scaffold
  # as the EMPTY authoring-chain skeleton (see init.sh, no --example flag), so
  # lint.sh would correctly reject content.md's citations against an empty
  # facts sheet. init.sh --example (see init_example_* tests above) is the
  # flow that pairs content.md with a matching filled chain and lints clean.
  "$S/init.sh" t-verify >/dev/null
  "$S/serve.sh" t-verify --no-lint >/dev/null
  local out rc; out="$(verify_run t-verify)"; rc=$?
  echo "$out"
  (( rc == 2 )) && return 2
  (( rc == 0 )) &&
  grep -q '^PASS: 1 mermaid svg=1 fences=1' <<<"$out" &&
  ! grep -q '^FAIL' <<<"$out"
}
test_verify_dump_text() {  # --dump-text: clean reader-visible text on stdout, exit 0, no raw markup leaks
  local out rc; out="$(verify_run t-verify --dump-text)"; rc=$?
  echo "chars=${#out}"
  (( rc == 2 )) && return 2
  (( rc == 0 )) &&
  [[ -n "$out" ]] &&
  ! grep -q 'data-nav' <<<"$out" &&
  ! grep -q '```mermaid' <<<"$out" &&
  ! grep -qE '^(PASS|FAIL|SKIP):' <<<"$out"
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
check_or_skip verify_dump_text       test_verify_dump_text
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
