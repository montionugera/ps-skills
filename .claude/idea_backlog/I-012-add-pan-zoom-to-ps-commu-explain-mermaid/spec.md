---
title: "Replace Mermaid with draw.io in ps-commu-explain"
id: I-012
status: idea
---

# Replace Mermaid with draw.io in ps-commu-explain

## Orientation

- **What we're building:** ps-commu-explain (the Claude Code skill that renders rich
  explainer pages, redesigned in F-011) currently diagrams with Mermaid — static SVG,
  no pan/zoom, generic shapes. This idea replaces Mermaid entirely with draw.io
  (diagrams.net): a richer shape library (standard flowchart/network/UML/cloud icons)
  and built-in pan/zoom/toolbar on every diagram, for free.
- **Decisions made (batch-grill, 2026-09-24):**
  - Full replacement, not coexistence with Mermaid — user's explicit call after the
    coexistence tradeoff (lower risk, zero rewrite of the just-hardened Mermaid
    validator) was raised and considered.
  - Diagrams render via draw.io's official **static embed** (`viewer-static.min.js` +
    a `data-mxgraph` div), confirmed via drawio.com's own docs to ship pan/zoom/toolbar
    out of the box — not the full interactive editor (`embed.diagrams.net` iframe +
    postMessage), which is a heavier, edit-oriented integration this use case doesn't need.
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
- **What's assumed (state, don't ask — R2, reversible at implementation time):**
  - Theme color integration (the F-011 color rule: `--accent`/`--pitfall`/`--check`)
    uses draw.io's `<mxfile vars="...">` + `%variableName%` substitution if that
    mechanism works in static-embed mode; falls back to hardcoded hex with one
    documented palette block if it doesn't. Confirm which during implementation —
    this is an execution detail, not a design fork.
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

**Rendering** (`cherry-setup.js`, `index.html`): swap the Mermaid CDN script for
`https://viewer.diagrams.net/js/viewer-static.min.js` (same CDN-load pattern already
used for Mermaid/Cherry-Markdown/Lucide — no new deploy complexity). Replace
`frameAndRunMermaid()` with an equivalent that detects ` ```drawio ` fences (mirroring
today's Mermaid-fence detection), wraps each in a `data-mxgraph`-configured div, and
triggers the viewer's render pass after Cherry-Markdown inserts the fence into the DOM
(today's `mermaid.run()` call point is the direct analog).

**Validation** (`scripts/lint.sh`): replace the ~628-line Mermaid-grammar parser
(`parse_flowchart()` and friends — the product of 4 fix rounds hardening it during
F-011) with an `xml.etree.ElementTree`-based validator: structural checks informed by
`mxfile.xsd` (root cell + default layer present, `vertex="1"` XOR `edge="1"`, unique
cell ids, valid parent references), plus the same domain rules translated from Mermaid
(a node-count cap per diagram, every edge cell has a non-empty label). Fail-closed on
anything unparseable or unrecognized — never a silent pass, per the lesson Mermaid's
lint.sh learned the hard way.

**Render gate** (`scripts/verify.sh`): assert 1 changes from "rendered Mermaid `<svg>`
count == fenced ` ```mermaid ` count" to the draw.io equivalent — the first
implementation task must load a served page with `--dump-dom` (verify.sh's existing
technique) and inspect what the static viewer actually leaves in the DOM per diagram
(most likely a nested `<svg>` inside the `.mxgraph` div, mirroring Mermaid's own
`<svg aria-roledescription>` pattern, but confirm empirically rather than assume)
before writing the new assert against it.

**Content migration**: every Mermaid fence in the shipped exemplar (`content.md`) and
component gallery (`components.md`) rewritten as an equivalent ` ```drawio ` diagram.
`SKILL.md`'s mechanism-diagram rules (today: "LR, ≤7 nodes, every edge labeled, real
identifiers") translated to the XML format's equivalent constraints.

**Test migration**: `lifecycle_test.sh`'s Mermaid-fixture-based tests (a large surface,
given the 4 fix rounds' worth of regression coverage already built for Mermaid)
rewritten against draw.io fixtures. This is likely the single largest line-count item
in the implementation plan — budget accordingly, and budget 1-2 fix-loop rounds for the
new XML validator even though it's informed by an official schema (realistic, not
pessimistic, given Mermaid's own hardening history).

**Out of scope for this idea:** the full interactive draw.io editor (readers editing
diagrams in-page); any diagram type Mermaid never supported either (this is a rendering
engine swap, not a scope expansion).

## Acceptance criteria

- [ ] `scripts/lint.sh` validates ` ```drawio ` fenced mxGraph XML in `content.md`:
      rejects malformed/unparseable XML, rejects a diagram over the node-count cap,
      rejects any edge with no label — all as visible defects, never a silent pass.
- [ ] A served infographic-tier page renders every ` ```drawio ` fence as an
      interactive draw.io diagram: mouse-wheel or pinch zoom works, click-drag pans,
      and the diagram uses the F-011 color rule's `--accent`/`--pitfall`/`--check`
      hues (not draw.io's default palette).
- [ ] `scripts/verify.sh` has a render-gate assert equivalent to the retired Mermaid
      svg-count check, and zero page-origin console errors on a page with `drawio`
      diagrams.
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
