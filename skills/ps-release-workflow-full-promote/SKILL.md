---
name: ps-release-workflow-full-promote
description: |
  Use when the user wants the ENTIRE release turnover in one shot — "full
  promote", "babysit merge clean + new release", "ship the release end to
  end". Chains: promote (Gate 2 + PR) → babysit CI → squash-merge (prod
  deploy) → watch deploy → cleanup → start the NEXT release. Release-manager
  only. Saying "full promote" IS the standing authorization for the merge +
  prod deploy it contains.
---

# ps-release-workflow:full-promote

One-shot release turnover: promote → merge → prod deploy → cleanup → next release open.

## Preconditions

- A release is in progress and its features are all shipped (check `psrw status`).
- You are the release manager. Invoking this skill = standing authorization for
  the squash-merge and the prod deploy it triggers (same convention as
  "babysit + merge") — do NOT re-ask at each step.

## The happy path (one command)

```bash
psrw promote --deploy --babysit
```

`--babysit` does: Gate 2 → push + PR → `gh pr checks --watch` → finalize →
`gh pr merge --squash` → cleanup. If it completes cleanly, skip to
**Start the next release** below. The only thing it does NOT do is watch the
post-merge prod deploy run — do that explicitly:

```bash
cd <repo-main-checkout>
RUN_ID=$(gh run list --branch main --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status --interval 30
```

## Fallback path — promote already ran without --babysit (PR exists, release finalized)

Re-running promote errors with "release already finalized". Babysit manually:

```bash
cd <repo-main-checkout>
gh pr checks <pr#> --watch --interval 30          # red checks -> STOP, fix, do not merge
gh pr merge <pr#> --squash                        # this deploys prod
RUN_ID=$(gh run list --branch main --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status --interval 30
psrw promote --cleanup-only <version>
```

Cleanup verifies the PR is merged before pruning (refuses otherwise); it marks
features promoted, archives F-NNN folders, prunes per-feature + `_release`
worktrees/branches, and finalizes `.release.json` on `main`.

## Start the next release

After cleanup succeeds (and ONLY after — a stale `_release` worktree wedges it):

```bash
# fast-forward local main first — new-release off a stale main mints colliding ids
cd <repo-main-checkout> && git fetch origin && git merge --ff-only origin/main
psrw new-release
```

(Opens `release/<v+1>`, marks `.release.json` in_progress, recreates the
`_release` worktree.)

## Stop conditions (the ONLY reasons to halt and report)

- Gate 2 red, PR checks red, merge failure, or prod deploy run failure —
  report the failing output; never merge over red.
- Cleanup refuses (PR not actually merged / gh cannot verify).
- Anything requiring a new R0 decision beyond the merge+deploy this skill covers.

## After this skill

- If running as a standalone single-release turnover: report one consolidated summary: PR #, merge SHA, prod deploy run result, cleanup output (features promoted / worktrees pruned), and the new release version.
- **Chained Execution Mode ("and chain", multi-wave / multi-release roadmap):**
  - Do NOT stop or yield the turn.
  - NEVER say polite stalls like *"we can trigger the next wave whenever you are ready"* or *"let me know when to proceed"*.
  - Immediately proceed to claim the next feature (`psrw claim <F-NNN>`) or refine the next idea and keep executing.

