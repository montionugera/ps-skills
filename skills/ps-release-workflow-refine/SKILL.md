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

Refine is a **promotion gate**, not a formatting step. Before running it, the
idea (`I-NNN`) must already be **brainstormed with an approved spec** (via
`/superpowers:brainstorming`, saved under `docs/superpowers/specs/`). Do **NOT**
run idea -> refine -> claim as one automatic chain — promoting an
under-specified idea mints an `F-NNN` feature (and invites a premature claim +
worktree) before the design is settled.

> ⚠️ This script writes **fresh skeleton** `spec.md`/`plan.md`/`research.md`
> into the new `F-NNN` folder — it does **not** copy the idea folder's contents.
> So keep the canonical spec under `docs/superpowers/specs/` (it travels with
> the feature branch), not in the backlog stub.

## Usage

```bash
python3 ~/.claude/ps-release-workflow/scripts/promote_idea_to_refined.py I-NNN
```

## What it does

1. Reads the idea catalog, finds `I-NNN`, mints the next `F-NNN` id.
2. Moves `.claude/idea_backlog/I-NNN-<slug>/` to `.claude/refined_backlog/F-NNN-<slug>/`.
3. Updates both catalogs (idea marked promoted, refined entry added).
4. Commits on `release/<v>` via the `_release` worktree (D11).

## Hand-off

With the spec already solid (the precondition), the next step is the plan:
`/superpowers:writing-plans`, then `/ps-release-workflow:claim F-NNN`.

## Refuses if

- Repo not opted into ps-release-workflow (no `.release.json`).
- No release in progress.
- Idea `I-NNN` not found in the idea catalog.
- Idea already promoted (an `F-NNN` already exists for it).
