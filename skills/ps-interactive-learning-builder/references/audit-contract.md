# Independent Audit Contract

Assign independent coverage for every artifact and audit dimension. Provide the research strategy and source records; claims and knowledge map; curriculum, build specification, and acceptance matrix; application source and assets; test and browser evidence; and traceability and manifest evidence without the builder's conclusions. Assign each item to a reviewer who did not author or approve that item. No artifact or audit dimension may be accepted solely by its author.

Before review, make each auditor declare authorship, prior approval, implementation, remediation, and reporting involvement for the assigned scope. Treat any overlapping responsibility that could bias acceptance as an independence conflict; record the conflict and affected artifacts or dimensions in `verification/08-audit-report.md`, then assign a different auditor before accepting that scope. Permit several independent auditors to cover the project; require complete coverage rather than assuming one application's reviewer is independent of research or curriculum.

Audit all five dimensions:

1. **Source and factual integrity:** Check authority, evidence coverage, freshness, claim accuracy, uncertainty, and citation fidelity.
2. **Learning effectiveness:** Check learner fit, prerequisite order, measurable objectives, cognitive load, exercise quality, feedback, and assessment alignment.
3. **Technical and security quality:** Check reproducible builds, input validation, dependency risk, secrets, unsafe rendering, privacy, performance, and maintainability.
4. **Accessibility and user experience:** Check keyboard access, semantics, contrast, reduced motion, responsive layout, navigation, readability, and interaction clarity.
5. **Traceability and reproducibility:** Check the complete source-to-evidence mapping, deterministic instructions, durable-preview equivalence, and sufficiency of verification evidence.

Classify every finding as `critical`, `high`, `medium`, or `low`, cite raw evidence, identify affected artifacts and gates, and prescribe an actionable disposition. Critical and high findings block the `audited` state. Medium and low findings require an explicit disposition in `verification/08-audit-report.md` even when accepted without remediation.

After remediation, rerun every affected build, test, browser, manifest, and audit check. Require independent re-audit for critical or high fixes and for changes that alter claims, learning alignment, security boundaries, accessibility-critical behavior, or durable-preview equivalence. Ensure the builder or author of a remediation cannot be the sole auditor of that work. Preserve earlier findings and append disposition evidence rather than erasing audit history.
