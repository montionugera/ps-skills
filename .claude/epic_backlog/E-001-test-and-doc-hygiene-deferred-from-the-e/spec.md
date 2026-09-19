---
title: "Test and doc hygiene deferred from the epic-run review"
id: E-001
status: epic
---

# Test and doc hygiene deferred from the epic-run review

## Goal (one sentence)

Close three small hygiene items that the F-002 (`epic run`) review deferred, touching only engine tests and skill/docs
text, so that the pilot proves the `epic run` mechanics (refine, claim, sync, ship, stop rules) on real but low-risk work.
This is the FIRST pilot of `epic run`. Repo: `/Users/pasitnusso/ps-skills`, release 1.1, engine at
`.claude/worktrees/_release/engine/ps-release-workflow/`.

## Outcome

What is true once all slices have shipped on release/1.1:

- No private `_git` helper remains in the engine tests; one shared helper is in `tests/_helpers.py` (S1).
- The two untested `epic plan` refusal branches have tests; the known-issues bullet is corrected (S2).
- `skills/ps-release-workflow-refine/SKILL.md` describes what refine does now; its known-issues bullet is removed (S3).
- Full engine suite from `engine/ps-release-workflow`: `python3 -m pytest tests -q` = `468 passed, 2 skipped`
  (baseline 465 passed, 2 skipped; S1 +0, S2 +2, S3 +1).
- No file under `scripts/` or `lib/` is changed by any slice (the chain never edits code it executes).

## Slices

Fanout order IS chain order. Slice titles are as passed to `psrw epic fanout` (they differ slightly from the working titles
in the draft; the specs are unchanged).

| # | Slice idea title | Working name | Files touched | ~Size |
|---|---|---|---|---|
| 1 | Share one git test helper | S1 shared git helper | new `tests/_helpers.py`; 3 test files | ~32 lines |
| 2 | Cover the untested epic plan refusals | S2 untested refusals | new `tests/test_epic_plan_refusals.py`; `docs/known-issues.md` | ~40 lines |
| 3 | Fix the stale refine skill text | S3 refine skill text | refine `SKILL.md`; `tests/test_epic_run_skill.py`; `docs/known-issues.md` | ~20 lines |

Dependencies, honestly: S2 imports the helper S1 creates (a real import, so a failed `epic sync` shows as a red test), but the
dependency is ENGINEERED, not semantic; S3 is independent and is placed last only so it is the slice whose ship completes the
epic. Reordering S3 first would work equally well. All slices edit `engine/ps-release-workflow/docs/known-issues.md` (S2 line 36,
S3 line 27) at different bullets.

## Epic verification (what will actually happen: nothing runs)

ps-skills has no `scripts/` directory, so there is no `scripts/epic-check.sh` (the epic outcome check) and no
`scripts/precheck.sh` (Gate 1). Verified in code (`lib/epic_gate.py:24-64`, `lib/epic_gate.py:135-137`):

- When the last slice ships, the epic's outcome check is looked up at `hooks.epic_check` (default `scripts/epic-check.sh`),
  found missing, and a stderr warning `hooks.epic_check not found ... outcome check SKIPPED` is printed. The ship result
  carries `epic_outcome: {"epic": ..., "rc": null, "sha": ...}`.
- SURPRISE: `run_and_record` treats `rc is None` the same as `rc == 0` and calls `mark_epic_verified`. So the epic catalog
  entry will read `status: verified` even though NO check ran. The only trace is the stderr warning and `rc: null`.
  The `epic-run` skill (line 57) instructs the driver to report `rc` null as "unverified, check skipped", never as success.
  The catalog will disagree with that wording; trust the `rc: null`, not the status.
- Gate 1 is likewise skipped with a warning on every ship, and `epic plan` needs `--allow-no-precheck`.

Consequence: the ONLY enforced test gate in this pilot is the pytest step in the `epic-run` skill (prose), plus the human's
post-run re-run. The epic's real verification is therefore MANUAL; see `verification.md`.

Do NOT add a `scripts/epic-check.sh` or `precheck.sh` to make this look automated: adding a precheck sends a Gate 1 failure
through the known ship rollback defect (`git reset --hard HEAD~1`), and it would be a code change on the chain's own path.

## Pilot stop rule (the chain stops, and no one resumes without a human decision, on ANY of these)

1. Any gate failure: `epic plan` refusal, `epic sync` conflict, whole-slice review still failing after 2 rounds, red or
   unclean tree, empty diff, non-zero `psrw ship --no-deploy`.
2. A mandatory step is skipped: the per-slice `epic plan` re-run, the plan self-audit, the independent whole-slice review of
   `git diff <base> HEAD`, the full-suite pytest tail pasted to the ledger. A skipped step is a pilot failure even if the code is fine.
3. Out-of-scope files: `git diff --stat <base> HEAD` for a slice shows any path not in that slice's Scope list, or any path under
   `scripts/` or `lib/`.
4. A second tab or session is found operating on the epic (or any claim/ship/hotfix in ps-skills runs during the pilot).
5. Also stop on: any slice taking more than 2x the wall-clock of the previous one or over 3 hours; any push, PR, promote,
   `--deploy`, `--amend`, or hand edit of a `_catalog.json`; subagent nesting refused.

Never promote as part of the pilot; release/1.1 stays unpromoted.

## Approval gates (nothing runs before these)

1. Human approves this epic spec (approved as drafted).
2. Human approves each of the three slice specs (approved as drafted).
3. Human pastes the exact allowlist, `--slices <I-a>,<I-b>,<I-c>` (ids read from the fanout output), into the run instruction.
   That paste is the authorization to start the chain; run as `epic run E-001 --slices ... --allow-no-precheck`.
