# ps-commu-explain Component System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace handwritten explainer pages with validated YAML/JSON artifacts rendered through reusable, accessible React components while preserving the secure lifecycle and historical explanation semantics.

**Architecture:** A portable JSON Schema and semantic validator feed an immutable normalized artifact into a server-rendered React registry. Stable primitives compose into educational patterns and presets; Mermaid, React Flow, Vega-Lite, and Shiki remain adapter boundaries. Server-rendered fallbacks preserve essential meaning, while hydration adds interaction.

**Tech Stack:** React 18, TypeScript, Vite, Vitest, Testing Library, Playwright, React Aria Components, Ajv, YAML, Mermaid, React Flow, Vega-Lite/Vega, Shiki, Bash lifecycle scripts.
---

## Execution Preconditions

- Invoke `using-git-worktrees` before Task 1.
- Create branch `feat/ps-commu-component-system` from commit `e06618c` in `/Users/pnusso/Workspace/.worktree/ps-commu-component-system`.
- Verify `/Users/pnusso/Workspace/.worktree` is ignored before creating the worktree.
- Do not modify or discard the dirty checkout at `/Users/pnusso/Workspace/ps-skills`.
- Use one implementation subagent per task and a fresh review subagent after each task. Only the active task owner may edit the worktree.
- Use zsh for terminal commands unless a test explicitly invokes Bash.

## File Map

- `SKILL.md` and `references/`: concise routing plus progressively disclosed lite, rich, and component-selection guidance.
- `assets/template-react/schema/` and `src/artifact/`: portable schema, types, loading, validation, and immutable normalization.
- `assets/template-react/src/`: renderer, primitives, compositions, adapters, presets, accessibility, and styles.
- `scripts/`, `tests/`, and `.github/workflows/ci.yml`: artifact build lifecycle, compatibility fixtures, and complete verification.

## Task 1: Create an Isolated, Reconciled Baseline

**Files:**
- Import into: `skills/ps-commu-explain/**`
- Test: `skills/ps-commu-explain/tests/content_contract_test.sh`
- Test: `skills/ps-commu-explain/tests/lifecycle_test.sh`

- [ ] **Step 1: Create the isolated worktree**

```zsh
git check-ignore -q /Users/pnusso/Workspace/.worktree
git worktree add /Users/pnusso/Workspace/.worktree/ps-commu-component-system -b feat/ps-commu-component-system e06618c
```

Expected: a clean worktree on `feat/ps-commu-component-system`.

- [ ] **Step 2: Prove the installed skill is the reconciliation source**

```zsh
cd /Users/pnusso/Workspace/.worktree/ps-commu-component-system
diff -qr /Users/pnusso/Workspace/ps-skills/skills/ps-commu-explain /Users/pnusso/.codex/skills/ps-commu-explain
```

Expected: installed-only `agents/`, `technical-explanation-contract.md`, and `content_contract_test.sh`; newer differing instruction files; repository-only generated `scripts/__pycache__`; identical current lifecycle scripts.

- [ ] **Step 3: Import the installed superset without generated cache**

```zsh
rsync -a --delete --exclude '__pycache__' /Users/pnusso/.codex/skills/ps-commu-explain/ skills/ps-commu-explain/
find skills/ps-commu-explain -type d -name __pycache__ -prune -exec rm -rf '{}' +
```

- [ ] **Step 4: Run the reconciled baseline tests**

```zsh
zsh skills/ps-commu-explain/tests/content_contract_test.sh
zsh skills/ps-commu-explain/tests/lifecycle_test.sh
```

Expected: contract regression fixtures pass and lifecycle reports `20 passed, 0 failed`.

- [ ] **Step 5: Commit only reconciled skill files**

```zsh
git diff --check
git add skills/ps-commu-explain
git commit -m "chore: reconcile installed ps-commu skill"
```

## Task 2: Add the Portable Artifact Contract Test-First

**Files:**
- Modify: `skills/ps-commu-explain/assets/template-react/package.json`
- Create: `skills/ps-commu-explain/assets/template-react/vitest.config.ts`
- Create: `skills/ps-commu-explain/assets/template-react/src/test/setup.ts`
- Create: `skills/ps-commu-explain/assets/template-react/schema/explanation.schema.json`
- Create: `skills/ps-commu-explain/assets/template-react/src/artifact/types.ts`
- Create: `skills/ps-commu-explain/assets/template-react/src/artifact/validateArtifact.ts`
- Test: `skills/ps-commu-explain/assets/template-react/src/artifact/validateArtifact.test.ts`

