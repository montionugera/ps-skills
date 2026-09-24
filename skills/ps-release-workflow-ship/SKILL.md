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
- `--no-sync-main` — skip the automatic absorption of `main` (hotfixes). By default,
  `ship` automatically merges `origin/main` into `release/<v>` under lock before merging the
  feature, verifying the combined tree with Gate 1.
- You never need `--no-deploy` for a non-local kubectl context: the deploy script
  self-refuses those.

## Automated main sync (hotfix absorption)

`psrw ship` automatically fetches `origin/main` outside the lock and merges it into `release/<v>`
before merging your feature branch. Gate 1 runs on the integrated tree (`release + hotfix + feature`).
If Gate 1 fails, `ship` atomically rolls back to the exact pre-sync commit (`pre_sha`), undoing both
the hotfix sync and the feature merge. If a conflict occurs during main sync, the merge is cleanly
aborted and the feature remains claimed.

## The local deploy

Runs the repo's own local deploy script against `release/<v>`, so the local env
reflects the integrated release: `scripts/deploy-local.sh`, or whatever
`hooks.deploy_local` in `.release.json` points at (an unusable value refuses the
deploy loudly and leaves the merge standing). That script is
responsible for refusing any non-local kubectl context, so ship can never touch prod.
Prod stays untouched until `psrw promote`, whose `--deploy` runs against the `_release`
worktree — the release tree, not `main` — because the local DB may already be migrated
ahead of `main` by the release's own migrations. To deploy by hand after `--no-deploy`,
run the script from a tree that is on `release/<v>` (the `_release` worktree is).

## Then

Claim the next feature, or `psrw promote` when the release is full.

## Refuses if

Not inside a feature worktree · dirty tree · Gate 1 (`precheck.sh`) fails. Gate 1 runs
twice — pre-merge on the feature worktree, then again post-merge on `_release`, where a
failure rolls the merge back.

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#gates`
Flags: `psrw ship --help`
