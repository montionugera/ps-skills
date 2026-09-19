# Batch E (epic skills, status rollup, docs) — review-fix closure

**Goal:** Fix the confirmed review findings on Batch E of the psrw epic layer,
verify, and commit. Findings A-F below; each was checked against the code first.

| # | Finding | Resolution |
|---|---|---|
| A | `psrw status` printed promoted epics forever (epic entries are never pruned). | `render_full` now lists only epics whose status is not `promoted` and adds `(+N promoted epic(s) omitted)`, mirroring the feature table. The structured `epics` key stays complete, as `features` does. Tests: promoted omitted + count line; in-flight epic shown; only-promoted shows no table. |
| B | An idea with `promoted_to` set but no matching refined-catalog entry rendered as `idea`, hiding drift that later hard-blocks `psrw promote`. | Such a slice now reports status `missing` (id = the `promoted_to` feature id) and adds a `warnings` entry. Slices with `promoted_to` None stay `idea`. Tests: missing feature -> `missing` + warning; unpromoted stays `idea` with no warning. |
| C | Two rollup tests were vacuous (no feature folders read; no epic in the legacy fixture). | `test_rollup_does_not_assume_plan_md_exists` builds real feature folders and covers plan.md deleted, empty folder, and folder gone. `test_rollup_tolerates_legacy_entries_without_epic_key` now has a real epic alongside legacy ideas/features and asserts they are excluded from its counts and sibling list. |
| D | Fanout skill claimed the epic outcome is checked against `E-NNN/verification.md`; no code reads that file. | Reworded: the repo's `hooks.epic_check` runs; `verification.md` is the human-written statement. Same clarification added to the epic-open skill. Bodies stay <= 40 non-blank lines, anchor unchanged. |
| E | `lifecycle.md` said gates run the outcome check "only once the epic is complete", but `psrw epic verify` never checks completeness. | Reworded: completeness gates the automatic runs (`ship` trigger, `promote` refusal); hand-run `epic verify` skips it. Hooks table needed no change. No code behaviour changed. |
| F | `known-issues.md` said a crashed check strands the epic in `verifying`. | Reworded: exceptions are recorded as `failed_verification`; only a hard process kill (SIGKILL, power loss) strands it. `lifecycle.md` "crashed run" changed to "hard-killed run". |

**Not fixed by design:** "new headings are new anchors" (subheadings under the
permitted anchors are intended); `scripts/epic.py` empty-title SlugError (filed separately).
