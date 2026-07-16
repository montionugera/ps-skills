# ps-commu-explain Declarative Component System

**Date:** 2026-07-16

**Status:** Approved design

**Canonical repository:** `/Users/pnusso/Workspace/ps-skills`
**Target skill:** `skills/ps-commu-explain`

## Summary

Replace per-artifact page construction with a versioned declarative artifact format rendered by a reusable React component system. The system will preserve semantic equivalence with recoverable historical explainers while reducing repeated markup, styling, interaction, accessibility, and verification work.

Authors will normally write sourced YAML or JSON. A deterministic renderer will validate the artifact, compose reusable educational components, server-render the complete reading path, add hydration for interactive behavior, build an offline-capable artifact, and hand it to the existing secure serving lifecycle.

The design has three presentation layers:

1. Stable visual primitives
2. Evidence-backed educational compositions
3. Artifact presets

Custom TSX remains an explicit last-resort escape hatch.

## Goals

- Reduce prompt and implementation tokens spent recreating page structure, CSS, and JavaScript.
- Preserve the existing evidence-first and no-hallucination requirements.
- Support interactive explanations: selection, expansion, progress, stepping, scrubbing, filtering, prediction, feedback, simulations, and linked views.
- Keep essential meaning available without hover and without successful hydration.
- Express recurring historical artifact patterns through a reusable registry.
- Verify compatibility using recovered artifacts and explicit evidence levels.
- Keep `ps-skills` as the canonical source and verify installed copies after synchronization.
- Maintain at least 80% automated test coverage, including unit, integration, and end-to-end tests.

## Non-goals

- Pixel-perfect reproduction of historical artifacts.
- Reconstructing deleted content that is not recoverable from files or transcripts.
- Building graph layout, chart grammar, syntax highlighting, diff parsing, accessibility primitives, or schema validation from scratch.
- Making every artifact interactive.
- Replacing the secure `init`, `serve`, `list`, `stop`, and `clean` lifecycle.
- Providing a general-purpose website builder outside technical and educational explanations.

## Evidence Base

### Historical corpus

The investigation recovered:

- 13 transcript-backed `/tmp/ps-commu` build traces.
- 5 rendered workspace explanation artifacts.
- 3 recoverable factsheet/key-area/outline source packs.
- One initial Git commit plus later uncommitted repository and installed-copy evolution.
- Several cleaned or partial builds whose exact content is no longer recoverable.

Recurring historical patterns include diagrams, navigation, callouts, tables, evidence receipts, progressive disclosure, comparisons, timelines, code walks, traces, failure diagnosis, ownership views, progress displays, lightboxes, and responsive layouts.

The corpus is sufficient to identify reusable patterns but insufficient to claim exact reconstruction of every past page.

### Educational research

The component model incorporates evidence for:

- Retrieval practice: <https://doi.org/10.3102/0034654316689306>
- Worked examples: <https://doi.org/10.1007/s10648-023-09745-1>
- Feedback: <https://doi.org/10.3389/fpsyg.2019.03087>
- Prediction/pretesting: <https://doi.org/10.1037/xap0000345>
- Self-explanation: <https://doi.org/10.1007/s10648-018-9434-x>
- Case comparison: <https://doi.org/10.1080/00461520.2013.775712>
- Segmenting: <https://doi.org/10.1007/s10648-018-9456-4>
- Signaling: <https://doi.org/10.1016/j.edurev.2017.11.001>
- Concept mapping: <https://doi.org/10.3102/00346543076003413>

The mapping from instructional treatments to named React components is a design inference. The research does not establish that any particular widget is universally effective.

The interaction model also draws from:

- Bret Victor, Explorable Explanations: <https://worrydream.com/ExplorableExplanations/>
- Nicky Case, How I Make Explorable Explanations: <https://blog.ncase.me/how-i-make-an-explorable-explanation/>
- Distill, Communicating with Interactive Articles: <https://distill.pub/2020/communicating-with-interactive-articles/>
- WCAG 2.2: <https://www.w3.org/TR/WCAG22/>

## Decisions

### Compatibility target

Use semantic equivalence rather than pixel equivalence. A migrated artifact must preserve its explanation, evidence, diagrams, interactions, accessibility, and educational intent. Styling may be refreshed within the shared design system.

### Canonical source

