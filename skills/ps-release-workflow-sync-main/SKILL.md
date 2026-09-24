---
name: ps-release-workflow-sync-main
description: |
  Use when a hotfix (or any commit) has landed on main while a release is in
  progress in a ps-release-workflow repo, and release/<v> should carry it now
  — before the next ship or promote, e.g. to redeploy locally or because
  `psrw status` says "behind origin/main (hotfix pending sync)". Merges main
  into release/<v> via the _release worktree and verifies it with Gate 1.
---

# ps-release-workflow:sync-main

Absorb `main` (squash-merged hotfixes) into `release/<v>` on demand.

## Run

    psrw sync-main            # merge main into release/<v>, then Gate 1
    psrw sync-main --deploy   # ...then run the local deploy from _release

`psrw hotfix --sync-release [--deploy]` is an alias for the same code path. `--deploy`
warns when Gate 1 did not run (no precheck script).

## What matters

- `ship` and `promote` already sync `main` before they merge, deploy or gate; use this
  when the release must carry the hotfix sooner (a local redeploy, for example).
- Gate 1 (`precheck.sh`) runs from `_release` on the synced tree; a failure rolls the
  sync back to the previous release head.
- No-op when `release/<v>` already contains `main`, or when no release is in progress.

## Refuses if

The merge conflicts, or `main` changed release bookkeeping (`.release.json`, backlog
dirs); both print the exact manual `git merge` · the release is frozen for promote
(re-run promote instead) · Gate 1 fails (rolled back).

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#gates`
Flags: `psrw sync-main --help`
