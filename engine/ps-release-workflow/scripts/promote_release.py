"""ps-release-workflow:promote — Gate 2 + squash-merge → main + auto-cleanup."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib.backlog_paths import NoReleaseInProgressError as PathsNoReleaseInProgressError
from lib.backlog_paths import get_backlog_catalog_path, read_release_state
from lib.catalog import CatalogEntryNotFoundError, find_entry, list_entries, mark_promoted_to_main
from lib.epic import (
    epic_children, epic_completeness, epic_folder_path, mark_epic_failed,
    mark_epic_promoted, set_split_approved, try_begin_verification,
)
from lib.epic_gate import run_and_record
from lib.git_ops import (
    GitError, _run as git_run, commit_all, is_ancestor, is_dirty,
    delete_branch_local, delete_branch_remote, push, remove_worktree,
)
from lib.hooks import resolve_hook
from lib.main_sync import (
    MainSyncConflictError, MainUnreachableError, ProtectedPathSyncError,
    resolve_main_sha, sync_main_into_release,
)
from lib.owner import resolve_owner_id
from lib.repo import find_repo_root, is_ps_release_workflow_repo
from lib.state import file_lock, mutate_state


class NoReleaseInProgressError(Exception): pass
class Gate2FailedError(Exception): pass


class EpicGateError(RuntimeError):
    """G-E3 refused to promote: an epic with a feature shipped into this
    release is incomplete, or failed/needs re-verification at release HEAD.

    Subclasses RuntimeError deliberately: promote_release.main() catches
    (NoReleaseInProgressError, Gate2FailedError, CatalogEntryNotFoundError,
    RuntimeError) — a plain Exception here would escape as a raw traceback
    instead of the guaranteed `ERROR: ...` line every other verb gives.
    lib/hooks.py's HookPathError follows the exact same pattern.
    """


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_origin(repo: Path) -> bool:
    """True if an `origin` remote is configured (False in local-only repos/tests)."""
    return git_run(repo, "remote", "get-url", "origin", check=False).returncode == 0


def _finalized_uncleaned_version(repo: Path) -> str | None:
    """Version of a finalized-but-not-cleaned release, or None.

    Evidence of an uncleaned release (cleanup would have removed both):
    - the _release worktree still exists → its .release.json names the version;
    - a release/<v> branch still exists → prefer last_promoted_version's branch,
      else the first surviving release branch.
    """
    rel_rj = repo / ".claude" / "worktrees" / "_release" / ".release.json"
    if rel_rj.exists():
        try:
            v = json.loads(rel_rj.read_text()).get("version")
            if v:
                return str(v)
        except (OSError, json.JSONDecodeError):
            pass
    branches = git_run(repo, "branch", "--list", "release/*", check=False).stdout
    names = [ln.strip().lstrip("*+ ").strip() for ln in branches.splitlines() if ln.strip()]
    if not names:
        return None
    try:
        last = json.loads((repo / ".release.json").read_text()).get("last_promoted_version")
    except (OSError, json.JSONDecodeError):
        last = None
    if last and f"release/{last}" in names:
        return str(last)
    return names[0].split("/", 1)[1]


def _finalize_release_state(worktree: Path, version: str) -> bool:
    """Flip .release.json to finalized ON the release branch (in the _release
    worktree) and commit it there.

    This is fix #2: by finalizing on the release branch BEFORE the PR is opened,
    the squash-merge that lands on main already carries the finalized state
    (in_progress=False, last_promoted=<version>). The PR thus becomes the SOLE
    writer of main's .release.json — there is no separate finalize-on-main commit
    to diverge from the squash (the exact breakage fix #1 guards against).

    Returns True if a finalize commit was made, False if there was nothing to do
    (no _release worktree, or already finalized).
    """
    rj_path = worktree / ".release.json"
    if not rj_path.exists():
        return False
    rj = json.loads(rj_path.read_text())
    if not rj.get("in_progress"):
        return False
    rj["in_progress"] = False
    rj["last_promoted_at"] = _now()
    rj["last_promoted_version"] = version
    rj_path.write_text(json.dumps(rj, indent=2) + "\n")
    commit_all(worktree, f"chore(release): finalize {version} in .release.json")
    return True


# ── gh interactions ────────────────────────────────────────────────────────────
# Each one is a tiny function taking an injectable `runner` (defaulting to
# subprocess.run) so tests can stub gh without a network or a GitHub remote.

def _create_or_adopt_pr(repo: Path, release_branch: str, version: str,
                        pr_body: str, runner) -> tuple[str, str | None]:
    """Open the release PR; if one already exists for the branch, adopt it.

    Returns (pr_url, note). Raises Gate2FailedError when the PR can neither be
    created nor found — WITHOUT having touched any release state, so promote
    can simply be re-run (fix A3).
    """
    cp = runner(
        ["gh", "pr", "create", "--base", "main", "--head", release_branch,
         "--title", f"release {version}", "--body", pr_body],
        cwd=repo, capture_output=True, text=True,
    )
    out = (cp.stdout or "").strip()
    err = (cp.stderr or "").strip()
    if cp.returncode == 0:
        return out, None
    # A PR may already exist for this branch — surface its URL instead of failing.
    view = runner(
        ["gh", "pr", "view", release_branch, "--json", "url", "-q", ".url"],
        cwd=repo, capture_output=True, text=True,
    )
    existing = (view.stdout or "").strip() if view.returncode == 0 else ""
    if existing:
        # ADOPT path: an existing PR is being reused, not created — `gh pr
        # create` above never ran, so the PR's body (which may carry a
        # split-epic disclosure, or an updated Gate 2 line) would otherwise go
        # stale forever. Best-effort: a failed edit must not fail the whole
        # promote — the PR still exists and is still usable.
        edit = runner(
            ["gh", "pr", "edit", release_branch, "--body", pr_body],
            cwd=repo, capture_output=True, text=True,
        )
        if edit.returncode != 0:
            print(
                f"⚠️  gh pr edit failed to refresh the body of the existing PR "
                f"for {release_branch}: {(edit.stderr or edit.stdout or '').strip()}",
                file=sys.stderr,
            )
        return existing, "PR already existed"
    raise Gate2FailedError(f"gh pr create failed: {err or out}")


def _watch_pr_checks(repo: Path, ref: str, runner) -> int:
    """`gh pr checks <ref> --watch` — streams to the terminal; returns exit code."""
    return runner(["gh", "pr", "checks", ref, "--watch"], cwd=repo).returncode


def _merge_pr_squash(repo: Path, ref: str, runner) -> subprocess.CompletedProcess:
    return runner(["gh", "pr", "merge", "--squash", ref],
                  cwd=repo, capture_output=True, text=True)


def _ensure_release_pr_merged_or_absent(repo: Path, release_branch: str,
                                        version: str, runner) -> None:
    """B3: cleanup deletes the remote release branch, and GitHub auto-closes any
    open PR whose head branch disappears — i.e. cleanup on an unmerged release
    PR silently destroys the release. Proceed only when the PR is MERGED or no
    PR exists; refuse (fail safe) on anything else, including gh being
    unavailable or failing for an unrelated reason.
    """
    force_hint = (f"if you are SURE, override with: "
                  f"promote_release.py --cleanup-only {version} --force-cleanup")
    try:
        cp = runner(["gh", "pr", "view", release_branch, "--json", "state", "-q", ".state"],
                    cwd=repo, capture_output=True, text=True)
    except (FileNotFoundError, OSError) as e:
        raise RuntimeError(
            f"cannot verify the PR state for {release_branch} (gh unavailable: {e}); "
            f"refusing to clean up — an open release PR would be destroyed. {force_hint}"
        )
    if cp.returncode != 0:
        err = ((cp.stderr or "") + " " + (cp.stdout or "")).strip()
        if "no pull requests found" in err.lower():
            return  # no PR for the branch — nothing to destroy
        raise RuntimeError(
            f"cannot verify the PR state for {release_branch} (gh failed: {err}); "
            f"refusing to clean up — an open release PR would be destroyed. {force_hint}"
        )
    state = (cp.stdout or "").strip().upper()
    if state == "MERGED":
        return
    raise RuntimeError(
        f"the PR for {release_branch} is {state or 'in an UNKNOWN state'} — cleanup would "
        f"delete the remote release branch and auto-close the PR, destroying the unmerged "
        f"release. Merge (or close) the PR first, then re-run: "
        f"promote_release.py --cleanup-only {version}. Otherwise {force_hint}"
    )


def _relevant_epics(refined_cat: Path, version: str) -> set[str]:
    """Every epic id with >=1 feature shipped/promoted into `version`."""
    return {
        f["epic"] for f in list_entries(refined_cat)
        if f.get("epic") and f.get("release_version") == version
        and f.get("status") in ("shipped", "promoted")
    }


# Everything psrw's own epic bookkeeping writes to release/<v> lives under this
# one directory: the epic catalog (the CAS-claim commit) and the E-NNN-<slug>/
# folder the outcome check copies its output into (lib/epic_gate.py).
_EPIC_BOOKKEEPING_PATHSPEC = ":(exclude).claude/epic_backlog"


def _verification_is_fresh(rel_wt: Path, verified_sha: str | None, head: str) -> bool:
    """True when `verified_sha` verified the same release content that `head` carries.

    A literal `verified_sha == head` comparison (spec 5.3's "Pass" row, as
    originally implemented) can NEVER be true: ship-time G-E2 captures
    `cas_sha = HEAD` and psrw itself then adds at least two more commits to
    release/<v> — the CAS-claim commit (ship_current_work_to_release.py) and the
    outcome commit (lib/epic_gate.run_and_record) — so `verified_sha` is
    permanently >=2 commits behind release HEAD by the time promote reads it.
    The fast path was dead code, and every promote re-ran the multi-minute
    epic_check for every epic unconditionally: exactly the cost blowup spec 5.4
    warns gets a gate disabled.

    What the gate actually cares about is spec 5.3's own wording — "the answer
    is always about the tree actually being promoted". So the comparison is
    content-based: the verification is still fresh while NOTHING but psrw's own
    epic bookkeeping has changed between the two commits. Any real change (a
    ship's merge, a doc, another catalog's status flip) makes it stale and the
    check re-runs. `git diff --quiet` exits 0 for "no difference", 1 for
    "differs", 128 for anything it cannot answer (a missing or garbage sha) —
    only 0 is treated as fresh, so every unknown is stale, never a false pass.
    """
    if not verified_sha:
        return False
    if verified_sha == head:
        return True
    return git_run(rel_wt, "diff", "--quiet", verified_sha, head, "--",
                   _EPIC_BOOKKEEPING_PATHSPEC, check=False).returncode == 0


def check_epics(repo: Path, rel_wt: Path, version: str, allow_split: bool = False) -> None:
    """G-E3: the completeness-and-freshness gate at promote time.

    For every epic with at least one feature shipped into `version`:
    - split_approved_by already set -> exempt, permanently.
    - not complete (lib.epic.epic_completeness) -> refuse, UNLESS allow_split
      is True, in which case this promote permanently split-approves it
      (lib.epic.set_split_approved) instead of raising.
    - complete, verified against the content being promoted -> pass
      (_verification_is_fresh).
    - complete but never verified / failed / verified against stale content ->
      re-run the outcome check at release HEAD (same CAS + throwaway-worktree
      mechanism ship-time G-E2 already uses — lib.epic_gate.run_and_record),
      then pass or raise.

    Raises EpicGateError on any refusal. The multi-minute epic_check hook run
    happens OUTSIDE file_lock(rel_wt) — only the CAS win + its commit, the
    split-approval writes, and the outcome recording inside run_and_record,
    take the lock.

    Every escaping exception is normalised to EpicGateError (a RuntimeError, so
    main() turns it into the guaranteed `ERROR: ...` line): the helpers this
    calls raise lib.backlog_paths.NoReleaseInProgressError — a DIFFERENT class
    from this module's own same-named one — and lib.git_ops.GitError, a plain
    Exception subclass, neither of which main() catches. Without this they
    escaped as raw tracebacks, defeating EpicGateError's whole design.
    """
    try:
        _check_epics(repo, rel_wt, version, allow_split)
    except (EpicGateError, CatalogEntryNotFoundError):
        raise  # already an intended, main()-caught refusal
    except (GitError, PathsNoReleaseInProgressError) as e:
        raise EpicGateError(
            f"G-E3 could not complete for release {version} "
            f"({type(e).__name__}: {e}) — refusing to promote unverified"
        ) from e


def _check_epics(repo: Path, rel_wt: Path, version: str, allow_split: bool) -> None:
    if not rel_wt.exists():
        raise EpicGateError(
            f"_release worktree missing at {rel_wt} — cannot verify epic "
            f"completeness for {version}"
        )
    epic_cat = get_backlog_catalog_path(repo, "epic")
    idea_cat = get_backlog_catalog_path(repo, "idea")
    refined_cat = get_backlog_catalog_path(repo, "refined")

    # ── Pass 1: decide for every epic, writing NOTHING ─────────────────────
    # set_split_approved is PERMANENT (there is no un-approve verb), so it must
    # not be committed for an earlier epic while a later epic in the same sweep
    # can still refuse the promote — that left a real, permanent operator
    # decision on release/<v> as a side effect of a promote that never
    # succeeded. Nothing is written until the whole sweep is known to pass.
    to_split_approve: list[str] = []
    to_verify: list[str] = []
    for epic_id in sorted(_relevant_epics(refined_cat, version)):
        epic = find_entry(epic_cat, epic_id)
        if epic is None:
            # Drifted/typo'd epic id: a feature shipped into this release names
            # an epic the catalog does not have, so completeness CANNOT be
            # evaluated — F1 (a half-epic reaching main) is exactly what would
            # slip through. Refusing is not an option: no override in this
            # toolkit can fix a missing catalog entry (--allow-split-epic would
            # itself raise CatalogEntryNotFoundError, `epic verify` needs the
            # entry too), so a hard error would brick promote with no way out.
            # Warn UNMISSABLY instead and keep going — the same call this
            # codebase already makes for the identical condition in cleanup().
            print(
                f"⚠️  G-E3: epic {epic_id} is MISSING from the epic catalog "
                f"({epic_cat}) but is named by a feature shipped into {version} "
                f"— its completeness could NOT be checked and this release may "
                f"be carrying a half-epic to main. Restore the catalog entry (or "
                f"clear the `epic` field on that feature) and re-run promote.",
                file=sys.stderr,
            )
            continue
        if epic.get("split_approved_by"):
            continue  # exempt, permanently

        complete, reasons = epic_completeness(idea_cat, refined_cat, epic_id, version)
        if not complete:
            if allow_split:
                to_split_approve.append(epic_id)
                continue
            raise EpicGateError(
                f"{epic_id} is not complete for release {version}: "
                f"{'; '.join(reasons)} (pass --allow-split-epic to promote anyway "
                f"and permanently mark this epic as an approved split)"
            )
        to_verify.append(epic_id)

    # ── Pass 2: freshness + outcome check for every complete epic ─────────
    for epic_id in to_verify:
        with file_lock(rel_wt):
            head = git_run(rel_wt, "rev-parse", "HEAD").stdout.strip()
            # Re-read under the lock: pass 1's snapshot predates this loop's own
            # catalog commits (and any concurrent ship's).
            epic = find_entry(epic_cat, epic_id) or {}
            if epic.get("status") == "verified" and _verification_is_fresh(
                rel_wt, epic.get("verified_sha"), head
            ):
                continue  # pass — already verified against this exact content
            status = epic.get("status")
            claim_sha = epic.get("verifying_sha")
            # reclaim_settled, NOT force: a 'verifying' epic has a check in
            # flight (a concurrent ship's G-E2, or `psrw epic verify`) and
            # stealing it would run two epic_checks against the same epic
            # concurrently, both writing the same epic_dir.
            won = try_begin_verification(epic_cat, epic_id, head, reclaim_settled=True)
            if won and is_dirty(rel_wt):
                commit_all(
                    rel_wt,
                    f"chore(epic): {epic_id} verification reclaimed at {head} (G-E3)",
                )
        if not won:
            sha_note = f" at {claim_sha[:12]}" if claim_sha else ""
            raise EpicGateError(
                f"{epic_id} could not be claimed for verification (status="
                f"{status}). G-E3 never steals an in-flight check: another run "
                f"— a concurrent ship's G-E2, or `psrw epic verify` — holds the "
                f"claim{sha_note}. Wait for it to finish and re-run promote; if "
                f"that run died, clear the stale claim with "
                f"`psrw epic verify --force {epic_id}`, then re-run promote"
            )

        # From the CAS win to run_and_record's own try/except there is a window
        # (epic_children / epic_folder_path, both of which can raise) where an
        # exception would leave the epic pinned in 'verifying' forever, with no
        # timeout — recoverable only by a human running `epic verify --force`.
        # Record the failure on the way out, matching run_and_record's pattern.
        try:
            features = [i["promoted_to"] for i in epic_children(idea_cat, epic_id)
                        if i.get("promoted_to")]
            epic_dir = epic_folder_path(repo, epic_id)
            rc, entry = run_and_record(repo, rel_wt, epic_cat, epic_id, features, head,
                                       epic_dir, version)
        except Exception as e:
            with file_lock(rel_wt):
                mark_epic_failed(epic_cat, epic_id, version, sha=head)
                if is_dirty(rel_wt):
                    commit_all(
                        rel_wt,
                        f"chore(epic): {epic_id} verification result (G-E3 crashed)",
                    )
            raise EpicGateError(
                f"{epic_id} verification crashed at promote (G-E3) "
                f"({type(e).__name__}: {e}) — recorded as failed_verification. "
                f"Fix it, then re-run promote"
            ) from e
        if entry.get("status") != "verified":
            raise EpicGateError(
                f"{epic_id} failed its outcome check at promote (G-E3), exit "
                f"code {rc} at {head[:12]} — fix the epic (or its hooks.epic_check) "
                f"and re-run promote; re-run just the check with "
                f"`psrw epic verify --force {epic_id}`. --allow-split-epic does "
                f"NOT cover this: per spec 5.3 it only approves promoting an "
                f"INCOMPLETE epic, never one whose outcome check failed"
            )

    # ── Pass 3: the permanent split approvals, now that the sweep has passed ──
    for epic_id in to_split_approve:
        with file_lock(rel_wt):
            set_split_approved(epic_cat, epic_id, resolve_owner_id())
            if is_dirty(rel_wt):
                commit_all(
                    rel_wt,
                    f"chore(epic): {epic_id} split-approved at promote {version}",
                )


def _epic_split_disclosure_lines(rel_wt: Path, version: str) -> list[str]:
    """PR-body lines for every split-approved epic touched by this release.

    _create_or_adopt_pr passes pr_body only to `gh pr create`; without this,
    the adopt path (an existing PR being reused) never updated the PR body, so
    a second promote silently dropped the split-epic disclosure a reviewer
    needs to see (fixed alongside this: the adopt branch now also calls
    `gh pr edit`).
    """
    epic_cat = rel_wt / ".claude" / "epic_backlog" / "_catalog.json"
    refined_cat = rel_wt / ".claude" / "refined_backlog" / "_catalog.json"
    lines = []
    for epic_id in sorted(_relevant_epics(refined_cat, version)):
        epic = find_entry(epic_cat, epic_id)
        if epic and epic.get("split_approved_by"):
            lines.append(
                f"- ⚠️ SPLIT EPIC: `{epic_id}` is being promoted incomplete — "
                f"approved by {epic['split_approved_by']}."
            )
    return lines


def promote_release(
    repo: Path,
    *,
    run_gate2: bool = True,
    run_deploy: bool = True,
    push: bool = True,
    keep: bool = False,
    use_pr: bool = True,
    allow_missing_gate2: bool = False,
    allow_split_epic: bool = False,
    allow_stale_main: bool = False,
    babysit: bool = False,
    gh_runner=subprocess.run,
) -> dict:
    repo = Path(repo).resolve()
    if not is_ps_release_workflow_repo(repo):
        raise RuntimeError(f"{repo} not opted into ps-release-workflow")
    # In-progress + version come from the _release worktree's .release.json
    # (fix #2 source of truth), not main — main carries only last-promoted state.
    state = read_release_state(repo)
    if state is None:
        # M1: distinguish "nothing to promote" from "promoted but not cleaned".
        # A finalized-but-uncleaned release (leftover _release worktree or a
        # surviving release/<v> branch) needs --cleanup-only, not a re-promote.
        leftover = _finalized_uncleaned_version(repo)
        if leftover:
            raise NoReleaseInProgressError(
                f"release {leftover} already finalized — if its PR is merged run: "
                f"promote_release.py --cleanup-only {leftover}"
            )
        raise NoReleaseInProgressError("No release in progress")
    version = state["version"]
    release_branch = f"release/{version}"
    rel_wt = repo / ".claude" / "worktrees" / "_release"

    main_sync_result = None
    if not allow_stale_main:
        try:
            main_sha, source = resolve_main_sha(repo, strict=use_pr)
        except Exception as e:
            raise Gate2FailedError(f"Main sync failed before promote: {e}")

        with file_lock(rel_wt):
            pre_sha = git_run(rel_wt, "rev-parse", "HEAD").stdout.strip()
            try:
                sync_res = sync_main_into_release(repo, rel_wt, release_branch, main_sha, source)
            except (MainSyncConflictError, ProtectedPathSyncError) as e:
                raise Gate2FailedError(
                    f"promote refused — release/{version} cannot absorb {source}@{main_sha[:12]}: {e}"
                )
            if sync_res.synced:
                main_sync_result = sync_res
                # Re-verify Gate 1 on the release branch after absorbing main
                precheck = resolve_hook(rel_wt, "precheck")
                if precheck.exists():
                    rc = subprocess.run([str(precheck)], cwd=rel_wt).returncode
                    if rc != 0:
                        git_run(rel_wt, "reset", "--hard", pre_sha)
                        raise Gate2FailedError(
                            f"Gate 1 failed after absorbing {source}@{main_sha[:12]} — rolled back to {pre_sha[:12]}"
                        )

    # G-E3: the completeness-and-freshness epic gate, before any other gate —
    # a release must not reach Gate 2 (let alone main) carrying an epic that
    # is incomplete or unverified at this release's HEAD.
    check_epics(repo, rel_wt, version, allow_split_epic)

    if run_deploy:
        # Deploy the RELEASE tree, not the main checkout: deploy-local is
        # worktree-aware, and the shared local DB may already be migrated
        # AHEAD of main by the release's own migrations (ship deploys
        # release/<v>). Deploying main pre-merge then fails alembic with
        # "Can't locate revision" for any migration-bearing release.
        deploy_root = rel_wt if rel_wt.exists() else repo
        deploy = resolve_hook(deploy_root, "deploy_local")
        if deploy.exists():
            cp = subprocess.run([str(deploy)], cwd=deploy_root)
            if cp.returncode != 0:
                raise Gate2FailedError(f"local deploy script ({deploy}) failed")

    gate2_ran = False
    if run_gate2:
        # Gate 2 must run from the _release worktree so the integration script
        # resolves the repo's source paths against the release branch's tree,
        # not the main checkout's.
        gate2_root = rel_wt if rel_wt.exists() else repo
        integ = resolve_hook(gate2_root, "integration")
        if integ.exists():
            cp = subprocess.run([str(integ)], cwd=gate2_root)
            if cp.returncode != 0:
                raise Gate2FailedError(f"Gate 2 ({integ}) failed for release/{version}")
            gate2_ran = True
        else:
            # A1: never skip a requested gate silently. Missing script means the
            # release would go to main with zero integration verification.
            print(
                f"⚠️  Gate 2 SKIPPED — {integ} not found on release/{version}; "
                f"the release is going to main UNVERIFIED",
                file=sys.stderr,
            )
            if not allow_missing_gate2:
                raise Gate2FailedError(
                    f"Gate 2 requested but {integ} is missing on release/{version}. "
                    f"Add it to the release branch, or pass "
                    f"--allow-missing-gate2 to promote UNVERIFIED (or --no-gate2 to skip the gate)."
                )

    # ── PR mode (default) ──────────────────────────────────────────────
    # Push release/<v> and open a PR to main; a human reviews + squash-merges
    # it (the merge triggers the prod deploy). We do NOT merge or clean up here
    # — the branches must survive until the PR lands. After the PR merges, run
    # `promote_release.py --cleanup-only <version>` to archive + prune.
    if use_pr:
        try:
            git_run(repo, "push", "-u", "origin", release_branch)
        except GitError as e:
            raise Gate2FailedError(f"failed to push {release_branch} to origin: {e}")
        gate2_line = (
            f"- Gate 2 (`integration.sh`{' + local prod-style deploy' if run_deploy else ''}) passed at promote."
            if gate2_ran else
            "- ⚠️ Gate 2 did NOT run at promote (skipped or `integration.sh` missing) — UNVERIFIED."
        )
        sync_line = ""
        if main_sync_result and main_sync_result.synced:
            sync_line = f"- Synced with {main_sync_result.source}@{main_sync_result.main_sha[:12]} before Gate 2 ({main_sync_result.behind} commits absorbed).\n"
        split_lines = _epic_split_disclosure_lines(rel_wt, version)
        split_block = ("\n".join(split_lines) + "\n") if split_lines else ""
        pr_body = (
            f"Promote `{release_branch}` → `main`.\n\n"
            f"- Gate 1 (`precheck.sh`) passed at ship.\n"
            f"{sync_line}"
            f"{gate2_line}\n"
            f"{split_block}\n"
            f"Squash-merging this PR triggers the prod (Vultr) deploy.\n"
            f"After it merges, run: `promote_release.py --cleanup-only {version}` "
            f"(archives the F-NNN folders, prunes worktrees/branches, finalizes `.release.json`)."
        )
        pr_url, note = _create_or_adopt_pr(repo, release_branch, version, pr_body, gh_runner)

        # Fix A3 ordering: finalize the release state ONLY once the PR exists.
        # (Previously finalize ran before `gh pr create`; a gh failure then left
        # in_progress=False and every retry hit NoReleaseInProgressError.)
        # Fix #2 still holds: the finalize commit lands on the release branch and
        # is pushed, so the squash-merge carries in_progress=False to main and
        # the PR stays the sole writer of main's .release.json.
        def _finalize_and_push() -> None:
            if _finalize_release_state(rel_wt, version):
                try:
                    git_run(repo, "push", "origin", release_branch)
                except GitError as e:
                    raise Gate2FailedError(
                        f"PR created ({pr_url}) but pushing the finalize commit to "
                        f"{release_branch} failed: {e}\n"
                        f"Push it manually (git push origin {release_branch}) before merging the PR."
                    )

        result = {"ok": True, "version": version, "mode": "pr", "pr_url": pr_url,
                  "gate2_ran": gate2_ran}
        if note:
            result["note"] = note

        if not babysit:
            _finalize_and_push()
            return result

        # ── --babysit (B4): the user's "babysit + merge" convention ────────
        # M1 ordering: create PR → watch checks → finalize+push → merge →
        # cleanup. Finalizing only AFTER green checks means red checks leave
        # in_progress=True and promote is simply re-runnable — no post-finalize
        # failure can brick the re-run. (The finalize push adds a commit after
        # the checks passed; acceptable — the merge follows immediately.)
        ref = pr_url or release_branch
        if _watch_pr_checks(repo, ref, gh_runner) != 0:
            raise Gate2FailedError(
                f"PR checks FAILED for {ref} — NOT merging.\n"
                f"The release is still in progress: fix the failures and re-run "
                f"promote (or merge the PR yourself with gh pr merge --squash {ref}, "
                f"then run: promote_release.py --cleanup-only {version})"
            )
        # Babysit race check: re-verify origin/main hasn't moved during CI
        if not allow_stale_main and _has_origin(repo):
            try:
                curr_main, _ = resolve_main_sha(repo, strict=True)
                if not is_ancestor(rel_wt, curr_main, "HEAD"):
                    raise Gate2FailedError(
                        f"origin/main advanced to {curr_main[:12]} while PR checks were running!\n"
                        f"Aborting merge to prevent deploying code unverified against the latest hotfix.\n"
                        f"Re-run `psrw promote` to re-sync, re-gate, and merge."
                    )
            except MainUnreachableError as e:
                raise Gate2FailedError(f"Could not verify origin/main freshness before merge: {e}")
        _finalize_and_push()
        merged = _merge_pr_squash(repo, ref, gh_runner)
        if merged.returncode != 0:
            raise Gate2FailedError(
                f"gh pr merge --squash failed for {ref}: "
                f"{(merged.stderr or merged.stdout or '').strip()}\n"
                f"Merge manually, then run: promote_release.py --cleanup-only {version}"
            )
        # verify_pr=False: the PR was squash-merged two lines up — the
        # merged state is known by construction.
        cleanup(repo, version=version, gh_runner=gh_runner, verify_pr=False)
        result["merged"] = True
        result["cleaned_up"] = True
        return result

    # ── Direct mode (--direct) ─────────────────────────────────────────
    # Legacy path: squash-merge release/<v> into main locally + push + cleanup.
    try:
        git_run(repo, "merge", "--squash", release_branch)
        git_run(repo, "commit", "-m", f"release {version}")
    except GitError as e:
        raise Gate2FailedError(f"squash-merge {release_branch} → main failed: {e}")

    # Bypass guard for subsequent toolkit-driven cleanup.
    os.environ["PS_RELEASE_WORKFLOW_SCRIPTED"] = "1"

    if push:
        from lib.git_ops import push as push_fn
        push_fn(repo, "main")

    if not keep:
        # verify_pr=False: --direct never opened a PR for this release.
        cleanup(repo, version=version, verify_pr=False)

    return {"ok": True, "version": version, "mode": "direct"}


def cleanup(repo: Path, version: str, *, gh_runner=subprocess.run,
            verify_pr: bool = True, force: bool = False) -> dict:
    """Idempotent cleanup after promote.

    Each step tolerates already-done state so re-running is safe.

    PR SAFETY (B3): before deleting ANYTHING, verify the release PR (if any)
    is MERGED — deleting the remote release branch auto-closes an open PR,
    destroying an unmerged release. `verify_pr=False` is for promote's own
    internal calls where the check is meaningless by construction (--direct
    never opened a PR; --babysit just merged it). `force=True`
    (--force-cleanup) is the explicit human override.

    ORDERING NOTE: a worktree that has a branch checked out must be removed
    BEFORE deleting that branch — git refuses to delete a branch that is
    checked out in a linked worktree. So per-feature and for the release we
    remove the worktree first, then delete the (now-detached) branch.
    """
    repo = Path(repo).resolve()

    if verify_pr and not force and _has_origin(repo):
        _ensure_release_pr_merged_or_absent(repo, f"release/{version}", version, gh_runner)

    # ── Adopt origin/main BEFORE accumulating any cleanup changes ──────────
    # PR-based promote advances origin/main via the GitHub squash-merge, so the
    # local checkout is behind/diverged. Every cleanup edit below (archival moves,
    # catalog, claims, the finalize .release.json) is committed together in the
    # finalize commit at the end. If we don't base that commit on origin/main now,
    # it lands on a diverged local main and the finalize push becomes a
    # non-fast-forward — which previously failed SILENTLY, leaving origin's
    # .release.json stale and local main diverged. No-op when there is no origin
    # (local-only repos / tests) or in --direct mode (main was just pushed).
    if _has_origin(repo):
        git_run(repo, "fetch", "origin", "main")
        # Only adopt origin/main when it carries commits the local checkout lacks
        # — i.e. the PR squash-merge advanced origin under a diverged/behind local
        # main. If local main is ahead/equal (e.g. --direct mode merged the squash
        # locally and hasn't pushed), it IS the source of truth; resetting would
        # discard the just-merged release.
        origin_ahead = git_run(repo, "rev-list", "HEAD..origin/main", check=False).stdout.strip()
        if origin_ahead:
            # reset --hard discards disposable local release-bookkeeping commits, but
            # would also nuke uncommitted tracked edits — refuse rather than lose them.
            if git_run(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip():
                raise RuntimeError(
                    "main checkout has uncommitted tracked changes; refusing to reset "
                    "to origin/main during cleanup. Commit or stash them, then re-run: "
                    f"promote_release.py --cleanup-only {version}"
                )
            git_run(repo, "checkout", "main")
            git_run(repo, "reset", "--hard", "origin/main")

    refined_cat = repo / ".claude" / "refined_backlog" / "_catalog.json"
    idea_cat = repo / ".claude" / "idea_backlog" / "_catalog.json"
    epic_cat = repo / ".claude" / "epic_backlog" / "_catalog.json"
    claims_file = repo / ".claude" / "state" / "claims.json"
    archive_root = repo / ".claude" / "refined_backlog" / "_archive" / version
    archive_root.mkdir(parents=True, exist_ok=True)

    # For each F-NNN shipped in this version: archive + remove worktree + delete branches.
    touched_epics: set[str] = set()
    for entry in list_entries(refined_cat):
        if entry.get("release_version") != version:
            continue
        if entry.get("status") not in ("shipped", "promoted"):
            continue

        feature_id = entry["id"]
        if entry.get("epic"):
            touched_epics.add(entry["epic"])
        # 1. Mark promoted. This is a bulk sweep: one drifted entry (removed
        # concurrently between the list_entries snapshot and here) must not kill
        # the whole cleanup — warn, then keep cleaning this feature + the rest
        # (audit A6). Already-promoted entries are a no-op inside mark itself.
        if entry["status"] != "promoted":
            try:
                mark_promoted_to_main(refined_cat, feature_id)
            except CatalogEntryNotFoundError as e:
                print(f"⚠️ cleanup: {e} — promote-stamp skipped, continuing sweep",
                      file=sys.stderr)

        # 2. Archive folder.
        candidates = list((repo / ".claude" / "refined_backlog").glob(f"{feature_id}-*"))
        for src in candidates:
            if src.is_dir() and "_archive" not in src.parts:
                dst = archive_root / src.name
                if not dst.exists():
                    shutil.move(str(src), str(dst))
                    _shipped = {
                        "shipped_at": entry.get("shipped_at"),
                        "promoted_at": _now(),
                        "release_version": version,
                        "original_branch": f"feat/{feature_id}",
                    }
                    (dst / "_shipped.json").write_text(json.dumps(_shipped, indent=2))

        # 3. Remove feature worktree(s) FIRST (must precede local branch deletion).
        for wt_path in (repo / ".claude" / "worktrees").glob(f"{feature_id}-*"):
            try:
                remove_worktree(repo, wt_path, force=True)
            except GitError:
                pass

        # 4. Delete feat branches (worktree is gone, so local delete can succeed).
        feat_branch = f"feat/{feature_id}"
        delete_branch_remote(repo, feat_branch)
        try:
            delete_branch_local(repo, feat_branch)
        except GitError:
            pass

        # 5. Clear claim entry.
        def drop_claim(claims: dict) -> dict:
            claims.pop(feature_id, None)
            return claims
        try:
            mutate_state(claims_file, drop_claim, default={})
        except FileNotFoundError:
            pass

    # For each epic touched by a feature shipped into this version: archive
    # its E-NNN-<slug>/ folder, mirroring the refined-feature archival above.
    # Reads from THIS (main) checkout, not _release — that worktree is removed
    # later in this same call. Refuses to archive an INCOMPLETE epic unless it
    # is permanently split-approved (G-E3 already gated this at promote time;
    # this is a defensive mirror for a standalone --cleanup-only run).
    if touched_epics:
        epic_archive_root = repo / ".claude" / "epic_backlog" / "_archive" / version
        epic_archive_root.mkdir(parents=True, exist_ok=True)
        for epic_id in sorted(touched_epics):
            epic_entry = find_entry(epic_cat, epic_id)
            if epic_entry is None:
                print(f"⚠️ cleanup: epic {epic_id} missing from catalog — archive "
                      f"skipped, continuing sweep", file=sys.stderr)
                continue
            complete, reasons = epic_completeness(idea_cat, refined_cat, epic_id, version)
            if not complete and not epic_entry.get("split_approved_by"):
                print(f"⚠️ cleanup: {epic_id} is not complete for {version} and not "
                      f"split-approved — leaving it un-archived: {'; '.join(reasons)}",
                      file=sys.stderr)
                continue
            if epic_entry.get("status") != "promoted":
                try:
                    mark_epic_promoted(epic_cat, epic_id)
                except CatalogEntryNotFoundError as e:
                    print(f"⚠️ cleanup: {e} — epic promote-stamp skipped, "
                          f"continuing sweep", file=sys.stderr)

            candidates = list((repo / ".claude" / "epic_backlog").glob(f"{epic_id}-*"))
            for src in candidates:
                if src.is_dir() and "_archive" not in src.parts:
                    dst = epic_archive_root / src.name
                    if not dst.exists():
                        shutil.move(str(src), str(dst))

    # Remove _release worktree FIRST (must precede release branch deletion).
    rel_wt = repo / ".claude" / "worktrees" / "_release"
    if rel_wt.exists():
        try:
            remove_worktree(repo, rel_wt, force=True)
        except GitError:
            pass

    # Delete release branch (worktree is gone, so local delete can succeed).
    release_branch = f"release/{version}"
    delete_branch_remote(repo, release_branch)
    try:
        delete_branch_local(repo, release_branch)
    except GitError:
        pass

    # Finalize .release.json (only when still in progress) THEN commit + push
    # everything cleanup produced. We based on origin/main above, so this is a
    # clean fast-forward. Do NOT swallow a failed push — a silent failure here is
    # exactly what left origin's .release.json stale and local main diverged;
    # surface it with a concrete remediation instead.
    #
    # The commit+push MUST NOT be gated on in_progress. In PR-mode promote,
    # _finalize_release_state already flipped in_progress=False on the release
    # branch and the squash carried it to main — so by cleanup time in_progress
    # is already False, yet the archival moves + catalog promote-stamps + cleared
    # claims still need committing. Nesting the commit inside `if in_progress`
    # (old bug) stranded all of that uncommitted in the main checkout.
    rj_path = repo / ".release.json"
    rj = json.loads(rj_path.read_text())
    if rj.get("in_progress"):
        rj["in_progress"] = False
        rj["last_promoted_at"] = _now()
        rj["last_promoted_version"] = version
        rj_path.write_text(json.dumps(rj, indent=2) + "\n")

    # Commit any pending cleanup changes (archival, catalog, claims, and the
    # finalize above) regardless of the in_progress flag. No-op when clean.
    if git_run(repo, "status", "--porcelain").stdout.strip():
        commit_all(repo, f"chore(release): finalize {version} cleanup on main")
        if _has_origin(repo):
            try:
                git_run(repo, "push", "origin", "main")
            except GitError as e:
                raise Gate2FailedError(
                    f"finalize push to origin/main failed: {e}\n"
                    f"origin/main moved under us. Reconcile with:\n"
                    f"  git fetch origin && git reset --hard origin/main\n"
                    f"then re-run: promote_release.py --cleanup-only {version}"
                )

    return {"ok": True, "version": version}


def _build_parser():
    import argparse
    p = argparse.ArgumentParser(
        prog="psrw promote",
        description="Gate 2, then open a PR from release/<v> to main.",
    )
    p.add_argument("--gate2", action=argparse.BooleanOptionalAction, dest="gate2", default=True,
                   help="run Gate 2 (scripts/integration.sh) before promoting "
                        "(default: on; --no-gate2 to skip)")
    p.add_argument("--allow-missing-gate2", action="store_true", dest="allow_missing_gate2",
                   help="proceed even when scripts/integration.sh is missing on the "
                        "release branch (the release goes to main UNVERIFIED)")
    p.add_argument("--allow-split-epic", action="store_true", dest="allow_split_epic",
                   help="permanently mark any incomplete epic touched by this release "
                        "as an approved split (lib.epic.set_split_approved) instead of "
                        "refusing G-E3 — disclosed in the PR body, and exempts the epic "
                        "from G-E3 in every later release too")
    p.add_argument("--allow-stale-main", action="store_true", dest="allow_stale_main",
                   help="proceed even if release/<v> does not contain the latest main")
    p.add_argument("--deploy", action="store_true",
                   help="run the repo-specific local deploy (scripts/deploy-local.sh) first "
                        "(default: off)")
    p.add_argument("--push", action="store_true", default=True)
    p.add_argument("--no-push", action="store_false", dest="push")
    p.add_argument("--keep", action="store_true", help="skip auto-cleanup")
    p.add_argument("--cleanup-only", help="run cleanup for a previously-promoted version", default=None)
    p.add_argument("--force-cleanup", action="store_true", dest="force_cleanup",
                   help="with --cleanup-only: skip the release-PR safety check and clean "
                        "up even if the PR is not merged / gh is unavailable (DANGEROUS: "
                        "deleting the remote release branch auto-closes an open PR)")
    p.add_argument("--direct", action="store_false", dest="use_pr",
                   help="legacy: squash-merge release→main locally + push, no PR (default opens a PR)")
    p.add_argument("--babysit", action="store_true",
                   help="after opening the PR: watch checks (gh pr checks --watch), "
                        "squash-merge on green, and run cleanup automatically — the "
                        "'babysit + merge' convention")
    return p


def main() -> int:
    args = _build_parser().parse_args()
    repo = find_repo_root(Path.cwd())
    try:
        if args.cleanup_only:
            result = cleanup(repo, args.cleanup_only, force=args.force_cleanup)
        else:
            result = promote_release(repo, run_gate2=args.gate2, run_deploy=args.deploy,
                                     push=args.push, keep=args.keep, use_pr=args.use_pr,
                                     allow_missing_gate2=args.allow_missing_gate2,
                                     allow_split_epic=args.allow_split_epic,
                                     allow_stale_main=args.allow_stale_main,
                                     babysit=args.babysit)
    except (NoReleaseInProgressError, Gate2FailedError,
            CatalogEntryNotFoundError, RuntimeError) as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    if result.get("mode") == "pr":
        gated = " (Gate 2 passed)" if result.get("gate2_ran") else " (local Gate 2 skipped — PR CI gates it)"
        if result.get("merged"):
            print(f"\n✅ Babysat release/{result['version']} → main{gated}: checks green, "
                  f"squash-merged, cleaned up.\n   {result.get('pr_url','(see GitHub)')}")
        else:
            print(f"\n✅ PR opened for release/{result['version']} → main{gated}:\n   {result.get('pr_url','(see GitHub)')}")
            print(f"   Review + squash-merge it to deploy to prod. After merge: --cleanup-only {result['version']}")
    else:
        print(f"\n✅ Promoted v{result['version']} to main.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