- [ ] **Step 1: Write the failing validator test**

```ts
import { describe, expect, it } from 'vitest'
import { validateArtifact } from './validateArtifact'

const artifact = {
  schemaVersion: 1,
  id: 'request-flow',
  preset: 'architecture',
  metadata: {
    title: 'Request flow', audience: 'implementer',
    status: 'live-code-verified',
    summary: 'A request crosses one verified boundary.',
    learningObjectives: ['Name the payload at the boundary.'],
  },
  sources: { request: { locator: 'Service.scala:42', confidence: 'verified' } },
  sections: [{
    id: 'overview', type: 'callout', title: 'Overview',
    body: 'The service validates the request.', sourceRefs: ['request'],
  }],
}

describe('validateArtifact', () => {
  it('accepts a sourced artifact', () => expect(validateArtifact(artifact)).toEqual(artifact))
  it('rejects unsafe HTML', () => expect(() => validateArtifact({
    ...artifact,
    sections: [{ ...artifact.sections[0], body: '<script>alert(1)</script>' }],
  })).toThrow(/sections\/0\/body.*unsafe HTML/i))
  it('rejects unresolved evidence', () => expect(() => validateArtifact({
    ...artifact,
    sections: [{ ...artifact.sections[0], sourceRefs: ['missing'] }],
  })).toThrow(/sections\/0\/sourceRefs\/0.*missing/i))
})
```

- [ ] **Step 2: Install the test and validation toolchain**

```zsh
cd skills/ps-commu-explain/assets/template-react
npm install ajv yaml react-aria-components
npm install -D @testing-library/jest-dom @testing-library/react @testing-library/user-event @vitest/coverage-v8 jsdom tsx vitest
```

Add scripts `test`, `test:coverage`, and `typecheck`. Configure Vitest for `jsdom`, `src/test/setup.ts`, and 80% line/function/branch/statement thresholds. The setup file imports `@testing-library/jest-dom/vitest`.

- [ ] **Step 3: Run the test to prove RED**

```zsh
npx vitest run src/artifact/validateArtifact.test.ts
```

Expected: FAIL because `validateArtifact` does not exist.

- [ ] **Step 4: Define the initial schema and types**

Require `schemaVersion`, `id`, `metadata`, `sources`, and `sections`; set `additionalProperties: false` at each object boundary. Define block types `callout`, `section`, `progress`, `data-table`, `code`, `diagram`, and `disclosure`. Use exact unions for audiences, evidence status, confidence, and the eight approved preset names.

- [ ] **Step 5: Implement minimal validation**

Compile the schema with Ajv `allErrors: true`. After schema success, reject `<script>`, `<iframe>`, `<object>`, `<embed>`, `<style>`, `<link>`, and `<meta>` in string fields, then resolve every `sourceRefs` entry against `artifact.sources`. Error messages must include the artifact path used by the test.

- [ ] **Step 6: Run tests and commit**

```zsh
npm test -- --run src/artifact/validateArtifact.test.ts
npm run typecheck
git add skills/ps-commu-explain/assets/template-react
git commit -m "feat: define ps-commu artifact contract"
```

## Task 3: Add Loading, Normalization, and Semantic Gates

**Files:**
- Create: `assets/template-react/src/artifact/loadArtifact.ts`
- Create: `assets/template-react/src/artifact/normalizeArtifact.ts`
- Modify: `assets/template-react/src/artifact/validateArtifact.ts`
- Test: `assets/template-react/src/artifact/loadArtifact.test.ts`
- Test: `assets/template-react/src/artifact/normalizeArtifact.test.ts`
- Test: `assets/template-react/src/artifact/semanticValidation.test.ts`

- [ ] **Step 1: Write failing tests**

Cover YAML and JSON loading, unsupported extensions, immutable output, stable default preset, exact-type versus semantic-pseudotype payloads, conditional-stage evidence gaps, and rejection of unlabeled material edges.

```ts
const input = structuredClone(validArtifact)
const snapshot = structuredClone(input)
const normalized = normalizeArtifact(input)
expect(input).toEqual(snapshot)
expect(normalized).not.toBe(input)
expect(normalized.sections).not.toBe(input.sections)
```

- [ ] **Step 2: Run tests to prove RED**

