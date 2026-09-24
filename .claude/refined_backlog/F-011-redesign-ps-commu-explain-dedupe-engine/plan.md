---
title: "F-011 plan: redesign ps-commu-explain (Phases 1–2)"
id: F-011
spec: docs/superpowers/specs/2026-09-22-ps-commu-explain-redesign-design.md
status: in_progress
---

# F-011 — Redesign ps-commu-explain: engine fixes + evidence-first chain

Goal (verbatim): Execute Phases 0–2 of the ps-commu-explain redesign: dedupe the two skills,
fix the rendering engine, rewrite SKILL.md and the component set in ~/ps-skills, each phase
gated by verify + independent review, regression-run on the three past asks.

Phase 0 is done outside this repo (explainer-kit stub, `~/.claude/skills` commit 5b14a9b);
only the description-anchor half lands here (Task 8).

Worktree: `/Users/pasitnusso/ps-skills/.claude/worktrees/F-011-redesign-ps-commu-explain-dedupe-engine`
Skill dir (all paths below relative to it): `skills/ps-commu-explain/`
Test command (must stay green after every task): `bash skills/ps-commu-explain/tests/lifecycle_test.sh`

Execution: subagent-driven. One fresh subagent per task; each returns ≤15 lines (status,
files, verification output). Every phase ends: verify → independent review (code-reviewer +
a design-review pass for visual tasks) → refactor → re-verify → README.

## Phase 1 — fix the engine (`assets/template-infographic/`)

### Task 1 — navigation, centering, contrast, escaping
- [ ] `cherry-setup.js` ~305-313: sidebar click scrolls the viewport to the section (the
      `history.replaceState` lands; the scroll must too, and the active item must update).
