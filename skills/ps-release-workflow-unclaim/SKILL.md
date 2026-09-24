---
name: ps-release-workflow-unclaim
description: |
  Use when the user wants to abandon or release a claimed feature (F-NNN) in a
  ps-release-workflow repo — "abandon this feature", "unclaim F-NNN", "release
  my claim", or cleaning up a stale claim whose worktree is gone. Removes the
  worktree, clears the ledger + catalog claim, and ALWAYS keeps the feature
  branch. To take over a claim instead of abandoning it, use claim --resume.
---

# ps-release-workflow:unclaim

Release a claimed feature: put it back to `open` without losing committed work.

## Run

    psrw unclaim F-NNN
    psrw unclaim F-NNN --force   # discard uncommitted changes instead of refusing

## What matters

- **The `feat/F-NNN` branch is always kept.** Committed work is preserved; the output
  shows the manual `git branch -D` for when the work is truly abandoned.
- The catalog entry goes back to `open`, `claimed_by` is cleared, and the `claims.json`
  ledger entry is deleted.
- **Drift cleanup** — if the worktree was already deleted out-of-band (stale claim),
  unclaim still prunes the dangling metadata and cleans the ledger + catalog.
- To take over a claim instead of abandoning it: `psrw claim --resume F-NNN`.
- **Never `--force` another session's claim blind.** Local sessions share one owner id;
  unclaim warns when the claim recorded a different session id. Uncommitted and
  untracked files are listed in the refusal, and `--force` deletes exactly those.

## Refuses if

No release in progress · the feature does not exist or is not status `claimed` · the
worktree has uncommitted or untracked changes (listed) and `--force` was not given.

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#state-layout`
Flags: `psrw unclaim --help`
