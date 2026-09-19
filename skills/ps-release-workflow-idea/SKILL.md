---
name: ps-release-workflow-idea
description: |
  Use BEFORE capturing a new idea in a ps-release-workflow repo.
  Creates I-NNN-<slug> folder with spec/plan/research skeletons and
  commits the backlog entry on the release branch via the _release worktree.
  After this skill: brainstorm the idea into a SOLID, approved spec FIRST;
  refine only once the spec is solid. Never auto-chain idea -> refine -> claim.
  Sole exception: the epic-run skill, for slices a human allowlisted.
---

# ps-release-workflow:idea

Capture a new idea into the backlog as `I-NNN-<slug>` (spec/plan/research skeletons).

## Run

    psrw idea "Add fee cap to MT5"

## Then — brainstorm BEFORE refine (deliberate gate)

A fresh idea is just a title + empty skeleton. **Do NOT** chain straight into refine or
claim. Each step is a deliberate, human-approved gate:

1. **Brainstorm it** — `/brainstorming`: explore the problem, get the design
   approved, produce a **solid spec** under `docs/superpowers/specs/` (that is the
   canonical spec — it travels with the feature branch; the backlog `spec.md` is a stub).
2. **Only once the spec is solid** → `psrw refine I-NNN`.

Refining or claiming an idea whose spec is still the empty skeleton is the exact mistake
this gate prevents.

**Sole exception:** the `epic-run` skill (`ps-release-workflow-epic-run`) refines and
claims slices in one chain, but only those a human listed in its `--slices` allowlist.

## Refuses if

Repo not opted in · no release in progress (backlog commits route through `release/<v>`,
so run `psrw new-release` first).

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#d11-backlog-routing`
Flags: `psrw idea --help`