- [ ] `explainer.css`: content column (`--maxw`) centered inside the post-sidebar area.
- [ ] `theme.css`: section kicker text and any ≤12px text on the paper surface ≥ 4.5:1.
- [ ] `components.md`: fix the stray empty inline-code chip ("Any fenced **[empty]** `mermaid`
      block") and the autolinked hyphenated word in the components table.
- [ ] Verify: serve the template (`scripts/init.sh t1 && scripts/serve.sh t1`), load in
      Chrome via a subagent, confirm click-to-jump moves `scrollY` and the active nav item
      changes; contrast measured, not eyeballed. `lifecycle_test.sh` green.

### Task 2 — the color rule
- [ ] `theme.css` 74-89: remove the collisions. Semantic tokens: `--accent` (one structural
      hue), `--pitfall` (one reserved hue), `--check` (one reserved hue), neutral cream ramp.
      Delete `--info/--success/--idea/--metric/--action` aliases.
- [ ] `explainer.css`: remove the six-hue `cat-*` rotation on section heads, steps, tiles;
      ordinal steps use one hue with a value ramp; callouts only `note | pitfall | check`.
- [ ] `cherry-setup.js`: Mermaid `themeVariables` follow the same rule (no per-node rainbow).
- [ ] `components.md`: callout docs reduced to the three kinds; the gallery's FIRST diagram is
      the labeled `sequenceDiagram` from content.md; the three-noun flowchart is removed.
- [ ] Verify: Chrome load via subagent, zero page-origin console errors, callouts render with
      distinct reserved hues, no `cat-*` rotation remains (`grep -c 'cat-' explainer.css`).

### Task 3 — `scripts/verify.sh` (render gate)
- [ ] New `scripts/verify.sh <slug> [--url URL]`: uses Google Chrome headless
      (`--headless=new --dump-dom` plus a small injected check, or `--remote-debugging` via
      a tiny Python client, whichever is simplest and dependency-free) against the served page.
      Asserts: Mermaid `<svg>` count == fenced ` ```mermaid ` count in `app/content.md`;
      no `~~CODE` placeholder in body text; no raw `data-nav` text in body; zero page-origin
      console errors; nav click changes `scrollY` (skip with a stated reason if headless cannot
      click). Exit 0, or exit 1 with a defect list, one per line.
- [ ] `tests/lifecycle_test.sh`: add `test_verify_passes_template`, `test_verify_fails_on_leak`
      (fixture content.md with a literal `~~CODE$` and a mermaid fence that cannot render).
      Headless Chrome missing → tests skip with a visible SKIP line, never silent pass.
- [ ] Verify: `lifecycle_test.sh` output shows the two new tests PASS.

### Phase 1 gate
- [ ] `lifecycle_test.sh` green; `verify.sh` exit 0 on the template.
- [ ] Independent review: `code-reviewer` on the Phase 1 diff + a design-review subagent that
      re-runs the Chrome audit and must find none of defects 1, 2, 7, 8, 9 from the spec.
- [ ] Refactor per findings, re-verify, commit (one commit per task, never `--amend`).

## Phase 2 — rewrite the chain

### Task 4 — workspace files and enforcement in scripts
- [ ] `init.sh <slug>`: in addition to `app/`, writes `00-brief.md`, `01-facts.md`,
      `02-storyboard.md` skeletons into the workspace (templates under
      `assets/workspace/`). Existing init tests keep passing.
- [ ] `serve.sh <slug>`: before serving, runs `scripts/lint.sh <slug>` and refuses (exit 1,
      printing the lint output) on failure. `--no-lint` exists only for `html`/`react` tiers'
      dev loops and prints a warning line.
- [ ] Verify: `lifecycle_test.sh` adds `test_serve_refuses_unlinted` and
      `test_init_writes_workspace_files`; both PASS.

### Task 5 — `scripts/lint.sh` (chain gate)
- [ ] Brief: no unfilled `(...)` placeholders; exactly three numbered reader questions; a
      section budget line 4–7.
- [ ] Facts: at least one row `F<n> | statement | source`; every source is `path:line`,
      `path` , a commit hash, or `user said`.
- [ ] Storyboard: every brief question id (Q1–Q3) appears in at least one row; every row
      cites ≥1 `F<n>` that exists.
- [ ] content.md: every `F<n>` mentioned exists in facts; forbidden classes absent
      (`stat-grid`, `stat-tile`, `meter`, `cat-`, `metric-grid`, `card-grid` benefits pattern);
      Mermaid `flowchart` edges carry a label (`-->|x|` or `-- x -->`), `sequenceDiagram`
      arrows carry text after the colon; flowchart node count ≤ 7 per diagram.
- [ ] Output: one defect per line with file and reason; exit 1 on any.
- [ ] Verify: `lifecycle_test.sh` adds `test_lint_passes_starter`, `test_lint_fails_unlabeled_edge`,
      `test_lint_fails_uncited_fact`; all PASS.

### Task 6 — component set v3 (`explainer.css`, `components.md`, `cherry-setup.js`)
- [ ] Add: `.reader-questions` (top-of-page box, 3 numbered questions), `.claim-card`
      (claim, `F<n>`, source, "check it" line), `.before-after` (two panels with real values),
      `.worked-example`, `.wrong-without` (pitfall hue), `.receipts` footer.
- [ ] Remove from CSS and docs: stat tiles/grids, meters, hero slogan block, pull-quote
      callouts, benefits card triptych, CTA, topic-chip row if purely decorative.
- [ ] Mechanism-diagram rules documented with one good and one bad example.
- [ ] `components.md` rewritten as the v3 gallery: syntax + rendered result per block, ordered
      by the chain (questions → mechanism → claims → wrong-without → before/after → receipts).
- [ ] Verify: Chrome load of `?doc=components.md` via subagent, zero console errors, every
      block renders; `lint.sh` passes on components.md's samples.

### Task 7 — the exemplar: starter `content.md` + example workspace files
- [ ] `assets/template-infographic/content.md` becomes a complete real explainer, "How a
      Markdown file becomes a verified local URL" (serve lifecycle), built only from facts in
      SKILL.md and `scripts/` with `F<n>` ids, matching the proposal's mockup board.
- [ ] `assets/workspace/example/` holds the matching filled `00-brief.md`, `01-facts.md`,
      `02-storyboard.md` so `init.sh --example <slug>` can scaffold a passing workspace.
- [ ] Verify: `init.sh --example ex && serve.sh ex` passes lint, `verify.sh ex` exit 0; a
      reader subagent that sees only the page text answers the three brief questions with
      `F<n>` citations.

### Task 8 — SKILL.md, description anchors, README
- [ ] `SKILL.md` rewritten around the six stages (brief, facts, storyboard, author, verify
      with render + reader gates, handoff), with: subagent budgets (facts gathering,
      authoring cycles, every screenshot in subagents returning ≤15 lines), the reader-gate
      prompt verbatim, ≤5 cycles then an honest defect list, tier rule unchanged, updated
      rationalizations table and red flags. Keep it under ~120 lines.
- [ ] Description gains literal anchors: explain, explainer, diagram, visualize,
      "walk me through", "how does X work", `/ps-commu-explain`; keeps "not for a 2-sentence
      answer / durable doc → render-spec".
- [ ] `README.md` (repo root) rows for ps-commu-explain reflect the chain, `lint.sh`,
      `verify.sh`, workspace files.
- [ ] Verify: `bin/` skill validator if present (`ls bin`), `lifecycle_test.sh` green.

### Phase 2 gate
- [ ] Regression on the three real asks, each in its own subagent using the worktree's
      scripts by absolute path: (a) "what is this project? use a diagram" on the
      `learn-with-ai-agent` project, (b) "render the Go migration plan" on `repos/quant`,
      (c) "explain the EPIC layer workflow" on `workspace/tools`. Each must pass `lint.sh`
      and `verify.sh`, and an independent reader subagent must answer the brief's three
      questions with citations. Report per ask: pass/fail + defects.
- [ ] Independent review: `code-reviewer` on the Phase 2 diff; `self-grill-audit` on the
      new SKILL.md.
- [ ] Refactor, re-verify, commit. Then `psrw ship` is the user's call (not in this plan).
