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

## Run

    psrw new-release [--version X.Y]

## What it does

1. Determines the next version (auto-increment minor, or `--version X.Y`).
2. Creates the `release/<v>` branch off `main`.
3. Sets `.release.json` to `in_progress=true` at the new version.
4. Creates the long-lived `_release` worktree that idea / refine / claim / ship commit
   backlog metadata through.

## Then

Claim a feature: `psrw claim --next`.

## Refuses if

Repo not opted in · a release is already in progress · the requested `--version` is not
strictly greater than the current version.

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#d11-backlog-routing`
Flags: `psrw new-release --help`
