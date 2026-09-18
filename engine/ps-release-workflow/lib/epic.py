"""Epic-layer state: the third catalog, the completeness predicate, and the CAS.

Pure state only — no git, no subprocess. lib/epic_gate.py owns execution.
"""
from datetime import datetime, timezone
from pathlib import Path

from lib.backlog_paths import get_release_worktree
from lib.catalog import CatalogEntryNotFoundError, list_entries, next_id, update_entry
from lib.state import mutate_state


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_epic_entry(catalog: Path, title: str) -> dict:
    new_entry: dict = {}

    def add(entries: list) -> list:
        new_entry.update({
            "id": next_id(entries, "E"),
            "title": title,
            "created_at": _now(),
            "status": "open",
            "release_version": None,
            "verified_sha": None,
            "verified_at": None,
            "split_approved_by": None,
        })
        return entries + [new_entry]

    mutate_state(catalog, add, default=[])
    return new_entry


def epic_children(idea_cat: Path, epic_id: str) -> list[dict]:
    """Ideas tagged to this epic. Legacy entries have no 'epic' key — .get() tolerates that."""
    return [e for e in list_entries(idea_cat) if e.get("epic") == epic_id]


def epic_completeness(
    idea_cat: Path, refined_cat: Path, epic_id: str, release_version: str
) -> tuple[bool, list[str]]:
    """Spec 5.1. Returns (is_complete, reasons_not_complete).

    Condition 3 checks status AND release_version: unclaim.py:112-118 clears
    claimed_by but LEAVES release_version set, so release_version alone would
    misread a reclaimed-then-unclaimed sibling as shipped.
    """
    reasons: list[str] = []
    ideas = epic_children(idea_cat, epic_id)

    if not ideas:
        return False, [f"{epic_id} has no ideas — it has not been fanned out"]

    unrefined = [i["id"] for i in ideas if not i.get("promoted_to")]
    if unrefined:
        reasons.append(f"not yet refined into a feature: {', '.join(sorted(unrefined))}")

    wanted = {i["promoted_to"] for i in ideas if i.get("promoted_to")}
    by_id = {f["id"]: f for f in list_entries(refined_cat)}
    for feature_id in sorted(wanted):
        feature = by_id.get(feature_id)
        if feature is None:
            reasons.append(f"{feature_id} is missing from the refined catalog")
        elif feature.get("status") not in ("shipped", "promoted"):
            reasons.append(f"{feature_id} is {feature.get('status')}, not shipped")
        elif feature.get("release_version") != release_version:
            reasons.append(
                f"{feature_id} shipped on {feature.get('release_version')}, not {release_version}"
            )

    return (not reasons), reasons


class _NoTransition(Exception):
    """Raised inside the mutate_state callback to leave the file untouched."""


def try_begin_verification(epic_cat: Path, epic_id: str, sha: str, force: bool = False) -> bool:
    """Compare-and-set: open|failed_verification -> verifying. True == this caller won.

    False means only "someone else is verifying, or already verified" — a lost
    CAS, not a missing epic. An absent id raises CatalogEntryNotFoundError
    instead, so a typo'd/drifted epic id cannot make the gate silently never
    run (the same silent-drift class this catalog already kills — see
    CatalogEntryNotFoundError's docstring).

    force=True additionally accepts verifying|verified as source states, in the
    SAME atomic mutation. This is the single path for the two callers that must
    claim an epic out of a non-idle state: `psrw epic verify --force` clearing a
    stale 'verifying' left by a crashed run, and G-E3 re-running a 'verified'
    epic whose verified_sha no longer matches release HEAD. Composing
    demote_epic() then try_begin_verification() instead would open a
    lock-acquisition gap between the two calls where a second caller could win
    a fresh CAS against the same stale epic — the exact double-run the CAS
    exists to prevent.

    No timestamp and no timeout: 'recently verifying' is not implementable without
    inventing a threshold nobody can defend. A crashed run is cleared by
    `psrw epic verify --force`.
    """
    won = False
    found = False
    allowed = ("open", "failed_verification", "verifying", "verified") if force \
        else ("open", "failed_verification")

    def cas(entries: list) -> list:
        nonlocal won, found
        won = found = False
        for e in entries:
            if e["id"] != epic_id:
                continue
            found = True
            if e.get("status") not in allowed:
                raise _NoTransition()
            e["status"] = "verifying"
            e["verifying_sha"] = sha
            won = True
            return entries
        raise _NoTransition()

    try:
        mutate_state(epic_cat, cas, default=[])
    except _NoTransition:
        if not found:
            raise CatalogEntryNotFoundError(epic_id, epic_cat)
        return False
    return won


