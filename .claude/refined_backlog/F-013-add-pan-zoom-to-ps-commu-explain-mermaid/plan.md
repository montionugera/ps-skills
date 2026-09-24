# Replace Mermaid with draw.io in ps-commu-explain (infographic tier) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Mermaid with draw.io (diagrams.net) as the diagram engine on
ps-commu-explain's infographic tier — pan/zoom + standard shapes, authored as plain
mxGraph XML, validated by a rewritten `lint.sh`, rendered via draw.io's static embed.

**Architecture:** Same six-stage chain F-011 built (brief → facts → storyboard → author
→ verify → handoff) — only the diagram sub-system changes. Author writes ` ```drawio `
fences of plain uncompressed mxGraph XML with `role=` semantic style tokens instead of
hex. `cherry-setup.js` detects the fences, substitutes real theme hex for role tokens,
and injects a `data-mxgraph`-configured div rendered by draw.io's `viewer-static.min.js`
(pinned version, CDN-loaded like Mermaid/Cherry/Lucide today). `lint.sh` validates the
XML with Python's stdlib `xml.etree.ElementTree` — structural checks informed by
`mxfile.xsd`, plus domain rules Mermaid never needed (vertex overlap/bounds, label
HTML-escaping, no raw hex). `verify.sh` gets a render-gate assert that explicitly FAILs
on the static viewer's documented silent-empty-render failure mode, plus a committed
(non-SKIP) interactivity proxy assert.

**Tech Stack:** Python 3 stdlib (`xml.etree.ElementTree`, no new dependency), Bash,
vanilla JS (`cherry-setup.js`), draw.io/diagrams.net `viewer-static.min.js` (CDN,
pinned version).

**Spec:** `.claude/refined_backlog/F-013-add-pan-zoom-to-ps-commu-explain-mermaid/spec.md`
(also mirrored from `.claude/idea_backlog/I-012-.../spec.md`) — read it fully; it
carries two independent review passes (self-grill-audit + a Fable architectural review)
already applied as corrections, not a first draft.

## Global Constraints

- **Tier scope**: infographic tier ONLY. `assets/template-html/mermaid.min.js` and
  `assets/template-react`'s Mermaid CSS/docs are UNTOUCHED — no task in this plan edits
  them.
- **`lint.sh` preservation boundary**: lines 1-191 (frontmatter checks for
  `00-brief.md`/`01-facts.md`/`02-storyboard.md`, `F<n>` citation validation against
  `01-facts.md`, and the forbidden-class check for `content.md`) are NOT Mermaid-specific
  and MUST survive every task in this plan untouched. Only the Mermaid-fence loop
  (`` `​``mermaid` `` regex at line 605, `parse_flowchart()` at line 265, and everything
  between) is replaced.
- **Color integration**: authors write `role=accent`, `role=pitfall`, or `role=check` as
  a token inside a vertex/edge's `style` attribute (mxGraph ignores unknown style keys,
  so this is inert until processed). `cherry-setup.js` substitutes these for real hex —
  read from the page's own CSS custom properties (`--accent`, `--pitfall`, `--check`) —
  before injecting the XML into the `data-mxgraph` div. `lint.sh` rejects any
  `fillColor=#...`/`strokeColor=#...` literal in a diagram's XML — raw hex is always a
  defect, never a style choice.
- **Dependency-free**: no new pip/npm dependency. XML parsing is stdlib
  `xml.etree.ElementTree` only.
- **Fail-closed**: any lint/render-gate check that cannot positively confirm a diagram
  is correct must report a defect (or FAIL), never silently pass. This is the single
  most important lesson from F-011's own Mermaid-validator hardening (4 fix rounds, each
  one a silent-pass bug) — do not repeat it.
- **Viewer version pinned**: `viewer-static.min.js` loaded from a specific tagged CDN
  URL, never `@latest`/unversioned — the render-gate's DOM-shape assert depends on the
  viewer's output structure staying stable across page loads.

---

### Task 0: Go/no-go spike — hand-author the exemplar's flowchart as mxGraph XML

This is a spike, not a feature. It exists to answer one question before anything else is
built on top of the answer: **can a real diagram from this skill actually be
hand-authored as mxGraph XML without unreasonable effort or fragility?** If the answer
is no, STOP and report back — do not proceed to Task 1 with a broken premise.

