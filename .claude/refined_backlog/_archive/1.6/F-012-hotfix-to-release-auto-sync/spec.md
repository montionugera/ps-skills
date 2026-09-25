---
title: "hotfix to release auto sync"
id: F-012
status: refined
from_idea: I-013
---

# Hotfix to Release Auto-Sync (Option D)

## Goal

Automatically absorb commits from `main` (specifically squash-merged hotfixes) into `release/<v>` during `psrw ship` and enforce parity before `psrw promote` Gate 2, eliminating branch divergence, stale local deploys, and unverified prod releases while keeping local shipping 100% automated.

## Problem

When a critical hotfix lands on `main` via `psrw hotfix` and a GitHub squash-merge:
1. The in-progress release branch (`release/<v>`) in `.claude/worktrees/_release` does not receive the hotfix.
2. In-flight feature branches (`feat/F-NNN`) are developed without the hotfix.
3. `psrw ship` merges features into `release/<v>` and Gate 1 verifies code that lacks the hotfix.
4. `psrw promote` runs Gate 2 on `release/<v>` without the hotfix, opening a PR to `main` that might conflict or silently regress hotfix behavior.
5. In addition, `psrw ship` currently rolls back failed post-merge Gate 1 with `git reset --hard HEAD~1`. Once `ship` performs both a sync merge and a feature merge, `HEAD~1` would leave an untested sync commit standing.

## Architecture

We adopt **Option D (Defense in Depth)** built on a single shared primitive:

### 1. Shared Primitive (`lib/main_sync.py`)
- `resolve_main_sha(repo: Path, *, strict: bool) -> tuple[str, str]`: Fetches `origin/main` outside the lock (if remote exists) and returns the pinned SHA and source label (`origin/main`, `origin/main (stale: fetch failed)`, or `main (no origin)`). Never touches the main checkout.
- `sync_main_into_release(repo, rel_wt, release_branch, main_sha, source) -> MainSyncResult`:
  - Must be called under `file_lock(rel_wt)`.
  - Checks if `main_sha` is already an ancestor of `HEAD`. If so, returns `synced=False`.
  - Checks protected paths: runs `git diff --name-only <merge-base> <main_sha>`. If changes intersect `.release.json` or `.claude/*_backlog`, raises `ProtectedPathSyncError` and refuses auto-sync.
  - Merges `main_sha` using `git merge --no-ff --no-edit -m "chore(release): sync main@<sha> into <branch>"`.
  - On merge conflict, aborts merge with `git merge --abort` and raises `MainSyncConflictError` with list of conflicting files.

### 2. Automated Local Ship (`ship_current_work_to_release.py`)
- Fetches `origin/main` outside lock, pins `main_sha`.
- Inside `with file_lock(rel_wt)`:
  - Records `pre_sha = rev-parse HEAD`.
  - Calls `sync_main_into_release()`.
  - Merges `feat/F-NNN` into `release/<v>`.
  - Runs Gate 1 (`scripts/precheck.sh`) on the combined tree (`release + hotfix + feature`).
  - **Atomic Rollback**: If Gate 1 fails or any error occurs, resets to `pre_sha` (`git reset --hard pre_sha`), cleanly undoing both the sync and the feature merge.
  - On success, marks catalog shipped, commits, and handles epic CAS.
- Supports `--no-sync-main` flag for emergency bypass.

### 3. Enforcing Promote (`promote_release.py`)
- Runs `resolve_main_sha(repo, strict=True)`.
- Inside `with file_lock(rel_wt)`:
  - Calls `sync_main_into_release()`.
  - If synced, runs Gate 1 on the release tree to verify integration.
- Evaluates epic gates (G-E3): a sync invalidates epic freshness (`verified_sha`), correctly triggering epic re-verification.
- Runs local deploy and Gate 2 (`scripts/integration.sh`).
- PR body includes sync line: `- Synced with main@<sha> before Gate 2 (<N> commits absorbed).`
- `--babysit`: Before squash-merging, re-checks that `origin/main` is still an ancestor of `release/<v>`. If a hotfix merged during CI, aborts merge and prompts re-promote.
- Supports `--allow-stale-main` for emergency bypass.

### 4. Standalone Tooling
- New verb `psrw sync-main`: Explicitly merges `main` into `release/<v>`, runs Gate 1, and rolls back on failure.
- `psrw sync`: Generalizes `psrw epic sync` so any feature branch can pull updated `release/<v>` into its worktree.
- `psrw hotfix`: Adds hint pointing to auto-sync and `psrw sync-main`.
- `psrw status`: Displays behind-count from cached `origin/main` ref.

## Acceptance Criteria

- [ ] `lib/main_sync.py` implements `resolve_main_sha` and `sync_main_into_release` with protected-path and conflict detection.
- [ ] `lib/git_ops.py` provides `has_origin`, `is_ancestor`, `unmerged_files`, and `rev_parse`.
- [ ] `ship_current_work_to_release.py` automatically absorbs `main` under lock and rolls back to `pre_sha` on any Gate 1 failure.
- [ ] `promote_release.py` strictly requires `origin/main` to be contained in `release/<v>` before Gate 2 and PR merge, with babysit race check.
- [ ] `psrw sync-main` CLI verb is registered and operational.
- [ ] `psrw sync` works in any feature worktree.
- [ ] `psrw hotfix` prints step-8 hint when release is in progress.
- [ ] `psrw status` shows `behind origin/main` count when release is behind.
- [ ] Full automated test suite passes with unit tests covering no-op, squash absorption, rollback to `pre_sha`, conflict abort, and protected path guard.
- [ ] Documentation (`docs/lifecycle.md`, `README.md`, and skills) is updated to reflect auto-sync behavior and flags.
