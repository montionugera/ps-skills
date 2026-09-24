---
title: "Replace Mermaid with draw.io in ps-commu-explain"
id: F-013
status: refined
from_idea: I-012
---

# Replace Mermaid with draw.io in ps-commu-explain

## Orientation

- **What we're building:** ps-commu-explain (the Claude Code skill that renders rich
  explainer pages, redesigned in F-011) currently diagrams with Mermaid — static SVG,
  no pan/zoom, generic shapes. This idea replaces Mermaid with draw.io (diagrams.net)
  **on the infographic tier** — the tier the whole F-011 chain (brief/facts/storyboard/
  content.md, `lint.sh`, `verify.sh`) is built around, and the one the user's feedback
  was about: a richer shape library (standard flowchart/network/UML/cloud icons) and
  pan/zoom/toolbar on every diagram, for free.
- **The real viability risk (Fable architectural review, 2026-09-24): no auto-layout.**
  Mermaid authors topology only; dagre places nodes automatically. mxGraph XML requires
  an explicit `<mxGeometry x y width height>` per vertex, hand-placed by whoever
  authors the diagram. The shipped exemplar's 7-line Mermaid flowchart becomes ~50
  lines of XML with 6 rectangles that must not overlap and must fit their labels. This
  is the thing that could make "replace" non-viable in practice even though every
  factual claim in this spec checks out — see the Task-0 spike below, which exists
  specifically to answer this before the rest of the migration is built on top of it.
- **Explicitly out of scope:** the `html` and `react` tiers each vendor their own,
  independent Mermaid integration — `assets/template-html/mermaid.min.js` (2.5MB,
  loaded by `template-html/index.html`, copied by `init.sh`) and
  `assets/template-react/src/styles.css`'s Mermaid CSS, documented separately in
  `references/visual-components.md` with their own (different) node-count cap. F-011's
  own spec already treats deep engagement with these tiers as a non-goal; this idea
  keeps that boundary rather than silently expanding scope to three independent
  diagram integrations instead of one. A follow-up idea can migrate them later if
  wanted.
- **Decisions made (batch-grill, 2026-09-24):**
  - Full replacement, not coexistence with Mermaid — user's explicit call after the
    coexistence tradeoff (lower risk, zero rewrite of the just-hardened Mermaid
    validator) was raised and considered.
  - Diagrams render via draw.io's official **static embed** (`viewer-static.min.js` +
    a `data-mxgraph` div) — not the full interactive editor (`embed.diagrams.net`
    iframe + postMessage), which is a heavier, edit-oriented integration this use case
    doesn't need. Pan/zoom/toolbar are NOT automatic: drawio.com's own docs are explicit
    that they appear "if you enable Layers or Zoom" — the `data-mxgraph` JSON must set
    `"toolbar":"zoom"` (and equivalent nav/zoom keys) explicitly; this is a one-line
    config choice, not a design risk, but the implementer must set it.
  - Diagrams are authored as **plain, uncompressed mxGraph XML** directly in
    ` ```drawio ` fences (draw.io's own official AI-authoring guidance recommends
    exactly this — LLMs write uncompressed XML, validated against `mxfile.xsd` +
    documented cell invariants). This is the fact that makes the migration viable:
    the original "draw.io means losing plain-text, LLM-writable, git-diffable
    authoring" concern is false — XML is more verbose than Mermaid's terse syntax,
    but it is still plain text an agent writes directly, same as today.
  - The chain's validator (`lint.sh`) is rewritten as a **hand-written XML structural +
    domain-rule checker** (Python's stdlib `xml.etree.ElementTree`, informed by
    `mxfile.xsd`'s documented invariants but not dependent on an external XML-schema
    library) — matching the dependency-free philosophy `lint.sh`/`verify.sh` have kept
    throughout F-011, and the same fail-closed pattern that made Mermaid's validator
    trustworthy after its own hardening.
- **Committed now, not deferred (Fable review corrected the original "defer to
  implementation" framing — these are design decisions, not execution details):**
  - **Theme color integration**: draw.io's `%variableName%` substitution (`<mxfile
    vars="...">`) only substitutes label/metadata TEXT, not style/color properties —
    so the "fallback" is actually the expected path, and hardcoded hex per diagram
    would silently re-create the exact single-source-of-truth drift the F-011 color
    rule was built to prevent. Instead: authors write semantic style tokens in each
    vertex/edge's `style` attribute (`role=accent|pitfall|check` — mxGraph ignores
    unknown style keys, so this is inert to the renderer until processed), and
    `cherry-setup.js`'s render function substitutes these for real hex (read from the
    page's own CSS custom properties) before injecting the XML into the `data-mxgraph`
    div. `lint.sh` rejects any diagram with a raw `fillColor=#`/`strokeColor=#` literal
    instead of a role token. This is the Mermaid `class N pitfall` classDef model,
    translated — same mechanism, new syntax.
  - **Label escaping**: the `data-mxgraph` config's default rendering mode uses
    `html=1` per-cell styling, under which a label's `value` attribute is parsed as
    HTML — meaning a literal `<` in a label (e.g. citing `F<n>` per this skill's own
    fact-citation convention, or any XML/HTML snippet used as example content) gets
    silently eaten or mis-rendered, not shown. `lint.sh` must reject any label value
    containing an unescaped `<`/`&` that isn't a valid XML entity — this is directly
    relevant to THIS skill's content, not a generic warning.
  - **Overlap/bounds validation**: since geometry is hand-authored (see the auto-layout
    risk above), a plausible-looking diagram can render with overlapping or off-canvas
    vertices — zero console errors, passes structural XML validation, still broken.
    `lint.sh` gains a cheap stdlib AABB (axis-aligned bounding box) overlap check across
    each diagram's vertex geometries, and a bounds check that no vertex's
    `x+width`/`y+height` exceeds the graph's declared canvas size.
  - The shipped F-011 exemplar (`content.md`, Task 7) and component gallery
    (`components.md`, Task 6) are rewritten as part of this migration, not deferred —
    leaving them on Mermaid while `SKILL.md` claims draw.io reintroduces the exact
    "docs vs. reality" drift F-011 existed to eliminate.

