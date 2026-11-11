---
title: "Release cleanup must not delete a work folder that holds unsaved files"
id: I-033
status: idea
---

# Release cleanup must not delete a work folder that holds unsaved files

## Problem

Release cleanup removes each feature worktree with force. Any file in that worktree
that was never committed is deleted with it, without a warning.

Concrete case, release 1.11 (2026-10-11): the F-021 feature worktree held
`.superpowers/sdd/2026-10-11-agentic-vault-sync-leftovers/`, about 30 files of review
notes and reports, including roughly 64 parked "fix later" findings. None of it was
committed. `psrw promote --cleanup-only 1.11` removed the worktree and the folder went
with it. Recovering the text took a search through saved session records and came back
incomplete (see I-032).

What was checked on 2026-10-13:

- `scripts/promote_release.py` calls `remove_worktree(repo, wt_path, force=True)` for
  feature worktrees (line 961) and for the `_release` worktree (line 1021).
- `lib/git_ops.py` `remove_worktree` passes `--force` to `git worktree remove`, which
  removes a worktree even when it has untracked or modified files.
- `.superpowers/sdd/` is not ignored by git in this repo, so plain
  `git worktree remove` without `--force` would have refused.

Not checked: whether `unclaim` and the refine path (which also call
`remove_worktree`) can lose files the same way.

## Why now

It has already cost one recovery effort. Every feature built with the subagent-driven
flow leaves the same kind of uncommitted notes folder in its worktree, so the next
cleanup will do it again.

## Sketch

Before removing a worktree, list files that are untracked or modified. If there are
any, either refuse and name them (with an explicit override flag), or copy them to a
kept location first (for example the feature's archived backlog folder). Which of the
two is the design decision for brainstorming.

## Acceptance criteria

- [ ] Cleanup of a release whose feature worktree holds an untracked file does not delete that file silently: it either refuses and names the file, or the file exists afterwards in a documented kept location.
- [ ] A test builds a worktree with an untracked file, runs cleanup, and asserts the outcome above.
- [ ] A worktree with no untracked or modified files is still removed as today.
