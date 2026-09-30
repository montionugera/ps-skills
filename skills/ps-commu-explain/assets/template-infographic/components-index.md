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
