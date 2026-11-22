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
_selected() { [[ -z "${ONLY:-}" || "$1" =~ $ONLY ]]; }   # ONLY=<regex>: run only matching test names
check(){               # on FAIL, show the test's output so CI logs say why
  _selected "$1" || return 0
  local name="$1"; shift
  if "$@" >"$CHECK_LOG" 2>&1; then ok "$name"; else bad "$name"; tail -n 25 "$CHECK_LOG" | sed 's/^/    /'; fi
}
check_or_skip(){       # like check, but exit code 2 = visible SKIP (e.g. no Chrome) — never a pass
  _selected "$1" || return 0
  local name="$1"; shift; local rc
  "$@" >"$CHECK_LOG" 2>&1; rc=$?
  if (( rc == 0 )); then ok "$name"
  elif (( rc == 2 )); then skip "$name — $(grep -m1 '^SKIP' "$CHECK_LOG" || head -n1 "$CHECK_LOG")"
  else bad "$name"; tail -n 25 "$CHECK_LOG" | sed 's/^/    /'; fi
}

# --- common.sh ---
source "$S/common.sh"
# Pre-F-015 tests build html-tier workspaces from the default template, which contains a
# .mermaid block; lint.sh would run real mmdc (~15s) for each. Point it at a missing binary
# by default (warn-and-skip); the F-015 tests that need real mmdc pass MMDC_BIN=mmdc explicitly.
export MMDC_BIN=/nonexistent/mmdc

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

Reader: a developer new to X.

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
test_lint_flags_unverifiable_q_coverage_when_brief_missing() {  # regression: an empty
  "$S/init.sh" t-lint-nobrief --tier html >/dev/null              # q_ids (brief missing) must
  _lint_valid_brief_facts_storyboard t-lint-nobrief                 # report "cannot verify", not
  rm -f /tmp/ps-commu/t-lint-nobrief/00-brief.md                    # silently skip Q-coverage
  local out rc; out="$("$S/lint.sh" t-lint-nobrief 2>&1)"; rc=$?
  (( rc == 1 )) && grep -qi 'cannot verify' <<<"$out"
}

check lint_passes_starter       test_lint_passes_starter
check lint_fails_uncited_fact   test_lint_fails_uncited_fact
check lint_flags_unverifiable_q_coverage_when_brief_missing test_lint_flags_unverifiable_q_coverage_when_brief_missing

# --- lint.sh (draw.io / mxGraph XML validator, Task 2 + Task 5 migration) ---
# The ```drawio fence loop that replaced the retired Mermaid-grammar scanner.
# Task 2's own 19 fixtures (through lint_fails_drawio_bare_ampersand below)
# are its own required coverage; the migration block after them (from
# lint_dedupes_drawio_defect_lines on) is Task 5's: every retired Mermaid
# test above this comment was read function-by-function and classified as
# (a) redundant with a Task 2 fixture already covering the same lesson —
# deleted, (b) a genuine format-agnostic lesson with no drawio-format test
# yet — a new test written below, or (c) genuinely Mermaid-syntax-specific
# with no XML analog (regex-tokenization ambiguities, keyword-case
# collisions, link-family enumeration — none of which a real XML parser can
# exhibit) — deleted with no replacement.
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
_drawio_br_fixture() {  # slug label-value — one-vertex diagram with the given label
  "$S/init.sh" "$1" --tier html >/dev/null
  _lint_valid_brief_facts_storyboard "$1"
  mkdir -p "/tmp/ps-commu/$1/app"
  cat > "/tmp/ps-commu/$1/app/content.md" <<EOF
See F1 for details.

\`\`\`drawio
<mxGraphModel pageWidth="800" pageHeight="400">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="$2"
        style="rounded=1;whiteSpace=wrap;html=1;role=accent;" vertex="1" parent="1">
      <mxGeometry x="40" y="40" width="160" height="60" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
\`\`\`
EOF
}
test_lint_passes_drawio_br_label() {  # &lt;br&gt; is draw.io's own html=1 line break
  _drawio_br_fixture t-lint-dbr 'line one&lt;br&gt;line two&lt;br/&gt;three'
  "$S/lint.sh" t-lint-dbr
}
test_lint_fails_drawio_double_escaped_br() {  # &amp;lt;br&amp;gt; shows the reader a literal <br>
  _drawio_br_fixture t-lint-dbr2 'line one&amp;lt;br&amp;gt;line two'
  local out rc; out="$("$S/lint.sh" t-lint-dbr2 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "double-escaped line break" <<<"$out"
}
test_lint_fails_drawio_br_lookalikes() {  # only a bare <br>/<br/> in an html=1 label is allowed
  local label out
  for label in 'a&lt;br onload=x&gt;b' 'a&lt;bra&gt;b'; do
    _drawio_br_fixture t-lint-dbr3 "$label"
    out="$("$S/lint.sh" t-lint-dbr3 2>&1)" && return 1
    grep -q "literal '<' after XML-decoding" <<<"$out" || return 1
  done
  _drawio_br_fixture t-lint-dbr3 'a&lt;br&gt;b'
  sed -i.bak 's/html=1;//' /tmp/ps-commu/t-lint-dbr3/app/content.md   # plain-text label
  out="$("$S/lint.sh" t-lint-dbr3 2>&1)" && return 1
  grep -q "needs html=1" <<<"$out"
}
test_lint_fails_missing_reader() {  # brief without a filled Reader: line
  "$S/init.sh" t-lint-noreader --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-noreader
  sed -i.bak '/^Reader:/d' /tmp/ps-commu/t-lint-noreader/00-brief.md
  local out rc; out="$("$S/lint.sh" t-lint-noreader 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "missing a filled 'Reader:' line" <<<"$out"
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

# --- fix round 1 (5 Important review findings, A-F) ---------------------
test_lint_passes_drawio_origin_vertex() {  # (A) mxCodec omits x/y at the
  "$S/init.sh" t-lint-dorigin --tier html >/dev/null              # default 0 -- a legit
  _lint_valid_brief_facts_storyboard t-lint-dorigin                # origin-positioned vertex
  mkdir -p /tmp/ps-commu/t-lint-dorigin/app                        # must lint clean, not
  cat > /tmp/ps-commu/t-lint-dorigin/app/content.md <<'EOF'         # "missing x/y"
See F1 for details.

```drawio
<mxGraphModel pageWidth="800" pageHeight="400">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="Origin" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry width="120" height="60" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  "$S/lint.sh" t-lint-dorigin
}
test_lint_fails_drawio_bounds_unverifiable() {  # (B) no pageWidth/pageHeight
  "$S/init.sh" t-lint-dnobounds --tier html >/dev/null              # at all -> must be its
  _lint_valid_brief_facts_storyboard t-lint-dnobounds                # own defect, never a
  mkdir -p /tmp/ps-commu/t-lint-dnobounds/app                        # silent skip
  cat > /tmp/ps-commu/t-lint-dnobounds/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxGraphModel>
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="A" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="9000" y="9000" width="120" height="60" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dnobounds 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q 'so vertex bounds cannot be verified' <<<"$out"
}
test_lint_fails_drawio_content_sniffed_fence() {  # (C) an UNLABELLED ```xml
  "$S/init.sh" t-lint-dsniff --tier html >/dev/null                 # fence whose body starts
  _lint_valid_brief_facts_storyboard t-lint-dsniff                  # with <mxGraphModel must
  mkdir -p /tmp/ps-commu/t-lint-dsniff/app                          # still be validated --
  cat > /tmp/ps-commu/t-lint-dsniff/app/content.md <<'EOF'          # cherry-setup.js renders
See F1 for details.                                                # it regardless of tag

```xml
<mxGraphModel pageWidth="800" pageHeight="300">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="A" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="40" y="40" width="120" height="60" as="geometry" />
    </mxCell>
    <mxCell id="B" value="B" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="240" y="40" width="120" height="60" as="geometry" />
    </mxCell>
    <mxCell id="e1" edge="1" parent="1" source="A" target="B">
      <mxGeometry relative="1" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dsniff 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "edge 'e1' has no label" <<<"$out"
}
test_lint_passes_drawio_grouped_siblings_no_false_overlap() {  # (D) two
  "$S/init.sh" t-lint-dgroupok --tier html >/dev/null                 # unrelated groups, each
  _lint_valid_brief_facts_storyboard t-lint-dgroupok                  # with a child at the SAME
  mkdir -p /tmp/ps-commu/t-lint-dgroupok/app                          # relative offset -- must
  cat > /tmp/ps-commu/t-lint-dgroupok/app/content.md <<'EOF'          # NOT be flagged: their
See F1 for details.                                                  # absolute positions don't
                                                                       # overlap
```drawio
<mxGraphModel pageWidth="1200" pageHeight="400">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="G1" value="Group 1" style="group;html=1;role=accent;" vertex="1"
        parent="1">
      <mxGeometry x="0" y="0" width="200" height="200" as="geometry" />
    </mxCell>
    <mxCell id="a" value="a" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="G1">
      <mxGeometry x="10" y="10" width="80" height="40" as="geometry" />
    </mxCell>
    <mxCell id="G2" value="Group 2" style="group;html=1;role=accent;" vertex="1"
        parent="1">
      <mxGeometry x="600" y="0" width="200" height="200" as="geometry" />
    </mxCell>
    <mxCell id="b" value="b" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="G2">
      <mxGeometry x="10" y="10" width="80" height="40" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  "$S/lint.sh" t-lint-dgroupok
}
test_lint_fails_drawio_grouped_child_out_of_bounds() {  # (D) the false-
  "$S/init.sh" t-lint-dgroupoob --tier html >/dev/null                 # negative direction: a
  _lint_valid_brief_facts_storyboard t-lint-dgroupoob                  # child whose ABSOLUTE
  mkdir -p /tmp/ps-commu/t-lint-dgroupoob/app                          # position (group offset
  cat > /tmp/ps-commu/t-lint-dgroupoob/app/content.md <<'EOF'          # + its own relative x/y)
See F1 for details.                                                   # is off-page must be
                                                                        # caught even though the
```drawio                                                              # group itself is in-bounds
<mxGraphModel pageWidth="400" pageHeight="300">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="G1" value="Group" style="group;html=1;role=accent;" vertex="1" parent="1">
      <mxGeometry x="10" y="10" width="60" height="60" as="geometry" />
    </mxCell>
    <mxCell id="a" value="a" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="G1">
      <mxGeometry x="380" y="10" width="80" height="40" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dgroupoob 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "vertex 'a' extends beyond the declared page bounds" <<<"$out"
}
test_lint_fails_drawio_negative_width() {  # (E) width="-160" must be its own
  "$S/init.sh" t-lint-dnegw --tier html >/dev/null                # defect (non-positive
  _lint_valid_brief_facts_storyboard t-lint-dnegw                 # geometry), not a silently
  mkdir -p /tmp/ps-commu/t-lint-dnegw/app                         # clean inverted AABB that
  cat > /tmp/ps-commu/t-lint-dnegw/app/content.md <<'EOF'         # masks a genuine overlap
See F1 for details.

```drawio
<mxGraphModel pageWidth="800" pageHeight="400">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="A" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="200" y="40" width="-160" height="60" as="geometry" />
    </mxCell>
    <mxCell id="B" value="B" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="60" y="40" width="120" height="60" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dnegw 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "vertex 'A' has non-positive geometry" <<<"$out"
}
test_lint_fails_drawio_negative_position_out_of_bounds() {  # (E) the bounds
  "$S/init.sh" t-lint-dnegpos --tier html >/dev/null                 # check was one-sided --
  _lint_valid_brief_facts_storyboard t-lint-dnegpos                  # x<0/y<0 (off-page to the
  mkdir -p /tmp/ps-commu/t-lint-dnegpos/app                          # left/top) must now be
  cat > /tmp/ps-commu/t-lint-dnegpos/app/content.md <<'EOF'          # caught too
See F1 for details.

```drawio
<mxGraphModel pageWidth="400" pageHeight="300">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="A" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="-900" y="-900" width="120" height="60" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dnegpos 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "vertex 'A' extends beyond the declared page bounds" <<<"$out"
}
test_lint_fails_drawio_vertex_edge_exclusivity() {  # (F) both vertex="1"
  "$S/init.sh" t-lint-dboth --tier html >/dev/null                # AND edge="1" set on the
  _lint_valid_brief_facts_storyboard t-lint-dboth                 # same cell
  mkdir -p /tmp/ps-commu/t-lint-dboth/app
  cat > /tmp/ps-commu/t-lint-dboth/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxGraphModel pageWidth="800" pageHeight="400">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="Weird" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" edge="1" parent="1">
      <mxGeometry x="40" y="40" width="120" height="60" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dboth 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q 'both vertex="1" and edge="1"' <<<"$out"
}
test_lint_fails_drawio_duplicate_id() {  # (F) two mxCell elements sharing id="A"
  "$S/init.sh" t-lint-ddupe --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-ddupe
  mkdir -p /tmp/ps-commu/t-lint-ddupe/app
  cat > /tmp/ps-commu/t-lint-ddupe/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxGraphModel pageWidth="800" pageHeight="400">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="First" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="40" y="40" width="120" height="60" as="geometry" />
    </mxCell>
    <mxCell id="A" value="Second" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="240" y="40" width="120" height="60" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-ddupe 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q "duplicate mxCell id 'A'" <<<"$out"
}
test_lint_fails_drawio_bare_ampersand() {  # (F) pins the "ET.fromstring itself
  "$S/init.sh" t-lint-damp --tier html >/dev/null                 # rejects a bare &" guarantee
  _lint_valid_brief_facts_storyboard t-lint-damp                  # that the bare-& check was
  mkdir -p /tmp/ps-commu/t-lint-damp/app                          # deliberately NOT built on
  cat > /tmp/ps-commu/t-lint-damp/app/content.md <<'EOF'          # top of, with a live fixture
See F1 for details.                                              # instead of manual-only proof

```drawio
<mxGraphModel pageWidth="800" pageHeight="400">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="Q&A" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="40" y="40" width="120" height="60" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-damp 2>&1)"; rc=$?
  (( rc == 1 )) && grep -qi 'unparseable' <<<"$out"
}