Implement and test the system in `/Users/pnusso/Workspace/ps-skills`. Reconcile the newer installed skill into the repository before changing the renderer. Synchronize to `~/.codex/skills` only after repository verification.

### Authoring model

Use YAML or JSON for standard artifacts. Validate both against one portable JSON Schema. Do not allow arbitrary HTML in declarative content.

Use custom TSX only when a documented semantic need cannot be represented by the registry. Require a justification and a static fallback.

### Rendering model

Use React with server rendering followed by hydration. Server rendering must contain the complete semantic reading path. Hydration may add interaction but must not introduce essential facts that are otherwise unavailable.

### Dependency boundaries

- Mermaid: authored, mostly static technical diagrams.
- React Flow: selectable or explorable node/edge systems.
- Vega-Lite compiled to Vega: declarative charts and data-driven timelines.
- Shiki: build-time code highlighting.
- React Aria: accessible disclosures, tabs, overlays, controls, and focus behavior.
- D3 modules: internal layout or mathematical utilities only.
- Ajv: portable JSON Schema validation.

All runtime assets must be local. Expensive adapters must be included only when referenced by an artifact.

## Architecture

```text
facts and evidence
      |
artifact.yaml or artifact.json
      |
JSON Schema + semantic validation
      |
preset expansion + immutable normalization
      |
React component registry
      |
server-rendered semantic HTML
      |
selective adapter bundles + hydration
      |
production artifact
      |
existing secure serve.sh lifecycle
```

### Layer 1: Visual primitives

Primitives own visual consistency, responsive behavior, accessibility semantics, and low-level interaction mechanics:

- `Section`, `Grid`, `Stack`
- `Tabs`, `Disclosure`, `DetailPanel`
- `Callout`, `Tip`, `Definition`, `EvidenceReceipt`
- `Progress`, `Stepper`, `TimelineControls`
- `CodeBlock`, `CodeDiff`, `DataTable`
- `Diagram`, `Chart`, `Graph`, `Annotation`
- `ParameterControl`, `ChoiceInput`, `Feedback`
- `Inspector`, `BeforeAfter`

Primitives must not embed topic-specific business rules.

### Layer 2: Educational compositions

Compositions combine primitives into reusable teaching experiences:

- `MentalModelMap`
- `AnnotatedSystemMap`
- `WorkedExampleStepper`
- `ExecutionTrace`
- `PredictThenRun`
- `CompareCases`
- `RetrievalCheck`
- `ExplainWhy`
- `ScenarioExplorer`
- `GuidedSimulation`
- `LinkedViews`
- `ParameterSweep`
- `ConceptMap`
- `FailureDiagnosis`
- `StageDossier`
- `DataContractExplorer`

Compositions must expose a static semantic representation of their core content.

### Layer 3: Artifact presets

Presets provide recommended learning sequences without fixing exact page styling:

- `orientation`
- `code-walkthrough`
- `architecture`
- `incident-debugging`
- `current-vs-target`
- `staff-deep-dive`
- `interactive-training`
- `reference-cheatsheet`

Artifact sections may override preset choices within schema constraints.

## Artifact Contract

Every artifact has a schema version, stable ID, metadata, normalized sources, and typed sections.

```yaml
schemaVersion: 1
id: discount-selection-flow
preset: architecture

metadata:
  title: How discount selection works
  audience: implementer
  status: live-code-verified
  summary: Discounts pass through eligibility, ranking, and selection.
  learningObjectives:
    - Identify where eligibility is decided
    - Explain which payload crosses each boundary

sources:
  eligibility:
    locator: EligibilityFilter.scala:42
    confidence: verified

sections:
  - id: request-flow
    type: annotated-system-map
    title: Request flow
    objective: Follow one request across system boundaries
    nodes:
      - id: eligibility
        label: Filter eligible discounts
        owner: DFAPI
        sourceRefs: [eligibility]
    edges:
      - from: request
        to: eligibility
        payload: DiscountCandidates
        payloadStatus: exact-type
    fallback:
      type: ordered-list
      items:
        - DFAPI receives discount candidates.
        - Eligibility rules remove invalid candidates.
```

### Shared content models

Normalize these models so one sourced fact can drive several views:

- `SourceRef`
- `Stage`
- `Edge`
- `Payload`
- `CodeLocation`
- `Scenario`
- `TraceStep`
- `BeforeAfterState`
- `LearningObjective`
- `AssessmentPrompt`
- `Unknown`
- `Owner`
- `CurrentTargetStatus`