## Problem

Diagrams rendered by ps-commu-explain (Mermaid SVG, static) cannot be zoomed or
panned — a dense diagram is hard to read on-page. Mermaid's shape vocabulary is also
generic (boxes, arrows) rather than the standard, recognizable shapes a reader expects
for network/cloud/UML/org-chart style diagrams. User feedback, verbatim: "seeing that
ps-commu give diagram but cannot be zoom / scale any idea for improve? can we use
draw.io component so we can have standard shape and not reinvent the wheel."

## Why now

F-011 (shipped 2026-09-24) just rebuilt ps-commu-explain's authoring chain around a
hard rule: every gate is enforced by a script, never prose, and the starter template
must be a real, fact-checked exemplar. Doing this diagram-engine swap now — while the
chain, its test suite, and its regression-test method are fresh and well understood —
is cheaper than doing it later against a chain that has drifted further from this
context. It also directly answers standing user feedback rather than leaving it open.

## Sketch

**Sequencing (Fable review): add draw.io first, delete Mermaid last.** Task 0 of the
implementation plan is a spike, not a feature: port the exemplar's existing 7-line
Mermaid flowchart to hand-authored mxGraph XML, render it, and inspect the result. This
is the go/no-go gate for the no-auto-layout risk above — if hand-placed geometry proves
unworkable even for this simple case, that's found in an afternoon, not after `lint.sh`
and 38 test functions have already been rewritten. Only after Task 0 passes does the
plan proceed to ripping out Mermaid.

**Authoring skeleton**: because two structural cells (`id="0"`, `id="1" parent="0"`)
are easy to omit and their absence isn't obvious from a broken render, `components.md`/
`SKILL.md` ship a copy-and-fill skeleton: the two mandatory root cells pre-filled, a
fixed left-to-right grid recipe (`x = 40 + 200*i`, consistent row height) so authors
don't have to invent coordinates from scratch, and `role=` style tokens (not hex) in
the example. This is the same "author copies the template, fills in content" model
`00-brief.md`/`01-facts.md`/`02-storyboard.md` already use.

