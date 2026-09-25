"""ps-release-workflow:unclaim — release a claimed feature F-NNN (audit B2).

Reverses claim without losing work: removes the per-feature worktree (refusing
on uncommitted changes unless --force), deletes the claims.json ledger entry
under its flock, and sets the catalog entry back to status=open via the
_release worktree — serialized under the same file_lock ship/claim take (SR-1).
The feature BRANCH is always kept, so committed work survives an unclaim.

Also heals the observed drift: a worktree already deleted out-of-band still
gets its ledger entry and catalog status cleaned up.
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import sys
from pathlib import Path

from lib.backlog_paths import (
    NoReleaseInProgressError,
    get_backlog_catalog_path,
    get_release_worktree,
)
from lib.catalog import CatalogEntryNotFoundError, find_entry, update_entry
from lib.epic import demote_epic
from lib.git_ops import GitError, _run as git_run, commit_all, is_dirty, remove_worktree
from lib.owner import current_session_id
from lib.repo import find_repo_root, is_ps_release_workflow_repo
from lib.slug import slugify
from lib.state import file_lock, mutate_state, read_state


class FeatureNotFoundError(Exception): pass
class NotClaimedError(Exception): pass
class DirtyWorktreeError(Exception): pass


def unclaim_feature(repo: Path, feature_id: str, *, force: bool = False) -> dict:
    repo = Path(repo)
    if not is_ps_release_workflow_repo(repo):
        raise RuntimeError(f"{repo} not opted into ps-release-workflow")

    # Release-in-progress check FIRST — the populated catalog lives only in the
    # _release worktree (D11/SR-1/D12).
    wt = get_release_worktree(repo)
    refined_cat = get_backlog_catalog_path(repo, "refined")
    claims_file = repo / ".claude" / "state" / "claims.json"

    feat = find_entry(refined_cat, feature_id)
    claims = read_state(claims_file, default={}) or {}
    ledger = claims.get(feature_id) or {}

    # Drift (M-1): a ledger row whose id is ABSENT from the catalog — e.g. a
    # claim that crashed mid-rollback. unclaim is the healing tool, so it must
    # be able to heal this: warn, then still remove the worktree (if any) and
    # drop the ledger row. Only when NEITHER side knows the id is it an error.
    catalog_entry_missing = feat is None
    if feat is None and not ledger:
        raise FeatureNotFoundError(feature_id)
    if feat is not None and feat.get("status") != "claimed":
        raise NotClaimedError(
            f"{feature_id} is '{feat.get('status')}', not 'claimed' — nothing to unclaim"
        )
    if catalog_entry_missing:
        print(
            f"⚠️  {feature_id} has a claims-ledger row but NO catalog entry "
            f"(drift) — removing the worktree and dropping the ledger row anyway",
            file=sys.stderr,
        )

    # Worktree path: prefer the ledger entry; reconstruct claim's naming
    # convention (<F-NNN>-<slug>) when the entry is missing (drift case).
    if ledger.get("worktree"):
        worktree_path = Path(ledger["worktree"])
    elif feat is not None:
        worktree_path = repo / ".claude" / "worktrees" / f"{feature_id}-{slugify(feat['title'])}"
    else:
        # Ledger row without a worktree path and no catalog title to slugify:
        # fall back to the naming-convention prefix (miss → nothing to remove).
        matches = sorted((repo / ".claude" / "worktrees").glob(f"{feature_id}-*"))
        worktree_path = matches[0] if matches else repo / ".claude" / "worktrees" / feature_id
    branch_name = f"feat/{feature_id}"

    # Local sessions share one machine-cached owner id, so an owner match does
    # not prove this is the caller's own claim. The claim records the harness
    # session id; warn loudly when a DIFFERENT session is abandoning it.
    claim_session = ledger.get("session_id")
    this_session = current_session_id()
    if claim_session and this_session and claim_session != this_session:
        print(
            f"⚠️  {feature_id} was claimed by a different session ({claim_session}); "
            f"this is session {this_session}. Make sure that session is done with "
            f"it — unclaim removes its worktree.",
            file=sys.stderr,
        )

    worktree_removed = False
    if worktree_path.is_dir():
        if is_dirty(worktree_path):
            # List every modified AND untracked path (porcelain includes both),
            # so the operator sees exactly what --force would destroy.
            dirty = git_run(worktree_path, "status", "--porcelain",
                            "--untracked-files=all").stdout.rstrip()
            if not force:
                raise DirtyWorktreeError(
                    f"{worktree_path} has uncommitted or untracked changes:\n{dirty}\n"
                    f"Commit them first, or re-run with --force to DISCARD them"
                )
            print(f"⚠️  --force: discarding uncommitted changes in {worktree_path}:\n{dirty}",
                  file=sys.stderr)
        remove_worktree(repo, worktree_path, force=force)
        worktree_removed = True
    else:
        # Drift: worktree already gone out-of-band. Prune the dangling
        # .git/worktrees/<id> metadata (and its marker) so nothing stale remains.
        git_run(repo, "worktree", "prune", check=False)

    # Ledger: drop the entry under the claims flock.
    def drop(c: dict) -> dict:
        c.pop(feature_id, None)
        return c
    mutate_state(claims_file, drop, default={})

    # Catalog: back to open, clear claimed_by; mutate+commit via the _release
    # worktree, serialized under the same lock ship/claim take (SR-1, A4).
    # update_entry raises CatalogEntryNotFoundError on a drifted id (A6).
    # Commit when the entry changed OR the worktree is dirty (M-2): a previous
    # run that crashed between mutate and commit left the change uncommitted —
    # "no change now" must not strand it forever. Skipped entirely when the
    # catalog never had the entry (nothing to reopen).
    def reopen(e: dict) -> None:
        e["status"] = "open"
        e["claimed_by"] = None
        e.pop("claimed_at", None)

    if not catalog_entry_missing:
        with file_lock(wt):
            changed = update_entry(refined_cat, feature_id, reopen)

            # Demote the epic this feature belongs to, IF it was already
            # 'verified' — a shipped→reclaimed→unclaimed feature (unclaim
            # leaves release_version set above; see epic_completeness's
            # docstring) means the epic's completeness truth just changed
            # underneath a verdict that no longer holds. Demote to 'open',
            # NEVER 'verifying' — that would collide with the ship-time CAS
            # (lib.epic.try_begin_verification) and strand the epic forever
            # in 'verifying' with no owner to finish it.
            epic_id = feat.get("epic") if feat is not None else None
            if epic_id:
                epic_cat = get_backlog_catalog_path(repo, "epic")
                epic_entry = find_entry(epic_cat, epic_id)
                if epic_entry is not None and epic_entry.get("status") == "verified":
                    demote_epic(epic_cat, epic_id)

            if changed or is_dirty(wt):
                commit_all(wt, f"chore(catalog): unclaim {feature_id}")

    return {
        "feature": feature_id,
        "worktree": str(worktree_path),
        "worktree_removed": worktree_removed,
        "branch": branch_name,
        "branch_kept": True,
        "catalog_entry_missing": catalog_entry_missing,
    }


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="psrw unclaim",
        description="Release a claimed feature: remove its worktree, clear the "
        "claims ledger entry, and set the catalog entry back to open. The "
        "feature branch is always kept, so committed work is preserved."
    )
    p.add_argument("feature_id", help="F-NNN")
    p.add_argument(
        "--force",
        action="store_true",
        help="discard uncommitted changes in the worktree instead of refusing",
    )
    args = p.parse_args()

    repo = find_repo_root(Path.cwd())
    try:
        result = unclaim_feature(repo, args.feature_id, force=args.force)
    except (
        FeatureNotFoundError,
        NotClaimedError,
        DirtyWorktreeError,
        NoReleaseInProgressError,
        CatalogEntryNotFoundError,
        GitError,
        RuntimeError,
    ) as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(json.dumps({"ok": True, **result}))
    if result["catalog_entry_missing"]:
        print(f"\n✅ Unclaimed {result['feature']} — ledger row dropped (catalog had no entry)")
    else:
        print(f"\n✅ Unclaimed {result['feature']} — catalog back to open")
    if result["worktree_removed"]:
        print(f"   Worktree removed: {result['worktree']}")
    else:
        print(f"   Worktree was already gone: {result['worktree']} (ledger + catalog cleaned)")
    print(f"   Branch {result['branch']} KEPT — committed work is preserved.")
    print(f"   Delete it manually only when truly abandoned: git branch -D {result['branch']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
