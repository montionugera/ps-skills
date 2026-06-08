---
name: ps-release-workflow-claim
description: |
  Use BEFORE implementing a refined feature (F-NNN) in a ps-release-workflow
  repo. Atomically claims the feature for your session and creates an isolated
  per-feature worktree with a working-feature.json owner marker. After this
  skill: hint to implement via /superpowers:subagent-driven-development.
---

# ps-release-workflow:claim

Claim a refined feature and get an isolated worktree to build it in.

## Precondition — spec + plan ready (deliberate gate)

Claim only a feature that already has an **approved spec** (under
`docs/superpowers/specs/`) and a **written plan** (`/superpowers:writing-plans`).
Claiming cuts a real worktree + branch; doing it before the design is settled
wastes that setup and risks throwaway code. **Never auto-chain
idea -> refine -> claim** — each is a separate, deliberate, human-approved step.

## Usage

```bash
python3 ~/.claude/ps-release-workflow/scripts/init_work_refined_backlog.py F-NNN
# or pick the next unclaimed feature automatically:
python3 ~/.claude/ps-release-workflow/scripts/init_work_refined_backlog.py --next
```

## What it does

1. Atomically records the claim in `.claude/state/claims.json` (owner = your `$CLAUDE_SESSION_ID`).
2. Creates a per-feature worktree under `.claude/worktrees/F-NNN-<slug>/` off `release/<v>`.
3. Writes the `working-feature.json` owner marker into the worktree's gitdir (the guard reads this).
4. Marks the feature claimed in the refined catalog via the `_release` worktree (D11).

## Hand-off

Prints: `Worktree created. Implement: /superpowers:subagent-driven-development` (reads the F-NNN plan.md).

## Refuses if

- No release in progress.
- The feature is already claimed (by you or someone else).
- `--next` with no free (unclaimed) feature available.
