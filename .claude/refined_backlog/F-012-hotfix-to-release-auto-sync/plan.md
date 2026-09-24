# Hotfix to Release Auto-Sync Implementation Plan (F-012)

> Implementation plan for Option D: automatic absorption of `main` into `release/<v>` during local `ship` and contractual parity enforcement at `promote`.

## User Review Checkpoint
> [!IMPORTANT]
> This plan executes across 5 phases. Each phase concludes with the mandatory Phased Quality Gate: Implement -> Verify -> Review -> Refactor -> Re-verify.

---

## Phase 1: Rollback Correctness (`pre_sha` across all rollback sites)

- [x] Task 1.1: Audit and replace `HEAD~1` rollbacks in `engine/ps-release-workflow/scripts/ship_current_work_to_release.py`.
  - Record `pre_sha = git_run(rel_wt, "rev-parse", "HEAD").stdout.strip()` at start of `with file_lock(rel_wt)`.
  - Replace `git_run(rel_wt, "reset", "--hard", "HEAD~1")` at line 148 (bad hook rollback) with `git_run(rel_wt, "reset", "--hard", pre_sha)`.
  - Replace `git_run(rel_wt, "reset", "--hard", "HEAD~1")` at line 152 (Gate 1 failure rollback) with `git_run(rel_wt, "reset", "--hard", pre_sha)`.
  - Audit and update any related rollback references in `epic.py`.
- [x] Task 1.2: Add unit tests verifying rollback to `pre_sha` in `tests/test_ship_current_work_to_release.py`.
- [x] Task 1.3: Quality Gate: Run pytest, review diff, refactor, re-verify.

---

## Phase 2: Core Shared Primitive (`lib/main_sync.py` & `lib/git_ops.py`)

- [x] Task 2.1: Add git helper functions to `engine/ps-release-workflow/lib/git_ops.py`.
  - `has_origin(repo: Path) -> bool` (move and expose from `promote_release.py`).
  - `is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool`.
  - `unmerged_files(repo: Path) -> list[str]`.
  - `rev_parse(repo: Path, rev: str) -> str`.
  - `diff_names(repo: Path, a: str, b: str) -> list[str]`.
- [x] Task 2.2: Implement `engine/ps-release-workflow/lib/main_sync.py`.
  - `MainSyncResult` dataclass (`synced`, `main_sha`, `source`, `behind`, `files`).
  - Exception classes: `MainSyncConflictError`, `ProtectedPathSyncError`, `MainUnreachableError`.
  - `_is_protected(path: str) -> bool` (checks `.release.json`, `.claude/idea_backlog/`, `.claude/refined_backlog/`, `.claude/epic_backlog/`, `.claude/state/`).
  - `resolve_main_sha(repo: Path, *, strict: bool) -> tuple[str, str]` (handles remote fetch, offline fallback, local main).
  - `sync_main_into_release(repo: Path, rel_wt: Path, release_branch: str, main_sha: str, source: str) -> MainSyncResult`.
  - `render_sync_failure(err: Exception, release_branch: str, feature_id: str) -> str`.
- [x] Task 2.3: Implement thorough unit test suite in `tests/test_main_sync.py`.
  - Test no-op when release already contains main.
  - Test absorption of squash-merged hotfix.
  - Test SHA pinning immunity against concurrent origin moves.
  - Test merge conflict abort and error diagnosis.
  - Test protected path refusal (`ProtectedPathSyncError`).
  - Test offline and no-origin fallbacks.
  - Test idempotence.
- [x] Task 2.4: Quality Gate: Run pytest on `test_main_sync.py`, review diff, refactor, re-verify.

---

## Phase 3: Ship Integration & Standalone Verbs (`psrw ship`, `psrw sync-main`, `psrw sync`)

- [x] Task 3.1: Integrate auto-sync into `engine/ps-release-workflow/scripts/ship_current_work_to_release.py`.
  - Fetch `origin/main` outside lock with `resolve_main_sha(repo, strict=False)`.
  - Under `file_lock(rel_wt)`, call `sync_main_into_release()` before feature merge.
  - Handle `MainSyncConflictError` and `ProtectedPathSyncError` with clear diagnostic output.
  - Run post-merge Gate 1 across the combined release tree.
  - Update `main_sync` field in JSON output.
  - Add `--no-sync-main` flag for emergency bypass.
- [x] Task 3.2: Implement `engine/ps-release-workflow/scripts/sync_main.py` (`psrw sync-main`).
  - CLI verb with `--strict`, `--deploy`, `--json` flags.
  - Acquires `file_lock(rel_wt)`, resolves main, syncs, runs Gate 1 on `_release`, rolls back to `pre_sha` on failure.
- [x] Task 3.3: Generalize `psrw sync` in `engine/ps-release-workflow/scripts/epic.py`.
  - Expose generic `psrw sync` (and keep `psrw epic sync` alias) to pull `release/<v>` into current feature worktree.
- [x] Task 3.4: Register `sync-main` and `sync` commands in dispatcher `bin/psrw`.
- [x] Task 3.5: Add integration tests in `tests/test_ship_current_work_to_release.py` and `tests/test_sync_main.py`.
- [x] Task 3.6: Quality Gate: Run pytest, review diff, refactor, re-verify.

---

## Phase 4: Promote Enforcement & Babysit Race Guard (`psrw promote`)

- [x] Task 4.1: Update `engine/ps-release-workflow/scripts/promote_release.py`.
  - In `promote_release()`, run strict main sync (`resolve_main_sha(repo, strict=use_pr)`) before G-E3 and Gate 2.
  - If sync performed, run Gate 1 on `_release` to verify integration before proceeding.
  - Ensure epic freshness check (`_verification_is_fresh`) recognizes the new content and triggers outcome re-verification.
  - Append sync summary line to PR body.
  - Add `--allow-stale-main` flag for emergency override.
- [x] Task 4.2: Add babysit race guard in `promote_release.py`.
  - In `--babysit` block, after watching CI checks, fetch `origin/main` again.
  - Verify `origin/main` is still an ancestor of `release/<v>`. If a hotfix merged during CI, abort merge with clear instructions to re-run `promote`.
- [x] Task 4.3: Add integration tests in `tests/test_promote_release.py`.
  - Test promote absorbs hotfix before Gate 2.
  - Test promote refuses when fetch fails in PR mode.
  - Test babysit aborts merge if main moves during CI.
- [x] Task 4.4: Quality Gate: Run pytest, review diff, refactor, re-verify.

---

## Phase 5: UX Polish, Documentation & README Synchronization

- [x] Task 5.1: Update `engine/ps-release-workflow/scripts/hotfix.py` to print step 8 auto-sync hint when release is in progress.
- [x] Task 5.2: Update `engine/ps-release-workflow/scripts/status.py` to display "N behind origin/main (hotfix pending sync)" from cached ref.
- [x] Task 5.3: Update documentation:
  - Add "Main Sync Mechanics" section to `engine/ps-release-workflow/docs/lifecycle.md`.
  - Update `skills/ps-release-workflow-{ship,promote,hotfix,status}/SKILL.md`.
  - Create `skills/ps-release-workflow-sync-main/SKILL.md`.
- [x] Task 5.4: Synchronize `README.md` with new `psrw sync-main`, `psrw sync`, `--no-sync-main`, `--allow-stale-main`, and hotfix sync mechanics.
- [x] Task 5.5: Run full test suite (`./engine/ps-release-workflow/verify.sh` or `pytest engine/ps-release-workflow/tests`).
- [x] Task 5.6: Final Quality Gate: Full adversarial review, simplification, and re-verification.
