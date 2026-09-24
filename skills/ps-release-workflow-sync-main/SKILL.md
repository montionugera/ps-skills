---
name: ps-release-workflow-sync-main
description: |
  Use to absorb changes from `main` (such as squash-merged hotfixes) into
  the active `release/<v>` branch on demand, verifying the combined tree
  with Gate 1 (precheck.sh).
---

# ps-release-workflow:sync-main

Absorb commits from `main` (such as squash-merged hotfixes) into `release/<v>` under lock.

## Precondition

A release must be in progress (`.claude/worktrees/_release` exists).

## Run

    psrw sync-main              # sync origin/main into release/<v> and run Gate 1
    psrw sync-main --deploy     # ...and run local deploy on success
    psrw sync-main --strict     # fail if origin/main cannot be fetched over network
    psrw sync-main --no-gate1   # skip Gate 1 verification (emergency only)

## What it does

1. Resolves `origin/main` SHA (fetches remote `origin/main` if remote exists).
2. Under `file_lock(_release)`:
   - Records `pre_sha = rev-parse HEAD`.
   - Checks ancestry: if `release/<v>` already contains `main`, no-ops cleanly.
   - Checks protected paths: refuses if changes on `main` touch `.release.json` or `.claude/*_backlog`.
   - Merges `main` into `release/<v>` (`--no-ff`).
   - Runs Gate 1 (`precheck.sh`) on `_release`.
   - **Atomic rollback**: If Gate 1 fails or merge errors occur, resets to `pre_sha`.
3. If `--deploy` is passed, runs local deploy from `_release`.

## Feature branches

To propagate the absorbed hotfix into your in-flight feature branch worktree:

    psrw sync

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#main-sync-mechanics`
Flags: `psrw sync-main --help`