**Files:**
- Create (scratch, not committed): a throwaway `.drawio.xml` fixture under this plan's
  SDD workspace, or directly render it via a temporary HTML file — whatever proves the
  point fastest.
- Read: `skills/ps-commu-explain/assets/template-infographic/content.md:32-40` (the
  source diagram — a 6-node `flowchart LR` with 7 labeled edges, one of them a loop-back:
  `A["init.sh"] -->|scaffold workspace + advisory port| B[...]`, `B -->|author edits
  content.md| C[...]`, `C -->|run lint.sh gate| D{...}`, `D -->|no: exit 1| B`, `D
  -->|yes: bind 127.0.0.1 + watchdog| E[...]`, `E -->|verify.sh: headless Chrome| F[...]`).

**Interfaces:**
- Produces: a verified, working mxGraph XML skeleton (root cells + a coordinate recipe)
  that Task 1's authoring-skeleton doc and Task 4's content migration both build on
  directly — do not let this be a one-off; save the exact XML you end up with.

- [ ] **Step 1: Hand-author the 6-node XML.** Starting point (verify and correct every
      value empirically — this is what the spike is FOR, do not assume this is already
      right):

```xml
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
      <mxGeometry relative="1" as="geometry" />
    </mxCell>
    <mxCell id="e2" value="author edits content.md" style="html=1;" edge="1" parent="1"
        source="B" target="C">
      <mxGeometry relative="1" as="geometry" />
    </mxCell>
    <mxCell id="e3" value="run lint.sh gate" style="html=1;" edge="1" parent="1"
        source="C" target="D">
      <mxGeometry relative="1" as="geometry" />
    </mxCell>
    <mxCell id="e4" value="no: exit 1" style="html=1;role=pitfall;" edge="1" parent="1"
        source="D" target="B">
      <mxGeometry relative="1" as="geometry">
        <Array as="points"><mxPoint x="750" y="60" /></Array>
      </mxGeometry>
    </mxCell>
    <mxCell id="e5" value="yes: bind 127.0.0.1 + watchdog" style="html=1;role=check;"
        edge="1" parent="1" source="D" target="E">
      <mxGeometry relative="1" as="geometry" />
    </mxCell>
    <mxCell id="e6" value="verify.sh: headless Chrome" style="html=1;" edge="1" parent="1"
        source="E" target="F">
      <mxGeometry relative="1" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
```

- [ ] **Step 2: Render it.** Build a throwaway HTML file loading
      `https://viewer.diagrams.net/js/viewer-static.min.js` (find the current stable
      tagged version — do not use `@latest` even for this spike, note the exact URL you
      used, Task 1 pins to it) and a `<div class="mxgraph" data-mxgraph='{"xml":
      "<escaped XML from step 1>", "toolbar":"zoom", "nav":1, "resize":1}'>`. Open it in
      a real browser (or headless Chrome via the claude-in-chrome tools / a
      `--dump-dom` check) and visually inspect: do all 6 nodes render without
      overlapping? Is the `D -->|no| B` loop-back edge legible (it needs a waypoint —
      the `<Array as="points">` above is a first guess, verify it doesn't cross through
      node C)? Are labels fully visible, not clipped?
- [ ] **Step 3: Inspect the DOM.** `--dump-dom` the rendered page. Note exactly what
      element structure the viewer produces per diagram (this is what Task 3's render-gate
      assert will check against) — is there a nested `<svg>`? What attributes does it
      carry? Save this DOM excerpt in your task report; Task 3 depends on it verbatim.
- [ ] **Step 4: Verify the `role=` token survives.** Confirm `role=accent;` etc. in the
      `style` string does NOT break mxGraph's rendering (unknown style keys should be
      silently ignored per mxGraph's style-string parsing) — render with the raw `role=`
      token still present (not yet substituted) and confirm the shape still renders with
      its default appearance, proving Task 1's "inert until processed" assumption.
- [ ] **Step 5: Decide.** If steps 1-4 succeed with reasonable effort (a few iterations
      to get coordinates/waypoints right, not open-ended fighting) — GO, write up the
      final working XML and DOM notes in your report, hand them to Task 1/3/4. If
      hand-authoring proves unreasonably fragile (e.g., the loop-back edge cannot be
      made to render legibly without many iterations, or labels reliably clip in ways
      hard to predict from source) — STOP, report NO-GO with specifics, and the
      controller adjudicates whether to narrow scope (e.g., keep Mermaid for anything
      with cycles/loop-backs, draw.io only for pure DAGs) rather than proceeding blind.
