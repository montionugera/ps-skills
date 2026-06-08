"""Test idea/refined catalog mutations."""
import json
from pathlib import Path

import pytest

from lib.catalog import (
    next_id, list_entries, find_entry, add_idea_entry,
    add_refined_entry, mark_promoted, mark_shipped,
)


def test_next_id_empty_returns_001():
    assert next_id([], prefix="I") == "I-001"


def test_next_id_increments_max():
    assert next_id([{"id": "I-001"}, {"id": "I-003"}], prefix="I") == "I-004"


def test_next_id_zero_padded_to_3():
    assert next_id([{"id": "I-099"}], prefix="I") == "I-100"


def test_add_idea_entry(tmp_path: Path):
    cat = tmp_path / "catalog.json"
    cat.write_text("[]")
    entry = add_idea_entry(cat, title="My idea")
    assert entry["id"] == "I-001"
    assert entry["title"] == "My idea"
    assert entry["promoted_to"] is None
    persisted = json.loads(cat.read_text())
    assert persisted == [entry]


def test_add_refined_entry_marks_idea_promoted(tmp_path: Path):
    idea_cat = tmp_path / "idea_catalog.json"
    ref_cat = tmp_path / "ref_catalog.json"
    idea_cat.write_text(json.dumps([{"id": "I-001", "title": "X", "promoted_to": None}]))
    ref_cat.write_text("[]")
    ref_entry = add_refined_entry(ref_cat, idea_id="I-001", title="X")
    mark_promoted(idea_cat, idea_id="I-001", refined_id=ref_entry["id"])
    assert json.loads(idea_cat.read_text())[0]["promoted_to"] == ref_entry["id"]
    assert ref_entry["from_idea"] == "I-001"
    assert ref_entry["status"] == "open"


def test_mark_shipped_sets_status_and_release_version(tmp_path: Path):
    ref_cat = tmp_path / "ref_catalog.json"
    ref_cat.write_text(json.dumps([{"id": "F-001", "status": "claimed", "release_version": None}]))
    mark_shipped(ref_cat, "F-001", release_version="1.1")
    entries = json.loads(ref_cat.read_text())
    assert entries[0]["status"] == "shipped"
    assert entries[0]["release_version"] == "1.1"