```zsh
npx vitest run src/artifact/loadArtifact.test.ts src/artifact/normalizeArtifact.test.ts src/artifact/semanticValidation.test.ts
```

- [ ] **Step 3: Implement loading and immutable normalization**

`loadArtifact` reads UTF-8, supports `.yaml`, `.yml`, and `.json`, parses through YAML or JSON, then calls `validateArtifact`. `normalizeArtifact` uses `structuredClone`, defaults a missing preset to `orientation`, derives text fallbacks only from existing visible content, and never invents facts or evidence.

- [ ] **Step 4: Add semantic gates**

For diagram/graph blocks, require every material edge to include `payload`, `payloadStatus`, and a source reference. Permit only `exact-type` and `semantic-pseudotype`. Require conditional stages to provide outcomes or an explicit evidence-gap string.

- [ ] **Step 5: Run tests and commit**

```zsh
npm test -- --run src/artifact
npm run typecheck
git add skills/ps-commu-explain/assets/template-react/src/artifact
git commit -m "feat: validate ps-commu artifact semantics"
```

## Task 4: Build the Server-Rendered Registry Shell

**Files:**
- Create: `assets/template-react/index.template.html`
- Modify: `assets/template-react/index.html` as the checked-in generated default
- Replace: `assets/template-react/src/App.tsx`
- Replace: `assets/template-react/src/main.tsx` with `src/client.tsx`
- Create: `assets/template-react/src/generated-artifact.ts`
- Create: `assets/template-react/src/renderer/ArtifactRenderer.tsx`
- Create: `assets/template-react/src/renderer/BlockRenderer.tsx`
- Create: `assets/template-react/src/renderer/registry.ts`
- Create: `assets/template-react/scripts/render.tsx`
- Test: `assets/template-react/tests/integration/static-render.test.tsx`

- [ ] **Step 1: Write the failing static-render test**

Render a minimal valid artifact with `renderToStaticMarkup`. Assert the title, learning objective, body, source locator, and skip link are present. Assert the result is not an empty root shell.

```tsx
const html = renderToStaticMarkup(<ArtifactRenderer artifact={artifact} />)
expect(html).toContain('Request flow')
expect(html).toContain('Name the payload')
expect(html).toContain('Service.scala:42')
expect(html).not.toBe('<div id="root"></div>')
```

- [ ] **Step 2: Run the test to prove RED**

```zsh
npx vitest run tests/integration/static-render.test.tsx
```

- [ ] **Step 3: Implement the renderer boundary**

`ArtifactRenderer` renders a skip link, header, objectives, generated navigation, `<main id="content">`, typed blocks, and source ledger. `BlockRenderer` uses an exhaustive discriminated switch; its default branch assigns the block to `never` so schema expansion cannot compile without a renderer.

- [ ] **Step 4: Add server generation and hydration**

`scripts/render.tsx` reads `ARTIFACT` or `artifact.yaml`, loads and normalizes it, writes `src/generated-artifact.ts`, renders `ArtifactRenderer` with `renderToString`, replaces `<!--APP_HTML-->` in the HTML shell, and writes `index.html` atomically. `client.tsx` hydrates the same artifact:

```tsx
hydrateRoot(document.getElementById('root')!, <ArtifactRenderer artifact={artifact} />)
```

- [ ] **Step 5: Make the checked-in default artifact buildable**

Check in matching minimal `artifact.yaml` and `generated-artifact.ts`. Configure scripts so `npm run build` runs render, typecheck, and Vite in that order.

- [ ] **Step 6: Verify static and production output, then commit**

```zsh
npm test -- --run tests/integration/static-render.test.tsx
npm run build
rg -q 'Request flow' dist/index.html
git add skills/ps-commu-explain/assets/template-react
git commit -m "feat: render declarative ps-commu artifacts"
```

Expected: built HTML contains essential content before JavaScript runs.

## Task 5: Implement Accessible Visual Primitives

**Files:**
- Create: `src/primitives/Section.tsx`
- Create: `src/primitives/Callout.tsx`
- Create: `src/primitives/Disclosure.tsx`
- Create: `src/primitives/Progress.tsx`
- Create: `src/primitives/DataTable.tsx`
- Create: `src/primitives/CodeBlock.tsx`
- Create: `src/primitives/EvidenceReceipt.tsx`
- Create: `src/primitives/DiagramFallback.tsx`
- Create: `src/primitives/Inspector.tsx`
- Create: `src/styles/tokens.css`
- Create: `src/styles/layout.css`
- Create: `src/styles/components.css`
- Create: `src/styles/motion.css`
- Modify: `src/renderer/registry.ts`
- Test: colocated `*.test.tsx` files

