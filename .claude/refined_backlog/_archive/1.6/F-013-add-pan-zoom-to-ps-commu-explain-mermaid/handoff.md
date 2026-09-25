# Handoff: F-013 — Replace Mermaid with draw.io in ps-commu-explain

**Goal (verbatim):** "let go with drawio; create full plan with good deterministic
result" + "run full chain" — replace Mermaid with draw.io as ps-commu-explain's
infographic-tier diagram engine, planned and implemented with the same rigor F-011 used.

**Plan:** `.claude/refined_backlog/F-013-add-pan-zoom-to-ps-commu-explain-mermaid/plan.md`
**Spec:** `.claude/refined_backlog/F-013-add-pan-zoom-to-ps-commu-explain-mermaid/spec.md`
(self-grill-audited + Fable-reviewed, both passes' fixes already applied)

**Current state:** Plan written, self-reviewed, committed (`a1d144f` on `release/1.6`).
Not yet claimed (no `feat/F-013` worktree exists). Not yet self-grill-audited (next
step, per writing-plans' own execution-handoff requirement, before dispatching
subagent-driven-development).

**Next step:** Run `self-grill-audit` on the plan, apply CRITICAL/HIGH fixes, then
`psrw claim F-013` to get the worktree, then invoke `subagent-driven-development` to
execute the plan task-by-task (Task 0 first — it's a go/no-go gate; do not dispatch
Task 1 if Task 0 returns NO-GO).
