# Visual components — ps-commu templates

> **Scope: `html` and `react` tiers ONLY.** These two tiers were explicitly out of scope
> for the F-011 infographic redesign and still use the dark visual language, `metric-grid`
> / `metric-tile`, `callout warn`/`danger`/`success`/`idea`, and `data-cat` classes
> documented below — confirmed current in `assets/template-html/index.html` and
> `assets/template-react/src/styles.css`. **None of this applies to the default
> infographic tier.** Its v3 component set is a different, cream visual language with only
> three callout kinds (`note`/`pitfall`/`check` — anything else silently renders as
> `note`), no `metric-grid` (lint-forbidden), and no `data-cat`/six-hue category system.
> For the infographic tier, use `assets/template-infographic/components.md` instead.

Catalog for phase 4 (outline treatment tags) and phase 5 (build). Both templates share
the same dark visual language. Tag each outline section with one PRIMARY treatment.

## Treatment tags → markup

| Tag | When | HTML tier markup | React tier |
|-----|------|------------------|------------|
| `mermaid-flow` | processes, architectures, sequences, state | `<div class="mermaid">flowchart LR ...</div>` | same div; call `mermaid.run()` after mount |
| `metric-tiles` | 2–6 headline numbers | `<div class="metric-grid"><div class="metric-tile"><strong>42ms</strong>label</div></div>` (`.alarm` variant) | `<MetricGrid items={[...]}/>` pattern in App.tsx |
| `callout` | warnings, gotchas, key ideas | `<div class="callout warn/danger/success/idea">` (pick one class) | same classes |
| `animated-sequence` | ordered steps that build up | consecutive `.reveal` blocks (IntersectionObserver staggers them) | `.reveal` + same observer in App.tsx |
| `schematic` | box-drawing / ASCII diagrams | `<div class="schematic">` (pre-formatted) | same |
| `code-walk` | annotated code | `<pre><code>` + `<mark>` highlights + a callout per insight | same |
| `two-up` | side-by-side comparison | `<div class="row two">` | same |
| `interactive-slider`, `step-sim`, `live-filter` | **React tier only** — requires state | n/a | typed `useState` component; see `SliderDemo` in template App.tsx |
| `scrolly` | a flowchart (≥5 nodes) with a narrative | `<div class="scrolly"><div class="scrolly-sticky">[mermaid]</div><div class="scrolly-steps"><div class="step" data-highlight="NodeA,NodeB">…</div>…</div></div>` — steps highlight named nodes as they scroll | same classes; wire the step IntersectionObserver like Section |
| `depth-toggle` | study-mode detail kept out of the skim path | `<details class="deeper"><summary>go deeper — …</summary><div>…</div></details>` | same |
| `tldr-strip` | 3–5 takeaway chips at the top, one per key area | `<div class="tldr"><span class="tldr-chip" data-cat="…">🔄 …</span></div>` | same |
| `source-receipts` | per-section fact provenance | `<footer class="receipts">facts: file.sh:NN · 01-factsheet.md #N</footer>` | same |

## Semantic categories (section `data-cat`)

Tag every `<section>` (React: `<Section cat="…">`) with ONE category — it drives the accent color,
top border, heading chip, and nav link color automatically:

| data-cat | Color | Use for | Pairs with emoji |
|---|---|---|---|
| `lifecycle` | cyan | flows, sequences, state machines | 🔄 |
| `safety` | green | guards, invariants, security | 🛡️ |
| `perf` | amber | speed, complexity, benchmarks | ⚡ |
| `cleanup` | violet | GC, teardown, retention | 🧹 |
| `concept` | blue | theory, definitions, mental models | 📐 |
| `demo` | magenta | interactive widgets, simulations | 🧪 |

## Tier rule (restated)
≥1 section tagged `interactive-slider` / `step-sim` / `live-filter` → React tier.
Otherwise HTML tier. "It would look impressive" is NOT a reason — animation and
diagrams are fully available in the HTML tier.

## Diagram rules (mermaid)
- The template themes mermaid into the design system (base theme, Futura, spaced layout) and node
  borders inherit the section's category color automatically — no per-diagram styling needed.
- Put one emoji at the start of each node label ("🚀 serve.sh"); group related nodes with a
  `subgraph name ["🧹 label"]`.
- Pick the type for the job: `flowchart` (flows/architecture), `sequenceDiagram` (protocols,
  request/response), `stateDiagram-v2` (lifecycles, modes), `timeline` (evolution/history),
  `quadrantChart` (trade-off positioning).
- ≤ ~15 nodes; short edge labels; prefer `LR` unless depth > breadth.

## Authoring rules
- Every section maps 1:1 to an outline entry; every fact traces to `01-factsheet.md`.
- **TL;DR strip is mandatory**: render `02-key-areas.md` as chips (one per key area, category-colored).
- **Receipts are mandatory**: every section footer cites its fact-sheet entries / file:line refs.
- Use `depth-toggle` whenever a section tempts you past ~120 words — skim path stays clean.
- `scrolly` `data-highlight` names must match the flowchart node ids (the part before `[` in `I["…"]`).
- **Emoji for scan speed**: start every section `<h2>` with one emoji (🔄 lifecycle, 🛡️ safety,
  ⚡ performance, 🧹 cleanup, 🧪 demo, 📐 theory…) — the nav auto-build carries it into the nav.
  Callouts get their emoji automatically via CSS (ℹ️/⚠️/🚨/✅/💡). Metric tiles: put an emoji in
  the label line when it sharpens meaning (e.g. `🔒 127.0.0.1`). Max one emoji per element — markers,
  not decoration.
- Mermaid: keep diagrams ≤ ~15 nodes; split rather than cram.
- Use `<mark>` for the 1–3 terms per section the user must retain.
- Respect `prefers-reduced-motion` (already handled in template CSS).
- Nav builds itself from `section[id] > h2` — give every section an `id`.
