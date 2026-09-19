"""Mutations on idea_backlog/_catalog.json and refined_backlog/_catalog.json."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from lib.state import mutate_state, read_state


class CatalogEntryNotFoundError(Exception):
    """A catalog mutation targeted an id that is not in the catalog (audit A6).

    Before this existed, mutations looped over entries looking for the id and,
    on a miss, rewrote the file unchanged and returned None — a typo'd or
    drifted id "succeeded" silently (observed in the wild: features stuck in
    `shipped` forever because a promote-stamp never matched).
    """

    def __init__(self, entry_id: str, path: Path):
        self.entry_id = entry_id
        self.path = Path(path)
        super().__init__(f"catalog entry {entry_id} not found in {path}")


class _NoChange(Exception):
    """Internal sentinel raised inside the mutate_state callback to skip the
    rewrite when the entry is already in the target state. mutate_state leaves
    the file untouched when its callback raises, so no mtime/inode churn."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def next_id(entries: list[dict], prefix: str) -> str:
    """Compute the next free id (e.g. I-003 → I-004)."""
    nums = [int(e["id"].split("-", 1)[1]) for e in entries if e["id"].startswith(prefix + "-")]
    n = max(nums, default=0) + 1
    return f"{prefix}-{n:03d}"


def list_entries(catalog: Path) -> list[dict]:
    return read_state(catalog, default=[]) or []


def find_entry(catalog: Path, entry_id: str) -> Optional[dict]:
    for e in list_entries(catalog):
        if e["id"] == entry_id:
            return e
    return None


def add_idea_entry(catalog: Path, title: str, epic: str | None = None) -> dict:
    new_entry: dict = {}
    def add(entries: list) -> list:
        nid = next_id(entries, "I")
        new_entry.update({
            "id": nid, "title": title,
            "created_at": _now(), "promoted_to": None,
        })
        if epic:
            new_entry["epic"] = epic
        return entries + [new_entry]
    mutate_state(catalog, add, default=[])
    return new_entry


def add_refined_entry(catalog: Path, idea_id: str, title: str, epic: str | None = None) -> dict:
    new_entry: dict = {}
    def add(entries: list) -> list:
        nid = next_id(entries, "F")
        new_entry.update({
            "id": nid, "title": title, "from_idea": idea_id,
            "created_at": _now(),
            "claimed_by": None, "status": "open", "release_version": None,
        })
        if epic:
            new_entry["epic"] = epic
        return entries + [new_entry]
    mutate_state(catalog, add, default=[])
    return new_entry


def update_entry(catalog: Path, entry_id: str, updater: Callable[[dict], None]) -> bool:
    """Apply `updater` to the entry with id `entry_id`, atomically under the state flock.

    Matches on id regardless of the entry's current status, so semantically
    idempotent callers stay tolerant (re-marking is fine; only a MISSING id is
    an error). Strictness + churn contract (audit A6):

    - id absent → raises CatalogEntryNotFoundError; the file is left untouched.
    - `updater` left the entry unchanged (already in the target state) → the
      file is NOT rewritten (no mtime/inode/lock churn); returns False.
    - entry actually changed → file rewritten atomically; returns True.
    """
    def apply(entries: list) -> list:
        matched = [e for e in entries if e.get("id") == entry_id]
        if not matched:
            raise CatalogEntryNotFoundError(entry_id, catalog)
        before = json.dumps(entries, sort_keys=True)
        for e in matched:
            updater(e)
        if json.dumps(entries, sort_keys=True) == before:
            raise _NoChange()
        return entries

    try:
        mutate_state(catalog, apply, default=[])
    except _NoChange:
        return False
    return True


def mark_promoted(idea_catalog: Path, idea_id: str, refined_id: str) -> bool:
    """Stamp idea `idea_id` as promoted to `refined_id`.

    Raises CatalogEntryNotFoundError on an unknown idea id. Returns False
    (no rewrite) when the stamp is already in place.
    """
    def set_promoted(e: dict) -> None:
        e["promoted_to"] = refined_id
    return update_entry(idea_catalog, idea_id, set_promoted)


def mark_shipped(refined_catalog: Path, feature_id: str, release_version: str) -> bool:
    """Mark feature `feature_id` shipped on `release_version`.

    Raises CatalogEntryNotFoundError on an unknown feature id. Transitions from
    ANY prior status (id is the match key). Already shipped on the same version
    → no-op success (shipped_at preserved, no rewrite), returns False.
    """
    def set_shipped(e: dict) -> None:
        if e.get("status") == "shipped" and e.get("release_version") == release_version:
            return  # already in target state; keep the original shipped_at
        e["status"] = "shipped"
        e["release_version"] = release_version
        e["shipped_at"] = _now()
    return update_entry(refined_catalog, feature_id, set_shipped)


def mark_promoted_to_main(refined_catalog: Path, feature_id: str) -> bool:
    """Mark feature `feature_id` promoted to main.

    Raises CatalogEntryNotFoundError on an unknown feature id. Transitions from
    ANY prior status (id is the match key). Already promoted → no-op success
    (promoted_at preserved, no rewrite), returns False.
    """
    def set_promoted(e: dict) -> None:
        if e.get("status") == "promoted":
            return  # already in target state; keep the original promoted_at
        e["status"] = "promoted"
        e["promoted_at"] = _now()
    return update_entry(refined_catalog, feature_id, set_promoted)