# --- Task 5: drawio-format migrations of still-relevant retired Mermaid lessons ---
test_lint_dedupes_drawio_defect_lines() {  # drawio-format instance of the SAME lesson
  # the retired Mermaid test_lint_dedupes_identical_defect_lines pinned: byte-identical
  # defect lines produced by TWO different cells must still print once. Two mxCell
  # elements sharing the duplicate id "e1", both unlabeled edges, make report() emit
  # the SAME "edge 'e1' has no label" text twice (once per cell) -- the final dedupe
  # pass (lint.sh's `seen` set) must still collapse that to a single printed line.
  "$S/init.sh" t-lint-ddedup --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-ddedup
  mkdir -p /tmp/ps-commu/t-lint-ddedup/app
  cat > /tmp/ps-commu/t-lint-ddedup/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxGraphModel>
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="e1" style="html=1;" edge="1" parent="1" />
    <mxCell id="e1" style="html=1;" edge="1" parent="1" />
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-ddedup 2>&1)"; rc=$?
  (( rc == 1 )) &&
  (( $(grep -c "edge 'e1' has no label" <<<"$out") == 1 ))
}
test_lint_checks_drawio_inside_mxfile_wrapper() {  # drawio-format instance of the SAME
  # lesson the retired Mermaid test_lint_checks_block_behind_init_directive pinned:
  # content sitting BEHIND something else (there: a %%{init}%% directive; here: draw.io's
  # own <mxfile><diagram> export wrapper) must still be fully checked. pageWidth/
  # pageHeight live on the NESTED <mxGraphModel>, not <mxfile> -- if lint.sh's own
  # unwrap (graph_model = model.find('.//mxGraphModel') when the root tag isn't
  # mxGraphModel) ever regresses, this out-of-bounds vertex would go unreported or get
  # the generic "cannot be verified" bounds message instead of the real defect.
  "$S/init.sh" t-lint-dmxfile --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-dmxfile
  mkdir -p /tmp/ps-commu/t-lint-dmxfile/app
  cat > /tmp/ps-commu/t-lint-dmxfile/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxfile host="app.diagrams.net">
  <diagram name="Page-1">
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
  </diagram>
</mxfile>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dmxfile 2>&1)"; rc=$?
  (( rc == 1 )) &&
  grep -q "vertex 'A' extends beyond the declared page bounds" <<<"$out" &&
  ! grep -qi 'cannot be verified' <<<"$out"
}
test_lint_fails_drawio_ambiguous_cell_type() {  # this lint's own vertex/edge-exclusivity
  # check has a branch for a non-root mxCell with NEITHER vertex="1" NOR edge="1" set
  # (mirroring the "both set" branch pinned by test_lint_fails_drawio_vertex_edge_
  # exclusivity), but nothing exercised it until now. This is the drawio-format
  # instance of the single most-repeated lesson across the retired Mermaid suite
  # (test_lint_fails_unparseable_statement_with_line_number, test_lint_fails_closed_
  # on_mermaid_rejected_forms, test_lint_reports_unknown_diagram_header_and_skips_
  # frontmatter): a cell of genuinely ambiguous/unclassifiable type must be reported,
  # fail closed, never silently skipped as though it were neither a vertex nor an edge.
  "$S/init.sh" t-lint-dambig --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-dambig
  mkdir -p /tmp/ps-commu/t-lint-dambig/app
  cat > /tmp/ps-commu/t-lint-dambig/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxGraphModel>
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="Ambiguous" style="html=1;" parent="1" />
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dambig 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q 'neither vertex="1" nor edge="1"' <<<"$out"
}
test_lint_reports_all_drawio_defects_without_masking() {  # drawio-format instance of a
  # lesson repeated across several retired Mermaid tests (test_lint_fails_closed_on_
  # mermaid_rejected_forms's explicit "never allowed to mask a neighbouring edge's real
  # defect"; test_lint_combined_regression_matrix's whole premise of many simultaneous
  # defects in one diagram): one diagram with THREE unrelated, independently-triggered
  # defect classes (an out-of-bounds vertex, a raw hex color, an unlabeled edge) must
  # report ALL THREE together in one lint run. None of Task 2's own 19 drawio fixtures
  # exercises more than one defect class at a time, so nothing yet proved the per-cell
  # loop never short-circuits after its first finding.
  "$S/init.sh" t-lint-dmulti --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-lint-dmulti
  mkdir -p /tmp/ps-commu/t-lint-dmulti/app
  cat > /tmp/ps-commu/t-lint-dmulti/app/content.md <<'EOF'
See F1 for details.

```drawio
<mxGraphModel pageWidth="200" pageHeight="200">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="A" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#1c4f8f;"
        vertex="1" parent="1">
      <mxGeometry x="150" y="50" width="100" height="60" as="geometry" />
    </mxCell>
    <mxCell id="B" value="B" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="10" y="10" width="60" height="30" as="geometry" />
    </mxCell>
    <mxCell id="e1" style="html=1;" edge="1" parent="1" source="A" target="B" />
  </root>
</mxGraphModel>
```
EOF
  local out rc; out="$("$S/lint.sh" t-lint-dmulti 2>&1)"; rc=$?
  (( rc == 1 )) &&
  grep -q "vertex 'A' extends beyond the declared page bounds" <<<"$out" &&
  grep -q "raw hex color 'fillColor=#1c4f8f'" <<<"$out" &&
  grep -q "edge 'e1' has no label" <<<"$out"
}