- [ ] **Step 1: Write failing primitive tests**

Test semantic role/name, visible source receipts, keyboard disclosure, determinate progress, table headers, code language, and persistent diagram fallback.

```tsx
render(<Progress label="Eligibility stage" value={2} max={4} />)
expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '2')
expect(screen.getByText('Step 2 of 4')).toBeVisible()
```

- [ ] **Step 2: Run tests to prove RED**

```zsh
npx vitest run src/primitives
```

- [ ] **Step 3: Implement primitives**

Use React Aria Components for non-trivial disclosure/overlay behavior and native semantic HTML for sections, progress, tables, code, and evidence. Required content must never exist only in a tooltip. Every diagram fallback renders an ordered stage/edge description.

- [ ] **Step 4: Implement the shared visual system**

Define tokens for canvas, panel, text, muted text, evidence, warning, danger, success, focus, spacing, measure, radius, and motion. Use a 78-character prose measure, visible `:focus-visible`, single-column layout below 760px, and reduced-motion overrides.

- [ ] **Step 5: Register and render every primitive block**

Create one fixture per initial schema type and a registry test that renders every key. No registry entry may return `null` for valid data.

- [ ] **Step 6: Run tests, coverage, build, and commit**

```zsh
npm test -- --run src/primitives src/renderer
npm run test:coverage
npm run build
git add skills/ps-commu-explain/assets/template-react/src
git commit -m "feat: add accessible explainer primitives"
```

## Task 6: Implement Core Educational Compositions

**Files:**
- Extend: `schema/explanation.schema.json`
- Extend: `src/artifact/types.ts`
- Create: `src/compositions/WorkedExampleStepper.tsx`
- Create: `src/compositions/ExecutionTrace.tsx`
- Create: `src/compositions/PredictThenRun.tsx`
- Create: `src/compositions/RetrievalCheck.tsx`
- Create: `src/compositions/CompareCases.tsx`
- Create: `src/compositions/ExplainWhy.tsx`
- Create: `src/compositions/FeedbackLoop.tsx`
- Create: `src/compositions/educationState.ts`
- Test: colocated tests

- [ ] **Step 1: Write failing state and interaction tests**

Define immutable transitions for `next`, `previous`, `jump`, `commit`, `reveal`, `retry`, and `reset`. Verify prediction cannot reveal before a committed response and retrieval feedback supports retry.

```ts
const initial = createLearningState(3)
const next = reduceLearningState(initial, { type: 'next' })
expect(next.step).toBe(1)
expect(initial.step).toBe(0)
expect(next).not.toBe(initial)
```

- [ ] **Step 2: Run tests to prove RED**

```zsh
npx vitest run src/compositions
```

- [ ] **Step 3: Extend the contract**

Add normalized `TraceStep`, `BeforeAfterState`, `AssessmentPrompt`, and `Feedback` definitions plus block variants for worked examples, execution traces, prediction, retrieval, comparison, and self-explanation. Require visible prompts, source references, authored answers/rubrics, retry behavior, and static solution summaries.

- [ ] **Step 4: Implement compositions from primitives**

Reuse progress, inspector, before/after, choice, and feedback primitives. Preserve the previous state beside the current state. Give every state-changing control an accessible name and restore focus after reveal/reset.

- [ ] **Step 5: Verify server fallbacks**

For each composition, server-render and assert the prompt, authored default state, complete step list or comparison, sources, and solution summary exist without hydration.

- [ ] **Step 6: Run tests and commit**

```zsh
npm test -- --run src/compositions
npm run typecheck
npm run build
git add skills/ps-commu-explain/assets/template-react
git commit -m "feat: add evidence-backed learning components"
```

## Task 7: Implement Exploratory and Staff-Level Compositions

**Files:**
- Extend: `schema/explanation.schema.json`
- Extend: `src/artifact/types.ts`
- Create: `src/compositions/ScenarioExplorer.tsx`
- Create: `src/compositions/GuidedSimulation.tsx`
- Create: `src/compositions/LinkedViews.tsx`
- Create: `src/compositions/ParameterSweep.tsx`
- Create: `src/compositions/ConceptMap.tsx`
- Create: `src/compositions/FailureDiagnosis.tsx`
- Create: `src/compositions/StageDossier.tsx`
- Create: `src/compositions/DataContractExplorer.tsx`
- Create: `src/compositions/selectionState.ts`
- Test: colocated tests

