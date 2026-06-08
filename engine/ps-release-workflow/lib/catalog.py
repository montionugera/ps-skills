"""Mutations on idea_backlog/_catalog.json and refined_backlog/_catalog.json."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from lib.state import mutate_state, read_state


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


def add_idea_entry(catalog: Path, title: str) -> dict:
    new_entry: dict = {}
    def add(entries: list) -> list:
        nid = next_id(entries, "I")
        new_entry.update({
            "id": nid, "title": title,
            "created_at": _now(), "promoted_to": None,
        })
        return entries + [new_entry]
    mutate_state(catalog, add, default=[])
    return new_entry


def add_refined_entry(catalog: Path, idea_id: str, title: str) -> dict:
    new_entry: dict = {}
    def add(entries: list) -> list:
        nid = next_id(entries, "F")
        new_entry.update({
            "id": nid, "title": title, "from_idea": idea_id,
            "created_at": _now(),
            "claimed_by": None, "status": "open", "release_version": None,
        })
        return entries + [new_entry]
    mutate_state(catalog, add, default=[])
    return new_entry


def mark_promoted(idea_catalog: Path, idea_id: str, refined_id: str) -> None:
    def update(entries: list) -> list:
        for e in entries:
            if e["id"] == idea_id:
                e["promoted_to"] = refined_id
        return entries
    mutate_state(idea_catalog, update, default=[])


def mark_shipped(refined_catalog: Path, feature_id: str, release_version: str) -> None:
    def update(entries: list) -> list:
        for e in entries:
            if e["id"] == feature_id:
                e["status"] = "shipped"
                e["release_version"] = release_version
                e["shipped_at"] = _now()
        return entries
    mutate_state(refined_catalog, update, default=[])


def mark_promoted_to_main(refined_catalog: Path, feature_id: str) -> None:
    def update(entries: list) -> list:
        for e in entries:
            if e["id"] == feature_id:
                e["status"] = "promoted"
                e["promoted_at"] = _now()
        return entries
    mutate_state(refined_catalog, update, default=[])
