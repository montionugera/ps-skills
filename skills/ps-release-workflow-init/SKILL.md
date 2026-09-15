---
name: ps-release-workflow-init
description: |
  Use ONCE per new repo to opt that repo into the ps-release-workflow.
  Creates .release.json, idea_backlog/, refined_backlog/, gitignores
  the state dir. Idempotently installs the global routing convention
  to ~/.claude/CLAUDE.md. Commits the opt-in.
---

# ps-release-workflow:init

Opt the current repo into ps-release-workflow. Run ONCE per repo.

## Run

    cd /path/to/repo
    psrw init

## What it does

1. Creates `.release.json` (version=1.0, in_progress=false).
2. Creates empty `.claude/idea_backlog/_catalog.json` and
   `.claude/refined_backlog/_catalog.json`.
3. Extends `.gitignore` with `.claude/state/` and `.claude/worktrees/`.
4. Installs the routing convention into `~/.claude/CLAUDE.md` (idempotent — skipped if
   already present).
5. Commits the opt-in as `chore: adopt ps-release-workflow`.

## Then

Open the first release: `psrw new-release`.

## Refuses if

`.release.json` already exists — subsequent runs error with `AlreadyInitializedError`.

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#state-layout`
Flags: `psrw init --help`