### Contract invariants

- Use discriminated section types.
- Represent unknown facts explicitly.
- Resolve every evidence reference.
- Distinguish exact production types from semantic pseudotypes.
- Label every material edge with a payload or artifact.
- Preserve authored default state and deterministic reset behavior.
- Provide a static fallback for essential interactive content.
- Reject arbitrary HTML and unsafe URLs.
- Keep required meaning available through keyboard, touch, and persistent content.

## Interaction Rules

- Begin simulations with an authored path; unlock open sandbox behavior later.
- Provide pause, step, scrub, backtrack, and comparison for temporal explanations.
- Preserve baselines when state changes; do not force comparison from memory.
- Treat hover as a supplement. Provide click, keyboard, touch, and persistent alternatives.
- Give explanatory feedback after prediction or retrieval attempts.
- Use progress to represent conceptual progress, not arbitrary scroll position.
- Avoid forced interaction for the core reading path.
- Respect reduced motion and retain context when details are disclosed.
- Announce meaningful state changes to assistive technologies.

## Proposed Repository Structure

```text
skills/ps-commu-explain/
|-- SKILL.md
|-- assets/template-react/
|   |-- schema/explanation.schema.json
|   |-- src/
|   |   |-- renderer/
|   |   |-- primitives/
|   |   |-- compositions/
|   |   |-- adapters/
|   |   |-- presets/
|   |   |-- accessibility/
|   |   `-- styles/
|   |-- scripts/
|   |   |-- validate.ts
|   |   |-- render.ts
|   |   `-- build.ts
|   `-- package.json
|-- scripts/
|   |-- init.sh
|   |-- render.sh
|   `-- existing lifecycle scripts
|-- references/
|   |-- lite-workflow.md
|   |-- rich-workflow.md
|   `-- component-selection.md
`-- tests/
    |-- fixtures/
    |   |-- historical/
    |   |-- invalid/
    |   `-- presets/
    |-- compatibility-manifest.yaml
    |-- unit/
    |-- integration/
    `-- e2e/
```

The final implementation may adjust individual filenames to match the chosen test runner, but it must preserve these boundaries.

## Skill Workflow

The shortened `SKILL.md` will route execution:

1. Lock audience, questions, depth, scope, and evidence ceiling.
2. Research and record sourced facts.
3. Choose lite or rich workflow and an artifact preset.
4. Write declarative artifact data.
5. Validate and render with scripts.
6. Run semantic, build, browser, and accessibility checks.
7. Serve through `serve.sh` and report its exact URL.

The skill must instruct agents to execute bundled scripts without reading renderer internals unless they are modifying the renderer.

## Historical Compatibility

### Evidence levels

- `rendered-equivalent`: recovered source/content is rebuilt and browser-compared.
- `pattern-covered`: every known historical pattern maps to the registry.
- `trace-only`: existence is known, but insufficient content survived.

### Compatibility manifest

Maintain a machine-readable manifest with:

- Artifact identifier and evidence location.
- Evidence level.
- Known sections and patterns.
- Required registry mappings.
- Migration fixture, when recoverable.
- Explicit missing evidence.

The compatibility suite must fail when a known pattern has no mapping. It must not fail merely because an unrecoverable artifact cannot be reconstructed.

### Initial migration fixtures

Prioritize the richest recoverable artifacts:

1. RC-3585 cross-system investigation.
2. IHG child-type flow.
3. ECC workflows.
4. Promotion refactor.
5. Agent-harness system-goal explainer.

Add a new component only when existing primitives cannot express the meaning and the need either recurs or represents a core educational pattern.

## Testing Strategy

### Test-driven workflow

For every behavior:

1. Add a failing unit, integration, or end-to-end test.
2. Implement the minimum behavior required to pass.
3. Refactor while preserving the test suite.

### Unit tests

- Schema validation and actionable error paths.
- Evidence-reference resolution.
- Immutable normalization and preset expansion.
- Every primitive and educational composition.
- Step, trace, simulation, and linked-selection reducers.
- Static fallback generation.
- Keyboard and reduced-motion decisions.

### Integration tests

