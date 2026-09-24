---
name: ps-release-workflow-status
description: |
  Use when the user asks "what's the status of the release?", "what's in
  flight?", "what should I claim next?", or any what's-going-on question in a
  ps-release-workflow repo. Prints a one-screen report: release line, features
  table (with owners, worktrees, drift flags), idea backlog counts, and a
  state-chosen Next hint. Read-only; safe to run anytime.
---

# ps-release-workflow:status

One-screen "what's in flight" report for the current repo. Read-only, safe anytime.

## Run

    psrw status
    psrw status --brief   # compact 6-line summary (what the SessionStart hook prints)

## What it reports

1. Release line from the `_release` worktree's `.release.json` (version, in_progress,
   started, last promoted), plus `N behind origin/main (hotfix pending sync; run psrw
   sync-main)` when the release lacks commits on `main` (cached ref, no fetch).
2. Features table — refined catalog joined with `claims.json` and the real
   `git worktree list`, flagging drift (e.g. claimed but worktree missing).
3. Idea counts (total / unpromoted) and promoted-but-uncleaned leftovers.
4. A `Next:` hint chosen by state — new-release, claim, idea/refine, ship, promote, or
   `psrw promote --cleanup-only <version>` once the release PR has merged.

## Then

Show the report to the user, then follow the `Next:` hint.

## Refuses if

Never — prints `not a ps-release-workflow repo` and exits 0 when the repo is not opted in.

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#state-layout`
Flags: `psrw status --help`