def _set_fields(epic_cat: Path, epic_id: str, **fields) -> dict:
    """Unconditional field update, reusing catalog.update_entry so an unknown id
    raises CatalogEntryNotFoundError (not a bare KeyError) and an unchanged entry
    is not rewritten — the same found-or-raise and churn contract every other
    catalog mutator in this codebase already gives its callers."""
    updated: dict = {}

    def updater(e: dict) -> None:
        e.update(fields)
        updated.update(e)

    update_entry(epic_cat, epic_id, updater)
    return updated


def _transition(epic_cat: Path, epic_id: str, from_status: str, **fields) -> dict:
    """Like _set_fields, but only applies `fields` when the entry's CURRENT status
    is `from_status`; otherwise the file is left untouched and the entry is
    returned as-is. Guards the CAS's exit the same way try_begin_verification
    guards its entry — a force-cleared or already re-verified epic must not be
    silently overwritten by a stale finishing run landing after it."""
    updated: dict = {}

    def updater(e: dict) -> None:
        if e.get("status") == from_status:
            e.update(fields)
        updated.update(e)

    update_entry(epic_cat, epic_id, updater)
    return updated


def mark_epic_verified(epic_cat: Path, epic_id: str, sha: str, release_version: str) -> dict:
    return _transition(
        epic_cat, epic_id, "verifying", status="verified", verified_sha=sha,
        verified_at=_now(), release_version=release_version, verifying_sha=None,
    )


def mark_epic_failed(epic_cat: Path, epic_id: str, release_version: str) -> dict:
    return _transition(
        epic_cat, epic_id, "verifying", status="failed_verification",
        verified_sha=None, release_version=release_version, verifying_sha=None,
    )


def demote_epic(epic_cat: Path, epic_id: str) -> dict:
    """Back to 'open' — never to 'verifying', which would collide with the CAS
    and strand the epic forever. Clears verifying_sha and release_version too, so
    an idle epic carries no stale in-flight or release breadcrumb (the same
    reasoning that clears verifying_sha on the verified/failed terminal states)."""
    return _set_fields(
        epic_cat, epic_id, status="open", verified_sha=None, verified_at=None,
        verifying_sha=None, release_version=None,
    )


def mark_epic_promoted(epic_cat: Path, epic_id: str) -> dict:
    return _set_fields(epic_cat, epic_id, status="promoted")


def set_split_approved(epic_cat: Path, epic_id: str, owner: str) -> dict:
    """Permanent: once set, G-E3 exempts this epic in every later release too.
    Otherwise the operator re-approves the same split each release and the
    override decays into a rubber stamp."""
    return _set_fields(epic_cat, epic_id, split_approved_by=owner)


def epic_folder_path(repo: Path, epic_id: str) -> Path | None:
    """`E-NNN-<slug>/` inside the _release worktree, or None if no folder matches
    that id. Requires a release in progress — raises NoReleaseInProgressError via
    get_release_worktree if not (same contract as every other _release-scoped
    path helper in this codebase)."""
    root = get_release_worktree(repo) / ".claude" / "epic_backlog"
    for child in sorted(root.glob(f"{epic_id}-*")):
        if child.is_dir():
            return child
    return None
