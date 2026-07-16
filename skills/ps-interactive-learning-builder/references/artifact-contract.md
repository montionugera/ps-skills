# Artifact Contract

Keep discovery and shared policy in the central library. Keep every executable artifact inside a portable topic project that does not depend on a shared mutable source tree or central dependency directory.

## Library layout

Use `/Users/pnusso/Workspace/Main/learning-materials` by default. Maintain `catalog.yaml`, `shared/quality-rubric.md`, `shared/source-policy.md`, and independent projects under `topics/<topic-slug>/`. Record topic identity, title, audience, format, status, freshness date, durable location, and current preview metadata in the catalog.

Create these canonical topic paths exactly:

```text
topics/<topic-slug>/
├── research/01-brief.md
├── research/02-research-strategy.md
├── research/03-factsheet.md
├── research/04-knowledge-map.md
├── design/05-curriculum.md
├── design/06-build-spec.md
├── design/07-acceptance-matrix.md
├── app/
└── verification/
    ├── 08-audit-report.md
    ├── 09-verification-report.md
    └── manifest.sha256
```

Treat `verification/08-audit-report.md`, `verification/09-verification-report.md`, and `verification/manifest.sha256` as the canonical verification files relative to the topic root.

Use `01-brief.md` for scope, learner, outcomes, destination, and acceptance criteria. Use `02-research-strategy.md` for source families, queries, authority rules, freshness requirements, and access gaps. In `03-factsheet.md`, assign stable claim IDs and preserve them across revisions; record source, access date, confidence, freshness, contradictions, and disposition for each claim. Use `04-knowledge-map.md` to connect claims, prerequisites, uncertainties, and gaps.

Map claims to objectives and modules in `05-curriculum.md`. Map modules to explanations, interactions, exercises, and assessments in `06-build-spec.md`. Define evidence for each objective and critical flow in `07-acceptance-matrix.md`. Store only durable website source and required assets in `app/`. Record independent findings in `08-audit-report.md`, final gate evidence in `09-verification-report.md`, and relevant application hashes in `manifest.sha256`.

Advance catalog status only in this order: `planned → researched → designed → built → audited → verified`. Retain the last valid state whenever a later gate fails.