- [ ] **Step 6: Report.** Write the final verified XML, the exact CDN URL used (pinned
      version), the DOM structure notes, and the go/no-go verdict to your task report.
      No commit for this task — it produces no shipped code, only verified facts the
      next tasks build on.
- [ ] **Step 7: Phase gate.** This spike has no code diff to review in the normal sense
      — instead, the controller reads the spike report and confirms GO before dispatching
      Task 1. Do not proceed past this task on an ambiguous or ignored NO-GO.

---

### Task 1: Rendering pipeline — `cherry-setup.js` + `index.html`

**Note on sequencing:** the spec's "add draw.io first, delete Mermaid last" principle is
about not committing to the rip-out before the core viability risk (hand-authored
geometry) is proven — that's what Task 0's spike is FOR, dedicated and gated before this
task starts. This task does a direct, single-pass replacement (not a temporary
dual-renderer coexistence) because only 2 content files exist to migrate (both handled
together in Task 4, "in scope now" per the spec's own decision) and the user's explicit
choice was full replacement, not ongoing coexistence — maintaining two parallel render
paths for a two-diagram migration would be complexity the spec didn't ask for. If Task 0
had returned NO-GO, this task would not be dispatched at all.

**Files:**
- Modify: `skills/ps-commu-explain/assets/template-infographic/cherry-setup.js`
  (remove `frameAndRunMermaid()` and its Mermaid-specific constants
  `MERMAID_THEME_VARIABLES`, `CLASSDEF_PRELUDE`, `MERMAID_HEAD`; add the draw.io
  equivalent)
- Modify: `skills/ps-commu-explain/assets/template-infographic/index.html:50` (swap the
  Mermaid CDN script for the pinned `viewer-static.min.js` URL Task 0 verified)
- Modify: `skills/ps-commu-explain/assets/template-infographic/explainer.css:1062-1082`
  (rename/generalize `.mermaid-frame` to a format-agnostic frame class, or add a
  `.drawio-frame` sibling reusing the same visual treatment — read the existing rule
  before deciding; keep the same visual language, this is a rendering-engine swap, not
  a redesign)
- Test: `skills/ps-commu-explain/tests/lifecycle_test.sh` (add one new test for the
  render function's fence detection + role-token substitution using a static HTML
  fixture, following this file's existing test style — read a few existing
  `test_verify_*` functions for the pattern before writing new ones)

**Interfaces:**
- Consumes: Task 0's verified XML skeleton, pinned CDN URL, and DOM-structure notes.
- Produces: `frameAndRunDrawio(rootEl)` — same call signature and return contract as
  the retired `frameAndRunMermaid(rootEl)` (returns a Promise the caller awaits before
  revealing the page), called from the same site `frameAndRunMermaid` was called from.
  Every `<div class="mxgraph" data-mxgraph="...">` this function creates carries
  `"toolbar":"zoom"` and `"nav":1` (per the spec's explicit-config-key requirement —
  these are NOT automatic).

- [ ] **Step 1: Write the failing test.** A static HTML fixture with a
      ` ```drawio ` fence containing a `role=accent;` styled vertex; assert that after
      `frameAndRunDrawio()` runs, the resulting `data-mxgraph` JSON's `xml` field
      contains a real hex value (e.g. matching `--accent`'s value from the page's
      computed style) and NOT the literal string `role=accent`.
- [ ] **Step 2: Run it, confirm it fails** (function doesn't exist yet).
- [ ] **Step 3: Implement `frameAndRunDrawio()`.** Detect ` ```drawio ` fences the same
      way `frameAndRunMermaid` detected ` ```mermaid ` fences (mirror the existing
      `candidates`/`isLabelled` pattern in the current file — read it before writing the
      replacement, don't invent a different detection strategy). For each fence: read
      its text content, run a role-token substitution pass (regex-replace
      `role=accent`/`role=pitfall`/`role=check` inside `style="..."` attributes with the
      real hex read from `getComputedStyle(document.documentElement)` for
      `--accent`/`--pitfall`/`--check`), build the `data-mxgraph` div with the
      substituted XML plus `"toolbar":"zoom","nav":1,"resize":1`, replace the fence's
      `<pre>`/`<code>` with it. Trigger the viewer's render pass (check whether
      `viewer-static.min.js` auto-scans on load, via a `MutationObserver`, or needs an
      explicit `GraphViewer.processElements()` call once the divs are in the DOM — Task
      0's DOM notes should tell you which; if ambiguous, test both and use whichever
      actually renders reliably when the divs are inserted AFTER initial page load,
      which is this skill's real usage pattern since Cherry-Markdown renders content
      asynchronously).
- [ ] **Step 4: Run the test, confirm it passes.**
- [ ] **Step 5: Update `index.html`** — replace the Mermaid script tag with the pinned
      `viewer-static.min.js` URL from Task 0.
- [ ] **Step 6: Update `explainer.css`** — generalize/rename the frame styling so it
      applies to the new `.mxgraph`/`data-mxgraph` divs the same way it applied to
      `.mermaid-frame`.
- [ ] **Step 7: Manual verification.** Serve the template
      (`skills/ps-commu-explain/scripts/init.sh f013t1 && scripts/serve.sh f013t1`),
      load in Chrome, confirm a ` ```drawio ` fence (use Task 0's verified XML as the
      fixture) renders with real theme colors (not the literal `role=` text, not
      draw.io's default palette) and the toolbar/zoom controls are visible. Stop the
      server after (`scripts/stop.sh f013t1`, never `clean.sh`).
- [ ] **Step 8: Update README & Documentation** — none required yet at this task's
      scope (SKILL.md/README updates are Task 6); skip.
- [ ] **Step 9: Commit** (`git add` the three modified files + the new test; new commit,
      never `--amend`).
- [ ] **Step 10: Phase gate** — verify (test + manual Chrome check above) → independent
      review (`code-reviewer` + `typescript-reviewer`, `model: opus` given the JS/CSS
      surface and that this is the rendering foundation every later task depends on) →
      `/simplify` → re-verify.

---

### Task 2: `lint.sh` — the mxGraph XML validator

**Files:**
- Modify: `skills/ps-commu-explain/scripts/lint.sh` — lines 1-191 UNTOUCHED (see Global
  Constraints); replace the Mermaid-fence loop and everything it calls (`re.finditer(r'`
  ` `​``mermaid\s*\n(.*?)`​``', ...)` at line 605, `parse_flowchart()` at line 265, the
  `FLOWCHART_HEADS`/`CHECKED_HEADS`/`OTHER_DIAGRAM_HEADS` constants, `seq_edge_re`) with
  a new `` `​``drawio` `` fence loop and `parse_drawio_xml()`.
- Test: `skills/ps-commu-explain/tests/lifecycle_test.sh` (new `test_lint_*` functions —
  see Task 5, but write the ones exercising THIS task's rules now so this task is
  independently verifiable; the bulk migration of old Mermaid tests is Task 5's job).

**Interfaces:**
- Consumes: nothing from earlier tasks except the file boundary (lines 1-191 preserved).
- Produces: exit 0 = clean, exit 1 = defects printed one per line (same contract as the
  retired Mermaid checker). Defect message format matches the existing style:
  `"app/content.md: <what> <why>"`.

- [ ] **Step 1: Write failing tests** for each new rule (one fixture, one assertion,
      following this file's existing `test_lint_*` pattern — read
      `test_lint_fails_unlabeled_edge` for the shape to copy):
      - `test_lint_fails_drawio_malformed_xml` — a fence with unclosed XML tags → exit
        1, defect mentions unparseable.
      - `test_lint_fails_drawio_missing_root_cells` — valid XML missing `id="0"`/`id="1"`
        → exit 1.
      - `test_lint_fails_drawio_unlabeled_edge` — an `edge="1"` cell with empty/missing
        `value` → exit 1.
      - `test_lint_fails_drawio_node_cap` — 8 vertex cells in one diagram → exit 1
        (mirror the existing 7-node cap).
      - `test_lint_fails_drawio_overlap` — two vertex geometries with overlapping
        x/y/width/height → exit 1.
      - `test_lint_fails_drawio_out_of_bounds` — a vertex geometry whose
        `x+width`/`y+height` exceeds the graph's declared `pageWidth`/`pageHeight` →
        exit 1.
      - `test_lint_fails_drawio_unescaped_label` — a `value="F<n> cites this"` (literal
        `<`, not an entity) → exit 1.
      - `test_lint_fails_drawio_raw_hex` — a style string containing
        `fillColor=#1c4f8f` instead of `role=accent` → exit 1.
      - `test_lint_passes_drawio_valid` — Task 0's final verified XML, wrapped in a
        ` ```drawio ` fence → exit 0.
- [ ] **Step 2: Run them, confirm all fail** (function doesn't exist).
- [ ] **Step 3: Implement `parse_drawio_xml(block, idx)`.** Use
      `xml.etree.ElementTree.fromstring()` (wrap in try/except — a `ParseError` is
      exactly the "malformed/unparseable" defect, report it, do not crash the whole
      lint run). Walk `<mxCell>` elements: confirm `id="0"` and `id="1" parent="0"`
      exist; for every other cell confirm exactly one of `vertex="1"`/`edge="1"` is set
      (both or neither is a structural defect); collect unique ids (a duplicate is a
      defect); for vertex cells with an `<mxGeometry x= y= width= height=>` child,
      collect the AABB `(x, y, x+width, y+height)`; for every pair of vertex AABBs,
      check overlap (`not (a.x2 <= b.x1 or b.x2 <= a.x1 or a.y2 <= b.y1 or b.y2 <=
      a.y1)` → overlap defect); check each vertex's `x+width`/`y+height` against the
      `<mxGraphModel pageWidth= pageHeight=>` attributes; for edge cells, confirm
      `value` is present and non-empty after stripping (mirrors the Mermaid
      "unlabeled edge" rule); for EVERY cell's `value` attribute, reject an unescaped
      `<` or bare `&` not part of a valid entity (`&amp;`, `&lt;`, etc. — use a regex
      like `r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;)'` for the bare-`&` half, and reject any
      literal `<` inside the attribute value directly since `ElementTree` will have
      already choked on a genuinely malformed `<` inside an attribute — this check is
      really about content that's technically valid XML but would still be
      mis-interpreted once handed to the `html=1` label renderer, e.g. an HTML-escaped
      `&lt;n&gt;` that LOOKS fine to XML but re-decodes to `<n>` before the browser's
      HTML parser sees it — verify this distinction empirically against a real render
      before finalizing the regex, this is exactly the kind of subtlety that burned 4
      fix rounds on the Mermaid parser); for every `style` attribute, reject a raw
      `fillColor=#`/`strokeColor=#` (regex `r'(fill|stroke)Color=#[0-9a-fA-F]{3,6}'`)
      instead of a `role=` token; count vertices, defect if over 7 (same cap Mermaid
      used, per the spec's "same domain rules translated").
- [ ] **Step 4: Wire the new dispatch loop** replacing line 605's
      `` `​``mermaid` `` regex with `` `​``drawio` ``, calling `parse_drawio_xml` per
      match, same defect-collection pattern as the retired code.
- [ ] **Step 5: Run the tests, confirm all pass.**
- [ ] **Step 6: Confirm lines 1-191 are byte-identical to before this task** (`git diff`
      the file, visually confirm no changes above the boundary) — this is the Global
      Constraint's hard requirement, verify it explicitly, don't just trust you didn't
      touch it.
- [ ] **Step 7: Commit.**
- [ ] **Step 8: Phase gate** — verify → independent review (`code-reviewer` +
      `python-reviewer`, `model: opus` — this is the validator every later task's
      content must pass, treat it with the same rigor F-011's Mermaid lint.sh eventually
      needed, not less) → `/simplify` → re-verify.

---

### Task 3: `verify.sh` — render gate + interactivity assert

**Files:**
- Modify: `skills/ps-commu-explain/scripts/verify.sh:114` (fence-count grep,
  `` `​``mermaid` `` → `` `​``drawio` ``), and the DOM-inspection Python block around
  lines 201-214 (SVG-role counting → the draw.io equivalent, using Task 0's DOM notes).
- Test: `skills/ps-commu-explain/tests/lifecycle_test.sh` (`test_verify_passes_drawio_template`,
  `test_verify_fails_drawio_empty_render`).

**Interfaces:**
- Consumes: Task 0's DOM-structure notes (what the rendered `.mxgraph` div actually
  contains); Task 1's `frameAndRunDrawio()` output shape.
- Produces: same PASS/FAIL/SKIP assert-line contract `verify.sh` already has.

- [ ] **Step 1: Write the failing tests.** `test_verify_passes_drawio_template`: serve
      Task 0's verified XML as `content.md`, run `verify.sh <slug>`, expect exit 0 and a
      PASS line for the drawio-count assert. `test_verify_fails_drawio_empty_render`:
      serve a fence with deliberately malformed XML that the STATIC VIEWER accepts as
      valid JSON but fails to parse as a graph (per the spec's documented failure mode —
      confirm this reproduces the "empty graph, zero console errors" case, not a case
      `lint.sh` would have already caught pre-serve; this assert is specifically the
      render-time backstop for whatever gets past lint, e.g. a `--no-lint` serve), run
      `verify.sh`, expect exit 1 (FAIL), not exit 2/0.
- [ ] **Step 2: Run them, confirm they fail.**
- [ ] **Step 3: Update the fence-count grep** at line 114 to count ` ```drawio ` fences.
- [ ] **Step 4: Update the DOM-inspection Python block.** Using Task 0's exact DOM
      notes, count rendered diagrams the equivalent way the old code counted
      `aria-roledescription` SVGs (likely: count `.mxgraph` divs that ended up with a
      real child `<svg>` vs. ones that stayed empty — an empty `.mxgraph` div after the
      viewer script has run is exactly the "silent empty render" failure to catch).
      Compare against the fence count from Step 3; FAIL (not SKIP, not silent pass) if
      they don't match OR if any `.mxgraph` div is empty.
- [ ] **Step 5: Add the interactivity proxy assert** (a new assert number after the
      existing 6): confirm the `GraphViewer` global exists after the viewer script
      loads (proves the script itself loaded and initialized, not just that the CDN tag
      is present in HTML source) AND confirm at least one rendered diagram's toolbar
      element (per Task 0's DOM notes — the concrete selector for the zoom-toolbar
      draw.io injects when `"toolbar":"zoom"` is set) is present in the DOM. FAIL
      (never SKIP) if `GraphViewer` is absent when Chrome IS available — this assert
      needs Chrome the same way asserts 1-5 do, so it's SKIP only in the existing
      no-Chrome branch, never silently omitted otherwise.
- [ ] **Step 6: Run the tests, confirm they pass.**
- [ ] **Step 7: Manual check.** Serve the template, run `verify.sh <slug>` for real
      against a live server (not just the test fixtures), confirm the output reads
      correctly end to end.
- [ ] **Step 8: Commit.**
- [ ] **Step 9: Phase gate** — verify → independent review (`code-reviewer`, `model:
      opus`) → `/simplify` → re-verify.

---

### Task 4: Content migration — `content.md` + `components.md`

**Files:**
- Modify: `skills/ps-commu-explain/assets/template-infographic/content.md:32-40`
  (replace the Mermaid flowchart with Task 0's verified `` `​``drawio` `` fence).
- Modify: `skills/ps-commu-explain/assets/template-infographic/components.md:93-106`
  (replace the Mermaid sequenceDiagram gallery example).
- Modify: `skills/ps-commu-explain/assets/workspace/example/01-facts.md` (if any fact
  cites a line number inside the Mermaid-era `lint.sh`/`verify.sh` sections that moved —
  re-verify every `F<n>` citation the same way F-011's own final-review adjudication
  did: open the cited line, confirm the claim is there, fix any drift Tasks 1-3 caused).
- Modify: `skills/ps-commu-explain/assets/template-infographic/components.md` — add the
  authoring skeleton (Task 0's verified root-cells + grid-recipe, per the spec's
  "components.md/SKILL.md ship a copy-and-fill skeleton" requirement).

**Interfaces:**
- Consumes: Task 0's verified XML (content.md's diagram) and Task 2's validator (to
  confirm both migrated diagrams actually lint clean).

- [ ] **Step 1: Replace `content.md`'s flowchart** with Task 0's exact final verified
      XML (already proven to render correctly and pass the viability spike — don't
      re-author it from scratch, reuse it).
- [ ] **Step 2: Handle the sequenceDiagram gallery example.** Sequence diagrams (4
      lifelines, 9 timed messages) are structurally harder to hand-author in mxGraph XML
      than a flowchart — lifelines need vertical position tracking and message arrows
      need correct Y-ordering, a different authoring model than flowchart nodes/edges.
      Decision (already made, not a new fork): if Task 0's spike found flowchart
      authoring reasonably tractable, attempt the sequence diagram with the same
      grid-coordinate approach (lifelines as tall thin vertices, messages as horizontal
      edges at increasing Y); if it proves meaningfully harder within a focused attempt
      (not open-ended), substitute an equivalent FLOWCHART-shaped diagram covering the
      same four components and their interaction order instead — the gallery's
      requirement is "a real diagram demonstrating the chain," not "must specifically be
      a sequence diagram" (that was a Mermaid-specific gallery-ordering rule from F-011's
      own spec, which does not need to carry over verbatim to a different diagram
      engine). State which path you took in your task report.
- [ ] **Step 3: Add the authoring skeleton** to `components.md`'s gallery: the two
      mandatory root cells pre-filled, Task 0's grid-coordinate recipe
      (`x = 40 + 200*i`, consistent row height) documented as the "start here" pattern,
      one `role=` example. Mirror the tone/format `00-brief.md`'s own skeleton uses.
- [ ] **Step 4: Run `lint.sh` against both files**, confirm exit 0 for the content.md
      diagram and the gallery's sample(s).
- [ ] **Step 5: Serve and Chrome-verify** both pages render correctly (`?doc=components.md`
      for the gallery), zero console errors, diagrams pan/zoom, colors match the theme.
- [ ] **Step 6: Re-verify every `F<n>` citation** in `01-facts.md` and `content.md`'s
      Receipts footer against the CURRENT state of `lint.sh`/`verify.sh` after Tasks
      1-3's edits — open each cited line, confirm the claim holds, fix any that drifted
      (this exact failure mode bit F-011's own Task 8 and its final review twice; don't
      let it happen a third time in this feature).
- [ ] **Step 7: Update README & Documentation** — none required yet (Task 6's scope).
- [ ] **Step 8: Commit.**
- [ ] **Step 9: Phase gate** — verify (lint + Chrome + citation re-check above) →
      independent review (`code-reviewer`, `model: opus` — fact-accuracy bar, same
      standard as F-011's Task 7) → `/simplify` → re-verify.

---

### Task 5: Test migration — `lifecycle_test.sh`

The single largest task in this plan by line count (~38 of 59 `test_` functions,
`lifecycle_test.sh:243-1063`, are Mermaid-grammar regression tests from F-011's 4-fix-round
hardening saga). Budget real time for this; do not treat it as mechanical
find-and-replace — many of these tests encode a specific historical bug (a regex
edge case, a parser ambiguity) that has a DIFFERENT XML-format analog worth preserving
the spirit of, not a literal 1:1 translation.

**Files:**
- Modify: `skills/ps-commu-explain/tests/lifecycle_test.sh:243-1063` — remove Mermaid-
  grammar-specific tests already superseded by Task 2's own new tests (avoid duplicate
  coverage of the same rule under two different test names); for each RETIRED Mermaid
  test that encoded a genuine, still-relevant lesson (e.g. "don't silently skip on
  unrecognized input" — a lesson Task 2's `parse_drawio_xml` must also honor), write an
  XML-format equivalent rather than just deleting it.

**Interfaces:**
- Consumes: Task 2's `parse_drawio_xml` behavior contract, Task 3's `verify.sh` assert
  behavior.

- [ ] **Step 1: Inventory.** List all ~38 Mermaid-specific `test_` functions
      (`lifecycle_test.sh:243-1063`) with a one-line note per test: what specific defect
      class it guards against, and whether that defect class (a) has a direct XML
      analog Task 2 already covers (dedupe — Task 2's own new tests already cover it,
      just delete the old one), (b) has an XML analog NOT yet covered (write a new test
      here), or (c) is genuinely Mermaid-syntax-specific with no XML analog (delete,
      note why in the task report).
- [ ] **Step 2: Delete category (a) and (c) tests.**
- [ ] **Step 3: Write category (b) tests** — TDD as normal (failing test first, confirm
      the fail, then confirm it passes against Task 2's already-implemented validator —
      note these tests exercise ALREADY-SHIPPED Task 2 code, so this is regression
      coverage, not new-feature TDD; still write the test before checking it passes, to
      confirm it actually exercises the intended code path and isn't vacuously green).
- [ ] **Step 4: Run the full suite**, confirm the total count and 0 failures/0 skips
      (Chrome must be available in this environment for the render-gate tests to
      actually run, not SKIP — confirm this explicitly in your report, the way every
      prior F-011 task did).
- [ ] **Step 5: Commit.**
- [ ] **Step 6: Phase gate** — verify → independent review (`code-reviewer`, `model:
      opus` — given this is the largest task and the one most likely to have silently
      dropped real coverage during the migration, this review should specifically check
      for coverage regressions, not just code quality: does every RETIRED Mermaid test's
      underlying lesson have either a surviving XML analog or a documented reason it
      doesn't apply?) → `/simplify` → re-verify.

---

### Task 6: `SKILL.md` + `README.md` updates

**Files:**
- Modify: `skills/ps-commu-explain/SKILL.md:18` (tier description mentions "Mermaid" —
  update), `:39` (`--no-lint` description lists "Mermaid edge-label checks" — update to
  the new checks), `:46` (Stage 4 table mentions "unlabeled Mermaid edges, >7 nodes" —
  update), `:59` (verify.sh description: "Mermaid `<svg>` count == fenced ` ```mermaid `
  count" and the whole 6-assert list — update to the new asserts, including the new
  interactivity assert from Task 3), `:61` (reader-gate text mentions "unrendered
  ` ```mermaid ` fences" — update), `:101` (rationalizations table mentions "Mermaid
  edge-label checks" — update), `:116` (red flags list mentions "A Mermaid edge with no
  label, or a flowchart with more than 7 nodes" — update to the drawio equivalents).
  Confirm the file stays under ~120 lines after edits (it's currently near that limit;
  trim a Minor item if needed rather than let it balloon).
- Modify: `README.md:11` (top-level ps-commu-explain description — check if it names
  Mermaid specifically; if it's generic "diagrams, animation, interactivity" it may not
  need a change, verify before editing), any other README line naming Mermaid for this
  skill specifically (grep for it, don't assume the earlier scan was exhaustive).

**Interfaces:** none — this is a leaf task, nothing downstream depends on it within this
plan.

- [ ] **Step 1: Grep `SKILL.md` and `README.md` for every remaining "Mermaid" mention**
      (do not rely solely on the line numbers listed above — they were accurate at
      spec-writing time but earlier tasks may have shifted line numbers; re-grep fresh).
- [ ] **Step 2: Rewrite each one** to accurately describe the draw.io chain — same
      fact-accuracy bar F-011 held itself to (a Critical-severity bug in F-011's own
      Task 8 was exactly a SKILL.md claim that didn't match what the code actually did;
      do not repeat that mistake here). For each claim you write, verify it against the
      actual current `lint.sh`/`verify.sh`/`cherry-setup.js` behavior from Tasks 1-3
      before committing to the wording — do not describe what you assume the code does.
- [ ] **Step 3: Run `bin/ps-skills-doctor --strict`** if present (check `ls bin` first,
      matching F-011's own Task 8 verification step).
- [ ] **Step 4: Run `lifecycle_test.sh`**, confirm still green (this task shouldn't
      touch anything it exercises, but confirm nothing broke).
- [ ] **Step 5: Commit.**
- [ ] **Step 6: Phase gate** — verify → independent review (`code-reviewer`, `model:
      opus` — fact-check the claims against the real scripts, the same standard applied
      to F-011's own SKILL.md rewrite) → `/simplify` → re-verify.

---

## Final Gate: regression + whole-branch review

- [ ] **3-real-project regression test**, same method F-011 used: three independent
      subagents, each following the shipped `SKILL.md` unaided on a real, unfamiliar
      codebase (reuse F-011's three targets if they still exist on disk, or substitute
      current ones per the same reasoning F-011's own regression gate used when a
      target had gone missing), each producing a page with at least one `` `​``drawio` ``
      diagram that passes `lint.sh`, `verify.sh`, and an independent reader-gate check.
- [ ] **Final whole-branch review**: `code-reviewer` + `typescript-reviewer`, `model:
      opus`, over the full feature diff — cross-task consistency (does Task 6's SKILL.md
      actually match Tasks 1-3's final behavior? Any leftover Mermaid reference anywhere
      in the infographic tier?), architecture, and a specific check for whether any
      `html`/`react` tier file was touched by mistake (Global Constraint violation).
- [ ] **README.md final check**: confirm the update from Task 6 is still accurate given
      whatever the final-review fix wave (if any) changed.
- [ ] Ship via `psrw ship` — the user's call, not automatic, per this plan's precedent
      from F-011 (though the user's "run full chain" instruction for this feature may
      supersede that — confirm before running if there's any ambiguity by the time this
      gate is reached, since this instruction predates the final-gate's own findings).
