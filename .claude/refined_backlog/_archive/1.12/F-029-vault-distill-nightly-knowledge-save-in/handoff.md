# I-040 handoff (I-039 slice 2: save in shadow mode)

Goal (owner, verbatim): "want it help auto save knowledge + auto retrieve knowledge to session", "make sure it is token efficient", "consider speed , session result, knowledge reusability , scale , robust, production grade", "visibility + readiness", "auto integrate + publish if pass".

Plan: `.claude/idea_backlog/I-040-vault-distill-nightly-knowledge-save-in/plan.md` (4 tasks, gates after Tasks 2 and 4, controller-only Go-live G1-G7). Spec: `spec.md` in the same folder.

State: plan written. Its code and tests were run in a scratch copy (72 unittest tests OK, e2e block OK against the real engine). Nothing is implemented in the repo; nothing is committed; no live change made.

Key call: the extractor is one `agy -p` print-mode call (no tools), not a `dispatch-worker` agent run. See plan Deviation 1. Go-live G4 verifies it with one real call.

Next:
1. `self-grill-audit` on plan.md; apply CRITICAL/HIGH fixes; note them in the Audit trail.
2. `psrw refine I-040`, then `psrw claim F-NNN`.
3. `subagent-driven-development` on the plan inside the claimed worktree.
4. Go-live G1-G7 by the controller only.
