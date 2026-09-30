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
  # F-013's content migration (Task 4) landed: the shipped content.md now
  # carries its real, migrated ```drawio fence (Task 0's verified 6-node
  # flowchart) instead of the pre-migration ```mermaid one. Assert 1 sees
  # exactly 1 fence and 1 rendered .mxgraph div, both non-empty — a real
  # PASS, not the old vacuous 0==0 one. test_verify_passes_drawio_template
  # below remains the dedicated positive-path drawio render-gate coverage,
  # using its own synthetic fixture rather than the shipped exemplar.
  (( rc == 0 )) &&
  grep -q '^PASS: 1 drawio svg=1 fences=1 (mxgraph-divs=1 empty-render=0 no-svg=0)' <<<"$out" &&
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
    printf '%s\n' '<html><body class="is-ready"><div class="cherry-previewer"><div class="mxgraph" style="margin-top: 10px"><svg><rect></rect></svg></div><p>Stub page text for F-018.</p></div></body></html>' > "$dir/page.html"
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
  # Also verify when DOM renders but an assert fails (e.g. explainer-error body): no page-text.txt
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
