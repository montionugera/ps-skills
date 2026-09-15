---
name: ps-release-workflow-guard
description: |
  Use when an edit is blocked in a ps-release-workflow repo, or to understand
  the PreToolUse guard. Auto-fired by the PreToolUse hook on every mutating
  tool call — you do not run it by hand. It blocks edits on main of an opted-in
  repo, and edits in a worktree owned by a different session.
---

# ps-release-workflow:guard

The PreToolUse guard that enforces "edit only inside the worktree you claimed."

## How it fires

Not run by hand. It is wired as a PreToolUse hook and runs before every `Edit` /
`Write` / `MultiEdit` / `NotebookEdit` tool call. When no `.release.json` exists
anywhere up the tree from the edit target, it allows immediately on a fast path.

## What it guarantees

Exactly two things:

1. **No edits on the main checkout of an opted-in repo.** This keys off **filesystem
   location, not branch name** — checking out a hotfix branch in the main checkout is
   still blocked. Claim a feature and edit inside the worktree it creates.
2. **Cross-machine claim safety.** A worktree claimed on another machine will not
   accept edits here.

It does **not** provide per-session isolation between two Claude sessions on the same
machine. It warns but allows on a marker-less legacy worktree, and allows the
`_release` worktree silently.

## How to satisfy it

- Don't edit on `main` — claim a feature first: `psrw claim --next`, then edit inside
  the worktree it creates.
- Blocked for owner mismatch on **your own feature from a previous session**:
  `psrw claim --resume F-NNN` (the F id is in the worktree's `working-feature.json`).
- Otherwise it is someone else's worktree — pick different work: `psrw claim --next`.

## Failure policy (fail-safe, never silent)

Unparseable stdin → allow with a stderr warning. A crash after the target path is known
→ **block** if the target sits under a workflow repo, otherwise allow with a warning. It
never exits 1, which Claude Code would fail-open on silently.

## Blocks if

The target is on the main checkout of an opted-in repo, or in a worktree whose
`working-feature.json` owner does not match this session.

Rationale: `~/.claude/ps-release-workflow/docs/lifecycle.md#guard-guarantees`
