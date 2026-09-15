---
name: ps-release-workflow-cleanup-legacy
description: |
  Use when a ps-release-workflow repo has accumulated old worktrees created
  outside the toolkit (no working-feature.json marker). Interactively lists
  each marker-less worktree, shows whether its branch is merged to main, and
  prompts keep/remove. A one-off housekeeping tool.
---

# ps-release-workflow:cleanup-legacy

Interactively garbage-collect marker-less ("legacy") worktrees. One-off housekeeping.

## Run

There is no `psrw` verb for this yet — invoke the script directly:

    python3 ~/.claude/ps-release-workflow/scripts/cleanup_legacy_worktrees.py

## What it does

1. Scans `.claude/worktrees/` for dirs that lack a `working-feature.json` marker (skips
   the long-lived `_release` worktree).
2. Resolves each one's branch and checks whether it is merged to `main`.
3. Prints each legacy worktree with its branch and `merged to main` / `NOT merged`.
4. Prompts `[k]eep / [r]emove / [s]kip` per worktree; `r` runs
   `git worktree remove --force`.

## Then

Nothing — a one-off housekeeping command.

## Refuses if

Repo not opted into ps-release-workflow (no `.release.json`).

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#state-layout`
