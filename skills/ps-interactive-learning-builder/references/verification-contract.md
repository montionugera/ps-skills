# Verification Contract

Verify gates in dependency order and cite commands, timestamps, outputs, artifact paths, and failure evidence in `verification/09-verification-report.md`.

## Required checks

- **Research:** Confirm every published claim has evidence, an access date, confidence, and a freshness check. Reconcile contradictions or label uncertainty. Ensure unsupported claims do not enter the application.
- **Learning design:** Confirm measurable objectives and assessment alignment. Trace `source → claim → objective → module → interaction → assessment → verification evidence` for every published objective.
- **Application:** Run applicable lint, typecheck, production build, unit tests, integration tests, and critical-flow end-to-end tests. Require at least 80% coverage for executable application logic and record justified non-applicability instead of silently skipping a category.
- **Accessibility:** Check keyboard navigation, semantic structure, contrast, focus visibility, and reduced-motion behavior across critical flows.
- **Browser:** Ensure responsive sections are inspected in Chrome at representative widths. Require the production preview to complete critical flows with zero console errors.
- **Durability:** Generate deterministic manifests for the temporary verified application and durable `app/` using the canonical procedure below. Prove durable-preview SHA-256 equivalence, then run durable build checks from the exported copy.
- **Audit:** Confirm an isolated audit is recorded in `verification/08-audit-report.md`, no unresolved critical or high findings remain, and every medium or low finding has an explicit disposition.
- **Catalog:** Ensure the catalog update is the final operation after all other gates pass. Record the resulting state and freshness date.

Write the final hashes to `verification/manifest.sha256`. Record the exact verified preview URL and cleanup command, but retain the durable application independently of the temporary preview lifecycle.

## Deterministic manifest procedure

Build each manifest from the same canonical included file classes: application source, required assets, configuration files needed to build or run, dependency lockfiles, and tests. Include every regular file in those classes recursively; do not select files based on modification time or local Git state.

Exclude generated build directories, cache directories, dependency directories, coverage output, logs, operating-system metadata, editor metadata, temporary files, secrets, local environment files, and preview runtime state such as ports, process identifiers, browser profiles, or cleanup metadata. Document any framework-specific exclusion before comparison and apply it identically to both trees.

Normalize all included paths into POSIX relative paths rooted at the compared application directory. Reject absolute paths, `..` traversal, duplicate normalized paths, and symbolic links that escape that root. Hash file bytes with SHA-256. Emit one lowercase record as `<sha256>  <path>` with exactly two spaces, sorted lexicographically by path under a byte-stable locale.

Require identical normalized file sets and identical hashes between the temporary and durable manifests. On failure, report every missing, extra, or hash-mismatched path in `verification/09-verification-report.md`; preserve both manifests as raw evidence and block the durability gate.

## Failure handling

On failure, preserve completed artifacts and raw evidence. Record audit findings in `08-audit-report.md`; record the failed gates, exact commands, outputs, and actionable remediation in `09-verification-report.md`; and retain `manifest.sha256` evidence when manifest work began. Keep the last valid catalog state, do not call the topic complete or verified, and resume at the failed gate only after the cause is fixed. Rerun every downstream check affected by the change.