- [ ] **Step 1: Write failing exploration-state tests**

Test authored defaults, immutable parameter updates, scenario snapshots, reset, synchronized selection, guided-stage locking, explicit unlock criteria, and persistent alternatives. An unguided sandbox must not be the initial stage.

- [ ] **Step 2: Run tests to prove RED**

```zsh
npx vitest run src/compositions/ScenarioExplorer.test.tsx src/compositions/GuidedSimulation.test.tsx src/compositions/LinkedViews.test.tsx
```

- [ ] **Step 3: Extend the contract**

Add `Scenario`, `Parameter`, `Stage`, `Edge`, `Payload`, `Owner`, `CurrentTargetStatus`, and eight matching block variants. Require bounded parameters, units when applicable, reset values, stable IDs, sources, and fallbacks.

- [ ] **Step 4: Implement exploratory compositions**

Keep the authored baseline visible during comparisons. Synchronize selection through one immutable store and announce changes through an `aria-live="polite"` region.

- [ ] **Step 5: Implement staff-level compositions**

`FailureDiagnosis` renders symptom, evidence, cause, repair, and proof. `StageDossier` renders purpose, trigger, input, fields read, rule, output delta, branches, owner, side effects, dependencies, observability, evidence, and confidence. `DataContractExplorer` separates exact types from semantic pseudotypes and provides a mobile stacked representation.

- [ ] **Step 6: Verify and commit**

```zsh
npm test -- --run src/compositions
npm run test:coverage
npm run build
git add skills/ps-commu-explain/assets/template-react
git commit -m "feat: add interactive system explainers"
```

## Task 8: Add Visualization Adapters Without Hiding Meaning

**Files:**
- Modify: `assets/template-react/package.json`
- Create: `src/adapters/mermaid/MermaidDiagram.tsx`
- Create: `src/adapters/react-flow/SystemGraph.tsx`
- Create: `src/adapters/vega/VegaChart.tsx`
- Create: `src/adapters/shiki/highlightCode.ts`
- Create: `src/adapters/adapterRegistry.ts`
- Test: adapter unit and integration tests

- [ ] **Step 1: Write failing adapter contract tests**

For every adapter, require a caption, long description, source receipt, structured fallback, and error fallback. Reject remote data URLs. Reject unlabeled material edges before adapter invocation.

- [ ] **Step 2: Run tests to prove RED**

```zsh
npx vitest run src/adapters tests/integration/adapters.test.tsx
```

- [ ] **Step 3: Install adopted engines**

```zsh
npm install mermaid @xyflow/react vega vega-lite shiki
```

- [ ] **Step 4: Implement explicit adapter boundaries**

Use keys `mermaid`, `react-flow`, `vega-lite`, and `shiki`. Load client visualization code dynamically. Server output always includes caption, long description, and structured fallback.

- [ ] **Step 5: Implement each adapter contract**

- Mermaid accepts authored DSL plus normalized stage/edge fallback.
- React Flow accepts normalized nodes/edges and keyboard-focusable nodes.
- Vega-Lite accepts inline specs and recursively rejects external `url` data.
- Shiki highlights at build time with explicit language/theme imports.

- [ ] **Step 6: Add bundle and offline checks**

Build one fixture per adapter. Assert `dist` has no remote runtime assets. Record compressed bundle sizes and fail when a fixture includes an unused adapter.

- [ ] **Step 7: Run tests and commit**

```zsh
npm test -- --run src/adapters tests/integration/adapters.test.tsx
npm run build
git add skills/ps-commu-explain/assets/template-react
git commit -m "feat: add explainer visualization adapters"
```

## Task 9: Add Presets and the Artifact Build Command

**Files:**
- Create: `src/presets/definitions.ts`
- Create: `src/presets/applyPreset.ts`
- Create: `skills/ps-commu-explain/scripts/render.sh`
- Modify: `skills/ps-commu-explain/scripts/init.sh`
- Test: `src/presets/applyPreset.test.ts`
- Test: `skills/ps-commu-explain/tests/render_command_test.sh`
- Modify: `skills/ps-commu-explain/tests/lifecycle_test.sh`

- [ ] **Step 1: Write failing preset tests**

Create one test per approved preset. Assert application returns a new artifact, preserves authored sections, adds only absent recommended shells, and never invents evidence or topic content.