check lint_fails_drawio_malformed_xml      test_lint_fails_drawio_malformed_xml
check lint_fails_drawio_missing_root_cells test_lint_fails_drawio_missing_root_cells
check lint_fails_drawio_unlabeled_edge     test_lint_fails_drawio_unlabeled_edge
check lint_fails_drawio_node_cap           test_lint_fails_drawio_node_cap
check lint_fails_drawio_overlap            test_lint_fails_drawio_overlap
check lint_fails_drawio_out_of_bounds      test_lint_fails_drawio_out_of_bounds
check lint_fails_drawio_unescaped_label    test_lint_fails_drawio_unescaped_label
check lint_fails_drawio_raw_hex            test_lint_fails_drawio_raw_hex
check lint_passes_drawio_br_label          test_lint_passes_drawio_br_label
check lint_fails_drawio_double_escaped_br  test_lint_fails_drawio_double_escaped_br
check lint_fails_missing_reader            test_lint_fails_missing_reader
check lint_fails_drawio_br_lookalikes      test_lint_fails_drawio_br_lookalikes
check lint_passes_drawio_valid             test_lint_passes_drawio_valid
check lint_passes_drawio_origin_vertex               test_lint_passes_drawio_origin_vertex
check lint_fails_drawio_bounds_unverifiable          test_lint_fails_drawio_bounds_unverifiable
check lint_fails_drawio_content_sniffed_fence        test_lint_fails_drawio_content_sniffed_fence
check lint_passes_drawio_grouped_siblings_no_false_overlap test_lint_passes_drawio_grouped_siblings_no_false_overlap
check lint_fails_drawio_grouped_child_out_of_bounds  test_lint_fails_drawio_grouped_child_out_of_bounds
check lint_fails_drawio_negative_width               test_lint_fails_drawio_negative_width
check lint_fails_drawio_negative_position_out_of_bounds test_lint_fails_drawio_negative_position_out_of_bounds
check lint_fails_drawio_vertex_edge_exclusivity      test_lint_fails_drawio_vertex_edge_exclusivity
check lint_fails_drawio_duplicate_id                 test_lint_fails_drawio_duplicate_id
check lint_fails_drawio_bare_ampersand               test_lint_fails_drawio_bare_ampersand
check lint_dedupes_drawio_defect_lines               test_lint_dedupes_drawio_defect_lines
check lint_checks_drawio_inside_mxfile_wrapper       test_lint_checks_drawio_inside_mxfile_wrapper
check lint_fails_drawio_ambiguous_cell_type          test_lint_fails_drawio_ambiguous_cell_type
check lint_reports_all_drawio_defects_without_masking test_lint_reports_all_drawio_defects_without_masking

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
# A verify run is ~45s on macOS (Chrome start + CDN load + draw.io render).
verify_run() {           # args... → verify.sh output on stdout; rc 2 = cannot run (Chrome/server)
  if command -v timeout >/dev/null; then timeout 150 "$S/verify.sh" "$@"; else "$S/verify.sh" "$@"; fi
}
test_verify_passes_template() {
  # --example pairs the shipped exemplar content.md with its matching filled
  # 00-brief/01-facts/02-storyboard, so it lints clean and serves through the
  # real lint gate (F-018: a plain init no longer ships app/content.md).
  rm -rf /tmp/ps-commu/t-verify
  "$S/init.sh" t-verify --example >/dev/null
  "$S/serve.sh" t-verify >/dev/null
  local out rc; out="$(verify_run t-verify)"; rc=$?
  echo "$out"
  (( rc == 2 )) && return 2
  [[ -s /tmp/ps-commu/t-verify/page-text.txt ]] || { echo "no page-text.txt after a real run"; return 1; }
  # F-013's content migration (Task 4) landed: the shipped content.md now
  # carries its real, migrated ```drawio fence (Task 0's verified 6-node
  # flowchart) instead of the pre-migration ```mermaid one. Assert 1 sees
  # exactly 1 fence and 1 rendered .mxgraph div, both non-empty — a real
  # PASS, not the old vacuous 0==0 one. test_verify_passes_drawio_template
  # below remains the dedicated positive-path drawio render-gate coverage,
  # using its own synthetic fixture rather than the shipped exemplar.
  (( rc == 0 )) &&
  grep -q '^PASS: 1 drawio svg=1 fences=1 (mxgraph-divs=1 empty-render=0 no-svg=0)' <<<"$out" &&
  grep -q '^PASS: 9 declarative interactive:' <<<"$out" &&
  ! grep -q '^FAIL' <<<"$out"
}
test_verify_dump_text() {  # --dump-text: clean reader-visible text on stdout, exit 0, no raw markup leaks
  local out rc; out="$(verify_run t-verify --dump-text)"; rc=$?
  echo "chars=${#out}"
  (( rc == 2 )) && return 2
  [[ "$out" == "$(cat /tmp/ps-commu/t-verify/page-text.txt 2>/dev/null)" ]] || { echo "stdout != page-text.txt"; return 1; }
  (( rc == 0 )) &&
  [[ -n "$out" ]] &&
  ! grep -q 'data-nav' <<<"$out" &&
  ! grep -q '```mermaid' <<<"$out" &&
  ! grep -qE '^(PASS|FAIL|SKIP):' <<<"$out"
}
test_verify_fails_on_br_leak() {  # a double-escaped draw.io label renders as literal "<br>"
  local port; port="$(meta_get t-verify port)"
  cat > /tmp/ps-commu/t-verify/app/brleak.md <<'MD'
Real break in a table: ok.

| a | b |
|---|---|
| one<br>two | `code<br>sample` |

```drawio
<mxGraphModel pageWidth="800" pageHeight="400"><root><mxCell id="0" /><mxCell id="1" parent="0" />
<mxCell id="A" value="init&amp;lt;br&amp;gt;sh" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
<mxGeometry x="40" y="40" width="160" height="60" as="geometry" /></mxCell></root></mxGraphModel>
```
MD
  local out rc; out="$(verify_run t-verify --url "http://127.0.0.1:$port/?doc=brleak.md")"; rc=$?
  echo "$out"
  (( rc == 2 )) && return 2
  (( rc == 1 )) && grep -q '^FAIL: 8 literal <br> text LEAKED in body text (1x)' <<<"$out"
}
test_verify_fails_on_leak() {  # literal ~~CODE$ in prose + a drawio fence that renders empty
  local port; port="$(meta_get t-verify port)"
  cat > /tmp/ps-commu/t-verify/app/leak.md <<'MD'
<div class="section-head cat-coral" data-nav="Intro" data-cat="coral" id="intro">
<h2>Intro</h2>
</div>

A literal ~~CODE$ placeholder stays in prose.

```drawio
<mxGraphModel><root><mxCell id="0" /><mxCell id="1" parent="0" /></root></mxGraphModel>
```
MD
  local out rc; out="$(verify_run t-verify --url "http://127.0.0.1:$port/?doc=leak.md")"; rc=$?
  echo "$out"
  (( rc == 2 )) && return 2
  (( rc == 1 )) &&
  grep -q '^FAIL: 1 drawio svg=0 fences=1 (mxgraph-divs=1 empty-render=1 no-svg=0)' <<<"$out" &&
  grep -q '^FAIL: 2 ~~CODE placeholder LEAKED' <<<"$out"
}
test_verify_passes_drawio_template() {  # Task 0's own verified diagram-v2.xml (task-0-report.md)
  # renders cleanly: assert 1's drawio-count PASSes, and assert 7's
  # interactivity proxy PASSes (GraphViewer loaded, toolbar's margin-top
  # side effect present) — served via a dedicated ?doc= fixture, same
  # workspace-reuse/isolation pattern leak.md already established above,
  # rather than overwriting the shared content.md.
  local port; port="$(meta_get t-verify port)"
  cat > /tmp/ps-commu/t-verify/app/drawio-good.md <<'MD'
A well-formed diagram.

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
MD
  local out rc; out="$(verify_run t-verify --url "http://127.0.0.1:$port/?doc=drawio-good.md")"; rc=$?
  echo "$out"
  (( rc == 2 )) && return 2
  (( rc == 0 )) &&
  grep -q '^PASS: 1 drawio svg=1 fences=1 (mxgraph-divs=1 empty-render=0 no-svg=0)' <<<"$out" &&
  grep -q '^PASS: 7 drawio interactivity: GraphViewer loaded, toolbar initialized on 1/1 diagram(s)' <<<"$out" &&
  ! grep -q '^FAIL' <<<"$out"
}
test_verify_fails_drawio_empty_render() {  # the spec's documented failure mode: well-formed XML,
  # zero vertex/edge cells -> GraphViewer renders <svg><g><g/><g/><g/><g/></g></svg> and NOTHING
  # else, with ZERO console output (confirmed empirically — this is genuinely NOT a case lint.sh's
  # structural XML validator would reject pre-serve: the XML parses fine, it's just contentless).
  # Served via --url on a raw fixture file (same --no-lint-equivalent bypass leak.md/drawio-good.md
  # above use), so lint.sh never gets a chance to see it either way.
  local port; port="$(meta_get t-verify port)"
  cat > /tmp/ps-commu/t-verify/app/drawio-empty.md <<'MD'
A diagram that parses but renders nothing.

```drawio
<mxGraphModel><root><mxCell id="0" /><mxCell id="1" parent="0" /></root></mxGraphModel>
```
MD
  local out rc; out="$(verify_run t-verify --url "http://127.0.0.1:$port/?doc=drawio-empty.md")"; rc=$?
  echo "$out"
  (( rc == 2 )) && return 2
  (( rc == 1 )) &&
  grep -q '^FAIL: 1 drawio svg=0 fences=1 (mxgraph-divs=1 empty-render=1 no-svg=0)' <<<"$out" &&
  # Assert 7 (interactivity) legitimately still PASSes here: GraphViewer DID
  # load and DID call addToolbar() for this div — the graph is just empty,
  # a content defect assert 1 alone catches. Confirmed empirically the two
  # assert numbers are independent, not redundant.
  grep -q '^PASS: 7 drawio interactivity: GraphViewer loaded, toolbar initialized on 1/1 diagram(s)' <<<"$out"
}
test_verify_counts_xml_fenced_drawio() {  # fix round 1, finding B: a ```xml fence whose body
  # starts with <mxGraphModel> is content-sniffed and rendered by cherry-setup.js's
  # frameAndRunDrawio() (DRAWIO_HEAD, the "pre code" broad candidate selector) exactly like
  # lint.sh already mirrors (lint.sh:464-485) — verify.sh's fence-count must agree, not just
  # count literal ```drawio fences, or a real live-rendered diagram gets a false FAIL on assert 1
  # (fences=0 while a real .mxgraph div rendered) and a vacuous assert-7 PASS if it's the only one.
  local port; port="$(meta_get t-verify port)"
  cat > /tmp/ps-commu/t-verify/app/drawio-xml-fence.md <<'MD'
A diagram authored inside a fence tagged xml instead of drawio.

```xml
<mxGraphModel dx="400" dy="200" grid="1" gridSize="10" guides="1" tooltips="1"
    connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="400"
    pageHeight="200" math="0" shadow="0">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="hi" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
      <mxGeometry x="40" y="40" width="120" height="40" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```
MD
  local out rc; out="$(verify_run t-verify --url "http://127.0.0.1:$port/?doc=drawio-xml-fence.md")"; rc=$?
  echo "$out"
  (( rc == 2 )) && return 2
  (( rc == 0 )) &&
  grep -q '^PASS: 1 drawio svg=1 fences=1 (mxgraph-divs=1 empty-render=0 no-svg=0)' <<<"$out" &&
  grep -q '^PASS: 7 drawio interactivity: GraphViewer loaded, toolbar initialized on 1/1 diagram(s)' <<<"$out" &&
  ! grep -q '^FAIL' <<<"$out"
}
test_verify_fails_partial_toolbar() {  # fix round 1, finding A: >=1 rendered diagram losing the
  # toolbar must FAIL the whole gate, not hide behind "at least one worked". Real content authoring
  # cannot reach this state (cherry-setup.js hardcodes toolbar:"zoom" per fence uniformly — see
  # task-3-report.md's self-flagged-concerns section), so this hand-crafts the exact DOM shape
  # GraphViewer would leave behind if ONE of two diagrams' addToolbar() silently didn't run: two
  # .mxgraph divs, both with a real rendered <rect> (so assert 1 stays clean), only the FIRST
  # carrying the margin-top side effect. Served from a throwaway static file server (bypasses
  # cherry-setup.js/GraphViewer entirely — this targets verify.sh's own threshold logic), while the
  # fence COUNT still comes from a real t-verify workspace doc (verify.sh always resolves the
  # markdown file from the workspace's own app/ dir via the slug, independent of --url's host).
  local d=/tmp/ps-commu/t-verify-partial-toolbar
  mkdir -p "$d"
  cat > "$d/fixture.html" <<'HTML'
<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body>
<div class="cherry-previewer theme__explainer is-ready">
<p>Two diagrams, one lost its toolbar.</p>
<div class="mxgraph" style="margin-top: 26px;">
<svg><g><g></g><g><g><rect x="0" y="0" width="10" height="10"></rect></g></g><g></g><g></g></g></svg>
</div>
<div class="mxgraph">
<svg><g><g></g><g><g><rect x="0" y="0" width="10" height="10"></rect></g></g><g></g><g></g></g></svg>
</div>
</div>
</body></html>
HTML
  cat > /tmp/ps-commu/t-verify/app/partial-toolbar.md <<'MD'
Two diagrams (content unused — this file only feeds verify.sh's fence count).

```drawio
<mxGraphModel><root><mxCell id="0" /><mxCell id="1" parent="0" /></root></mxGraphModel>
```

```drawio
<mxGraphModel><root><mxCell id="0" /><mxCell id="1" parent="0" /></root></mxGraphModel>
```
MD
  python3 -m http.server 7698 --bind 127.0.0.1 --directory "$d" >/dev/null 2>&1 &
  local httpd=$!
  sleep 1
  local out rc
  out="$(verify_run t-verify --url "http://127.0.0.1:7698/fixture.html?doc=partial-toolbar.md")"; rc=$?
  kill "$httpd" 2>/dev/null
  echo "$out"
  (( rc == 2 )) && return 2
  (( rc == 1 )) &&
  grep -q '^PASS: 1 drawio svg=2 fences=2 (mxgraph-divs=2 empty-render=0 no-svg=0)' <<<"$out" &&
  grep -q '^FAIL: 7 toolbar not initialized on 1/2 diagram(s)' <<<"$out"
}
test_verify_counts_html_commented_fence_because_it_still_renders() {  # fix round 2 correction:
  # the reviewer's premise (mirror lint.sh's strip_comments() so a "commented-out" fence isn't
  # counted) does NOT hold for this renderer -- checked empirically, not assumed. Cherry-Markdown
  # does not implement <!-- ... --> as an HTML comment block: a bare `<!--` line renders as an
  # ORDINARY escaped-text paragraph (confirmed via a real PS_COMMU_VERIFY_DOM dump: the DOM shows
  # literal `<p>&lt;!--</p>`, i.e. Cherry escaped it as plain text -- real HTML-block passthrough
  # never does that), and a ```drawio fence physically between `<!--`/`-->` lines parses as a
  # completely normal, independent fence and genuinely renders. So verify.sh must COUNT it (and
  # it does, deliberately NOT stripping comments -- see the comment above the fence-count snippet
  # in verify.sh) or it would under-count a diagram that's really on the page: exactly the same
  # false-FAIL failure class this fix round exists to close, just pointed the other way.
  local port; port="$(meta_get t-verify port)"
  cat > /tmp/ps-commu/t-verify/app/drawio-commented.md <<'MD'
An attempt to mark an example as NOT live, using an HTML comment:

<!--
```drawio
<mxGraphModel><root><mxCell id="0" /><mxCell id="1" parent="0" />
<mxCell id="A" value="x" style="rounded=1;html=1;" vertex="1" parent="1">
<mxGeometry x="10" y="10" width="60" height="30" as="geometry" /></mxCell>
</root></mxGraphModel>
```
-->

The comment markers do not stop it from rendering live.
MD
  local out rc; out="$(verify_run t-verify --url "http://127.0.0.1:$port/?doc=drawio-commented.md")"; rc=$?
  echo "$out"
  (( rc == 2 )) && return 2
  (( rc == 0 )) &&
  grep -q '^PASS: 1 drawio svg=1 fences=1 (mxgraph-divs=1 empty-render=0 no-svg=0)' <<<"$out" &&
  grep -q '^PASS: 7 drawio interactivity: GraphViewer loaded, toolbar initialized on 1/1 diagram(s)' <<<"$out" &&
  ! grep -q '^FAIL' <<<"$out"
}
test_verify_help() { "$S/verify.sh" --help | grep -q 'Usage: verify.sh' && ! "$S/verify.sh" >/dev/null 2>&1; }

check_or_skip verify_passes_template               test_verify_passes_template
check_or_skip verify_dump_text                     test_verify_dump_text
check_or_skip verify_fails_on_leak                 test_verify_fails_on_leak
check_or_skip verify_fails_on_br_leak              test_verify_fails_on_br_leak
check_or_skip verify_passes_drawio_template        test_verify_passes_drawio_template
check_or_skip verify_fails_drawio_empty_render     test_verify_fails_drawio_empty_render
check_or_skip verify_counts_xml_fenced_drawio      test_verify_counts_xml_fenced_drawio
check_or_skip verify_fails_partial_toolbar         test_verify_fails_partial_toolbar
check_or_skip verify_counts_html_commented_fence   test_verify_counts_html_commented_fence_because_it_still_renders
check verify_help                                  test_verify_help
"$S/stop.sh" t-verify >/dev/null 2>&1

# --- F-015: deterministic Mermaid validation (lint.sh html tier) + error trap + verify.sh html tier ---
# Real-mmdc cases (~15s per block on this Mac: Rosetta'd node + Chrome start) SKIP visibly (rc 2)
# when mmdc is not installed; the absent/launch-failure cases are simulated via MMDC_BIN.
_html_ws() {   # slug — html-tier workspace with a valid authoring chain; app/index.html from stdin
  "$S/init.sh" "$1" --tier html >/dev/null
  _lint_valid_brief_facts_storyboard "$1"
  cat > "/tmp/ps-commu/$1/app/index.html"
}
_need_mmdc() { command -v mmdc >/dev/null || { echo "SKIP: mmdc not installed"; return 2; }; }

test_lint_mermaid_valid_passes() {
  _need_mmdc || return 2
  _html_ws t-mm-ok <<'HTML'
<html><body><div class="mermaid">graph TD
  A[Start] --> B[End]</div></body></html>
HTML
  MMDC_BIN=mmdc "$S/lint.sh" t-mm-ok
}
test_lint_mermaid_invalid_fails_with_block_number() {
  _need_mmdc || return 2
  _html_ws t-mm-bad <<'HTML'
<html><body>
<div class="mermaid">graph TD
  A --> B</div>
<div class="mermaid">graph TD; A-->|[[x]]| B; B --></div>
</body></html>
HTML
  local out rc; out="$(MMDC_BIN=mmdc "$S/lint.sh" t-mm-bad 2>&1)"; rc=$?
  echo "$out"
  (( rc == 1 )) && grep -q 'mermaid block 2' <<<"$out" && ! grep -q 'mermaid block 1' <<<"$out" &&
  grep -qi 'parse error' <<<"$out"
}
test_lint_mermaid_unescapes_entities() {   # --&gt; is only valid Mermaid after HTML-unescaping
  _need_mmdc || return 2
  _html_ws t-mm-esc <<'HTML'
<html><body><div class="mermaid">graph TD
  A["a &amp; b"] --&gt; B["&lt;c&gt; &quot;d&quot;"]</div></body></html>
HTML
  MMDC_BIN=mmdc "$S/lint.sh" t-mm-esc
}
test_lint_mermaid_missing_mmdc_warns_and_passes() {
  _html_ws t-mm-absent <<'HTML'
<html><body><div class="mermaid">graph TD
  A --> B</div></body></html>
HTML
  local out rc; out="$(MMDC_BIN=/nonexistent/mmdc "$S/lint.sh" t-mm-absent 2>&1)"; rc=$?
  echo "$out"; (( rc == 0 )) && grep -q 'WARNING.*mmdc' <<<"$out"
}
test_lint_mermaid_missing_mmdc_strict_fails() {
  _html_ws t-mm-strict <<'HTML'
<html><body><div class="mermaid">graph TD
  A --> B</div></body></html>
HTML
  local out rc; out="$(EXPLAINER_STRICT_MERMAID=1 MMDC_BIN=/nonexistent/mmdc "$S/lint.sh" t-mm-strict 2>&1)"; rc=$?
  echo "$out"; (( rc == 1 )) && grep -q 'mmdc' <<<"$out"
}
_fake_mmdc_launch_failure() {   # path — mmdc stand-in that dies like a browser launch failure
  printf '#!/bin/sh\necho "Error: Tried to find the browser at the configured path (/x), but no executable was found." >&2\nexit 1\n' > "$1"
  chmod +x "$1"
}
test_lint_mermaid_launch_failure_is_not_syntax_error() {
  _html_ws t-mm-launch <<'HTML'
<html><body><div class="mermaid">graph TD
  A --> B</div></body></html>
HTML
  local fake="/tmp/ps-commu/t-mm-launch/fake-mmdc"; _fake_mmdc_launch_failure "$fake"
  local out rc; out="$(MMDC_BIN="$fake" "$S/lint.sh" t-mm-launch 2>&1)"; rc=$?
  echo "$out"
  (( rc == 0 )) && grep -q 'WARNING' <<<"$out" && ! grep -qi 'syntax error\|mermaid block 1:' <<<"$out" || return 1
  out="$(EXPLAINER_STRICT_MERMAID=1 MMDC_BIN="$fake" "$S/lint.sh" t-mm-launch 2>&1)"; rc=$?
  echo "$out"
  (( rc == 1 )) && ! grep -qi 'syntax error' <<<"$out"
}
test_lint_mermaid_no_blocks_needs_no_mmdc() {   # no .mermaid divs -> no mmdc, no warning, exit 0
  _html_ws t-mm-none <<'HTML'
<html><body><h1>no diagrams</h1></body></html>
HTML
  local out rc; out="$(MMDC_BIN=/nonexistent/mmdc "$S/lint.sh" t-mm-none 2>&1)"; rc=$?
  echo "$out"; (( rc == 0 )) && ! grep -q WARNING <<<"$out"
}
test_lint_mermaid_extraction_failure_never_fails_open() {   # non-UTF-8 index.html
  _html_ws t-mm-enc <<'HTML'
<html><body><div class="mermaid">graph TD
  A --> B</div></body></html>
HTML
  printf '<div class="mermaid">caf\xe9</div>' > /tmp/ps-commu/t-mm-enc/app/index.html
  local out rc; out="$(MMDC_BIN=/nonexistent/mmdc "$S/lint.sh" t-mm-enc 2>&1)"; rc=$?
  echo "$out"; (( rc == 0 )) && grep -q 'WARNING.*could not extract' <<<"$out" || return 1
  out="$(EXPLAINER_STRICT_MERMAID=1 MMDC_BIN=/nonexistent/mmdc "$S/lint.sh" t-mm-enc 2>&1)"; rc=$?
  echo "$out"; (( rc == 1 )) && grep -q 'could not extract' <<<"$out"
}
test_serve_refuses_bad_mermaid() {   # lint failure means serve.sh never binds
  _need_mmdc || return 2
  _html_ws t-mm-serve <<'HTML'
<html><body><div class="mermaid">graph TD; A-->|[[x]]| B; B --></div></body></html>
HTML
  local out rc; out="$(MMDC_BIN=mmdc "$S/serve.sh" t-mm-serve 2>&1)"; rc=$?
  echo "$out"
  local p; p="$(meta_get t-mm-serve pid)"
  (( rc != 0 )) && [[ -z "$p" ]]
}
test_template_has_error_trap() {
  local t="$SKILL_DIR/assets/template-html/index.html"
  grep -q 'mermaid.parseError' "$t" && grep -q "classList.add('explainer-error')" "$t"
}

check_or_skip lint_mermaid_valid_passes                 test_lint_mermaid_valid_passes
check_or_skip lint_mermaid_invalid_block_number         test_lint_mermaid_invalid_fails_with_block_number
check_or_skip lint_mermaid_unescapes_entities           test_lint_mermaid_unescapes_entities
check lint_mermaid_missing_mmdc_warns_and_passes        test_lint_mermaid_missing_mmdc_warns_and_passes
check lint_mermaid_missing_mmdc_strict_fails            test_lint_mermaid_missing_mmdc_strict_fails
check lint_mermaid_launch_failure_not_syntax_error      test_lint_mermaid_launch_failure_is_not_syntax_error
check lint_mermaid_no_blocks_needs_no_mmdc              test_lint_mermaid_no_blocks_needs_no_mmdc
check lint_mermaid_extraction_failure_never_fails_open test_lint_mermaid_extraction_failure_never_fails_open
check_or_skip serve_refuses_bad_mermaid                 test_serve_refuses_bad_mermaid
check template_has_error_trap                           test_template_has_error_trap

# verify.sh html tier (needs Chrome; ~45s per run). The scaffolded template is the fixture.
_verify_html() {   # slug — serve the workspace (lint skipped: no authoring chain here) and verify it
  "$S/serve.sh" "$1" --no-lint >/dev/null
  verify_run "$1"
}
test_verify_html_passes_template() {
  "$S/init.sh" t-vh-ok --tier html >/dev/null
  local out rc; out="$(_verify_html t-vh-ok)"; rc=$?; echo "$out"
  (( rc == 2 )) && return 2
  (( rc == 0 )) && grep -q '^PASS: html-1 no .explainer-error' <<<"$out" &&
  grep -Eq '^PASS: html-2 mermaid svg=[0-9]+ divs=[0-9]+' <<<"$out" && ! grep -q '^FAIL' <<<"$out"
}
test_verify_html_fails_on_mermaid_error() {
  "$S/init.sh" t-vh-err --tier html >/dev/null
  python3 - /tmp/ps-commu/t-vh-err/app/index.html <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace('<main', '<div class="mermaid">graph TD; A-->|[[x]]| B; B --></div>\n<main', 1)
open(p, 'w').write(s)
PY
  local out rc; out="$(_verify_html t-vh-err)"; rc=$?; echo "$out"
  (( rc == 2 )) && return 2
  (( rc == 1 )) && grep -q '^FAIL: html-1 .explainer-error' <<<"$out"
}
test_verify_html_fails_on_svg_count_mismatch() {   # a pre-"processed" div is skipped by mermaid -> no svg
  "$S/init.sh" t-vh-cnt --tier html >/dev/null
  python3 - /tmp/ps-commu/t-vh-cnt/app/index.html <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace('<main', '<div class="mermaid" data-processed="true">graph TD; A-->B</div>\n<main', 1)
open(p, 'w').write(s)
PY
  local out rc; out="$(_verify_html t-vh-cnt)"; rc=$?; echo "$out"
  (( rc == 2 )) && return 2
  (( rc == 1 )) && grep -q '^FAIL: html-2 mermaid svg=' <<<"$out"
}
check_or_skip verify_html_passes_template               test_verify_html_passes_template
check_or_skip verify_html_fails_on_mermaid_error        test_verify_html_fails_on_mermaid_error
check_or_skip verify_html_fails_on_svg_count_mismatch   test_verify_html_fails_on_svg_count_mismatch
for s in t-vh-ok t-vh-err t-vh-cnt t-mm-serve; do "$S/stop.sh" "$s" >/dev/null 2>&1; done

# --- F-018: speed quick wins ---
_stub_chrome() {  # dir page|fail — fake Chrome at $dir/chrome; one line in $dir/launches per launch
  local dir="$1" mode="$2"
  mkdir -p "$dir"; : > "$dir/launches"
  if [[ "$mode" == page ]]; then
    printf '%s\n' '<html><body class="is-ready"><div class="cherry-previewer"><div class="mxgraph" style="margin-top: 10px"><svg><rect></rect></svg></div><div class="tabs is-wired"><div class="tab-list"><button type="button" class="tab-btn" aria-pressed="true"></button><button type="button" class="tab-btn" aria-pressed="false"></button></div><div class="tab-panel is-active"></div><div class="tab-panel" hidden></div></div><div class="accordion is-wired"><div class="acc-item is-open"><button type="button" class="acc-btn" aria-expanded="true"></button><div class="acc-panel"></div></div><div class="acc-item"><button type="button" class="acc-btn" aria-expanded="false"></button><div class="acc-panel" hidden></div></div></div><p>Stub page text for F-018.</p></div></body></html>' > "$dir/page.html"
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

test_verify_one_load_writes_page_text() {  # asserts + page-text.txt from ONE Chrome launch
  _vstub_ws || return 1
  local d=/tmp/ps-commu/t-stub-one pt=/tmp/ps-commu/t-vstub/page-text.txt out
  _stub_chrome "$d" page; rm -f "$pt"
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub)"
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
  (( rc == 1 )) && [[ ! -e "$pt" ]] || return 1
  # Also when the DOM renders but the page shows an explainer-error panel (asserts 0 and 1 fail): no page-text.txt
  mkdir -p "$d"
  printf '%s\n' '<html><body class="is-ready"><div class="cherry-previewer"><div class="explainer-error"><div>fail</div></div></div></body></html>' > "$d/page.html"
  echo STALE > "$pt"
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

test_verify_assert6_failure_removes_page_text() {  # every python assert passes; only the CSS check fails
  _vstub_ws || return 1
  local d=/tmp/ps-commu/t-stub-a6 ws=/tmp/ps-commu/t-vstub pt=/tmp/ps-commu/t-vstub/page-text.txt out rc
  _stub_chrome "$d" page
  cp "$ws/app/explainer.css" "$d/explainer.css.bak"
  printf 'html { scroll-behavior: smooth; }\n' >> "$ws/app/explainer.css"
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub 2>&1)"; rc=$?
  cp "$d/explainer.css.bak" "$ws/app/explainer.css"
  echo "$out" | grep -E '^(FAIL|PASS): (1|6) '
  (( rc == 1 )) && grep -q '^PASS: 1 ' <<<"$out" && grep -q '^FAIL: 6 ' <<<"$out" && [[ ! -e "$pt" ]]
}
test_verify_dump_text_failed_render_no_page_text() {  # --dump-text keeps stdout/exit codes; failed renders leave no file
  _vstub_ws || return 1
  local d=/tmp/ps-commu/t-stub-dfail pt=/tmp/ps-commu/t-vstub/page-text.txt out rc
  _stub_chrome "$d" page; rm -f "$pt"
  # never reached .is-ready
  printf '%s\n' '<html><body><div class="cherry-previewer"><p>Half rendered.</p></div></body></html>' > "$d/page.html"
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub --dump-text 2>/dev/null)"; rc=$?
  (( rc == 0 )) && [[ "$out" == "Half rendered." ]] && [[ ! -e "$pt" ]] || return 1
  # explainer-error panel
  printf '%s\n' '<html><body class="is-ready"><div class="cherry-previewer"><div class="explainer-error"><div>boom</div></div><p>Some text.</p></div></body></html>' > "$d/page.html"
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub --dump-text 2>/dev/null)"; rc=$?
  (( rc == 0 )) && [[ -n "$out" ]] && [[ ! -e "$pt" ]]
}
test_verify_page_text_oserror_warns() {  # unwritable workspace dir: one-line warning, asserts + exit code intact
  _vstub_ws || return 1
  local d=/tmp/ps-commu/t-stub-ro ws=/tmp/ps-commu/t-vstub out rc
  _stub_chrome "$d" page; rm -f "$ws/page-text.txt"
  chmod a-w "$ws"
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub 2>&1)"; rc=$?
  chmod u+w "$ws"
  echo "$out" | grep -E 'warning|^(PASS|FAIL): (2|8) '
  (( rc == 0 )) && grep -q '^PASS: 8 ' <<<"$out" && grep -q 'warning: could not write' <<<"$out" && [[ ! -e "$ws/page-text.txt" ]]
}
check verify_assert6_failure_removes_page_text     test_verify_assert6_failure_removes_page_text
check verify_dump_text_failed_render_no_page_text  test_verify_dump_text_failed_render_no_page_text
check verify_page_text_oserror_warns               test_verify_page_text_oserror_warns

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

