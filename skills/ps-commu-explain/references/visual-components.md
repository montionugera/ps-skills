# Visual components — ps-commu templates

All three tiers (`infographic`, `html`, `react`) share the **Cream Explainer** design token system from `assets/template-infographic/theme.css` (warm paper `--bg`, raised cards `--surface-raised`, one structural `--accent`, and two reserved semantic hues `--pitfall` and `--check`) plus self-contained local fonts (`assets/vendor/fonts.css`, Latin + Thai). Dark mode, gradient heading text, decorative blurs, side-stripe borders, `metric-grid` / `metric-tile`, and six-hue `cat-*` categories are retired across all tiers.

For the default `infographic` tier, use `assets/template-infographic/components-index.md` and `components.md`.

## Treatment tags → markup (`html` and `react` tiers)

| Tag | When | HTML tier markup | React tier |
|---|---|---|---|
| `mermaid-flow` | processes, architectures, sequences, state | `<div class="mermaid">flowchart LR ...</div>` (light Cream theme) | same div; call `mermaid.run()` after mount |
| `tabs` | switching between 2+ related views/modes | `<div class="tabs"><div class="tab-list"><button type="button" class="tab-btn" aria-pressed="true" data-tab="0">…</button>…</div><div class="tab-panel is-active" data-panel="0">…</div>…</div>` | stateful React tab buttons (`>= 44px`) |
| `accordion` | expandable FAQs or layered detail | `<div class="accordion"><div class="acc-item is-open"><button type="button" class="acc-btn" aria-expanded="true">…</button><div class="acc-panel">…</div></div>…</div>` | stateful React disclosure panels |
| `callout` | notes, pitfalls, verified checks | `<div class="callout note\|pitfall\|check"><span class="co-ico"><i data-lucide="…"></i></span><div class="co-body">…</div></div>` | same classes |
| `schematic` | box-drawing / ASCII trees | `<div class="schematic">` (pre-formatted, `overflow-x: auto`) | same |
| `code-walk` | annotated code | `<pre><code>` + `<mark>` highlights + a callout | same |
| `two-up` | side-by-side comparison | `<div class="row two">` | same |
| `interactive-slider`, `step-sim`, `live-filter` | **React tier only** — requires state | n/a | typed `useState` component (`InteractiveLab` in `App.tsx`) |
| `scrolly` | a flowchart (`>=5` nodes) with narrative | `<div class="scrolly"><div class="scrolly-sticky">[mermaid]</div><div class="scrolly-steps"><div class="step" data-highlight="NodeA,NodeB">…</div>…</div></div>` | same classes |
| `depth-toggle` | study-mode detail kept out of skim path | `<details class="deeper"><summary>…</summary><div>…</div></details>` | same |
| `tldr-strip` | 2–5 takeaway chips at the top | `<div class="tldr"><span class="tldr-chip"><i data-lucide="…"></i> …</span></div>` | same |
| `source-receipts` | per-section fact provenance | `<footer class="receipts">facts: 01-facts.md F1</footer>` | same |

## Tier rule (restated)
`>=1` section requiring stateful simulation (`interactive-slider` / `step-sim` / `live-filter`) → React tier (`--tier react`).
Bespoke hand-built layout or Mermaid scrollytelling → HTML tier (`--tier html`).
Default → Infographic tier (`init.sh <slug>`).

## Typography, Diagrams, Thai (`Lang: th`) & Mobile Rules
- Set `Lang: en` or `Lang: th` in `00-brief.md`; `skeleton.sh` and `serve.sh` sync `<html lang="…">` automatically.
- `theme.css` automatically enforces `line-height >= 1.75` (body) and `>= 1.38` (headings), `letter-spacing: 0`, and `text-transform: none` whenever `lang="th"`.
- Never use `word-break: break-all`; wrap long tokens safely via `overflow-wrap: break-word`. On `< 640px`, tables auto-stack into `data-label` cards (set `data-label` + `<div className="td-val">` on React `<td>` cells); on `>= 640px`, `table-layout: auto` keeps 5-column tables inside reading width without clipping.
- Author diagrams vertically (`flowchart TB`, portrait draw.io `pageWidth <= 440`, or compact SVG `viewBox <= 440px` wide) with node/edge `fontSize >= 15` (`mermaid.initialize` uses `fontSize: '18px'`) so labels stay crisp on `390px` phones and `1280px` desktops.
- Keep all body/table/panel prose `>= 16px` (`1rem`) and all interactive controls (`button`, `summary`, `nav a`, `.nav-toggle`) `>= 44×44px`.
