---
name: ps-release-workflow-promote
description: |
  Use when the in-progress release is full and ready to go to main
  (release-manager only). Runs Gate 2 (integration.sh), squash-merges
  release/<v> into main, deploys, and auto-cleans worktrees + branches.
  Terminal step of the release lifecycle.
---

# ps-release-workflow:promote

Promote the in-progress release to `main` and deploy. **Release-manager only.**

## Usage

```bash
python3 ~/.claude/ps-release-workflow/scripts/promote_release.py --deploy --gate2
```

## What it does

1. Runs **Gate 2** (`integration.sh`) — the whole-release integration check.
2. Squash-merges `release/<v>` into `main`.
3. Deploys (`--deploy`).
4. Marks `.release.json` no longer in progress.
5. **Auto-cleans** on success: removes the per-feature worktrees and their branches (idempotent, worktree-before-branch). Pass `--keep` to skip cleanup.

## Hand-off

Prints: `Promoted to main; release auto-cleaned.` (terminal — the lifecycle is complete).

## Refuses if

- No release in progress.
- **Gate 2** (`integration.sh`) fails.