- [ ] **Step 2: Write failing shell acceptance tests**

Initialize `t-render`, assert `artifact.yaml` and app files exist, render it, assert `dist/index.html` contains its title, and reject a missing artifact or invalid slug.

- [ ] **Step 3: Run tests to prove RED**

```zsh
npx vitest run src/presets/applyPreset.test.ts
zsh skills/ps-commu-explain/tests/render_command_test.sh
```

- [ ] **Step 4: Implement preset recommendations**

Define the eight approved presets as ordered composition recommendations. `applyPreset` may add navigation, objectives, glossary, unknown, or evidence-ledger shells only from existing content.

- [ ] **Step 5: Implement initialization and rendering**

For React tier, `init.sh` copies `assets/template-react` into `<workspace>/app` and writes minimal valid `artifact.yaml`. `render.sh <slug> [artifact-path]` validates the slug/path, installs dependencies only when absent, and runs `ARTIFACT="$artifact" npm run build`. It must not start a server.

- [ ] **Step 6: Run shell, lifecycle, and build tests**

```zsh
zsh skills/ps-commu-explain/tests/render_command_test.sh
zsh skills/ps-commu-explain/tests/lifecycle_test.sh
cd skills/ps-commu-explain/assets/template-react
npm test
npm run build
```

- [ ] **Step 7: Commit**

```zsh
git add skills/ps-commu-explain
git commit -m "feat: compose artifacts from explainer presets"
```

## Task 10: Prove Historical Pattern Compatibility

**Files:**
- Create: `skills/ps-commu-explain/tests/compatibility-manifest.yaml`
- Create: `skills/ps-commu-explain/tests/fixtures/historical/rc-3585-megasale-signal.yaml`
- Create: `skills/ps-commu-explain/tests/fixtures/historical/ihg-child-type-id.yaml`
- Create: `skills/ps-commu-explain/tests/fixtures/historical/ecc-workflows.yaml`
- Create: `skills/ps-commu-explain/tests/fixtures/historical/promotion-refactor.yaml`
- Create: `skills/ps-commu-explain/tests/fixtures/historical/agent-harness-system-goal.yaml`
- Create: `assets/template-react/tests/integration/historicalCompatibility.test.ts`

- [ ] **Step 1: Write the compatibility manifest**

For every recovered artifact, record `id`, `evidenceLevel`, `evidencePaths`, `requiredPatterns`, and `gap`. Permit only `rendered-equivalent`, `pattern-covered`, or `trace-only`. Include all 13 transcript-backed builds and five workspace-rendered artifacts; record aliases explicitly.

- [ ] **Step 2: Write the failing coverage test**

```ts
for (const artifact of manifest.artifacts) {
  for (const pattern of artifact.requiredPatterns) {
    const mapped = registry.has(pattern)
    const explainedGap = artifact.gap?.patterns.includes(pattern) ?? false
    expect(mapped || explainedGap).toBe(true)
  }
}
```

- [ ] **Step 3: Run the test to prove RED**

```zsh
npx vitest run tests/integration/historicalCompatibility.test.ts
```

- [ ] **Step 4: Convert five recoverable artifacts**

- RC-3585 includes current flow, failure, loss point, repair, decisions, implementation, proof, and sources.
- IHG includes vertical system map, child-type payload, ownership, decision, and evidence.
- ECC includes comparison, lifecycle, hierarchy, scenarios, context pressure, memory paths, security scan, and timeline.
- Promotion refactor includes system flow, tables, callouts, code boundaries, and evidence.
- Agent harness includes overview map, progressive detail, code walk, and receipts.

Use recovered sources only; represent unavailable content as gaps.

- [ ] **Step 5: Build every rendered-equivalent fixture**

Initialize a temporary workspace per fixture, render, assert expected headings and source locators in `dist/index.html`, and keep screenshots only under test output.

- [ ] **Step 6: Run compatibility and commit**

```zsh
npm test -- --run tests/integration/historicalCompatibility.test.ts
git add skills/ps-commu-explain/tests skills/ps-commu-explain/assets/template-react/tests
git commit -m "test: verify historical explainer compatibility"
```

## Task 11: Add Browser, Accessibility, and No-Hydration Acceptance

