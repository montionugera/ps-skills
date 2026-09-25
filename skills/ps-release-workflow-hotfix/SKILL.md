---
name: ps-release-workflow-hotfix
description: |
  Use when an urgent fix must go straight to main in a ps-release-workflow
  repo, bypassing the release branch and Gate 2 — "hotfix", "urgent fix to
  prod", "patch main directly". Creates the sibling worktree the guard
  requires (editing the main checkout is blocked by location, regardless of
  branch name), then hands back the verify → commit → PR → babysit checklist.
---

# ps-release-workflow:hotfix

Urgent fix straight to `main`, bypassing the release branch and Gate 2.

## Precondition

The fix genuinely cannot wait for the release. Otherwise use `psrw idea` and the
normal lifecycle.

## Run

    psrw hotfix "mt5 idor"

## Why a sibling worktree

The PreToolUse guard blocks edits in the **main working tree** by filesystem
location, **regardless of branch name** — so checking out `hotfix/<desc>` in the
main checkout is still blocked. The sibling `../<repo>-hotfix-<desc>` is not the
main checkout and carries no claim marker, so edits are allowed.

## Then — the script does none of this for you

1. `cd` into the printed worktree.
2. **Install dependencies** — a fresh worktree has no `node_modules` / venv.
3. Make the fix.
4. Run the repo's verification with **visible exit codes**.
5. Commit — a **new commit**, never `git commit --amend`.
6. Push, open a PR to `main`, babysit CI, squash-merge.
7. `git worktree remove <path>` and delete the remote branch.
8. If a release is in progress, the hotfix reaches `release/<v>` automatically at the
   next `psrw ship` / `psrw promote`. To absorb it now (e.g. to redeploy locally):
   `psrw sync-main --deploy`.

Saying "babysit + merge" authorizes steps 6-8 without re-asking.

## Refuses if

The sibling directory already exists. (`--sync-release` is an alias for
`psrw sync-main`; see that skill.)

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#guard-guarantees`
