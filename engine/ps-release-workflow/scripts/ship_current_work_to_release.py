"""ps-release-workflow:ship — Gate 1 + merge feat/F-NNN into release/<v>.

D11/SR-1: the populated catalog lives ONLY in the _release worktree; MAIN's
catalog is []. So the catalog mutation/commit must target the _release worktree
in place — never the main checkout, and never copy main's catalog over it.
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import subprocess
import sys
from pathlib import Path

from lib.backlog_paths import (
    NoReleaseInProgressError,
    get_backlog_catalog_path,
    get_release_worktree,
    read_release_state,
)
from lib.catalog import CatalogEntryNotFoundError, find_entry, mark_shipped
from lib.epic import epic_children, epic_completeness, epic_folder_path, try_begin_verification
from lib.epic_gate import run_and_record
from lib.git_ops import GitError, _run as git_run, commit_all, is_dirty
from lib.hooks import HookPathError, resolve_hook
from lib.repo import is_ps_release_workflow_repo
from lib.state import file_lock


class DirtyTreeError(Exception): pass
class GateFailedError(Exception): pass
class NotInFeatureWorktreeError(Exception): pass


def _run_precheck(tree: Path) -> int | None:
    """Run the Gate 1 script with cwd=tree; return its exit code.

    Gate 1 must resolve its script from the tree whose code it is verifying
    (audit A5) — the feature worktree pre-merge, the _release worktree
    post-merge — never the main checkout, whose script/code may differ. Mirrors
    promote's Gate 2, which resolves its script from the _release worktree. The
    path comes from that tree's .release.json hooks block, defaulting to
    scripts/precheck.sh. Returns None (with a loud stderr warning, not a hard
    error) when the tree has no such script — repos without one must keep
    working. Raises GateFailedError when the hooks value itself is unusable: an
    unrunnable gate must refuse, never silently skip. Callers that have already
    committed a merge MUST roll it back around that raise (see ship_current_work).
    """
    try:
        precheck = resolve_hook(tree, "precheck")
    except HookPathError as e:
        print(f"❌ Gate 1 REFUSED — {e}", file=sys.stderr)
        raise GateFailedError(str(e))
    if not precheck.exists():
        print(f"⚠️ Gate 1 SKIPPED — {precheck} not found in {tree}", file=sys.stderr)
        return None
    return subprocess.run([str(precheck)], cwd=tree).returncode


def _find_marker(worktree: Path) -> dict:
    """Read .git/worktrees/<id>/working-feature.json for this worktree."""
    # Resolve the worktree's .git pointer.
    git_pointer = worktree / ".git"
    if git_pointer.is_file():
        # `gitdir: /path/to/.git/worktrees/<id>` format
        content = git_pointer.read_text().strip()
        gitdir = Path(content.split("gitdir:", 1)[1].strip())
        marker = gitdir / "working-feature.json"
        if marker.exists():
            return json.loads(marker.read_text())
    raise NotInFeatureWorktreeError(f"{worktree} has no working-feature.json marker")


def ship_current_work(worktree: Path) -> dict:
    worktree = Path(worktree).resolve()
    marker = _find_marker(worktree)
    feature_id = marker["feature"]

    if is_dirty(worktree):
        raise DirtyTreeError(f"{worktree} has uncommitted changes; commit or stash first")

    # Find repo root from the worktree's git common dir.
    common_dir = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], cwd=worktree, capture_output=True, text=True, check=True
    ).stdout.strip()
    repo = Path(common_dir).parent.resolve()
    if not is_ps_release_workflow_repo(repo):
        raise RuntimeError(f"{repo} not opted into ps-release-workflow")

    # In-progress + version come from the _release worktree's .release.json
    # (fix #2 source of truth), not main — main carries only last-promoted state.
    state = read_release_state(repo)
    if state is None:
        raise NoReleaseInProgressError("No release in progress")
    release_version = state["version"]
    release_branch = f"release/{release_version}"

    # The _release worktree (release/<v>) — also enforces the in-progress guard.
    rel_wt = get_release_worktree(repo)

    # Run Gate 1 from the FEATURE worktree — it verifies the code being shipped
    # (audit A5: resolving from `repo` ran the main checkout's precheck against
    # the main checkout's code). Missing precheck warns loudly but allows.
    rc = _run_precheck(worktree)
    if rc is not None and rc != 0:
        raise GateFailedError(f"Gate 1 (scripts/precheck.sh) failed in {worktree}")

    # Merge feat/<feature_id> into release/<v> in the _release worktree.
    # Serialize the whole merge → re-verify → rollback → mark critical section on
    # the shared _release worktree so two concurrent ships can't corrupt the tree
    # or roll back the wrong commit.
    feat_branch = f"feat/{feature_id}"
    with file_lock(rel_wt):
        try:
            git_run(rel_wt, "merge", "--no-ff", "-m", f"merge {feat_branch} into {release_branch}", feat_branch)
        except GitError as e:
            # Abort any partial/conflicted merge before surfacing the failure.
            git_run(rel_wt, "merge", "--abort", check=False)
            raise GateFailedError(f"merge of {feat_branch} into {release_branch} failed: {e}")

        # Re-verify Gate 1 on the MERGED result — precheck resolved from the
        # _release worktree itself, so it checks the combined release code.
        try:
            rc = _run_precheck(rel_wt)
        except GateFailedError:
            # A bad hooks.precheck path must not leave the merge standing: the
            # raise would otherwise skip the rollback below and escape the lock
            # with the feature merged on release/<v> while ship reports failure.
            git_run(rel_wt, "reset", "--hard", "HEAD~1")
            raise
        if rc is not None and rc != 0:
            # Roll back the merge: hard reset to release HEAD~1
            git_run(rel_wt, "reset", "--hard", "HEAD~1")
            raise GateFailedError(f"Gate 1 failed on combined release after merge — rolled back")

        # Mark catalog status=shipped IN PLACE in the _release worktree (D11/SR-1).
        # The populated catalog lives only here; main's is []. No copy step.
        # Raises CatalogEntryNotFoundError if the marker's feature id drifted out
        # of the catalog (audit A6) — surfaced as a clean CLI error in main().
        # Returns False when already shipped on this version (re-ship): no
        # rewrite. Commit also when the worktree is dirty (M-2): a previous run
        # that crashed between mark_shipped and commit_all left the change
        # uncommitted — "no change now" must not strand it forever.
        refined_cat = get_backlog_catalog_path(repo, "refined")
        if mark_shipped(refined_cat, feature_id, release_version) or is_dirty(rel_wt):
            commit_all(rel_wt, f"chore(catalog): {feature_id} status=shipped on {release_version}")

        # G-E2 CAS: decide, under this same lock (HEAD is stable here), whether
        # THIS ship is the one that triggers the epic outcome check. The check
        # itself must not run inside this lock — see below, outside the `with`.
        epic_id = (find_entry(refined_cat, feature_id) or {}).get("epic")
        cas_sha = None
        idea_cat = get_backlog_catalog_path(repo, "idea")
        epic_cat = get_backlog_catalog_path(repo, "epic")
        if epic_id:
            complete, _ = epic_completeness(idea_cat, refined_cat, epic_id, release_version)
            if complete:
                head = git_run(rel_wt, "rev-parse", "HEAD").stdout.strip()
                if try_begin_verification(epic_cat, epic_id, head):
                    cas_sha = head
                    # Commit the CAS win NOW, still inside the lock. try_begin_
                    # verification's write is a plain, uncommitted filesystem
                    # change (mutate_state does tmp-write + replace, no git);
                    # left uncommitted, a concurrent ship's Gate-1 rollback
                    # (`git reset --hard HEAD~1`, above) wipes it and reverts
                    # the epic to "open" while this run's multi-minute check
                    # is still in flight — the exact double-run the CAS exists
                    # to prevent (finding 1/7).
                    commit_all(rel_wt, f"chore(epic): {epic_id} verification claimed at {head}")

    # Lock released; only the CAS winner reaches here. The check can take
    # minutes, so holding the _release lock across it would stall every
    # concurrent ship — only the catalog write recording its outcome
    # (lib.epic_gate.run_and_record) is serialized, under its own short lock.
    epic_outcome = None
    if cas_sha:
        # promoted_to is None until an idea is promoted to refined (finding
        # 5/13) — filter it out exactly like epic.py's epic_verify does, so a
        # concurrent `epic fanout` landing between the lock release above and
        # this read can't crash `",".join(sorted(features))` on a mixed
        # str/None list downstream in run_epic_check.
        features = [i["promoted_to"] for i in epic_children(idea_cat, epic_id)
                    if i.get("promoted_to")]
        epic_dir = epic_folder_path(repo, epic_id)
        rc, _entry = run_and_record(repo, rel_wt, epic_cat, epic_id, features, cas_sha,
                                     epic_dir, release_version)
        epic_outcome = {"epic": epic_id, "rc": rc, "sha": cas_sha}

    return {"ok": True, "feature": feature_id, "release": release_version,
            "rel_wt": str(rel_wt), "epic_outcome": epic_outcome}


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="psrw ship",
        description="Run Gate 1 (precheck.sh), then merge this feature worktree "
                    "into release/<v>.",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--deploy", action="store_true",
                   help="force the post-merge local deploy")
    g.add_argument("--no-deploy", action="store_true",
                   help="skip the post-merge local deploy (use when other sessions "
                        "are shipping to the same release right now — batch the "
                        "deploy once after the burst instead of racing rebuilds)")
    args = p.parse_args()

    cwd = Path.cwd()
    try:
        result = ship_current_work(cwd)
    except (DirtyTreeError, GateFailedError, NotInFeatureWorktreeError,
            NoReleaseInProgressError, CatalogEntryNotFoundError, GitError,
            RuntimeError) as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    print(f"\n✅ Shipped {result['feature']} to release/{result['release']}")
    # The epic outcome check is separate from Gate 1 (finding 12): ship must
    # never go silently green when it ran and failed — an operator reading
    # only the checkmark below would not learn about it until G-E3 blocks
    # promote, minutes or a release cycle later.
    epic_outcome = result.get("epic_outcome")
    if epic_outcome is not None and epic_outcome["rc"] not in (None, 0):
        print(
            f"\n⚠️  Epic {epic_outcome['epic']} outcome check FAILED (exit "
            f"{epic_outcome['rc']}) at {epic_outcome['sha'][:12]} — recorded as "
            f"failed_verification. The merge above still stands; fix the epic "
            f"before promote, or re-check with "
            f"`psrw epic verify --force {epic_outcome['epic']}`.",
            file=sys.stderr,
        )

    rel_wt = Path(result["rel_wt"])
    # Resolve through the hooks block exactly as promote does — a hardcoded
    # rel_wt/"scripts"/"deploy-local.sh" made a repo with a custom
    # hooks.deploy_local get a deploy from promote and a silent no-op from ship
    # (the .exists() gate just failed), while ship/SKILL.md already advertised
    # "the repo's own local deploy script (default scripts/deploy-local.sh)".
    try:
        deploy_script = resolve_hook(rel_wt, "deploy_local")
    except HookPathError as e:
        # We are PAST the merge: ship_current_work() has already merged and
        # marked the catalog. Refuse the deploy LOUDLY (an unrunnable configured
        # hook must never be silently skipped) but do NOT imply the ship failed —
        # and keep the exit code 0, matching the existing precedent below where a
        # deploy script that runs and FAILS also leaves ship successful.
        print(
            f"\n❌ Post-merge local deploy REFUSED — {e}\n"
            f"   The merge into release/{result['release']} SUCCEEDED and the catalog "
            f"is marked shipped; only the deploy was skipped.\n"
            f"   Fix hooks.deploy_local in .release.json on release/{result['release']}, "
            f"then deploy by hand: cd {rel_wt} && ./scripts/deploy-local.sh",
            file=sys.stderr,
        )
        print(f"\n   Continue with next feature, or promote: psrw promote")
        return 0
    if deploy_script.exists():
        # Deploy-local is a DEFAULT step of ship (treat merge-to-release like an
        # MR merge that triggers a staging deploy). Precedence UNCHANGED:
        #   --no-deploy      -> skip (concurrent-session burst; batch the deploy)
        #   --deploy         -> force deploy
        #   interactive tty  -> prompt (Enter = yes)
        #   non-interactive  -> deploy by default
        # deploy-local.sh itself refuses any non-local kubectl context, so this
        # can never touch prod even when it runs unattended.
        if args.no_deploy:                      # was: "--no-deploy" in sys.argv
            deploy_now = False
        elif args.deploy:                       # was: "--deploy" in sys.argv
            deploy_now = True
        elif sys.stdin.isatty():
            deploy_now = False
            try:
                choice = input("\nDeploy the release locally now? [Y/n]: ").strip().lower()
                if choice in ('', 'y', 'yes'):
                    deploy_now = True
            except KeyboardInterrupt:
                pass
        else:
            deploy_now = True

        if deploy_now:
            print("\n🚀 Running local deployment...")
            rc = subprocess.run([str(deploy_script)], cwd=rel_wt).returncode
            if rc != 0:
                print(f"\n⚠️  {deploy_script.name} exited {rc} — verify pods (it can be "
                      f"a false negative on a stale image/migrate). Re-run: "
                      f"cd {rel_wt} && {deploy_script}")
        else:
            print(f"\n⏭️  Local deploy skipped. Run it manually when ready: "
                  f"cd {rel_wt} && {deploy_script}")

    print(f"\n   Continue with next feature, or promote: psrw promote")
    return 0


if __name__ == "__main__":
    sys.exit(main())