**Files:**
- Modify: `assets/template-react/package.json`
- Create: `assets/template-react/playwright.config.ts`
- Create: `assets/template-react/tests/e2e/historical.spec.ts`
- Create: `assets/template-react/tests/e2e/interactions.spec.ts`
- Create: `assets/template-react/tests/e2e/accessibility.spec.ts`
- Create: `assets/template-react/tests/e2e/no-hydration.spec.ts`

- [ ] **Step 1: Install E2E dependencies**

```zsh
npm install -D @axe-core/playwright @playwright/test
npx playwright install chromium
```

- [ ] **Step 2: Write failing E2E tests**

Cover all five historical fixtures, clean console, 390px viewport, keyboard, click/touch-equivalent controls, prediction/reveal/retry, trace reset, reduced motion, linked selection, and essential content with JavaScript disabled.

```ts
const errors: string[] = []
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(message.text())
})
await page.goto('/')
expect(errors).toEqual([])
```

- [ ] **Step 3: Run E2E to prove RED**

```zsh
npx playwright test
```

- [ ] **Step 4: Fix product defects exposed by E2E**

Fix accessible names, visible focus, 390px reflow, reduced-motion behavior, and missing no-JavaScript content. Do not weaken correct tests to accommodate product defects.

- [ ] **Step 5: Run the full frontend matrix**

```zsh
npm run typecheck
npm run test:coverage
npm run build
npx playwright test
```

- [ ] **Step 6: Commit**

```zsh
git add skills/ps-commu-explain/assets/template-react
git commit -m "test: add explainer browser acceptance"
```

## Task 12: Compact the Skill and Preserve Verification Gates

**Files:**
- Modify: `skills/ps-commu-explain/SKILL.md`
- Create: `skills/ps-commu-explain/references/lite-workflow.md`
- Create: `skills/ps-commu-explain/references/rich-workflow.md`
- Create: `skills/ps-commu-explain/references/component-selection.md`
- Remove after migration: `skills/ps-commu-explain/references/visual-components.md`
- Modify: `skills/ps-commu-explain/tests/content_contract_test.sh`
- Modify: `skills/ps-commu-explain/agents/openai.yaml`

- [ ] **Step 1: Rewrite the contract test before the skill**

Require mode selection, evidence gate, Sourcegraph rule, script commands, browser handoff, and conditional references. Require the root body below 80 non-frontmatter lines. Require staff gates in `rich-workflow.md`, without duplication in the root.

- [ ] **Step 2: Run the contract test to prove RED**

```zsh
zsh skills/ps-commu-explain/tests/content_contract_test.sh
```

- [ ] **Step 3: Write the concise router**

The root selects lite unless deep/staff/interactive output or multiple material systems justify rich mode. It reads only the selected workflow, requires Sourcegraph for code-flow claims, authors declarative data, executes `init.sh`, `render.sh`, and `serve.sh`, and requires current browser evidence plus the exact URL.

- [ ] **Step 4: Split detailed guidance by need**

`lite-workflow.md` keeps sourced facts, compact outline, standard presets, one browser cycle, and honest fallback. `rich-workflow.md` keeps dossiers, labeled edges, worked traces, ownership/current-target separation, multiagent gates, reader tests, and five-cycle limit. `component-selection.md` maps learning objectives to compositions and cautions.

- [ ] **Step 5: Regenerate metadata and validate**

```zsh
python3 /Users/pnusso/.codex/skills/.system/skill-creator/scripts/generate_openai_yaml.py skills/ps-commu-explain --interface display_name="ps-commu explain" --interface short_description="Build sourced interactive technical explainers" --interface default_prompt="Explain this topic as a verified interactive artifact."
python3 /Users/pnusso/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/ps-commu-explain
zsh skills/ps-commu-explain/tests/content_contract_test.sh
```

- [ ] **Step 6: Commit**

```zsh
git add skills/ps-commu-explain
git commit -m "refactor: route ps-commu through declarative workflows"
```

## Task 13: Extend CI and Run Complete Verification

**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: all skill and template suites

- [ ] **Step 1: Extend CI**

Make the React-template job run `npm ci`, typecheck, coverage, build, Chromium installation, and Playwright. Add contract and render-command tests to the macOS lifecycle job.

```yaml
- name: Typecheck and unit coverage
  working-directory: skills/ps-commu-explain/assets/template-react
  run: |
    npm run typecheck
    npm run test:coverage
- name: Build default artifact
  working-directory: skills/ps-commu-explain/assets/template-react
  run: npm run build
- name: Browser acceptance
  working-directory: skills/ps-commu-explain/assets/template-react
  run: |
    npx playwright install --with-deps chromium
    npx playwright test
```