test_reader_prompt_non_utf8_brief_exits_2() {
  _vstub_ws || return 1
  local ws=/tmp/ps-commu/t-vstub out rc
  cp "$ws/00-brief.md" "$ws/00-brief.md.bak"
  printf 'Reader: caf\xe9 \xff\xfe\n' > "$ws/00-brief.md"
  printf 'x\n' > "$ws/page-text.txt"
  out="$("$S/verify.sh" t-vstub --reader-prompt 2>&1)"; rc=$?
  mv "$ws/00-brief.md.bak" "$ws/00-brief.md"
  echo "$out" | head -n 3
  (( rc == 2 )) && ! grep -q Traceback <<<"$out"
}
test_reader_prompt_stale_page_text_exits_2() {  # compares app/content.md only; -nt has 1s granularity
  _vstub_ws || return 1
  local ws=/tmp/ps-commu/t-vstub out rc
  printf 'x\n' > "$ws/page-text.txt"; sleep 1; touch "$ws/app/content.md"
  out="$("$S/verify.sh" t-vstub --reader-prompt 2>&1)"; rc=$?
  echo "$out" | head -n 3
  (( rc == 2 )) && grep -qF 'stale page text' <<<"$out" || return 1
  sleep 1; touch "$ws/page-text.txt"      # fresh again: accepted
  "$S/verify.sh" t-vstub --reader-prompt >/dev/null 2>&1
}
test_reader_prompt_html_tier_hand_written_page_text() {  # html/react: page-text.txt is saved by the haiku render subagent
  local ws=/tmp/ps-commu/t-rphtml out rc
  rm -rf "$ws"; "$S/init.sh" t-rphtml --tier html >/dev/null 2>&1 || return 1
  printf 'Q1: what is A?\nQ2: what is B?\nQ3: what is C?\nReader: a newcomer\n' > "$ws/00-brief.md"
  out="$("$S/verify.sh" t-rphtml --reader-prompt 2>&1)"; rc=$?
  (( rc == 2 )) && grep -qF 'run verify.sh t-rphtml first' <<<"$out" || return 1
  printf 'hand-written visible text\n' > "$ws/page-text.txt"
  out="$("$S/verify.sh" t-rphtml --reader-prompt 2>&1)"; rc=$?
  echo "$out" | head -n 6
  (( rc == 0 )) && [[ "$(head -n1 <<<"$out")" == "Agent model: sonnet" ]] &&
  grep -qxF "$ws/page-text.txt" <<<"$out" && grep -qF 'Q2: what is B?' <<<"$out" &&
  grep -qE ' verify\.sh:reader-prompt [0-9]+$' "$ws/timings.log" &&
  ! grep -qE ' verify\.sh [0-9]+$' "$ws/timings.log"   # logged apart from a Chrome run
}
check reader_prompt_html_tier_hand_written_page_text test_reader_prompt_html_tier_hand_written_page_text
check reader_prompt_non_utf8_brief_exits_2     test_reader_prompt_non_utf8_brief_exits_2
check reader_prompt_stale_page_text_exits_2    test_reader_prompt_stale_page_text_exits_2
"$S/stop.sh" t-vstub >/dev/null 2>&1

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
test_skeleton_no_filled_rows() {  # plain init: storyboard has no filled rows -> exit 1, nothing written
  rm -rf /tmp/ps-commu/t-skel-plain; "$S/init.sh" t-skel-plain >/dev/null || return 1
  rm -f /tmp/ps-commu/t-skel-plain/app/content.md
  local rc; "$S/skeleton.sh" t-skel-plain 2>/dev/null; rc=$?
  (( rc == 1 )) && [[ ! -e /tmp/ps-commu/t-skel-plain/app/content.md ]]
}
test_skeleton_missing_chain_file() {
  _skel_ws && rm -f /tmp/ps-commu/t-skel/02-storyboard.md || return 1
  local rc; "$S/skeleton.sh" t-skel 2>/dev/null; rc=$?
  (( rc == 2 )) && [[ ! -e /tmp/ps-commu/t-skel/app/content.md ]]
}
test_skeleton_non_utf8_chain() {  # exit 2, one-line message, no traceback
  _skel_ws && printf 'F1 | bad \377 byte | src\n' >> /tmp/ps-commu/t-skel/01-facts.md || return 1
  local rc err; err="$("$S/skeleton.sh" t-skel 2>&1 >/dev/null)"; rc=$?
  (( rc == 2 )) && ! grep -q Traceback <<<"$err" && [[ "$(wc -l <<<"$err")" -le 1 ]] &&
  [[ ! -e /tmp/ps-commu/t-skel/app/content.md ]]
}
check skeleton_writes_todo_per_row test_skeleton_writes_todo_per_row
check skeleton_lint_gate           test_skeleton_lint_gate
check skeleton_refuses_overwrite   test_skeleton_refuses_overwrite
check skeleton_preconditions       test_skeleton_preconditions
check skeleton_no_filled_rows      test_skeleton_no_filled_rows
check skeleton_missing_chain_file  test_skeleton_missing_chain_file
check skeleton_non_utf8_chain      test_skeleton_non_utf8_chain

