---
name: ps-release-workflow-ship
description: |
  Use when a claimed feature is implemented and ready to merge into the
  release. Run from inside the feature worktree. Runs Gate 1 (precheck.sh),
  merges the feature branch into release/<v>, and marks the catalog shipped.
  After this skill: claim the next feature, or promote when the release is full.
---

# ps-release-workflow:ship

Ship the current feature into the in-progress release.

## Usage

```bash
# Run from inside the claimed feature worktree:
python3 ~/.claude/ps-release-workflow/scripts/ship_current_work_to_release.py
```

## What it does

1. Verifies you are inside a claimed feature worktree with a valid owner marker.
2. Runs **Gate 1** (`precheck.sh`) — the per-feature pre-merge check.
3. Merges the feature branch into `release/<v>`.
4. Marks the feature shipped in the refined catalog via the `_release` worktree (D11).

## Hand-off

Prints: `Shipped to release/<v>. Claim the next feature, or /ps-release-workflow:promote when the release is full.`

## After ship — deploy the release locally (MR-merge convention)

`ship` is **git-only**: it merges to `release/<v>` but does **not** deploy anything.
To keep the local env reflecting the integrated release — the same way merging an MR
triggers a staging deploy — deploy `release/<v>` after shipping:

```bash
# from a tree on release/<v> — the _release worktree is on it, and deploy-local
# is worktree-aware (it builds from the current working tree):
cd .claude/worktrees/_release && ./scripts/deploy-local.sh
```

This rebuilds the local `quant-{api,fe}:local` images from `release/<v>` and rolls the
deployments, so you can exercise the just-merged feature locally. `deploy-local.sh`
refuses any non-local kubectl context (`orbstack|kind-|minikube|docker-desktop`), so it
can't touch prod. **Prod stays untouched until `promote`** (which runs deploy-local
against `main` as part of Gate 2).

**Why this is a recommendation, not auto-run by the ship script:** multiple sessions
often ship to the same `release/<v>` concurrently. Auto-deploying after *every* ship
would mean constant local rebuilds and redeploy races between sessions. Deploy when you
want to *test* — typically once after a batch of ships, or right before exercising a
screen — not mechanically after each merge.

## Refuses if

- Not run from inside a feature worktree.
- The worktree has a dirty (uncommitted) tree.
- **Gate 1** (`precheck.sh`) fails.
