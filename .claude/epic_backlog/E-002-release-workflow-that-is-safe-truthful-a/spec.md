---
title: "Release workflow that is safe, truthful and cheap to run"
id: E-002
status: epic
---

# Release workflow that is safe, truthful and cheap to run

## Outcome

Once every slice has shipped:

- Two sessions on one machine cannot edit each other's claimed worktree: the guard tells them apart.
- Cleanup cannot lose uncommitted or unmerged work, and cannot push stray files to main.
- `psrw status` always names the true next step, including for a release that is finalized but not yet merged.
- A release goes from "promote" to "next release open" with one command.
- An unchanged tree is not gated twice.

## Evidence (audit of 2026-10-04, last 14 days)

- 12 claims checked line by line in the engine: 10 confirmed, 2 partly true, 0 refuted.
- 228 session transcripts across 10 adopted repos; 98 commits and 29 merged pull requests since 2026-09-20.
- Every claim in every repo carries the same owner id (`claude-a6c35399`): `lib/owner.py:39-45` reads only `CLAUDE_SESSION_ID`, which is unset in current sessions.
- Cleanup force-removes worktrees and force-deletes branches with no dirty or ahead check (`scripts/promote_release.py:959-971, 1019-1031`), stages everything in the main checkout and pushes to main (`:890-897`), and hard-resets local main (`:1055-1059`).
- 22 `commit_all` call sites stage everything in the `_release` worktree.
- State locks live in `tempfile.gettempdir()` (`lib/state.py:26-28`): two directories on this machine, 40 and 5,148 files, never pruned.
- Only ship and sync-main honour the release freeze; `--babysit` merges a finalize commit no check ran on.
- Ship runs Gate 1 twice with no cache, the second time inside the `_release` lock (up to 3,600 s wait).
- Live case, release 1.9: finalized 2026-10-01, its pull request sat open for 3 days with a red check and 10 commits behind main. `psrw status` said "last promoted: 1.8" and hinted `--cleanup-only 1.8` (`scripts/status.py:219`). `psrw sync-main` answered "No release in progress — nothing to sync", so a finalized release had no supported way to pick up main; it was merged with plain git.
- Engine size today: 6,553 lines of code, 840 lines across 17 skills, 8,542 lines of tests.

## Opportunity score

Score = Impact x Reach x Confidence / Effort (Impact, Reach, Effort 1-5; Confidence 0.5-1.0).

| Proposal | Impact | Reach | Conf. | Effort | Score | Decision |
|---|---|---|---|---|---|---|
| Session-true claim ownership | 5 | 5 | 1.0 | 2 | 12.5 | Slice 1 |
| Safe cleanup and explicit staging | 5 | 4 | 1.0 | 3 | 6.7 | Slice 2 |
| One lock directory, pruned | 3 | 3 | 0.7 | 1 | 6.3 | Folded into slice 2 |
| Truthful status and one-command release tail | 4 | 5 | 0.9 | 3 | 6.0 | Slice 5 |
| Freeze on every verb, re-check before merge, drift | 4 | 3 | 0.8 | 2 | 4.8 | Slice 3 |
| Gate result cache and single gate runner | 3 | 4 | 0.8 | 3 | 3.2 | Slice 4 |
| Pre-flight checks (dirty tree, refine readiness) | 2 | 3 | 0.8 | 2 | 2.4 | Deferred |
| Guard covers shell writes, fails closed | 3 | 3 | 0.6 | 4 | 1.4 | Deferred |
| Remove per-script boilerplate | 2 | 2 | 0.7 | 3 | 0.9 | Deferred (optional slice 6) |

## Slices

Build order is the list order. Slice 2 creates the shared helper that slices 3 and 4 build on; slice 5 automates cleanup, so it comes after cleanup is safe.

1. Session-true claim ownership: owner id from `CLAUDE_CODE_SESSION_ID`, guard compares the marker's session id, unclaim refuses on mismatch.
2. Safe release transaction and cleanup: one `release_txn` helper (lock, mutate catalog, commit named paths), cleanup skips and reports dirty or ahead worktrees, locks move to `~/.cache/psrw/locks` with pruning.
3. Freeze and drift invariants: every backlog verb honours the freeze, finalize happens before the check watch, a finalized-but-unmerged release can still sync main, status shows how far the release is behind main.
4. Gate result cache and single gate runner: one `run_gate` in `lib/`, pass cache keyed by tree hash plus gate-script hash, deploys inside the slot limit, slot wait time logged.
5. Truthful status and one-command release tail: status reads the real pull request state and version and flags old claims and ideas, `psrw full-promote` chains watch, merge, deploy watch, cleanup and new-release, one hints table.

## Migration

- One install covers all repos: the engine lives under `~/.claude/ps-release-workflow/`; re-running `install.sh` updates every adopted repo. No per-repo file changes.
- Slice 1: existing claims carry the legacy shared id. For one release the guard accepts it with a warning, `claim --resume` rewrites it, and status lists legacy-owner claims. After that release the legacy id is rejected. The two tests that pin the weak behaviour are inverted.
- Slice 2: scripts start per command, so the new lock directory applies right after install; the installer deletes the two old lock directories. Cleanup changes from "delete" to "skip and report", with an explicit override flag.
- Slice 3: backlog verbs refuse during a promote, with a "retry after cleanup" hint.
- Slice 4: the cache sits in the git-ignored state directory and `PSRW_GATE_CACHE=0` disables it. Gate 2 is cached only for an identical release head.
- Slice 5: skill names are unchanged; the full-promote skill body shrinks to call the new verb.
- Rollback: each slice is one feature merge; revert it and re-run the installer.

## Size estimate (estimates from measured line ranges, no prototype)

| Slice | Removed | Added | Net |
|---|---|---|---|
| 1 Ownership | 0 | 25 | +25 |
| 2 Transaction and cleanup | 115 | 90 | -25 |
| 3 Freeze and drift | 0 | 50 | +50 |
| 4 Gate cache | 90 | 60 | -30 |
| 5 Status and full-promote | 135 to 170 (mostly skill text) | 150 | -20 to +15 |
| Total | 340 to 375 | 375 | about flat (0 to +35) |

The five slices are safety work and roughly break even in size. A net cut of 150 to 200 lines (2 to 3 percent of the engine) needs the deferred boilerplate slice. Tests grow by an estimated 400 to 500 lines.

## Expected improvement

| Axis | Today | Target |
|---|---|---|
| Unexpected behaviour | Cross-session guard never fires; 3 confirmed ways for cleanup to lose or leak work; 5,188 stale lock files | Guard separates sessions; none of those paths remain, each covered by a test; no stale lock files |
| Unexpected behaviour | Backlog commits trip a refusal mid-promote; merged head unchecked; finalized release cannot sync main | Refused up front with a hint; merged head is the checked head; sync works until merge |
| Efficiency | Gate 1 runs twice per ship; Gate 2 repeats on an unchanged head | One run for an unchanged tree; time saved is unmeasured until slice 4 logs waits |
| Efficiency | Release tail is about 5 manual agent steps with permission denials | One command |
| Utilization | Status hint wrong or stale in 4 of 10 repos; no age signals | Hint derived from real state; old claims and ideas flagged |

## Not verified

- Time saved by the gate cache: no wait or duration data exists yet.
- The lock failure across two temp directories is inferred from code, not reproduced.
- The installed engine copy was not compared against the repo copy.
- `epic.py`, `hotfix.py`, `promote_idea_to_refined.py` and `new_idea.py` were not audited.
- This spec has not had an independent review.
