# Research — Epic layer

The spec in `spec.md` is the output of three review rounds, not a first draft.
Full provenance and the reviewers' raw findings live in the working copies:

- Design: `~/workspace/tools/research/2026-09-18-psrw-epic-workflow-design.md` (+ `.html`)
- Plan: `~/workspace/tools/research/2026-09-18-psrw-epic-workflow-plan.md` (+ `.html`)
- Handoff: `~/workspace/tools/research/2026-09-18-psrw-epic-handoff.md`

## Review rounds

1. **Adversarial audit of v1** — 3 blockers. The gate ran inside `ship` under the
   global lock with a rollback that would have erased the record of its own failure.
2. **Quality + efficiency review of v2** — verdict "needs rework". The gate still ran
   in the shared `_release` tree that concurrent ships mutate, and `verified` had no
   sha anchor. `slice_count`, the `fanned_out` state, and one of three skills were cut
   as unearned.
3. **Plan audit** — 3 blockers, all real API mismatches: `git_run` does not exist
   (it is `_run`), it returns a `CompletedProcess`, and `resolve_hook` returns an
   absolute path — so `snapshot / hook` silently discarded the snapshot.

Section 11 of `spec.md` carries every finding with its disposition.
