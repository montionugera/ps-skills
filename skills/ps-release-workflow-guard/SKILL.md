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

This skill is **not run by hand**. The `guard_check.py` script is wired as a
PreToolUse hook and runs automatically before every `Edit` / `Write` /
`MultiEdit` / `NotebookEdit` tool call.

## Usage (automatic)

```bash
# Invoked by the hook with the tool call JSON on stdin; exit 0 allow, 1 block:
echo '<tool-call-json>' | python3 ~/.claude/ps-release-workflow/scripts/guard_check.py
```

## What it does

1. Resolves the edit target's repo root (worktree pointers resolve to the main repo).
2. Allows anything outside a ps-release-workflow repo, and all non-mutating tools (e.g. `Read`).
3. **Blocks** edits on the main checkout of an opted-in repo.
4. Inside `.claude/worktrees/`: reads `working-feature.json`; **blocks** if the marker's `owner` is not your `$CLAUDE_SESSION_ID`.
5. Warns (but allows) on a marker-less legacy worktree.
6. Bypasses entirely when `PS_RELEASE_WORKFLOW_SCRIPTED=1` (so the toolkit's own scripts can write).

## How to satisfy it

- Don't edit on `main` — claim a feature first: `/ps-release-workflow:claim --next`, then edit inside the worktree it creates.
- If blocked for owner mismatch, you are in someone else's worktree; claim your own.

## Refuses if

- The target is on `main` of an opted-in repo.
- The target is in a worktree whose `working-feature.json` owner is not the current `$CLAUDE_SESSION_ID`.
