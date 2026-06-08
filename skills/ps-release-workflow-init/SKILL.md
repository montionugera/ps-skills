---
name: ps-release-workflow-init
description: |
  Use ONCE per new repo to opt that repo into the ps-release-workflow.
  Creates .release.json, idea_backlog/, refined_backlog/, gitignores
  the state dir. Idempotently installs the global routing convention
  to ~/.claude/CLAUDE.md. Commits the opt-in.
---

# ps-release-workflow:init

Opt the current repo into ps-release-workflow.

## What it does

1. Creates `.release.json` (version=1.0, in_progress=false)
2. Creates `.claude/idea_backlog/_catalog.json` and `.claude/refined_backlog/_catalog.json` (empty)
3. Extends `.gitignore` with `.claude/state/` and `.claude/worktrees/`
4. Installs the routing convention to `~/.claude/CLAUDE.md` (idempotent — skipped if already present)
5. Commits the opt-in as `chore: adopt ps-release-workflow`

## Usage

```bash
cd /path/to/repo
python3 ~/.claude/ps-release-workflow/scripts/init_repo.py
```

## When to use

- A new repo (or existing repo) needs to start using the workflow.
- Run ONCE per repo. Subsequent runs error with `AlreadyInitializedError`.

## Refuses if

- `.release.json` already exists.
