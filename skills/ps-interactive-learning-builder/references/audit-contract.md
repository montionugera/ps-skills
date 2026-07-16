# Independent Audit Contract

Assign an isolated reviewer who did not author the application. Give the reviewer the topic project, source records, acceptance matrix, application, and raw test evidence without the builder's conclusions. Ensure the builder or author of a remediation cannot be the sole auditor of that work.

Audit all five dimensions:

1. **Source and factual integrity:** Check authority, evidence coverage, freshness, claim accuracy, uncertainty, and citation fidelity.
2. **Learning effectiveness:** Check learner fit, prerequisite order, measurable objectives, cognitive load, exercise quality, feedback, and assessment alignment.
3. **Technical and security quality:** Check reproducible builds, input validation, dependency risk, secrets, unsafe rendering, privacy, performance, and maintainability.
4. **Accessibility and user experience:** Check keyboard access, semantics, contrast, reduced motion, responsive layout, navigation, readability, and interaction clarity.
5. **Traceability and reproducibility:** Check the complete source-to-evidence mapping, deterministic instructions, durable-preview equivalence, and sufficiency of verification evidence.

Classify every finding as `critical`, `high`, `medium`, or `low`, cite raw evidence, identify affected artifacts and gates, and prescribe an actionable disposition. Critical and high findings block the `audited` state. Medium and low findings require an explicit disposition in `verification/08-audit-report.md` even when accepted without remediation.

After remediation, rerun every affected build, test, browser, manifest, and audit check. Require independent re-audit for critical or high fixes and for changes that alter claims, learning alignment, security boundaries, accessibility-critical behavior, or durable-preview equivalence. Preserve earlier findings and append disposition evidence rather than erasing audit history.
