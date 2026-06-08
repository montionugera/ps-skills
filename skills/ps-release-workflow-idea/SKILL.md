---
name: ps-release-workflow-idea
description: |
  Use BEFORE capturing a new idea in a ps-release-workflow repo.
  Creates I-NNN-<slug> folder with spec/plan/research skeletons and
  commits the backlog entry on the release branch via the _release worktree.
  After this skill: brainstorm the idea into a SOLID, approved spec FIRST;
  refine only once the spec is solid. Never auto-chain idea -> refine -> claim.
---

# ps-release-workflow:idea

Capture a new idea into the backlog.

## Usage

```bash
python3 ~/.claude/ps-release-workflow/scripts/new_idea.py "Add fee cap to MT5"
```

## What it does

1. Reads `.claude/idea_backlog/_catalog.json` and mints the next `I-NNN` id.
2. Creates folder `.claude/idea_backlog/I-NNN-<slug>/` with `spec.md`, `plan.md`, `research.md` skeleton files.
3. Appends the catalog entry.
4. Commits as `chore(backlog): add I-NNN <title>` on `release/<v>` via the `_release` worktree (D11).

## Hand-off

Prints: `Refine when ready: /ps-release-workflow:refine I-NNN`.

## Next step — brainstorm BEFORE refine (deliberate gate)

A fresh idea is just a title + empty skeleton. **Do NOT** chain straight into
`:refine`/`:claim`. Each step is a deliberate, human-approved gate:

1. **Brainstorm it** — `/superpowers:brainstorming`: explore the problem, get
   the design approved, and produce a **solid spec** under
   `docs/superpowers/specs/` (this is the canonical spec — it travels with the
   feature branch; the backlog `spec.md` is only a stub).
2. **Only once the spec is solid** → `/ps-release-workflow:refine I-NNN`.

Refining (or claiming) an idea whose spec is still the empty skeleton is the
exact mistake this gate prevents — it mints an `F-NNN` feature, and tempts an
immediate claim + worktree, before anyone has decided what is being built.

## Refuses if

- Repo not opted into ps-release-workflow (no `.release.json`).
- No release in progress (backlog edits route through the `release/<v>` branch, so a release must be open first — run `/ps-release-workflow:new-release`).