test_components_index_covers_every_section() {
  local a="$SKILL_DIR/assets/template-infographic" ids id rc=0
  [[ -f "$a/components-index.md" ]] || { echo "no components-index.md"; return 1; }
  (( $(wc -l < "$a/components-index.md") <= 40 )) || { echo "index over 40 lines"; return 1; }
  # section-head lines, id= and class= in either order; then the reverse direction
  ids="$(grep 'class="section-head' "$a/components.md" | grep -oE ' id="[^"]+"' | sed -E 's/ id="([^"]+)"/\1/')"
  [[ -n "$ids" ]] || { echo "no section ids parsed from components.md"; return 1; }
  for id in $ids; do
    grep -qF "id=\"$id\"" "$a/components-index.md" || { echo "index misses section: $id"; rc=1; }
  done
  for id in $(grep -oE '^\| `id="[^"]+"`' "$a/components-index.md" | sed -E 's/.*id="([^"]+)".*/\1/'); do
    grep 'class="section-head' "$a/components.md" | grep -qF " id=\"$id\"" || { echo "index lists id not in components.md: $id"; rc=1; }
  done
  return $rc
}
check components_index_covers_every_section test_components_index_covers_every_section

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
test_handoff_rejects_bad_slug() {
  # a real brief outside the root, so only slug validation (not "no workspace") can give exit 2
  local rc=0 out="/tmp/hf-trav-x"
  mkdir -p "$out" && echo "Q1: x" > "$out/00-brief.md"
  out="$("$S/handoff.sh" ../../hf-trav-x 2>&1)" || rc=$?
  rm -rf /tmp/hf-trav-x
  [[ "$rc" == 2 && "$out" == *"bad slug"* ]]
}
check handoff_rejects_bad_slug          test_handoff_rejects_bad_slug
check handoff_prints_everything           test_handoff_prints_everything
check handoff_without_server_or_workspace test_handoff_without_server_or_workspace

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

# --- M1: httpserve.py hardening ---
test_httpserve_get_head_and_headers() {
  "$S/init.sh" t-http-hdr --tier html >/dev/null
  echo '<h1>ok</h1>' > /tmp/ps-commu/t-http-hdr/app/index.html
  "$S/serve.sh" t-http-hdr --no-lint >/dev/null
  local port hdrs body
  port="$(meta_get t-http-hdr port)"
  hdrs="$(curl -sD - -o /dev/null "http://127.0.0.1:$port/")"
  body="$(curl -sf "http://127.0.0.1:$port/")"
  "$S/stop.sh" t-http-hdr >/dev/null
  grep -qi '^HTTP/1\.[01] 200' <<<"$hdrs" &&
  grep -qi '^X-Content-Type-Options: nosniff' <<<"$hdrs" &&
  grep -qi '^Cache-Control: no-store' <<<"$hdrs" &&
  grep -q '<h1>ok</h1>' <<<"$body" &&
  curl -sI "http://127.0.0.1:$port/" >/dev/null 2>&1 || true
  "$S/serve.sh" t-http-hdr --no-lint >/dev/null
  port="$(meta_get t-http-hdr port)"
  hdrs="$(curl -sI "http://127.0.0.1:$port/")"
  "$S/stop.sh" t-http-hdr >/dev/null
  grep -qi '^HTTP/1\.[01] 200' <<<"$hdrs" &&
  grep -qi '^X-Content-Type-Options: nosniff' <<<"$hdrs"
}

test_httpserve_rejects_non_get_head_405() {
  "$S/init.sh" t-http-405 --tier html >/dev/null
  echo '<h1>ok</h1>' > /tmp/ps-commu/t-http-405/app/index.html
  "$S/serve.sh" t-http-405 --no-lint >/dev/null
  local port m hdrs
  port="$(meta_get t-http-405 port)"
  for m in POST PUT DELETE PATCH OPTIONS; do
    hdrs="$(curl -s -X "$m" -D - -o /dev/null "http://127.0.0.1:$port/")"
    if ! grep -qi '^HTTP/1\.[01] 405' <<<"$hdrs" || ! grep -qi '^X-Content-Type-Options: nosniff' <<<"$hdrs"; then
      echo "$m failed: $hdrs"
      "$S/stop.sh" t-http-405 >/dev/null
      return 1
    fi
  done
  "$S/stop.sh" t-http-405 >/dev/null
}

test_httpserve_blocks_dotfiles() {
  "$S/init.sh" t-http-dot --tier html >/dev/null
  echo 'secret' > /tmp/ps-commu/t-http-dot/app/.ready
  echo 'secret' > /tmp/ps-commu/t-http-dot/app/.env
  mkdir -p /tmp/ps-commu/t-http-dot/app/sub
  echo 'secret' > /tmp/ps-commu/t-http-dot/app/sub/.hidden
  "$S/serve.sh" t-http-dot --no-lint >/dev/null
  local port p code
  port="$(meta_get t-http-dot port)"
  for p in '/.ready' '/.env' '/%2eenv' '/sub/.hidden' '/sub/%2Ehidden'; do
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port$p")"
    if [[ "$code" != "404" ]]; then
      echo "dotfile $p returned $code (expected 404)"
      "$S/stop.sh" t-http-dot >/dev/null
      return 1
    fi
  done
  local hdrs; hdrs="$(curl -sD - -o /dev/null "http://127.0.0.1:$port/.ready")"
  "$S/stop.sh" t-http-dot >/dev/null
  grep -qi '^X-Content-Type-Options: nosniff' <<<"$hdrs"
}

test_httpserve_blocks_traversal_and_symlink_escape() {
  "$S/init.sh" t-http-esc --tier html >/dev/null
  echo '<h1>ok</h1>' > /tmp/ps-commu/t-http-esc/app/index.html
  ln -sfn /tmp/ps-commu/t-http-esc/meta.json /tmp/ps-commu/t-http-esc/app/leak.json
  ln -sfn /tmp/ps-commu/t-http-esc /tmp/ps-commu/t-http-esc/app/leakdir
  "$S/serve.sh" t-http-esc --no-lint >/dev/null
  local port p code
  port="$(meta_get t-http-esc port)"
  for p in '/../meta.json' '/%2e%2e/meta.json' '/leak.json' '/leakdir/meta.json'; do
    code="$(curl -s --path-as-is -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port$p")"
    if [[ "$code" != "404" ]]; then
      echo "escape $p returned $code (expected 404)"
      "$S/stop.sh" t-http-esc >/dev/null
      return 1
    fi
  done
  "$S/stop.sh" t-http-esc >/dev/null
}

test_httpserve_dir_listing_and_index() {
  "$S/init.sh" t-http-dir --tier html >/dev/null
  mkdir -p /tmp/ps-commu/t-http-dir/app/no_index /tmp/ps-commu/t-http-dir/app/with_index
  echo 'secret' > /tmp/ps-commu/t-http-dir/app/no_index/secret.txt
  echo '<h2>sub index</h2>' > /tmp/ps-commu/t-http-dir/app/with_index/index.html
  "$S/serve.sh" t-http-dir --no-lint >/dev/null
  local port c1 c2 c3
  port="$(meta_get t-http-dir port)"
  c1="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port/no_index/")"
  c2="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port/no_index")"
  c3="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port/with_index/")"
  "$S/stop.sh" t-http-dir >/dev/null
  [[ "$c1" == "404" && "$c2" == "404" && "$c3" == "200" ]]
}

# --- M1: Tailscale Serve stub helpers & R2 tests ---
_ts_stub_create() {  # [backend_state] [dns_name] → prints temp dir path
  local state="${1:-Running}" dns="${2:-test-node.tail9999.ts.net.}"
  local d; d="$(mktemp -d)"
  python3 - "$d/state.json" "$state" "$dns" <<'PY'
import json, sys
path, state, dns = sys.argv[1:4]
data = {
    "backend_state": state,
    "dns_name": dns,
    "serve_status": {
        "TCP": {"8443": {"HTTPS": True}},
        "Web": {
            f"{dns.rstrip('.')}:8443": {
                "Handlers": {"/": {"Proxy": "http://127.0.0.1:8789"}}
            }
        },
        "AllowFunnel": {f"{dns.rstrip('.')}:8443": True},
    },
}
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PY
  : > "$d/calls.jsonl"
  cat > "$d/tailscale" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
exec python3 - "$D" "$@" <<'PY'
import json, os, sys
d = sys.argv[1]
args = sys.argv[2:]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps(args) + "\n")
with open(os.path.join(d, "state.json")) as f:
    st = json.load(f)

if args == ["status", "--self", "--json"]:
    out = {"BackendState": st.get("backend_state", "Running"), "Self": {"DNSName": st.get("dns_name", "")}}
    print(json.dumps(out))
    sys.exit(0)

if args == ["serve", "status", "--json"]:
    print(json.dumps(st.get("serve_status", {})))
    sys.exit(0)

if args and args[0] == "serve":
    if "reset" in args or "funnel" in args:
        sys.stderr.write("FORBIDDEN tailscale command in stub\n")
        sys.exit(99)
    host = (st.get("dns_name") or "").rstrip(".")
    web = st.setdefault("serve_status", {}).setdefault("Web", {})
    tcp = st.setdefault("serve_status", {}).setdefault("TCP", {})
    if "off" in args:
        ts_port = ""
        for a in args:
            if a.startswith("--https="):
                ts_port = a.split("=", 1)[1]
        if ts_port in ("8443", "8444", "9443"):
            sys.stderr.write(f"FORBIDDEN port {ts_port} in stub\n")
            sys.exit(99)
        for k in [k for k in list(web.keys()) if k.endswith(":" + ts_port)]:
            del web[k]
        tcp.pop(ts_port, None)
        with open(os.path.join(d, "state.json"), "w") as f:
            json.dump(st, f, indent=2)
        sys.exit(0)
    if "--bg" in args:
        ts_port = ""
        for a in args:
            if a.startswith("--https="):
                ts_port = a.split("=", 1)[1]
        target = args[-1]
        if not ts_port or ts_port in ("8443", "8444", "9443"):
            sys.stderr.write(f"FORBIDDEN or missing port {ts_port}\n")
            sys.exit(99)
        tcp[ts_port] = {"HTTPS": True}
        web[f"{host}:{ts_port}"] = {"Handlers": {"/": {"Proxy": target}}}
        with open(os.path.join(d, "state.json"), "w") as f:
            json.dump(st, f, indent=2)
        sys.exit(0)

