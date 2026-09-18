---
name: ps-release-workflow-epic-open
description: |
  Use BEFORE capturing work that is bigger than one feature in a
  ps-release-workflow repo — an outcome that will take several features to
  deliver. Creates E-NNN-<slug> with spec + verification skeletons and commits
  the epic entry on the release branch via the _release worktree.
  After this skill: brainstorm the epic spec into a SOLID outcome statement
  FIRST, then fan it out with ps-release-workflow-epic-fanout.
---

# ps-release-workflow:epic-open

Open an epic: one outcome, delivered by several features, verified as a unit.

## Precondition

A release must be in progress (`psrw new-release` first) — epic metadata commits
route through the `_release` worktree.

## Run

    psrw epic open "<title>"

## Then

Brainstorm `E-NNN/spec.md` until the outcome and its slices are solid. Write
`E-NNN/verification.md` — what must be true once every slice has shipped.
Only then fan out. Never auto-chain open -> fanout -> refine -> claim.

## Refuses if

- no release is in progress
- the title is empty

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#state-layout`
Flags: `psrw epic --help`
