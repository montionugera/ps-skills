---
name: ps-release-workflow-new-release
description: |
  Use BEFORE starting a new release cycle in a ps-release-workflow repo.
  Opens release/<v>, marks .release.json in_progress, and creates the
  long-lived _release worktree that backlog metadata commits route through.
  After this skill: hint to claim a feature.
---

# ps-release-workflow:new-release

Open a new release cycle.

## Usage

```bash
python3 ~/.claude/ps-release-workflow/scripts/init_work_new_release.py [--version X.Y]
```

## What it does

1. Determines the next version (auto-increment minor, or `--version X.Y`).
2. Creates the `release/<v>` branch off `main`.
3. Sets `.release.json` to `in_progress=true` at the new version.
4. Creates the long-lived `_release` worktree (used by idea/refine/claim/ship to commit backlog metadata onto `release/<v>`, per D11).

## Hand-off

Prints: `Claim a feature: /ps-release-workflow:claim --next`.

## Refuses if

- Repo not opted into ps-release-workflow (no `.release.json`).
- A release is already in progress.
- The requested `--version` is not strictly greater than the current version.