- YAML/JSON through validation, server rendering, and production build.
- Mermaid, React Flow, Vega-Lite, and Shiki adapters.
- Preset overrides and custom-component refusal paths.
- Offline output with no remote runtime dependencies.
- Static output retaining essential meaning without hydration.

### End-to-end tests

- Five representative historical artifacts.
- Pointer, keyboard, and touch-equivalent interactions.
- Trace navigation, reset, and preserved baselines.
- Prediction, reveal, feedback, and retry.
- Linked diagram, dossier, code, and state selection.
- Mobile reflow at 390px.
- Reduced-motion behavior.
- Clean browser console.
- Automated accessibility checks.
- Screenshot-based structural regression checks.

### Coverage and acceptance

- Achieve at least 80% automated coverage.
- Include unit, integration, and end-to-end tests.
- Render every registered component and preset in test fixtures.
- Resolve every historical pattern to a registry entry, recipe, escape hatch, or evidence gap.
- Keep zero browser-console errors.
- Preserve the existing lifecycle test suite.

Automated accessibility checks supplement rather than replace keyboard, touch, and screen-reader-oriented acceptance tests.

## Synchronization and Existing Changes

The repository already contains unrelated and overlapping uncommitted changes. The installed skill also contains newer files absent from the repository.

Before renderer implementation:

1. Record a scoped diff of repository and installed skill versions.
2. Import missing installed requirements deliberately; do not copy blindly.
3. Preserve unrelated repository changes.
4. Implement and test only in `ps-skills`.
5. Run the repository installer after all local tests pass.
6. Compare the installed skill with the canonical directory using a scoped diff.

Do not reset, discard, or include unrelated changes in commits.

## Error Handling and Security

- Reject malformed schemas before rendering.
- Report errors with artifact paths and actionable messages.
- Reject unsafe URL protocols and unsanitized embedded markup.
- Do not execute artifact-provided JavaScript.
- Keep servers loopback-only and document roots scoped.
- Bundle assets locally and prohibit hidden network dependencies.
- Avoid logging private factsheets or artifact content unnecessarily.
- Preserve the watchdog, marker validation, port checks, and foreign-process protections.

## Risks and Mitigations

### Component explosion

Mitigation: keep a small primitive set, implement educational patterns as compositions, and require evidence for new primitives.

### Schema becomes a programming language

Mitigation: keep the schema declarative, reject executable expressions, and use custom TSX for exceptional behavior.

### Interaction adds distraction

Mitigation: require a learning objective, authored default path, and static baseline for each interactive block.

### Large bundles

Mitigation: pre-render static content, code-split adapters, highlight code at build time, and enforce adapter-level bundle budgets.

### Accessibility regressions in third-party visualizations

Mitigation: wrap adapters with captions, long descriptions, tables or outlines, keyboard instructions, focus restoration, and automated plus manual checks.

### False historical-completeness claims

Mitigation: record evidence levels and explicit gaps in the compatibility manifest.

### Dirty canonical repository

Mitigation: reconcile scoped files deliberately and commit only task-owned paths.

## Success Criteria

The design is successfully implemented when:

1. A standard explainer can be authored entirely as validated YAML or JSON.
2. The resulting artifact contains meaningful server-rendered HTML and interactive React enhancements.
3. The five representative historical fixtures build and pass semantic acceptance.
4. Every known historical pattern has a documented registry mapping or evidence gap.
5. Required information remains available without hover and without hydration.
6. Unit, integration, and end-to-end suites pass with at least 80% coverage.
7. Existing secure lifecycle tests continue to pass.
8. The installed skill matches the verified canonical source after synchronization.
9. The shortened skill routes lite and rich workflows without loading renderer internals into normal task context.

## Implementation Sequence

1. Reconcile canonical and installed skill requirements.
2. Add schema, validation, and failing contract fixtures.
3. Add server-rendered shell and accessibility primitives.
4. Add core visual primitives and presets.
5. Add historical presentation compositions.
6. Add active-learning compositions.
7. Add Mermaid, Shiki, Vega-Lite, and React Flow adapters as fixtures require them.
8. Migrate the five representative historical artifacts.
9. Complete compatibility, accessibility, performance, and lifecycle verification.
10. Shorten `SKILL.md`, synchronize the installed skill, and verify the scoped diff.

Detailed task ordering, file-level changes, and test-first checkpoints will be defined in the implementation plan after this design is reviewed.
