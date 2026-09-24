---
name: ps-release-workflow-promote
description: |
  Use when the in-progress release is full and ready to go to main
  (release-manager only). Runs Gate 2 (integration.sh, on by default), then
  opens a PR from release/<v> to main for review + squash-merge (the merge
  deploys to prod). With --babysit it also watches checks, merges, and cleans
  up. NOT the terminal step by itself — cleanup (--cleanup-only <version>,
  after the PR merges) is the actual terminal step of the release lifecycle.
---

# ps-release-workflow:promote

Open a PR from `release/<v>` to `main`. **Release-manager only.** Not the terminal step
by itself — cleanup is.

## Run

    psrw promote --deploy                      # Gate 2, then open the PR
    psrw promote --deploy --babysit            # ...also watch checks, merge, clean up
    psrw promote --cleanup-only <version>      # REQUIRED after the PR merges
    psrw promote --deploy --direct             # legacy: local merge + push, no PR

## Flags that change behavior

- Gate 2 (`scripts/integration.sh`, from the `_release` worktree) is **on by default**.
  - `--no-gate2` — deliberately skip the gate.
  - `--allow-missing-gate2` — the gate is still wanted but the script is absent from the
    release branch; proceed UNVERIFIED (for repos that never had one). Without it, a
    missing `integration.sh` makes promote **refuse** rather than silently skip.
- `--deploy` — opt-in local prod-style deploy, run from the `_release` worktree.
- `--babysit` — watch checks → finalize → squash-merge → cleanup. Red checks stop before
  finalize AND merge, so the release stays in progress: fix and re-run promote.
- `--cleanup-only <version>` — **required after the PR merges** unless you used
  `--babysit`. It marks features promoted, archives the `F-NNN` folders, prunes the
  per-feature + `_release` worktrees/branches, and finalizes `.release.json` on `main`.
  It verifies the PR is MERGED first and **refuses while the PR is unmerged** (deleting
  the remote release branch would auto-close an open PR); `--force-cleanup` is the
  explicit override. Until cleanup runs, the next `psrw new-release` is wedged.

## Then
 
Without `--babysit`: a human reviews and squash-merges the PR (that merge deploys prod),
then run `psrw promote --cleanup-only <version>`. With `--babysit`: release is fully promoted.

**If in chained mode ("and chain", multi-wave / multi-release directive)**: do NOT pause or say *"whenever you are ready"*; immediately open the next release or claim the next feature and continue executing.

## Refuses if

No release in progress · `main` (a hotfix) cannot merge cleanly into `release/<v>` —
promote syncs it first, before the epic gate, deploy and Gate 2 · Gate 2 fails, or is missing without `--allow-missing-gate2` ·
`--deploy` fails · `gh` cannot create or find the PR (release left in progress — fix gh
and re-run, or use `--direct`) · `--cleanup-only` when the PR is not merged or gh cannot
verify it.

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#promote-sequence`
Gates: `~/.claude/ps-release-workflow/docs/lifecycle.md#gates`
Flags: `psrw promote --help`
