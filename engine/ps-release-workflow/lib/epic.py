"""Epic-layer state: the third catalog, the completeness predicate, and the CAS.

Pure state only — no git, no subprocess. lib/epic_gate.py owns execution.
"""
from datetime import datetime, timezone
from pathlib import Path

from lib.catalog import list_entries, next_id
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


def try_begin_verification(epic_cat: Path, epic_id: str, sha: str) -> bool:
    """Compare-and-set: open|failed_verification -> verifying. True == this caller won.

    No timestamp and no timeout: 'recently verifying' is not implementable without
    inventing a threshold nobody can defend. A crashed run is cleared by
    `psrw epic verify --force`.
    """
    won = False

    def cas(entries: list) -> list:
        nonlocal won
        for e in entries:
            if e["id"] != epic_id:
                continue
            if e.get("status") not in ("open", "failed_verification"):
                raise _NoTransition()
            e["status"] = "verifying"
            e["verifying_sha"] = sha
            won = True
            return entries
        raise _NoTransition()

    try:
        mutate_state(epic_cat, cas, default=[])
    except _NoTransition:
        return False
    return won


def _set_fields(epic_cat: Path, epic_id: str, **fields) -> dict:
    updated: dict = {}

    def apply(entries: list) -> list:
        for e in entries:
            if e["id"] == epic_id:
                e.update(fields)
                updated.update(e)
                return entries
        raise _NoTransition()

    try:
        mutate_state(epic_cat, apply, default=[])
    except _NoTransition:
        raise KeyError(f"epic {epic_id} not found in {epic_cat}")
    return updated


def mark_epic_verified(epic_cat: Path, epic_id: str, sha: str, release_version: str) -> dict:
    return _set_fields(
        epic_cat, epic_id, status="verified", verified_sha=sha,
        verified_at=_now(), release_version=release_version,
    )


def mark_epic_failed(epic_cat: Path, epic_id: str, release_version: str) -> dict:
    return _set_fields(
        epic_cat, epic_id, status="failed_verification",
        verified_sha=None, release_version=release_version,
    )


def demote_epic(epic_cat: Path, epic_id: str) -> dict:
    """Back to 'open' — never to 'verifying', which would collide with the CAS
    and strand the epic forever."""
    return _set_fields(epic_cat, epic_id, status="open", verified_sha=None, verified_at=None)


def mark_epic_promoted(epic_cat: Path, epic_id: str) -> dict:
    return _set_fields(epic_cat, epic_id, status="promoted")


def set_split_approved(epic_cat: Path, epic_id: str, owner: str) -> dict:
    """Permanent: once set, G-E3 exempts this epic in every later release too.
    Otherwise the operator re-approves the same split each release and the
    override decays into a rubber stamp."""
    return _set_fields(epic_cat, epic_id, split_approved_by=owner)


def epic_folder_path(repo: Path, epic_id: str):
    """`E-NNN-<slug>/` inside the _release worktree, or None if absent."""
    from lib.backlog_paths import get_release_worktree
    root = get_release_worktree(repo) / ".claude" / "epic_backlog"
    for child in sorted(root.glob(f"{epic_id}-*")):
        if child.is_dir():
            return child
    return None
