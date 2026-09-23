---
name: ps-release-workflow-refine
description: |
  Use BEFORE promoting a captured idea (I-NNN) into the refined backlog
  in a ps-release-workflow repo. Mints F-NNN, copies the idea folder into
  refined_backlog/, and commits on the release branch via the _release
  worktree. Refine ONLY an idea that already has a solid, approved spec —
  never auto-chain idea -> refine -> claim.
  Sole exception: the epic-run skill, for slices a human allowlisted.
---

# ps-release-workflow:refine

Promote an idea (`I-NNN`) into a refined, plannable feature (`F-NNN`).

## Precondition — spec must be solid FIRST (deliberate gate)

Refine is a **promotion gate**, not a formatting step. The idea must already be
brainstormed with an **approved spec** under `docs/superpowers/specs/`. Do **NOT** run
idea -> refine -> claim as one automatic chain — promoting an under-specified idea mints
an `F-NNN` (and invites a premature claim + worktree) before the design is settled.
The sole exception is the `epic-run` skill, which refines only slices a human listed in
its `--slices` allowlist; `psrw epic plan` refuses a slice whose spec is still a skeleton.

> ℹ️ Refine **carries the idea's content forward**: it copies the idea folder into the new
> `F-NNN` folder (the idea folder stays where it is) and replaces only *untouched* skeletons.
> A filled-in `spec.md` arrives with its `title`/`id`/`from_idea`/`status` frontmatter
> restated for the `F-NNN`; an untouched `plan.md` gets the `F-NNN` plan skeleton; an
> untouched `research.md` is dropped (refine seeds none). Keep the canonical spec under
> `docs/superpowers/specs/`, where it travels with the feature branch.

## Run

    psrw refine I-NNN

## Then

`/writing-plans`, then `psrw claim F-NNN`.

## Refuses if

Repo not opted in · no release in progress · `I-NNN` not found in the idea catalog ·
idea already promoted · the idea's `spec.md` still holds a template placeholder, or has no
"Acceptance criteria" heading with at least one `- [ ]` item (the message names each gap).
`--allow-empty-spec` overrides with a warning — a human decision, never an agent default.

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#d11-backlog-routing`
Flags: `psrw refine --help`