- [ ] **Step 2: Run every local test**

```zsh
zsh skills/ps-commu-explain/tests/content_contract_test.sh
zsh skills/ps-commu-explain/tests/render_command_test.sh
zsh skills/ps-commu-explain/tests/lifecycle_test.sh
cd skills/ps-commu-explain/assets/template-react
npm ci
npm run typecheck
npm run test:coverage
npm run build
npx playwright test
```

- [ ] **Step 3: Run cleanup and security checks**

```zsh
cd /Users/pnusso/Workspace/.worktree/ps-commu-component-system
find skills/ps-commu-explain -type d -name __pycache__ -prune -exec rm -rf '{}' +
git diff --check
git status --short
```

Search the task-owned files for credential assignments and unsafe remote runtime references. Remove unused imports, warnings, generated cache, and unexpected files.

- [ ] **Step 4: Request independent reviews**

Dispatch fresh read-only code and security reviewers with the diff and test evidence. Address all CRITICAL and HIGH findings, rerun affected tests, then rerun the complete matrix.

- [ ] **Step 5: Commit CI changes**

```zsh
git add .github/workflows/ci.yml
git commit -m "ci: verify declarative ps-commu artifacts"
```

## Task 14: Verify Canonical Installation Without Losing User State

**Files:**
- Canonical: `skills/ps-commu-explain/**`
- Installed: `/Users/pnusso/.codex/skills/ps-commu-explain/**`
- Backup: `/tmp/ps-commu-installed-backup-<timestamp>/`

- [ ] **Step 1: Back up the installed skill**

```zsh
stamp="$(date +%Y%m%d-%H%M%S)"
backup="/tmp/ps-commu-installed-backup-$stamp"
mkdir -p "$backup"
rsync -a /Users/pnusso/.codex/skills/ps-commu-explain/ "$backup/"
find /Users/pnusso/.codex/skills/ps-commu-explain -type f -print0 | sort -z | xargs -0 shasum -a 256 > "$backup/before.sha256"
```

- [ ] **Step 2: Synchronize only the approved skill**

```zsh
rsync -a --delete --exclude node_modules --exclude dist skills/ps-commu-explain/ /Users/pnusso/.codex/skills/ps-commu-explain/
```

- [ ] **Step 3: Prove installed and canonical copies match**

```zsh
diff -qr --exclude node_modules --exclude dist skills/ps-commu-explain /Users/pnusso/.codex/skills/ps-commu-explain
zsh /Users/pnusso/.codex/skills/ps-commu-explain/tests/content_contract_test.sh
zsh /Users/pnusso/.codex/skills/ps-commu-explain/tests/lifecycle_test.sh
```

- [ ] **Step 4: Forward-test lite mode**

Using only the root skill and lite reference, initialize, author, render, serve, open the exact URL in Chromium, require a clean console, and stop the slug. Success requires no renderer-internal files to be read.

- [ ] **Step 5: Forward-test rich mode**

Using only the root plus rich/component-selection references, render an annotated system map, worked example, prediction/reveal, progress, dossier, payload-labeled edge, receipts, and no-hydration fallback. Verify keyboard, touch-equivalent, 390px, reduced-motion, and clean-console acceptance.

- [ ] **Step 6: Record final evidence**

Capture branch commits, complete test outputs, coverage, compatibility statuses, installed diff, forward-test gaps, and exact changed files. Do not push, merge, or delete the worktree without explicit approval.

## Final Definition of Done

- [ ] YAML and JSON artifacts validate and render.
- [ ] Server HTML contains the essential reading path.
- [ ] Interactive enhancements pass keyboard, pointer, touch-equivalent, and reduced-motion tests.
- [ ] Every registered component and preset has automated coverage.
- [ ] Five representative historical artifacts pass semantic acceptance.
- [ ] Every other recovered pattern maps to a component, recipe, escape hatch, or evidence gap.
- [ ] Unit, integration, and E2E suites pass with at least 80% coverage.
- [ ] Lifecycle and contract regression suites pass.
- [ ] Browser console has zero errors.
- [ ] No remote runtime assets, unsafe artifact HTML, exposed secrets, generated caches, warnings, or unused imports remain.
- [ ] Installed and canonical skill directories match after scoped synchronization.
- [ ] User receives exact evidence and controls merge/worktree cleanup.
