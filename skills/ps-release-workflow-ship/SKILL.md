---
name: ps-release-workflow-ship
description: |
  Use when a claimed feature is implemented and ready to merge into the
  release. Run from inside the feature worktree. Runs Gate 1 (precheck.sh),
  merges the feature branch into release/<v>, and marks the catalog shipped.
  After this skill: claim the next feature, or promote when the release is full.
---

# ps-release-workflow:ship

Merge the claimed feature into `release/<v>`, then deploy the release locally.

## Precondition

Clean tree, run from inside the claimed feature worktree.

## Run

    psrw ship

## Flags that change behavior

- `--no-deploy` — skip the post-merge local deploy. **Use it when other sessions are
  shipping to the same `release/<v>` right now**: batch one deploy after the burst
  instead of racing rebuilds. Also when you are mid-sweep and will deploy at the end.
- `--deploy` — force the deploy. An interactive run prompts `[Y/n]`; without a TTY the
  default is to deploy.
- You never need `--no-deploy` for a non-local kubectl context: the deploy script
  self-refuses those.

## The local deploy

Runs the repo's own local deploy script against `release/<v>`, so the local env
reflects the integrated release: `scripts/deploy-local.sh`, or whatever
`hooks.deploy_local` in `.release.json` points at (an unusable value refuses the
deploy loudly and leaves the merge standing). With no script at all, ship prints
`no local deploy configured` instead of skipping silently. That script is
responsible for refusing any non-local kubectl context, so ship can never touch prod.
Prod stays untouched until `psrw promote`, whose `--deploy` runs against the `_release`
worktree — the release tree, not `main` — because the local DB may already be migrated
ahead of `main` by the release's own migrations. To deploy by hand after `--no-deploy`,
run the script from a tree that is on `release/<v>` (the `_release` worktree is).

## Then

Claim the next feature, or `psrw promote` when the release is full.

## Refuses if

Not inside a feature worktree · dirty tree · the release is **frozen** (promote has
started or its PR is open or merged: ship into the next release instead) · `main` cannot merge cleanly into
`release/<v>` (ship first absorbs any hotfix on `main`; a conflict prints the exact
`git merge` to run) · Gate 1 (`precheck.sh`) fails. Gate 1 runs
twice — pre-merge on the feature worktree, then again post-merge on `_release`, where a
failure rolls the sync and merge back. The deploy refuses a release still behind `main`.

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#gates`
Flags: `psrw ship --help`
