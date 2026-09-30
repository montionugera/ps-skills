# Fix 3 red docs-style skill tests (I-017)

**Goal:** make `engine/ps-release-workflow/tests/test_docs_single_source.py` fully green on main without changing any skill behaviour.

## Failures (identical on main before release 1.9)

| Test | Skill | Cause |
|---|---|---|
| `test_skill_body_is_within_budget` | `ps-release-workflow-promote` | 47 non-blank body lines, budget 40 |
| `test_skill_body_is_within_budget` | `ps-release-workflow-ship` | 45 non-blank body lines, budget 40 |
| `test_skill_links_to_lifecycle_or_needs_no_mechanics` | `ps-release-workflow-sync-main` | links to `lifecycle.md#main-sync-mechanics`, a real anchor that is missing from the test's `ANCHORS` list |

## Design

1. **sync-main:** add `main-sync-mechanics` to `ANCHORS` in the test. The anchor already exists at `docs/lifecycle.md` (`<a id="main-sync-mechanics">`). No skill edit. Also check `test_lifecycle_doc_has_every_anchor` still passes.
2. **promote and ship:** cut each SKILL.md body to 40 non-blank lines or fewer by moving explanatory mechanics into the matching `docs/lifecycle.md` section (`promote-sequence` for promote; `gates` or `main-sync` for ship), leaving a `lifecycle.md#<anchor>` link. Keep every `psrw` command, flag and "Refuses if" line the skill needs; move only prose that explains how it works.

## Out of scope

Changing `LINE_BUDGET`, changing engine code, touching `full-promote` (exempt).

## Verification

- `pytest engine/ps-release-workflow/tests/test_docs_single_source.py` reports 0 failed.
- Full `pytest engine tests` shows no new failures versus the 788 passed baseline.
- README update: none needed, because no capability, endpoint, env var or migration changes.

## Reversibility

Docs and one test constant only. Revert with a normal `git revert`.
