---
name: ps-release-workflow-epic-fanout
description: |
  Use AFTER an epic (E-NNN) has a solid spec, to split it into slices in a
  ps-release-workflow repo. Mints one IDEA per slice, tagged to the epic, and
  commits them on the release branch via the _release worktree. Never mints a
  feature. After this skill: brainstorm each slice into its own approved spec
  before refining it.
---

# ps-release-workflow:epic-fanout

Split an epic into slices: one idea `I-NNN` per slice, each tagged with the epic id.

## Precondition

The epic exists (`psrw epic open`) and its `spec.md` names the slices.

## Run

    psrw epic fanout E-001 "Slice one" "Slice two" "Slice three"

## Then

Fanout mints **ideas, never features**. Each slice still needs its own brainstorm
and approved spec before `psrw refine I-NNN`. Do NOT chain fanout -> refine -> claim.
Once every slice has shipped, the repo's `hooks.epic_check` script runs against the
combined tree (`psrw epic verify E-NNN` to re-run it by hand). `E-NNN/verification.md`
is the human-written statement of what must be true; no code reads it.

## Refuses if

- no release is in progress
- the epic id does not exist
- no slice titles are given

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#state-layout`
Flags: `psrw epic --help`
