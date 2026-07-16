# ps-interactive-learning-builder design

**Date:** 2026-07-16
**Status:** Approved for implementation planning

## Purpose

Create a reusable `ps-interactive-learning-builder` skill that turns a learning topic into a researched, structured, interactive, and verified educational website. The skill must support public technical subjects such as OpenTelemetry, internal projects such as Dragon Fruit, and financial breakdowns that require dated assumptions and stronger source controls.

The skill is a thin orchestrator. It coordinates existing research, frontend, and verification capabilities instead of duplicating the templates, preview server, or browser lifecycle already owned by `ps-commu-explain`.

## User experience

When invoked, the skill establishes:

- the topic and its boundaries;
- the intended learners and prerequisite knowledge;
- measurable learning outcomes;
- public, private, code, or mixed source families;
- the appropriate format: structured course, explorable visual reference, or hybrid;
- the central learning-library root and topic slug;
- assessment depth and freshness requirements.

The default library root is:

```text
/Users/pnusso/Workspace/Main/learning-materials
```

The default library is a standalone private Git repository with this remote:

```text
gitlab.agodadev.io/pnusso/learning-materials
```

The user may override the local path or remote. The skill creates or updates one self-contained topic project and provides both a durable project and a verified temporary localhost preview.

## Repository lifecycle and external-write boundary

Keep the learning library separate from `ps-skills`. When the root does not exist, prepare the local directory, central catalog, shared policy files, and Git history. Create the personal GitLab project only when the user has explicitly approved that external write. Use private visibility by default.

Local research, design, build, testing, and commits may continue without pushing. Before each push, show the branch, commits, destination remote, and verification evidence, then require explicit approval unless the user already granted scoped push approval for that run. Never push incomplete research or a topic described as verified when its required gates have failed.

## Architecture

The workflow has four gated phases:

1. **Frame:** define the learner model, goals, scope, output destination, format, and acceptance criteria.
2. **Research:** create a research strategy, gather authoritative evidence, assign stable claim identifiers, record confidence and freshness, and expose gaps or contradictions.
3. **Design learning:** synthesize a knowledge map, measurable objectives, modules, interactions, exercises, assessments, build specification, and acceptance matrix.
4. **Build and verify:** delegate the visual application lifecycle to `ps-commu-explain`, run content and software checks, export the result to the durable topic directory, compare the durable copy with the verified build, and update the catalog.

The traceability chain is:

```text
source → claim → objective → module → interaction → assessment → verification evidence
```

No phase may publish downstream artifacts until its gate passes.

## Central library and topic boundaries

Use a central catalog with independent topic projects:

```text
learning-materials/
├── catalog.yaml
├── shared/
│   ├── quality-rubric.md
│   └── source-policy.md
└── topics/
    └── <topic-slug>/
        ├── research/
        ├── design/
        ├── app/
        └── verification/
```

The central layer owns discovery and policy only:

- topic identity, title, audience, format, status, and freshness date;
- durable project location and current preview metadata when available;
- the shared quality rubric and source policy.

Each topic owns all executable knowledge:

- research evidence and claim records;
- curriculum and build specification;
- application source and tests;
- verification evidence.

Topic applications must not depend on a shared mutable application source tree or central `node_modules`. Reusable application templates remain in the builder skills, keeping each generated topic portable and independently rebuildable.

## Canonical topic artifacts

Each topic project contains:

```text
<topic-slug>/
├── research/
│   ├── 01-brief.md
│   ├── 02-research-strategy.md
│   ├── 03-factsheet.md
│   └── 04-knowledge-map.md
├── design/
│   ├── 05-curriculum.md
│   ├── 06-build-spec.md
│   └── 07-acceptance-matrix.md
├── app/
│   └── durable website source
└── verification/
    ├── 08-verification-report.md
    └── manifest.sha256
```

`03-factsheet.md` assigns stable claim IDs and records source, access date, confidence, and freshness. `05-curriculum.md` maps claims to objectives and modules. `06-build-spec.md` maps modules to visual explanations, interactions, exercises, and assessments. `07-acceptance-matrix.md` defines evidence for every objective and critical user flow.

## Source strategy

Prefer authoritative primary sources. For public technical topics, use official documentation, specifications, standards, and source repositories. For internal code flows, use Sourcegraph for code search and discovery; do not substitute GitLab search when Sourcegraph authentication is unavailable. Use company documentation and issue systems only when relevant and available.

Every published factual claim must have a source record. Conflicting sources must be reconciled or presented as an explicit uncertainty. Missing private access stops factual publication for the affected area but may still produce a clearly marked research-gap report.

Financial topics additionally require:

- valuation and retrieval dates;
- currencies and units;
- explicit assumptions and formulas;
- base, upside, and downside scenarios when projections are used;
- sensitivity analysis for material assumptions;
- a clear educational-not-personal-financial-advice boundary.

## Learning-design selection

Select the output format from learner goals rather than forcing one template:

- **Structured course:** use for sequential prerequisites, skill acquisition, exercises, and progress checks.
- **Explorable reference:** use for non-linear discovery, architecture exploration, visual comparison, and just-in-time lookup.
- **Hybrid:** use when learners need a guided path plus optional deep dives or simulations.

Each measurable objective must map to relevant claims, a module, and at least one suitable interaction, exercise, or assessment. Avoid decorative interactions that do not improve understanding or test an objective.

## Build ownership and preview lifecycle

`ps-interactive-learning-builder` owns orchestration and canonical artifacts. `ps-commu-explain` owns the temporary application build, lifecycle scripts, preview server, and Chrome verification. Preserve its single-writer application ownership and single server/browser owner per verification cycle.

After the temporary application passes verification:

1. Copy the finalized application source and required assets to the durable topic `app/` directory.
2. Run the applicable static checks and production build from the durable copy.
3. Produce a SHA-256 manifest for the durable application and the verified temporary application.
4. Confirm the relevant file sets and hashes match, excluding generated caches and environment-specific runtime files.
5. Keep the verified localhost preview under the existing 24-hour cleanup lifecycle.
6. Hand back the durable path, exact verified preview URL, catalog status, verification summary, and cleanup command.

## Verification contract

The central catalog recognizes these ordered states:

```text
planned → researched → designed → built → verified
```

A topic becomes `verified` only when all applicable checks pass:

- **Research:** every published claim has evidence, an access date, confidence, and a freshness check.
- **Synthesis:** contradictions and unresolved gaps are visible; unsupported claims do not enter the application.
- **Learning design:** objectives are measurable and trace through modules, interactions or exercises, assessments, and evidence.
- **Application:** lint, typecheck, production build, unit tests, integration tests, and critical-flow end-to-end tests pass where applicable. Executable application logic targets at least 80% coverage.
- **Accessibility:** keyboard navigation, semantic structure, contrast, focus visibility, and reduced-motion behavior are checked.
- **Browser:** responsive sections are inspected in Chrome and the production preview has zero console errors.
- **Traceability:** the complete source-to-verification chain is represented in the artifacts.
- **Durability:** the exported topic application matches the verified temporary build through the manifest comparison and passes its own build checks.
- **Catalog:** the central catalog update is the final operation after every other gate passes.

## Failure handling

On a failed gate:

- preserve completed artifacts and raw evidence;
- record the gate, failing checks, commands, and actionable remediation in `08-verification-report.md`;
- retain the topic's last valid catalog state;
- do not describe the topic as complete or verified;
- never convert unavailable evidence or failed checks into confident educational content.

The workflow may resume from the failed gate after the underlying issue is fixed, but it must re-run all downstream checks affected by the change.

## Skill package

Create the skill at:

```text
skills/ps-interactive-learning-builder/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── artifact-contract.md
│   ├── learning-design.md
│   └── verification-contract.md
└── tests/
    └── test_skill.py
```

Keep `SKILL.md` concise and imperative. Put detailed artifact schemas and quality gates in the three directly linked reference files. Do not add scripts or application assets unless implementation reveals deterministic behavior that cannot safely reuse an existing tool. Update the repository catalog, usage documentation, development commands, and CI so the new structure tests run on every change.

## Skill tests

Use standard-library `unittest` tests to verify:

- exact frontmatter name and a trigger-rich description;
- the required phase order and gate language;
- the default root and canonical topic paths;
- references to research, `ps-commu-explain`, frontend building, and verification capabilities;
- stable claim identifiers and the complete traceability chain;
- adaptive structured-course, explorable-reference, and hybrid modes;
- financial source, date, assumption, sensitivity, and advice-boundary controls;
- failure-state preservation and catalog update ordering;
- required reference and agent metadata files;
- absence of placeholders, stale paths, and duplicated server or application templates;
- automatic discovery by the existing installer for both Claude and Codex.
- the private personal GitLab default and approval boundary for remote creation and pushes.

Validation must include the official skill validator, the new unit tests, relevant existing skill tests, and repository CI-equivalent checks. After implementation, forward-test the skill with representative OpenTelemetry, internal-project, and financial prompts using isolated subagents that receive only the skill and task-local inputs.

## Out of scope

- Hosting or publishing the generated learning website to an external service.
- Personalized financial, legal, or medical advice.
- Replacing `ps-commu-explain` lifecycle scripts or frontend templates.
- A shared runtime framework that couples all topic applications.
- Updating the central catalog before a topic passes verification.