sys.stderr.write(f"Unhandled stub args: {args}\n")
sys.exit(2)
PY
SH
  chmod +x "$d/tailscale"
  echo "$d"
}

test_tailnet_publish_derives_host_and_records_meta() {
  local stub; stub="$(_ts_stub_create Running "custom-box.tail12345.ts.net.")"
  "$S/init.sh" t-ts-pub --tier html >/dev/null
  echo '<h1>tailnet</h1>' > /tmp/ps-commu/t-ts-pub/app/index.html
  local out port ts_port expected_url
  out="$(TAILSCALE_BIN="$stub/tailscale" "$S/serve.sh" t-ts-pub --no-lint --tailnet)"
  port="$(meta_get t-ts-pub port)"
  ts_port=$((port + 10000))
  expected_url="https://custom-box.tail12345.ts.net:${ts_port}/"
  local ok_flag=1
  grep -qxF "$expected_url" <<<"$out" || ok_flag=0
  [[ "$(meta_get t-ts-pub tailnet_port)" == "$ts_port" ]] || ok_flag=0
  [[ "$(meta_get t-ts-pub tailnet_url)" == "$expected_url" ]] || ok_flag=0
  grep -qF "\"--https=${ts_port}\"" "$stub/calls.jsonl" || ok_flag=0
  grep -qF "\"http://127.0.0.1:${port}\"" "$stub/calls.jsonl" || ok_flag=0
  grep -qF ':8443' "$stub/state.json" || ok_flag=0
  TAILSCALE_BIN="$stub/tailscale" "$S/stop.sh" t-ts-pub >/dev/null
  rm -rf "$stub"
  (( ok_flag ))
}

test_tailnet_refuses_dev() {
  local stub; stub="$(_ts_stub_create Running "dev-refuse.tail9999.ts.net.")"
  "$S/init.sh" t-ts-dev --tier react >/dev/null
  local out rc=0
  out="$(TAILSCALE_BIN="$stub/tailscale" "$S/serve.sh" t-ts-dev --no-lint --tailnet --dev 2>&1)" || rc=$?
  local p; p="$(meta_get t-ts-dev pid)"
  local calls; calls="$(wc -l < "$stub/calls.jsonl" | tr -d ' ')"
  rm -rf "$stub"
  (( rc != 0 )) && grep -qi 'cannot be combined' <<<"$out" && [[ -z "$p" && "$calls" == "0" ]]
}

test_tailnet_missing_and_logged_out_fallback() {
  "$S/init.sh" t-ts-miss --tier html >/dev/null
  echo '<h1>local</h1>' > /tmp/ps-commu/t-ts-miss/app/index.html
  local err out rc=0 port
  err="$(TAILSCALE_BIN=/nonexistent/tailscale "$S/serve.sh" t-ts-miss --no-lint --tailnet 2>&1 >/dev/null)" || rc=$?
  port="$(meta_get t-ts-miss port)"
  (( rc == 0 )) && grep -qi 'WARNING' <<<"$err" &&
  curl -sf "http://127.0.0.1:$port/" | grep -q '<h1>local</h1>' &&
  [[ -z "$(meta_get t-ts-miss tailnet_port)" ]] || { "$S/stop.sh" t-ts-miss >/dev/null; return 1; }
  "$S/stop.sh" t-ts-miss >/dev/null

  local stub; stub="$(_ts_stub_create NeedsLogin "")"
  err="$(TAILSCALE_BIN="$stub/tailscale" "$S/serve.sh" t-ts-miss --no-lint --tailnet 2>&1 >/dev/null)" || rc=$?
  port="$(meta_get t-ts-miss port)"
  local ok_flag=1
  (( rc == 0 )) || ok_flag=0
  grep -qi 'WARNING' <<<"$err" || ok_flag=0
  curl -sf "http://127.0.0.1:$port/" | grep -q '<h1>local</h1>' || ok_flag=0
  [[ -z "$(meta_get t-ts-miss tailnet_port)" ]] || ok_flag=0
  ! grep -q '"--bg"' "$stub/calls.jsonl" || ok_flag=0
  "$S/stop.sh" t-ts-miss >/dev/null
  rm -rf "$stub"
  (( ok_flag ))
}

test_without_tailnet_preserves_localhost_and_cleans_stale() {
  local stub; stub="$(_ts_stub_create Running "plain-box.tail9999.ts.net.")"
  "$S/init.sh" t-ts-plain --tier html >/dev/null
  echo '<h1>plain</h1>' > /tmp/ps-commu/t-ts-plain/app/index.html
  local out
  out="$(TAILSCALE_BIN="$stub/tailscale" "$S/serve.sh" t-ts-plain --no-lint)"
  [[ "$(wc -l <<<"$out" | tr -d ' ')" == "1" ]] &&
  ! grep -q 'https://' <<<"$out" &&
  [[ "$(wc -l < "$stub/calls.jsonl" | tr -d ' ')" == "0" ]] || { "$S/stop.sh" t-ts-plain >/dev/null; rm -rf "$stub"; return 1; }
  "$S/stop.sh" t-ts-plain >/dev/null

  # Serve with --tailnet, then re-serve without --tailnet → stale 177xx cleaned up
  TAILSCALE_BIN="$stub/tailscale" "$S/serve.sh" t-ts-plain --no-lint --tailnet >/dev/null
  local ts_port; ts_port="$(meta_get t-ts-plain tailnet_port)"
  out="$(TAILSCALE_BIN="$stub/tailscale" "$S/serve.sh" t-ts-plain --no-lint)"
  local ok_flag=1
  [[ "$(wc -l <<<"$out" | tr -d ' ')" == "1" ]] || ok_flag=0
  [[ -z "$(meta_get t-ts-plain tailnet_port)" ]] || ok_flag=0
  [[ -z "$(meta_get t-ts-plain tailnet_url)" ]] || ok_flag=0
  grep -qF "\"--https=${ts_port}\"" "$stub/calls.jsonl" && grep -qF '"off"' "$stub/calls.jsonl" || ok_flag=0
  "$S/stop.sh" t-ts-plain >/dev/null
  rm -rf "$stub"
  (( ok_flag ))
}

