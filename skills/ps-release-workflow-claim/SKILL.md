---
name: ps-release-workflow-claim
description: |
  Use BEFORE implementing a refined feature (F-NNN) in a ps-release-workflow
  repo. Atomically claims the feature for your session and creates an isolated
  per-feature worktree with a working-feature.json owner marker. Also use with
  --resume to re-own an already-claimed feature (fresh session resuming
  in-flight work, or after the guard blocks with "claim --resume F-NNN").
  After this skill: hint to implement via /subagent-driven-development.
---

# ps-release-workflow:claim

Claim a refined feature and get an isolated worktree to build it in.

## Precondition — deliberate gate

Claim only a feature that already has an **approved spec** (under
`docs/superpowers/specs/`) and a **written plan**. **Never auto-chain
idea -> refine -> claim** — each is a separate, human-approved step.

## Run

    psrw claim F-NNN
    psrw claim --next            # pick the next unclaimed feature automatically
    psrw claim --resume F-NNN    # re-own / recreate an ALREADY-claimed feature

A plain claim re-attaches to an existing `feat/F-NNN` branch if there is one — prior
commits stay intact — because `psrw unclaim` **always keeps the branch**.

## `--resume F-NNN`

Use when the feature is already status `claimed` but this session does not own it, or
its worktree is gone:

- **Fresh session resuming in-flight work** — the guard blocks edits and points here.
  Resume rewrites the owner in both `working-feature.json` and `claims.json`.
- **Worktree deleted out-of-band** (drift) — recreates it on the surviving
  `feat/F-NNN` branch, or off `main` if the branch is gone too.
- Refuses if the feature is not status `claimed` — resume re-owns existing claims, it
  never creates new ones.

To abandon a claim instead of resuming it: `psrw unclaim F-NNN`.

## Then

Implement via `/subagent-driven-development` (it reads the F-NNN `plan.md`).

## Refuses if

No release in progress · the feature is already claimed · `--next` with no free feature.

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#d11-backlog-routing`
Flags: `psrw claim --help`
