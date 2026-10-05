---
title: "Worktree GC and claim reopen for ps-release-workflow"
id: F-019
status: refined
from_idea: I-025
---

# Worktree GC and claim reopen for ps-release-workflow

## Problem
In `ps-release-workflow` repos, `psrw claim` creates isolated worktrees under `.claude/worktrees/<F-NNN>-<slug>`. When a feature ships, `psrw ship` merges the feature into `release/<v>`, but leaves the worktree directory on disk until `psrw promote`. For releases spanning dozens of features over weeks (such as `joy-companion`'s `release/1.16` with 35 features), worktrees accumulate linearly, consuming 30–50+ GB of disk space. Furthermore, `cleanup_legacy_worktrees.py` is currently disabled in `NON_VERBS` and only checks for missing markers, and `psrw claim --resume` refuses to recreate worktrees for already-shipped features if a fix is needed prior to release promotion.

## Why now
A deep system disk audit revealed that 81+ GB of disk space was hoarded by uncleaned worktrees and caches. Implementing worktree garbage collection (`psrw gc`) and safe post-ship teardown (`psrw ship` teardown with `psrw claim --reopen`) is necessary to permanently prevent disk bloat across all repos using `ps-release-workflow`.

## Sketch
1. **Shared Safety Core (`lib/worktree_gc.py`)**:
   - `removable(repo, wt)` evaluates S1–S8 and L1–L3 checks against catalog status (`shipped`/`promoted` in `_release` or `main`), ensuring active/uncommitted work is never deleted.
   - Requires ignored files to match a regenerable allowlist (`node_modules`, `.venv`, `dist`, `build`, etc.).
2. **`psrw gc` Verb (`scripts/gc_worktrees.py`)**:
   - Registered as a first-class verb in `psrw`.
   - Default is a report-only dry-run; `--apply` executes deletions via `git worktree remove --force`.
   - Exposes `--json` for automation tools.
   - Refuses when release is frozen.
3. **`psrw claim --reopen F-NNN` (`scripts/init_work_refined_backlog.py`)**:
   - Recreates the worktree for a shipped feature from `feat/<F-NNN>`, writing the marker without resetting catalog status.
4. **`psrw ship` Teardown**:
   - Shipped feature worktrees are cleanly torn down as the final step of a 100% clean ship (with `--keep-worktree` override). Prints the release worktree path to `cd` into.

## Acceptance criteria
- [ ] `lib/worktree_gc.py` implements `removable(repo, wt)` returning safety verdicts for S1–S8 and L1–L3.
- [ ] `psrw gc` is registered in `bin/psrw` and defaults to a safe report-only dry-run.
- [ ] `psrw gc --apply` safely removes eligible worktrees using `git worktree remove --force` and drops claims.
- [ ] `psrw claim --reopen F-NNN` successfully recreates the worktree of a shipped feature from its kept branch.
- [ ] `psrw ship` automatically tears down its own worktree on clean completion unless `--keep-worktree` is specified.
- [ ] `psrw status` surfaces a "reclaimable worktree(s)" notice when eligible worktrees exist.
