---
name: ps-release-workflow-cleanup-legacy
description: |
  Use when a ps-release-workflow repo has accumulated old worktrees created
  outside the toolkit (no working-feature.json marker). Interactively lists
  each marker-less worktree, shows whether its branch is merged to main, and
  prompts keep/remove. A one-off housekeeping tool.
---

# ps-release-workflow:cleanup-legacy

Interactively garbage-collect marker-less ("legacy") worktrees.

## Usage

```bash
python3 ~/.claude/ps-release-workflow/scripts/cleanup_legacy_worktrees.py
```

## What it does

1. Scans `.claude/worktrees/` for worktree dirs that lack a `working-feature.json` marker (skips the long-lived `_release` worktree).
2. For each, resolves the branch name and checks whether it is merged to `main`.
3. Prints each legacy worktree with its branch and `merged to main` / `NOT merged` status.
4. Prompts `[k]eep / [r]emove / [s]kip` per worktree; `r` runs `git worktree remove --force`.

## Hand-off

None — a one-off housekeeping command.

## Refuses if

- Repo not opted into ps-release-workflow (no `.release.json`).
