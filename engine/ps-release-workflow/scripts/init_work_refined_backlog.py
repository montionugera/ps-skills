"""ps-release-workflow:claim — atomically claim F-NNN + cut a feature worktree (D11/SR-1/D12).

Atomicity: the host-local claim ledger (.claude/state/claims.json) lives in the MAIN
checkout and is gitignored — the flock-guarded try_claim runs there. The refined-backlog
catalog read (for --next / lookup) AND the status=claimed mutation + commit all happen on
the long-lived `_release` worktree (release/<v>), never the main checkout (SR-1). Refuses
before any feature lookup if no release is in progress (D12).
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib.backlog_paths import (
    NoReleaseInProgressError,
    get_backlog_catalog_path,
    get_release_worktree,
)
from lib.catalog import CatalogEntryNotFoundError, find_entry, list_entries, update_entry
from lib.git_ops import (
    GitError,
    _run as git_run,
    add_worktree,
    add_worktree_new_branch,
    branch_exists,
    commit_all,
    delete_branch_local,
    is_dirty,
    remove_worktree,
)
from lib.owner import resolve_owner_id
from lib.repo import find_repo_root, is_ps_release_workflow_repo
from lib.slug import slugify
from lib.state import file_lock, mutate_state


class AlreadyClaimedError(Exception): pass
class NoFreeFeatureError(Exception): pass
class FeatureNotFoundError(Exception): pass
class NotClaimedError(Exception): pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _drop_claim(claims_file: Path, feature_id: str) -> None:
    """Remove the claims.json entry for `feature_id` (under the ledger flock)."""
    def drop(claims: dict) -> dict:
        claims.pop(feature_id, None)
        return claims
    mutate_state(claims_file, drop, default={})


def claim_feature(
    repo: Path, feature_id: Optional[str], *, owner: str, select_next: bool = False
) -> dict:
    repo = Path(repo)
    if not is_ps_release_workflow_repo(repo):
        raise RuntimeError(f"{repo} not opted into ps-release-workflow")

    # Release-in-progress check FIRST — before any feature lookup (D12).
    # Raises NoReleaseInProgressError if .release.json not in_progress or _release missing.
    wt = get_release_worktree(repo)

    # Catalog reads + the status mutation/commit all target the _release worktree (SR-1).
    refined_cat = get_backlog_catalog_path(repo, "refined")
    # The claim ledger stays in the MAIN checkout (gitignored, host-local).
    claims_file = repo / ".claude" / "state" / "claims.json"

    if select_next:
        feature_id = None
        for e in list_entries(refined_cat):
            if e.get("status") == "open":
                feature_id = e["id"]
                break
        if not feature_id:
            raise NoFreeFeatureError("no unclaimed open features in refined_backlog")

    if feature_id is None:
        raise ValueError("must pass feature_id or select_next=True")

    feat = find_entry(refined_cat, feature_id)
    if feat is None:
        raise FeatureNotFoundError(feature_id)

    slug = slugify(feat["title"])
    worktree_path = repo / ".claude" / "worktrees" / f"{feature_id}-{slug}"
    branch_name = f"feat/{feature_id}"

    # Atomic claim attempt — flock around claims.json (in the main checkout).
    def try_claim(claims: dict) -> dict:
        if feature_id in claims:
            raise AlreadyClaimedError(
                f"{feature_id} held by owner={claims[feature_id]['owner']}"
            )
        claims[feature_id] = {
            "owner": owner,
            "worktree": str(worktree_path),
            "claimed_at": _now(),
        }
        return claims

    mutate_state(claims_file, try_claim, default={})

    # Transactional claim (audit A4): everything after the ledger entry must
    # either complete or roll the entry back — a failed claim leaves no
    # half-state (no orphaned ledger row, no dangling worktree/branch, no
    # ledger/catalog drift). The catalog mutate+commit step is INSIDE this
    # rollback too (M-1): a failure there tears everything down before
    # re-raising, so the feature never gets wedged half-claimed.
    created_worktree = False
    created_branch = False
    reattached = False
    try:
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        if branch_exists(repo, branch_name):
            # Re-attach (B-1): the branch survives an unclaim (branches are
            # always kept), so attach a fresh worktree to it — prior commits
            # stay intact — instead of dying on "branch already exists".
            add_worktree(repo, worktree_path, branch_name)
            reattached = True
        else:
            # No prior branch: cut feat/<F-NNN> off main.
            add_worktree_new_branch(repo, worktree_path, branch_name, "main")
            created_branch = True
        created_worktree = True

        # Write working-feature.json marker into .git/worktrees/<id>-<slug>/.
        wt_meta = repo / ".git" / "worktrees" / f"{feature_id}-{slug}"
        marker = wt_meta / "working-feature.json"
        marker.write_text(
            json.dumps(
                {"feature": feature_id, "owner": owner, "claimed_at": _now()}, indent=2
            )
        )

        # SR-1: mark catalog status=claimed in the _release worktree and commit
        # THERE. Serialized under the same lock ship takes on the shared
        # _release worktree, so a concurrent ship/claim can't interleave
        # mutate+commit and commit the wrong snapshot (audit A4).
        # update_entry raises CatalogEntryNotFoundError if the id drifted out
        # of the catalog since the find_entry check above (A6); claimed_at is
        # freshly stamped so a real claim always changes the entry. Commit also
        # when the worktree is dirty (M-2): a previous run that crashed between
        # mutate and commit left the change uncommitted — sweep it in now.
        def mark_claimed(e: dict) -> None:
            e["status"] = "claimed"
            e["claimed_by"] = owner
            e["claimed_at"] = _now()

        with file_lock(wt):
            if update_entry(refined_cat, feature_id, mark_claimed) or is_dirty(wt):
                commit_all(wt, f"chore(catalog): claim {feature_id}")
    except BaseException:
        if created_worktree:
            # Best-effort: tear down what this claim created so a retry is clean.
            try:
                remove_worktree(repo, worktree_path, force=True)
            except GitError:
                pass
        if created_branch:
            # Only delete a branch the claim itself created — a re-attached
            # pre-existing branch carries prior work and must survive (B-1).
            try:
                delete_branch_local(repo, branch_name, force=True)
            except GitError:
                pass
        _drop_claim(claims_file, feature_id)
        raise

    if reattached:
        print(
            f"ℹ️  re-attached to existing branch {branch_name} (has prior commits "
            f"from a previous claim — review before building on top)",
            file=sys.stderr,
        )

    return {
        "feature": feature_id,
        "worktree": str(worktree_path),
        "branch": branch_name,
        "owner": owner,
        "reattached": reattached,
    }


def resume_feature(repo: Path, feature_id: str, *, owner: str) -> dict:
    """Re-own (or recreate) the worktree of a feature already `claimed` in the catalog.

    Heals the observed drift (audit B2): features stuck `claimed` whose worktrees
    were deleted out-of-band, some missing from claims.json entirely (owner only
    in the catalog's claimed_by). Never goes through the AlreadyClaimedError path
    — `claimed` status is the precondition here, not a conflict.
    """
    repo = Path(repo)
    if not is_ps_release_workflow_repo(repo):
        raise RuntimeError(f"{repo} not opted into ps-release-workflow")

    # Release-in-progress check FIRST, same as claim (D12).
    wt = get_release_worktree(repo)
    refined_cat = get_backlog_catalog_path(repo, "refined")
    claims_file = repo / ".claude" / "state" / "claims.json"

    feat = find_entry(refined_cat, feature_id)
    if feat is None:
        raise FeatureNotFoundError(feature_id)
    if feat.get("status") != "claimed":
        raise NotClaimedError(
            f"{feature_id} is '{feat.get('status')}', not 'claimed' — --resume only "
            f"re-owns an existing claim. Claim it normally instead: "
            f"init_work_refined_backlog.py {feature_id}"
        )

    # Same naming convention as claim: worktree dir <F-NNN>-<slug>, branch feat/<F-NNN>.
    slug = slugify(feat["title"])
    worktree_path = repo / ".claude" / "worktrees" / f"{feature_id}-{slug}"
    branch_name = f"feat/{feature_id}"
    wt_meta = repo / ".git" / "worktrees" / f"{feature_id}-{slug}"
    marker = wt_meta / "working-feature.json"

    recreated = False
    if worktree_path.is_dir() and wt_meta.is_dir():
        # Case (a): worktree intact. If a marker exists it must be for THIS feature.
        if marker.exists():
            marker_feature = json.loads(marker.read_text()).get("feature")
            if marker_feature != feature_id:
                raise RuntimeError(
                    f"marker at {marker} belongs to {marker_feature}, expected "
                    f"{feature_id} — refusing to overwrite"
                )
        # Loud warning (m-2): resuming rewrites ownership; if the previous owner
        # left uncommitted changes behind, say so instead of silently taking
        # over on top of half-done work. No --force needed — just a warning.
        if is_dirty(worktree_path):
            dirty_files = git_run(worktree_path, "status", "--porcelain").stdout.rstrip()
            print(
                f"⚠️  {worktree_path} has UNCOMMITTED changes from the previous "
                f"owner ({feat.get('claimed_by')}):\n{dirty_files}\n"
                f"   Review/commit/stash them before building on top.",
                file=sys.stderr,
            )
    else:
        # Case (b): worktree gone (the drift case). Prune stale worktree metadata
        # so re-adding at the same path can't collide with a dangling admin dir.
        git_run(repo, "worktree", "prune", check=False)
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        if branch_exists(repo, branch_name):
            # Branch survives: re-attach — prior commits stay intact.
            add_worktree(repo, worktree_path, branch_name)
        else:
            # Branch gone too: recreate branch + worktree from the same base claim uses.
            add_worktree_new_branch(repo, worktree_path, branch_name, "main")
        recreated = True

    # Re-own: fresh marker + upsert the ledger entry (created if missing — heals
    # the catalog-only drift), both owned by the resuming session.
    marker.write_text(
        json.dumps(
            {"feature": feature_id, "owner": owner, "claimed_at": _now()}, indent=2
        )
    )

    def upsert(claims: dict) -> dict:
        entry = claims.get(feature_id) or {}
        entry.setdefault("claimed_at", _now())
        entry.update({"owner": owner, "worktree": str(worktree_path), "resumed_at": _now()})
        claims[feature_id] = entry
        return claims

    mutate_state(claims_file, upsert, default={})

    # Catalog stays `claimed`; refresh claimed_by so status shows the real owner.
    # Commit when the entry changed OR the _release worktree is dirty (M-2): a
    # previous run that crashed between mutate and commit left the catalog
    # change uncommitted — "no change now" must not strand it forever.
    def reown(e: dict) -> None:
        e["claimed_by"] = owner

    with file_lock(wt):
        if update_entry(refined_cat, feature_id, reown) or is_dirty(wt):
            commit_all(wt, f"chore(catalog): resume {feature_id} (owner -> {owner})")

    return {
        "feature": feature_id,
        "worktree": str(worktree_path),
        "branch": branch_name,
        "owner": owner,
        "recreated": recreated,
    }


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="psrw claim",
        description="Claim a refined feature (F-NNN) into an isolated worktree.",
    )
    p.add_argument("feature_id", nargs="?", help="F-NNN; required unless --next")
    p.add_argument("--next", action="store_true", dest="select_next")
    p.add_argument(
        "--resume",
        action="store_true",
        help="re-own (or recreate) the worktree of a feature already claimed "
        "in the catalog — e.g. a fresh session resuming in-flight work",
    )
    p.add_argument("--owner", default=None)
    args = p.parse_args()

    if args.resume and args.select_next:
        print("ERROR: --resume and --next are mutually exclusive", file=sys.stderr)
        return 1
    if args.resume and not args.feature_id:
        print("ERROR: --resume requires a feature id (F-NNN)", file=sys.stderr)
        return 1

    owner = args.owner or resolve_owner_id()
    repo = find_repo_root(Path.cwd())
    try:
        if args.resume:
            result = resume_feature(repo, args.feature_id, owner=owner)
        else:
            result = claim_feature(
                repo, args.feature_id, owner=owner, select_next=args.select_next
            )
    except (
        AlreadyClaimedError,
        NoFreeFeatureError,
        NoReleaseInProgressError,
        FeatureNotFoundError,
        NotClaimedError,
        CatalogEntryNotFoundError,
        GitError,
        ValueError,
        RuntimeError,
    ) as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(json.dumps({"ok": True, **result}))
    if args.resume:
        verb = "Recreated worktree for" if result["recreated"] else "Resumed"
        print(f"\n✅ {verb} {result['feature']} (worktree: {result['worktree']})")
        print(f"   Owner is now {result['owner']} (marker + claims ledger rewritten)")
    else:
        print(f"\n✅ Claimed {result['feature']} (worktree: {result['worktree']})")
    print("   Implement: /superpowers:subagent-driven-development")
    print(f"   (reads {result['worktree']}/plan.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
