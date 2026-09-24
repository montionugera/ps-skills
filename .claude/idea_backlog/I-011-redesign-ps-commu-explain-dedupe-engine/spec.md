---
title: "Redesign ps-commu-explain: dedupe, engine fixes, evidence-first chain"
id: I-011
status: approved
approved_by: user, 2026-09-22 (chose "Execute Phases 0–2 now" on the proposal canvas)
canvas: https://claude.ai/artifact/7eNuf7H99J6k3gFJHnV2TH
---

# Redesign ps-commu-explain: dedupe, engine fixes, evidence-first chain

## Problem

`ps-commu-explain` produces pages that look explained but do not explain, and the chain
around the page fails before and after it. Evidence gathered 2026-09-22:

- **The skill never fires.** `explainer-kit` (`~/.claude/skills/explainer-kit`, Jul 2026) and
  `ps-commu-explain` shared one trigger description and byte-identical infographic assets
  (`theme.css`, `components.md`, `content.md`, `cherry-setup.js`, `explainer.css`, shell).
  Transcripts (`~/.claude/projects/*/*.jsonl`, Aug–Sep 2026) show 0 invocations of
  `ps-commu-explain`; all 4 real sessions (2026-09-12 ×2, 2026-09-18 ×2) went through
  `explainer-kit`. The fact-sheet and verify gates have therefore never run.
- **No session ended well.** 0 of 4 wrote a fact sheet. 2 of 4 died at the context limit
  during verification (169k, 232k tokens). The only voiced complaint, "I cant see usecase /
  flow diagram", was a page under `/tmp` that no longer existed by the next session.
- **Verify checks the wrong thing.** The gate is "zero console errors". Pages passed it with a
  raw `data-nav-sub` attribute leaking into body text and with broken Mermaid fences.
- **The page markets instead of teaching.** Chrome audit of the default tier (template
  scaffolded 2026-09-22): dead sidebar click-to-jump (`cherry-setup.js:305-313`); palette
  collisions, `--danger`=`--primary`=coral, `--warning`=`--action`=amber, `--idea`=`--secondary`
  =violet (`theme.css:74-89`); sections and steps colored in list order; stat tiles with
  invented numbers ("5 files · 0 build steps · 30s") and percentage meters ("Style drift 0%");
  gallery flagship diagram is three nouns with no edge labels; content column left-shoved
  (`--maxw` without centering); 11px coral kickers on cream ≈3.2:1 contrast; two escaping bugs.
- **Design churn.** The 2026-07-16 spec/plan for a React declarative renderer has zero tasks
  checked; the September infographic tier was copied from explainer-kit instead, unvalidated.

## Goals

1. One skill owns "explain X" asks and is the one that actually fires.
2. Every gate in the chain is enforced by a script or an independent subagent, never by prose
   alone (global rule 11).
3. A page is judged by whether an independent reader can answer the brief's questions from
   it, with citations, not by console cleanliness.
4. The starter template is a real worked explainer, because agents copy the exemplar.
5. The main thread stays a thin orchestrator; screenshots and authoring cycles live in
   subagents (global rule 12).

## Non-goals (this feature)

- Phase 3 (persist outside `/tmp`) and Phase 4 (two-week measurement): separate ideas.
- The html and react tiers: unchanged except for shared script fixes.
- Replacing cherry-markdown or Mermaid.
- Offline vendoring of CDN deps.

## Design

### Phase 0 — one trigger
- `~/.claude/skills/explainer-kit` becomes a stub whose description says RETIRED and whose
  body says "invoke ps-commu-explain". Engine files archived to
  `~/.claude/skills-archive/explainer-kit-2026-09-22/`. **Done 2026-09-22, commit 5b14a9b in
  `~/.claude/skills`.**
- `ps-commu-explain`'s description gains literal anchors that appear in real asks: "explain",
  "explainer", "diagram", "visualize", "walk me through", "how does X work", "/ps-commu-explain".

### Phase 1 — fix the engine (`assets/template-infographic/`)
- Nav click-to-jump scrolls the viewport (cherry-setup.js).
- Color rule: neutral cream ramp + one structural accent; `pitfall` and `check` each get one
  reserved hue used nowhere else; ordinal sequences use one hue with a value ramp; section
  order is never colored. Remove the six-hue `cat-*` rotation.
- Content column centered inside the post-sidebar area.
- Kicker text ≥ 4.5:1 contrast on the paper surface.
- Fix the stray empty code chip and the autolinked hyphenated word in components.md.
- Gallery's first diagram becomes the labeled sequence diagram.
- New `scripts/verify.sh <slug>`: loads the served page in headless Chrome, asserts
  Mermaid SVG count == fence count, no `~~CODE` placeholder, no raw `data-nav` text in body,
  nav click changes `scrollY`, zero page-origin console errors. Exit 0/1 with a defect list.

### Phase 2 — rewrite the chain (SKILL.md, components.md, content.md, scripts)
Stages, each producing a file the next reads:

| # | Stage | Output | Enforced by |
|---|---|---|---|
| 1 | Brief | `00-brief.md` (≤10 lines): reader, 3 questions the reader must answer afterwards, the one mechanism, 4–7 section budget | `init.sh` refuses to scaffold `app/` without it |
| 2 | Facts | `01-facts.md`: `F<n> \| statement \| source (file:line or "user said")`, gathered by a subagent | `serve.sh` refuses if any `F<n>` cited in content.md is missing from the sheet |
| 3 | Storyboard | `02-storyboard.md` replaces key-areas + outline: one row per section = claim, fact ids, visual type, brief question answered | `lint.sh` refuses if any brief question is uncovered |
| 4 | Author | `app/content.md` with component set v3 | `lint.sh` rejects removed components (stat-grid, meter, cat-* rotation) and Mermaid edges without labels |
| 5 | Verify | render gate (`verify.sh`) then reader gate (subagent sees only page text, answers the 3 questions with citations) | both pass or an honest defect list; ≤5 cycles |
| 6 | Handoff | URL, the 3 questions + reader answers, re-serve command | prose |

Component set v3: keep type system, cream substrate, section-head + nav, Mermaid, callouts
reduced to `note`/`pitfall`/`check`. Remove stat tiles, meters, slogan hero, pull-quote
callouts, benefits triptych, CTA, six-hue palette. Add reader-questions box, claim card
(claim + fact id + source + "check it"), mechanism-diagram rules (LR, ≤7 nodes, every edge
labeled, real identifiers), before/after with fact-sheet values, worked example,
"what goes wrong without it" panel, evidence-receipts footer generated from `01-facts.md`.

Starter `content.md` becomes a complete real explainer of the serve lifecycle (facts from
SKILL.md and `scripts/`), matching the proposal's mockup board.

## Verification plan

- Phase 1: `tests/lifecycle_test.sh` still green; `verify.sh` exit 0 on the template; an
  independent design-review subagent re-runs the Chrome audit and finds none of defects
  1, 2, 7, 8, 9.
- Phase 2: the three regression asks rebuilt with the new chain, each in a subagent —
  (a) "what is this project? use a diagram" on `learn-with-ai-agent`, (b) "render the Go
  migration plan" on `repos/quant`, (c) "explain the EPIC layer workflow" on `tools` — and for
  each an independent reader subagent answers the brief's 3 questions with citations.
- Each phase ends with the standing quality gate: verify → independent review → refactor →
  re-verify, and `README.md` updated.

## Decisions

- Explainers stay untracked; never committed (like render-spec HTML).
- Phases 3–4 deferred to their own ideas so this feature ships on evidence, not scope.