test_tailnet_ownership_refuses_non_owned() {
  local stub; stub="$(_ts_stub_create Running "own-box.tail9999.ts.net.")"
  "$S/init.sh" t-ts-own --tier html >/dev/null
  # Case 1: tailnet_port = 8443 → refused, zero off calls
  meta_set t-ts-own tailnet_port 8443
  local err rc=0
  err="$(TAILSCALE_BIN="$stub/tailscale" ts_unpublish_owned t-ts-own 2>&1)" || rc=$?
  (( rc != 0 )) && grep -q 'REFUSED' <<<"$err" && ! grep -q '"off"' "$stub/calls.jsonl" || { rm -rf "$stub"; return 1; }

  # Case 2: tailnet_port = 17742 but serve_status points to :3000 (not 77xx) → refused
  python3 - "$stub/state.json" <<'PY'
import json, sys
with open(sys.argv[1]) as f: st = json.load(f)
st["serve_status"]["Web"]["own-box.tail9999.ts.net:17742"] = {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3000"}}}
with open(sys.argv[1], "w") as f: json.dump(st, f, indent=2)
PY
  meta_set t-ts-own tailnet_port 17742
  rc=0; err="$(TAILSCALE_BIN="$stub/tailscale" ts_unpublish_owned t-ts-own 2>&1)" || rc=$?
  (( rc != 0 )) && grep -q 'REFUSED' <<<"$err" && ! grep -q '"off"' "$stub/calls.jsonl" || { rm -rf "$stub"; return 1; }

  # Case 3: listener already gone from status JSON → clears meta keys cleanly
  meta_set t-ts-own tailnet_port 17743
  meta_set t-ts-own tailnet_url "https://own-box.tail9999.ts.net:17743/"
  TAILSCALE_BIN="$stub/tailscale" ts_unpublish_owned t-ts-own || { rm -rf "$stub"; return 1; }
  [[ -z "$(meta_get t-ts-own tailnet_port)" && -z "$(meta_get t-ts-own tailnet_url)" ]]
  local ok=$?
  rm -rf "$stub"
  return $ok
}

test_tailnet_stop_unpublishes() {
  local stub; stub="$(_ts_stub_create Running "stop-box.tail9999.ts.net.")"
  "$S/init.sh" t-ts-stop --tier html >/dev/null
  echo ok > /tmp/ps-commu/t-ts-stop/app/index.html
  TAILSCALE_BIN="$stub/tailscale" "$S/serve.sh" t-ts-stop --no-lint --tailnet >/dev/null
  local ts_port; ts_port="$(meta_get t-ts-stop tailnet_port)"
  TAILSCALE_BIN="$stub/tailscale" "$S/stop.sh" t-ts-stop >/dev/null
  local ok_flag=1
  [[ -z "$(meta_get t-ts-stop tailnet_port)" && -z "$(meta_get t-ts-stop tailnet_url)" ]] || ok_flag=0
  grep -qF "[\"--https=${ts_port}\", \"off\"]" "$stub/calls.jsonl" || grep -qE "\"--https=${ts_port}\".*\"off\"" "$stub/calls.jsonl" || ok_flag=0
  ! grep -qF ":${ts_port}" "$stub/state.json" || ok_flag=0
  grep -qF ":8443" "$stub/state.json" || ok_flag=0
  rm -rf "$stub"
  (( ok_flag ))
}

test_tailnet_re_serve_port_change_unpublishes_old() {
  local stub; stub="$(_ts_stub_create Running "resv-box.tail9999.ts.net.")"
  "$S/init.sh" t-ts-resv --tier html >/dev/null
  echo ok > /tmp/ps-commu/t-ts-resv/app/index.html
  TAILSCALE_BIN="$stub/tailscale" "$S/serve.sh" t-ts-resv --no-lint --tailnet >/dev/null
  local ts1; ts1="$(meta_get t-ts-resv tailnet_port)"

  "$S/init.sh" t-ts-hold --tier html >/dev/null
  echo ok > /tmp/ps-commu/t-ts-hold/app/index.html
  "$S/serve.sh" t-ts-hold --no-lint >/dev/null
  local hold_port; hold_port="$(meta_get t-ts-hold port)"

  # Force next serve attempt to try t-ts-hold's occupied port and land on hold_port+1
  meta_set t-ts-resv port "$hold_port"
  TAILSCALE_BIN="$stub/tailscale" "$S/serve.sh" t-ts-resv --no-lint --tailnet >/dev/null
  local ts2; ts2="$(meta_get t-ts-resv tailnet_port)"
  local ok_flag=1
  [[ "$ts1" != "$ts2" ]] || ok_flag=0
  grep -qE "\"--https=${ts1}\".*\"off\"" "$stub/calls.jsonl" || ok_flag=0
  ! grep -qF ":${ts1}" "$stub/state.json" || ok_flag=0
  grep -qF ":${ts2}" "$stub/state.json" || ok_flag=0
  TAILSCALE_BIN="$stub/tailscale" "$S/stop.sh" t-ts-resv >/dev/null
  "$S/stop.sh" t-ts-hold >/dev/null
  rm -rf "$stub"
  (( ok_flag ))
}

test_tailnet_watchdog_unpublishes() {
  local stub; stub="$(_ts_stub_create Running "ttl-box.tail9999.ts.net.")"
  "$S/init.sh" t-ts-ttl --tier html >/dev/null
  echo ok > /tmp/ps-commu/t-ts-ttl/app/index.html
  TAILSCALE_BIN="$stub/tailscale" "$S/serve.sh" t-ts-ttl --no-lint --tailnet --keep-alive 2s >/dev/null
  local pid ts_port
  pid="$(meta_get t-ts-ttl pid)"
  ts_port="$(meta_get t-ts-ttl tailnet_port)"
  local died=0
  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null && ! grep -qF ":${ts_port}" "$stub/state.json"; then
      died=1; break
    fi
    sleep 0.5
  done
  local ok_flag=1
  (( died )) || ok_flag=0
  grep -qE "\"--https=${ts_port}\".*\"off\"" "$stub/calls.jsonl" || ok_flag=0
  [[ -z "$(meta_get t-ts-ttl tailnet_port)" ]] || ok_flag=0
  rm -rf "$stub"
  (( ok_flag ))
}

test_tailnet_init_sweep_unpublishes() {
  local stub; stub="$(_ts_stub_create Running "sweep-box.tail9999.ts.net.")"
  mkdir -p /tmp/ps-commu/t-ts-old
  meta_set t-ts-old port 7788
  meta_set t-ts-old tailnet_port 17788
  meta_set t-ts-old tailnet_url "https://sweep-box.tail9999.ts.net:17788/"
  python3 - "$stub/state.json" <<'PY'
import json, sys
with open(sys.argv[1]) as f: st = json.load(f)
st["serve_status"]["Web"]["sweep-box.tail9999.ts.net:17788"] = {"Handlers": {"/": {"Proxy": "http://127.0.0.1:7788"}}}
with open(sys.argv[1], "w") as f: json.dump(st, f, indent=2)
PY
  touch -t 202601010000 /tmp/ps-commu/t-ts-old
  TAILSCALE_BIN="$stub/tailscale" "$S/init.sh" t-ts-sweeper >/dev/null
  local ok_flag=1
  [[ ! -d /tmp/ps-commu/t-ts-old ]] || ok_flag=0
  grep -qE '"--https=17788".*"off"' "$stub/calls.jsonl" || ok_flag=0
  ! grep -qF ':17788' "$stub/state.json" || ok_flag=0
  rm -rf "$stub"
  (( ok_flag ))
}

test_tailnet_list_and_handoff_and_orphan() {
  local stub; stub="$(_ts_stub_create Running "view-box.tail9999.ts.net.")"
  "$S/init.sh" t-ts-lh --example >/dev/null
  TAILSCALE_BIN="$stub/tailscale" "$S/serve.sh" t-ts-lh --tailnet >/dev/null
  local turl; turl="$(meta_get t-ts-lh tailnet_url)"
  local lout hout
  lout="$(TAILSCALE_BIN="$stub/tailscale" "$S/list.sh")"
  hout="$(TAILSCALE_BIN="$stub/tailscale" "$S/handoff.sh" t-ts-lh)"
  local ok_flag=1
  grep -qxF "$turl" <<<"$lout" || ok_flag=0
  grep -qxF "Tailnet URL: $turl" <<<"$hout" || ok_flag=0
  grep -qxF "$turl" <<<"$hout" || ok_flag=0
  ! grep -q 'ORPHANED' <<<"$lout" || ok_flag=0

  # Add orphaned 17777 listener with no live server
  python3 - "$stub/state.json" <<'PY'
import json, sys
with open(sys.argv[1]) as f: st = json.load(f)
st["serve_status"]["Web"]["view-box.tail9999.ts.net:17777"] = {"Handlers": {"/": {"Proxy": "http://127.0.0.1:7777"}}}
with open(sys.argv[1], "w") as f: json.dump(st, f, indent=2)
PY
  lout="$(TAILSCALE_BIN="$stub/tailscale" "$S/list.sh")"
  grep -q 'ORPHANED tailnet listener: https://view-box.tail9999.ts.net:17777/' <<<"$lout" || ok_flag=0
  ! grep -q 'ORPHANED.*8443' <<<"$lout" || ok_flag=0
  TAILSCALE_BIN="$stub/tailscale" "$S/stop.sh" t-ts-lh >/dev/null
  rm -rf "$stub"
  (( ok_flag ))
}

test_tailnet_clean_unpublishes() {
  local stub; stub="$(_ts_stub_create Running "clean-box.tail9999.ts.net.")"
  "$S/init.sh" t-ts-clean --tier html >/dev/null
  echo ok > /tmp/ps-commu/t-ts-clean/app/index.html
  TAILSCALE_BIN="$stub/tailscale" "$S/serve.sh" t-ts-clean --no-lint --tailnet >/dev/null
  local ts_port; ts_port="$(meta_get t-ts-clean tailnet_port)"
  TAILSCALE_BIN="$stub/tailscale" "$S/clean.sh" >/dev/null
  local ok_flag=1
  [[ ! -d /tmp/ps-commu/t-ts-clean ]] || ok_flag=0
  grep -qE "\"--https=${ts_port}\".*\"off\"" "$stub/calls.jsonl" || ok_flag=0
  ! grep -qF ":${ts_port}" "$stub/state.json" || ok_flag=0
  grep -qF ":8443" "$stub/state.json" || ok_flag=0
  rm -rf "$stub"
  (( ok_flag ))
}

check httpserve_get_head_and_headers          test_httpserve_get_head_and_headers
check httpserve_rejects_non_get_head_405      test_httpserve_rejects_non_get_head_405
check httpserve_blocks_dotfiles               test_httpserve_blocks_dotfiles
check httpserve_blocks_traversal_and_symlink  test_httpserve_blocks_traversal_and_symlink_escape
check httpserve_dir_listing_and_index         test_httpserve_dir_listing_and_index
check tailnet_publish_derives_host            test_tailnet_publish_derives_host_and_records_meta
check tailnet_refuses_dev                     test_tailnet_refuses_dev
check tailnet_missing_and_logged_out_fallback test_tailnet_missing_and_logged_out_fallback
check without_tailnet_and_cleans_stale        test_without_tailnet_preserves_localhost_and_cleans_stale
check tailnet_ownership_refuses_non_owned     test_tailnet_ownership_refuses_non_owned
check tailnet_stop_unpublishes                test_tailnet_stop_unpublishes
check tailnet_re_serve_port_change            test_tailnet_re_serve_port_change_unpublishes_old
check tailnet_watchdog_unpublishes            test_tailnet_watchdog_unpublishes
check tailnet_init_sweep_unpublishes          test_tailnet_init_sweep_unpublishes
check tailnet_list_and_handoff_and_orphan     test_tailnet_list_and_handoff_and_orphan


# --- M2: R1 Vendored assets, shared tokens, Thai+EN lang sync, declarative interactivity ---
test_vendor_assets_budget_and_no_external_urls() {
  local v="$SKILL_DIR/assets/vendor"
  local f
  for f in cherry-markdown.engine.core.js cherry-markdown.markdown.min.css viewer-static.min.js lucide.min.js fonts.css \
           fonts/bricolage-grotesque-latin.woff2 fonts/inter-latin.woff2 fonts/jetbrains-mono-latin.woff2 fonts/noto-sans-thai-thai.woff2; do
    [[ -s "$v/$f" ]] || { echo "missing vendor file: $f"; return 1; }
  done
  python3 - "$SKILL_DIR" <<'PY'
import os, re, sys
sd = sys.argv[1]
v = os.path.join(sd, "assets", "vendor")
total = sum(os.path.getsize(os.path.join(r, fn)) for r, _, fs in os.walk(v) for fn in fs)
assert total <= 6291456, f"vendor dir {total} > 6291456"
for rel in (
    "assets/template-infographic/index.html",
    "assets/template-html/index.html",
    "assets/template-react/index.html",
    "assets/vendor/fonts.css",
    "assets/vendor/cherry-markdown.markdown.min.css",
):
    txt = open(os.path.join(sd, rel), encoding="utf-8").read()
    hits = re.findall(r"https?://[^\s\x22\x27<>)]+", txt)
    assert not hits, f"{rel} has external URLs: {hits}"
inf = open(os.path.join(sd, "assets/template-infographic/index.html"), encoding="utf-8").read()
for tok in ("window.MathJax", "window.mxLoadResources = false", 'window.DRAWIO_BASE_URL = "."'):
    assert tok in inf, f"missing {tok} in template-infographic/index.html"
PY
}

test_shared_tokens_and_impeccable_bans() {
  python3 - "$SKILL_DIR" <<'PY'
import os, re, sys
sd = sys.argv[1]
theme = open(os.path.join(sd, "assets/template-infographic/theme.css"), encoding="utf-8").read()
assert "--accent:       #1c4f8f;" in theme or "--accent: #1c4f8f;" in theme
assert "Noto Sans Thai" in theme

for rel in (
    "assets/template-infographic/explainer.css",
    "assets/template-html/index.html",
    "assets/template-react/src/styles.css",
):
    txt = open(os.path.join(sd, rel), encoding="utf-8").read()
    for bad in ("#0a0e1a", "background-clip: text", "backdrop-filter", "border-left: 4px", "metric-grid", "metric-tile", "break-all"):
        assert bad not in txt, f"{rel} contains banned pattern: {bad}"
    assert "cat-" not in txt, f"{rel} contains cat-* classes"

html_tpl = open(os.path.join(sd, "assets/template-html/index.html"), encoding="utf-8").read()
assert "./theme.css" in html_tpl and "./vendor/fonts.css" in html_tpl
rmain = open(os.path.join(sd, "assets/template-react/src/main.tsx"), encoding="utf-8").read()
assert "../../vendor/fonts.css" in rmain and "../../template-infographic/theme.css" in rmain
PY
}

test_thai_lang_sync_and_css_rules() {
  rm -rf /tmp/ps-commu/t-thai-sync /tmp/ps-commu/t-thai-html
  "$S/init.sh" t-thai-sync --example >/dev/null
  sed -i.bak 's/^Lang: en$/Lang: th/' /tmp/ps-commu/t-thai-sync/00-brief.md && rm -f /tmp/ps-commu/t-thai-sync/00-brief.md.bak
  "$S/lint.sh" t-thai-sync || return 1
  rm -f /tmp/ps-commu/t-thai-sync/app/content.md
  "$S/skeleton.sh" t-thai-sync >/dev/null || return 1
  grep -q '<html lang="th">' /tmp/ps-commu/t-thai-sync/app/index.html || return 1

  # Reject invalid Lang
  sed -i.bak 's/^Lang: th$/Lang: (...)/' /tmp/ps-commu/t-thai-sync/00-brief.md && rm -f /tmp/ps-commu/t-thai-sync/00-brief.md.bak
  ! "$S/lint.sh" t-thai-sync >/dev/null 2>&1 || return 1

  # serve.sh syncs Lang: th into html tier index.html
  "$S/init.sh" t-thai-html --tier html >/dev/null
  _lint_valid_brief_facts_storyboard t-thai-html
  printf '\nLang: th\n' >> /tmp/ps-commu/t-thai-html/00-brief.md
  "$S/serve.sh" t-thai-html >/dev/null || return 1
  grep -q '<html lang="th">' /tmp/ps-commu/t-thai-html/app/index.html || { "$S/stop.sh" t-thai-html >/dev/null; return 1; }
  "$S/stop.sh" t-thai-html >/dev/null

  python3 - "$SKILL_DIR/assets/template-infographic/theme.css" <<'PY'
import re, sys
css = open(sys.argv[1], encoding="utf-8").read()
assert 'html[lang^="th"]' in css
m_body = re.search(r'html\[lang\^="th"\][^{]*\{[^}]*--lh-body:\s*([0-9.]+)', css)
m_tight = re.search(r'html\[lang\^="th"\][^{]*\{[^}]*--lh-tight:\s*([0-9.]+)', css)
assert m_body and float(m_body.group(1)) >= 1.7
assert m_tight and float(m_tight.group(1)) >= 1.35
assert "text-transform: none" in css and "letter-spacing: 0" in css
PY
}

test_lint_rejects_script_and_malformed_declarative() {
  rm -rf /tmp/ps-commu/t-decl-lint
  "$S/init.sh" t-decl-lint --example >/dev/null
  local c=/tmp/ps-commu/t-decl-lint/app/content.md out rc

  # 1. Inline <script> rejected
  printf '\n<script>alert(1)</script>\n' >> "$c"
  out="$("$S/lint.sh" t-decl-lint 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q 'inline <script> is forbidden' <<<"$out" || return 1

  # 2. Malformed .tabs (only 1 button) rejected
  cat > "$c" <<'EOF'
See F1.
<div class="tabs"><div class="tab-list"><button type="button" class="tab-btn">Only</button></div><div class="tab-panel">P1</div></div>
EOF
  out="$("$S/lint.sh" t-decl-lint 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q '.tabs #1 requires >=2' <<<"$out" || return 1

  # 3. Malformed .accordion (mismatched panels) rejected
  cat > "$c" <<'EOF'
See F1.
<div class="accordion"><div class="acc-item"><button type="button" class="acc-btn">Q1</button><div class="acc-panel">A1</div></div><div class="acc-item"><button type="button" class="acc-btn">Q2</button></div></div>
EOF
  out="$("$S/lint.sh" t-decl-lint 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q '.accordion #1 requires >=2' <<<"$out" || return 1

  # 4. Valid .tabs + .accordion passes
  cat > "$c" <<'EOF'
See F1.
<div class="tabs"><div class="tab-list"><button type="button" class="tab-btn" aria-pressed="true">A</button><button type="button" class="tab-btn" aria-pressed="false">B</button></div><div class="tab-panel is-active">PA</div><div class="tab-panel" hidden>PB</div></div>
<div class="accordion"><div class="acc-item is-open"><button type="button" class="acc-btn" aria-expanded="true">Q1</button><div class="acc-panel">A1</div></div><div class="acc-item"><button type="button" class="acc-btn" aria-expanded="false">Q2</button><div class="acc-panel" hidden>A2</div></div></div>
EOF
  "$S/lint.sh" t-decl-lint
}

test_verify_assert9_declarative_interactivity() {
  _vstub_ws || return 1
  local d=/tmp/ps-commu/t-stub-a9 out rc
  _stub_chrome "$d" page
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub 2>&1)"; rc=$?
  (( rc == 0 )) && grep -q '^PASS: 9 declarative interactive:' <<<"$out" || return 1

  # Missing .tabs/.accordion on content.md -> FAIL: 9
  printf '%s\n' '<html><body class="is-ready"><div class="cherry-previewer"><div class="mxgraph" style="margin-top: 10px"><svg><rect></rect></svg></div><p>No interactive.</p></div></body></html>' > "$d/page.html"
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q '^FAIL: 9 declarative interactive:' <<<"$out" || return 1

  # Unwired .tabs -> FAIL: 9
  printf '%s\n' '<html><body class="is-ready"><div class="cherry-previewer"><div class="mxgraph" style="margin-top: 10px"><svg><rect></rect></svg></div><div class="tabs"><div class="tab-list"><button class="tab-btn"></button><button class="tab-btn"></button></div><div class="tab-panel"></div><div class="tab-panel" hidden></div></div><div class="accordion is-wired"><div class="acc-item"><button class="acc-btn"></button><div class="acc-panel"></div></div><div class="acc-item"><button class="acc-btn"></button><div class="acc-panel" hidden></div></div></div></div></body></html>' > "$d/page.html"
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q '^FAIL: 9 declarative interactive unwired/malformed' <<<"$out"
}