**Rendering** (`cherry-setup.js`, `index.html`): swap the Mermaid CDN script for
`https://viewer.diagrams.net/js/viewer-static.min.js`, **pinned to a specific tagged
version** (not `@latest`/unversioned — the render-gate's DOM-shape assert below depends
on the viewer's output structure staying stable; the `html` tier already vendors a
pinned Mermaid copy for the same reason). Replace `frameAndRunMermaid()` with an
equivalent that detects ` ```drawio ` fences (mirroring today's Mermaid-fence
detection), substitutes `role=` style tokens for real theme hex (see color-integration
above), wraps each in a `data-mxgraph`-configured div, and triggers the viewer's render
pass after Cherry-Markdown inserts the fence into the DOM (today's `mermaid.run()` call
point is the direct analog).

**Validation** (`scripts/lint.sh`, 640 lines total): lines 1-192 (frontmatter/citation
checks for `00-brief.md`/`01-facts.md`/`02-storyboard.md`, including `F<n>` citation
validation) are NOT Mermaid-specific and must survive untouched. Lines ~193-640 are the
Mermaid-grammar parser (`parse_flowchart()` and friends — the product of 4 fix rounds
hardening it during F-011); this is the part to replace. The implementation plan must
name the exact preserved line range/functions explicitly so no implementer treats the
whole file as disposable. Replace the Mermaid-specific portion with an
`xml.etree.ElementTree`-based validator: structural checks informed by
`mxfile.xsd` (root cell + default layer present, `vertex="1"` XOR `edge="1"`, unique
cell ids, valid parent references), plus the same domain rules translated from Mermaid
(a node-count cap per diagram, every edge cell has a non-empty label) **plus two new
rules the XML format itself requires that Mermaid never needed**: an AABB overlap +
canvas-bounds check on vertex geometry (since layout is hand-authored, not automatic),
and a label-escaping check rejecting any `value` with an unescaped `<`/`&` (the
`html=1` rendering mode silently eats malformed inline HTML — directly relevant given
this skill's `F<n>` citation convention). Fail-closed on anything unparseable or
unrecognized — never a silent pass, per the lesson Mermaid's lint.sh learned the hard
way.

**Render gate** (`scripts/verify.sh`): the static viewer's failure mode is WORSE than
Mermaid's — malformed XML inside otherwise-valid `data-mxgraph` JSON renders an EMPTY
graph with zero console errors (mxUtils.parseXml swallows the parse error into a
`parsererror` DOM node the viewer doesn't surface), and a CDN miss for the viewer
script leaves empty, silent divs. "Zero console errors" alone is exactly as insufficient
a gate here as F-011's own spec said it was for the OLD Mermaid pipeline. Assert 1
changes from "rendered Mermaid `<svg>` count == fenced ` ```mermaid ` count" to the
draw.io equivalent, but must explicitly FAIL (not silently pass) on an empty/failed
render — the first implementation task must load a served page with `--dump-dom`
(verify.sh's existing technique) and inspect what the static viewer actually leaves in
the DOM for both a good and a deliberately-broken diagram (most likely a nested `<svg>`
inside the `.mxgraph` div, mirroring Mermaid's own `<svg aria-roledescription>` pattern,
but confirm empirically rather than assume) before writing the new assert. Interactivity
(pan/zoom) is NOT deferred to a permanent SKIP the way Mermaid's click-to-jump assert
eventually was — commit now to a static proxy check analogous to Fix-round-1's
`scroll-behavior` assert: e.g., assert the viewer-injected toolbar element is present in
the DOM (confirms `"toolbar":"zoom"` actually took effect) and FAIL (not SKIP) if the
`GraphViewer` global is absent after the script loads.

**Content migration**: `content.md` and `components.md` each contain exactly one
Mermaid fence (confirmed by grep) — trivial in size, not a large migration surface.
`SKILL.md`'s mechanism-diagram rules (today: "LR, ≤7 nodes, every edge labeled, real
identifiers") translated to the XML format's equivalent constraints.

**Test migration**: `lifecycle_test.sh` is 1159 lines; ~38 of its 59 `test_` functions
(lines 243-1063) are Mermaid-grammar regression tests from the 4-fix-round hardening
saga. This IS the largest line-count item in the implementation plan — budget
accordingly, and budget 1-2 fix-loop rounds for the new XML validator even though it's
informed by an official schema (realistic, not pessimistic, given Mermaid's own
hardening history).

**Out of scope for this idea:** the full interactive draw.io editor (readers editing
diagrams in-page); any diagram type Mermaid never supported either (this is a rendering
engine swap, not a scope expansion).

## Acceptance criteria

- [ ] `scripts/lint.sh` validates ` ```drawio ` fenced mxGraph XML in `content.md`:
      rejects malformed/unparseable XML, rejects a diagram over the node-count cap,
      rejects any edge with no label, rejects overlapping or off-canvas vertex
      geometry, rejects a label with unescaped `<`/`&`, and rejects a raw
      `fillColor=#`/`strokeColor=#` hex literal instead of a `role=` token — all as
      visible defects, never a silent pass.
- [ ] Task 0 (the auto-layout spike: port the exemplar's Mermaid flowchart to
      hand-authored mxGraph XML, render, inspect) passes before any other task starts —
      this is the go/no-go gate for the whole migration's viability.
- [ ] A served infographic-tier page renders every ` ```drawio ` fence as an
      interactive draw.io diagram (`data-mxgraph` config includes an explicit
      `"toolbar":"zoom"`/nav key — not assumed automatic): mouse-wheel or pinch zoom
      works, click-drag pans, and the diagram uses the F-011 color rule's
      `--accent`/`--pitfall`/`--check` hues via renderer-side `role=` token
      substitution (not draw.io's default palette, not hardcoded hex in the XML).
      Interactivity is verified by a static proxy assert in `verify.sh` (the injected
      toolbar element and `GraphViewer` global are present), not by prose or a
      permanent SKIP.
- [ ] `html` and `react` tier Mermaid integrations are untouched — this migration does
      not touch `assets/template-html/mermaid.min.js` or `assets/template-react`'s
      Mermaid wiring/docs.
- [ ] `scripts/verify.sh` has a render-gate assert equivalent to the retired Mermaid
      svg-count check, that assert FAILs (not passes) against a deliberately malformed
      `drawio` fixture whose XML renders an empty graph with zero console errors (the
      static viewer's documented failure mode), and zero page-origin console errors on
      a page with valid `drawio` diagrams.
- [ ] `bash skills/ps-commu-explain/tests/lifecycle_test.sh` is green, migrated off
      every Mermaid-specific fixture/assertion.
- [ ] The shipped Task-7 exemplar (`content.md`) and Task-6 gallery (`components.md`)
      contain zero remaining Mermaid fences or Mermaid-specific prose; both re-pass
      the existing fact-citation and reader-gate checks F-011 established.
- [ ] `SKILL.md`'s mechanism-diagram rules and any other Mermaid-specific text are
      updated to describe the draw.io chain accurately (same fact-accuracy bar F-011
      held itself to — no claim about the new gate that the code doesn't actually do).
- [ ] The 3-real-project regression-test method F-011 used (independent subagents
      follow the shipped `SKILL.md` unaided on real, unfamiliar codebases) is re-run
      against the new chain and passes.

## Decisions (batch-grill, 2026-09-24)

- Replace vs. coexist with Mermaid → **replace** — user's explicit call; recommended
  default was coexist (lower risk), overridden after the tradeoff was stated.
- Diagram authoring format → **plain uncompressed mxGraph XML in fences**, mirroring
  Mermaid's authoring model — official draw.io AI-authoring guidance confirms this is
  the intended way for an LLM to write draw.io diagrams as text.
- Rendering integration → **static embed** (`viewer-static.min.js` + `data-mxgraph`),
  not the interactive editor iframe — matches the "render from text, don't edit
  in-page" model this skill already uses.
- XML validation approach → **hand-written stdlib validator informed by `mxfile.xsd`**,
  not an external schema-validation dependency (default, not asked) — keeps
  `lint.sh`/`verify.sh` dependency-free, consistent with F-011's whole toolchain.
- Script hosting → **CDN** (`viewer.diagrams.net`), not vendored/self-hosted (default,
  not asked) — matches the existing Mermaid/Cherry-Markdown/Lucide CDN pattern exactly.
- Exemplar/gallery migration timing → **in scope now**, not deferred (default, not
  asked) — leaving them on Mermaid while docs claim draw.io reintroduces the exact
  "docs vs. reality" drift F-011 existed to eliminate.
- Tier scope → **infographic tier only** (default, not asked) — `html`/`react` tiers
  each vendor an independent Mermaid integration; F-011's own spec already treats them
  as non-goals, so this idea keeps that boundary rather than tripling its surface area.

## Appendix — audit trail

- 2026-09-24 self-grill-audit: verdict safe-with-fixes. Corrected: scoped the migration
  explicitly to the infographic tier (spec originally implied all three tiers, missing
  that `html`/`react` each vendor independent Mermaid integrations with their own node
  caps); corrected the pan/zoom/toolbar claim from "automatic" to "requires an explicit
  `data-mxgraph` config key"; corrected `lint.sh`'s line accounting (640 total, only
  ~193-640 is Mermaid-specific and replaceable, lines 1-192 are non-Mermaid
  citation/frontmatter checks that must survive); corrected the unreproducible "~628"
  line count; corrected the content-migration framing from "large surface" to "1 fence
  each, trivial" while confirming the test-migration surface genuinely is large (~38 of
  59 `lifecycle_test.sh` functions). draw.io's embed API and AI-authoring-XML claims
  were independently re-verified against the live docs and hold. Open: none — all
  CRITICAL/HIGH findings fixed inline above.
- 2026-09-24 architectural review (Fable, at user's request — "check with thinker"):
  verdict proceed with named changes, all applied. Surfaced the real viability risk the
  fact-audit couldn't catch (no auto-layout — mxGraph geometry is hand-authored, unlike
  Mermaid's automatic dagre layout) and added: Task-0 go/no-go spike, add-first/
  delete-last sequencing, an authoring skeleton, overlap/bounds and label-escaping lint
  rules, a corrected (not-deferred) color-integration design (role tokens + renderer-side
  substitution, since draw.io's `%name%` vars substitute label text, not style colors —
  the original spec's "defer to implementation" framing for this was wrong), a
  fail-on-empty-render requirement for the render gate, and a committed (not-SKIP)
  interactivity assert. Open: none.
