---
name: ps-release-workflow-refine
description: |
  Use BEFORE promoting a captured idea (I-NNN) into the refined backlog
  in a ps-release-workflow repo. Mints F-NNN, moves the folder, and commits
  on the release branch via the _release worktree. Refine ONLY an idea that
  already has a solid, approved spec — never auto-chain idea -> refine -> claim.
---

# ps-release-workflow:refine

Promote an idea (`I-NNN`) into a refined, plannable feature (`F-NNN`).

## Precondition — spec must be solid FIRST (deliberate gate)

Refine is a **promotion gate**, not a formatting step. The idea must already be
brainstormed with an **approved spec** under `docs/superpowers/specs/`. Do **NOT** run
idea -> refine -> claim as one automatic chain — promoting an under-specified idea mints
an `F-NNN` (and invites a premature claim + worktree) before the design is settled.

> ⚠️ Refine writes **fresh skeleton** `spec.md`/`plan.md`/`research.md` into the new
> `F-NNN` folder — it does **not** copy the idea folder's contents. Keep the canonical
> spec under `docs/superpowers/specs/`, where it travels with the feature branch.

## Run

    psrw refine I-NNN

## Then

`/writing-plans`, then `psrw claim F-NNN`.

## Refuses if

Repo not opted in · no release in progress · `I-NNN` not found in the idea catalog ·
idea already promoted.

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#d11-backlog-routing`
Flags: `psrw refine --help`