check vendor_assets_budget_and_offline    test_vendor_assets_budget_and_no_external_urls
check shared_tokens_and_impeccable_bans   test_shared_tokens_and_impeccable_bans
check thai_lang_sync_and_css_rules        test_thai_lang_sync_and_css_rules
check lint_script_and_declarative         test_lint_rejects_script_and_malformed_declarative
check verify_assert9_declarative          test_verify_assert9_declarative_interactivity

# --- M3: Polish regression tests ---
test_thai_tt_label_and_nav_title_tokens() {
  python3 - "$SKILL_DIR" <<'PY'
import os, re, sys
sd = sys.argv[1]
theme = open(os.path.join(sd, "assets/template-infographic/theme.css"), encoding="utf-8").read()
assert "--tt-label:" in theme and "uppercase" in theme
assert re.search(r'html\[lang\^="th"\][^{]*\{[^}]*--tt-label:\s*none', theme, re.S), "missing --tt-label: none for Thai"

ecss = open(os.path.join(sd, "assets/template-infographic/explainer.css"), encoding="utf-8").read()
for sel in (
    r'\.explainer-nav \.nav-brand \.nav-sub\s*\{[^}]*text-transform:\s*var\(--tt-label\)',
    r'\.cherry-markdown\.theme__explainer thead th\s*\{[^}]*text-transform:\s*var\(--tt-label\)',
    r'\.toc-title\s*\{[^}]*text-transform:\s*var\(--tt-label\)',
    r'\.explainer-nav \.nav-brand \.nav-title\s*\{[^}]*line-height:\s*var\(--lh-tight\)',
    r'\.tabs \.tab-btn\s*\{[^}]*line-height:\s*var\(--lh-snug\)',
):
    assert re.search(sel, ecss, re.S), f"explainer.css missing expected rule: {sel}"
assert "text-transform: uppercase" not in ecss, "explainer.css still has hardcoded text-transform: uppercase"

h = open(os.path.join(sd, "assets/template-html/index.html"), encoding="utf-8").read()
assert re.search(r'thead th\s*\{[^}]*text-transform:\s*var\(--tt-label\)', h, re.S)
assert re.search(r'\.tab-btn\s*\{[^}]*line-height:\s*var\(--lh-snug\)', h, re.S)
r = open(os.path.join(sd, "assets/template-react/src/styles.css"), encoding="utf-8").read()
assert re.search(r'\.readout-k\s*\{[^}]*text-transform:\s*var\(--tt-label\)', r, re.S)
assert re.search(r'thead th\s*\{[^}]*text-transform:\s*var\(--tt-label\)', r, re.S)
PY
}

test_cherry_setup_toc_locale_object() {
  python3 - "$SKILL_DIR/assets/template-infographic/cherry-setup.js" <<'PY'
import re, sys
js = open(sys.argv[1], encoding="utf-8").read()
assert '"en_US"' not in js and "'en_US'" not in js, "bare string en_US still in cherry-setup.js"
assert re.search(r'locale\s*=\s*\{\s*toc:', js), "locale object with toc key missing"
assert "สารบัญ" in js and "Table of Contents" in js
assert "String(i) === String(targetIdx)" in js
PY
}

test_lint_allows_backtick_script_prose_rejects_html_script() {
  rm -rf /tmp/ps-commu/t-lint-bt
  "$S/init.sh" t-lint-bt --example >/dev/null
  local c=/tmp/ps-commu/t-lint-bt/app/content.md out rc
  printf '\nProse citing `<script>` and ``<script src="x">`` safely (F1).\n' >> "$c"
  "$S/lint.sh" t-lint-bt || return 1
  printf '\n<SCRIPT>alert(2)</SCRIPT>\n' >> "$c"
  out="$("$S/lint.sh" t-lint-bt 2>&1)"; rc=$?
  (( rc == 1 )) && grep -q 'inline <script> is forbidden' <<<"$out"
}

test_init_react_excludes_node_modules_and_dist() {
  rm -rf /tmp/ps-commu/t-react-clean-copy
  local tpl="$SKILL_DIR/assets/template-react" created_dist=0 created_nm=0
  if [[ ! -d "$tpl/dist" ]]; then mkdir -p "$tpl/dist"; touch "$tpl/dist/.probe"; created_dist=1; fi
  if [[ ! -d "$tpl/node_modules" ]]; then mkdir -p "$tpl/node_modules"; touch "$tpl/node_modules/.probe"; created_nm=1; fi
  "$S/init.sh" t-react-clean-copy --tier react >/dev/null
  local ok=1
  [[ ! -e /tmp/ps-commu/t-react-clean-copy/app/node_modules ]] || ok=0
  [[ ! -e /tmp/ps-commu/t-react-clean-copy/app/dist ]] || ok=0
  [[ -f /tmp/ps-commu/t-react-clean-copy/app/package.json && -d /tmp/ps-commu/t-react-clean-copy/app/vendor ]] || ok=0
  (( created_dist )) && rm -rf "$tpl/dist"
  (( created_nm )) && rm -rf "$tpl/node_modules"
  (( ok ))
}

test_list_flags_orphan_even_when_localhost_port_live() {
  local stub; stub="$(_ts_stub_create Running "orphan-box.tail9999.ts.net.")"
  "$S/init.sh" t-local-reuse --tier html >/dev/null
  echo '<h1>local</h1>' > /tmp/ps-commu/t-local-reuse/app/index.html
  "$S/serve.sh" t-local-reuse --no-lint >/dev/null
  local port ts_port lout ok_flag=1
  port="$(meta_get t-local-reuse port)"
  ts_port=$((port + 10000))
  # Inject an orphaned 177xx listener pointing to the live localhost app's 77xx port
  python3 - "$stub/state.json" "$port" "$ts_port" <<'PY'
import json, sys
path, port, ts_port = sys.argv[1:4]
with open(path) as f: st = json.load(f)
st["serve_status"]["Web"][f"orphan-box.tail9999.ts.net:{ts_port}"] = {"Handlers": {"/": {"Proxy": f"http://127.0.0.1:{port}"}}}
with open(path, "w") as f: json.dump(st, f, indent=2)
PY
  lout="$(TAILSCALE_BIN="$stub/tailscale" "$S/list.sh")"
  grep -q "ORPHANED tailnet listener: https://orphan-box.tail9999.ts.net:${ts_port}/" <<<"$lout" || ok_flag=0
  "$S/stop.sh" t-local-reuse >/dev/null
  rm -rf "$stub"
  (( ok_flag ))
}

test_verify_booting_retry_and_diagnostics() {
  _vstub_ws || return 1
  local d=/tmp/ps-commu/t-stub-boot pt=/tmp/ps-commu/t-vstub/page-text.txt out rc
  _stub_chrome "$d" page
  rm -f "$pt"
  cat > "$d/chrome" <<EOF
#!/usr/bin/env bash
echo launch >> "$d/launches"
n="\$(wc -l < "$d/launches" | tr -d ' ')"
if [[ "\$n" -eq 1 ]]; then
  printf '<html><body><div id="app"><div class="booting">Loading explainer…</div></div></body></html>\n'
else
  cat "$d/page.html"
fi
EOF
  chmod +x "$d/chrome"
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub --dump-text 2>/dev/null)"; rc=$?
  (( rc == 0 )) && [[ "$(wc -l < "$d/launches" | tr -d ' ')" == 2 ]] &&
  [[ "$out" == "Stub page text for F-018." ]] || return 1

  # Persistent .booting must stay bounded at 2 launches, exit 1, emit diagnostic, and leave no page-text.txt
  : > "$d/launches"; rm -f "$pt"
  cat > "$d/chrome" <<EOF
#!/usr/bin/env bash
echo launch >> "$d/launches"
printf '<html><body><div id="app"><div class="booting">Loading explainer…</div></div></body></html>\n'
EOF
  chmod +x "$d/chrome"
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub --dump-text 2>&1)"; rc=$?
  (( rc == 1 )) && [[ "$(wc -l < "$d/launches" | tr -d ' ')" == 2 ]] &&
  grep -q 'page never reached .is-ready' <<<"$out" &&
  grep -q 'no .cherry-previewer subtree' <<<"$out" &&
  [[ ! -e "$pt" ]] || return 1

  # Booting DOM whose <script> mentions 'explainer-error' (like real template-infographic/index.html)
  # must still trigger the retry on launch 1, while a real rendered <div class="explainer-error"> does not.
  : > "$d/launches"; rm -f "$pt"
  cat > "$d/chrome" <<EOF
#!/usr/bin/env bash
echo launch >> "$d/launches"
n="\$(wc -l < "$d/launches" | tr -d ' ')"
if [[ "\$n" -eq 1 ]]; then
  printf '<html><body><div id="app"><div class="booting">Loading…</div></div><script>var x="<div class=\\"explainer-error\\">";</script></body></html>\n'
else
  cat "$d/page.html"
fi
EOF
  chmod +x "$d/chrome"
  out="$(CHROME_BIN="$d/chrome" "$S/verify.sh" t-vstub --dump-text 2>/dev/null)"; rc=$?
  (( rc == 0 )) && [[ "$(wc -l < "$d/launches" | tr -d ' ')" == 2 ]] &&
  [[ "$out" == "Stub page text for F-018." ]]
}

test_m4_visual_polish_css_and_table_rules() {
  python3 - "$SKILL_DIR" <<'PY'
import os, re, sys
sd = sys.argv[1]
for rel in (
    "assets/template-infographic/explainer.css",
    "assets/template-html/index.html",
    "assets/template-react/src/styles.css",
):
    txt = open(os.path.join(sd, rel), encoding="utf-8").read()
    assert "overflow-wrap: anywhere" not in txt, f"{rel} still uses overflow-wrap: anywhere"
    assert "overflow-wrap: break-word" in txt, f"{rel} missing overflow-wrap: break-word"
    assert "position: static" in txt, f"{rel} missing static mobile nav rule"
    assert "scroll-margin-top" in txt, f"{rel} missing scroll-margin-top"
    assert "min-width: 7.5rem" not in txt, f"{rel} still has rigid min-width: 7.5rem"
    assert "table-layout: auto" in txt, f"{rel} missing table-layout: auto"
    assert "max-width: 639px" in txt and "attr(data-label)" in txt, f"{rel} missing responsive stacked table card CSS"
    assert "nav-toggle" in txt and "nav-links" in txt and ".is-open" in txt, f"{rel} missing collapsible mobile nav CSS"
    assert "tab-list" in txt and "tab-btn" in txt, f"{rel} missing segmented tab styling"
    assert "abbr[title]" in txt, f"{rel} missing abbr[title] reset"

js = open(os.path.join(sd, "assets/template-infographic/cherry-setup.js"), encoding="utf-8").read()
assert 'setAttribute("data-label"' in js and "td-val" in js, "cherry-setup.js missing data-label/.td-val table stamping"
assert "nav-toggle" in js and "aria-expanded" in js and "nav-links" in js, "cherry-setup.js missing collapsible mobile nav toggle"
assert "scrollHeight - 48" in js, "cherry-setup.js missing scrollspy bottom-of-page accuracy"

ht = open(os.path.join(sd, "assets/template-html/index.html"), encoding="utf-8").read()
assert '.acc-item.is-open > .acc-btn' in ht and '.acc-btn[aria-expanded="true"]' in ht
assert 'code-nowrap' in ht
assert "setAttribute('data-label'" in ht and "td-val" in ht, "template-html missing data-label/.td-val table stamping"
assert "nav-toggle" in ht and "aria-expanded" in ht and "nav-links" in ht, "template-html missing collapsible mobile nav toggle"
assert "scrollHeight - 48" in ht, "template-html missing scrollspy bottom-of-page accuracy"
assert "startOnLoad: false" in ht and "fontSize: '18px'" in ht and "mermaid.run" in ht, "template-html missing updated Mermaid readability config"

rapp = open(os.path.join(sd, "assets/template-react/src/App.tsx"), encoding="utf-8").read()
assert "IntersectionObserver" in rapp and "setActiveId" in rapp
assert "data-label=" in rapp and "td-val" in rapp, "template-react App.tsx missing explicit data-label/.td-val"
assert "nav-toggle" in rapp and "navOpen" in rapp and "aria-expanded" in rapp, "template-react App.tsx missing collapsible mobile nav"
assert "scrollHeight - 48" in rapp, "template-react App.tsx missing scrollspy bottom-of-page accuracy"
PY
}

check thai_tt_label_and_nav_title       test_thai_tt_label_and_nav_title_tokens
check cherry_setup_toc_locale_object    test_cherry_setup_toc_locale_object
check lint_backtick_script_vs_html      test_lint_allows_backtick_script_prose_rejects_html_script
check init_react_excludes_build_dirs    test_init_react_excludes_node_modules_and_dist
check list_orphan_with_live_local_port  test_list_flags_orphan_even_when_localhost_port_live
check verify_booting_retry_diagnostics  test_verify_booting_retry_and_diagnostics
check m4_visual_polish_css_and_tables   test_m4_visual_polish_css_and_table_rules

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
check tailnet_clean_unpublishes test_tailnet_clean_unpublishes

echo "----- $PASS passed, $FAIL failed, $SKIP skipped"
exit $(( FAIL > 0 ))
