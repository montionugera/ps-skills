"""Test idea/refined catalog mutations."""
import json
from pathlib import Path

import pytest

from lib.catalog import (
    CatalogEntryNotFoundError,
    next_id, list_entries, find_entry, add_idea_entry,
    add_refined_entry, mark_promoted, mark_shipped, mark_promoted_to_main,
    update_entry,
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
    assert mark_shipped(ref_cat, "F-001", release_version="1.1") is True
    entries = json.loads(ref_cat.read_text())
    assert entries[0]["status"] == "shipped"
    assert entries[0]["release_version"] == "1.1"


# ── A6: unknown ids must raise, not silently no-op ─────────────────────────────


def _stat_sig(p: Path) -> tuple:
    st = p.stat()
    return (st.st_ino, st.st_mtime_ns)


def test_mark_shipped_unknown_id_raises_naming_id_and_file(tmp_path: Path):
    ref_cat = tmp_path / "ref_catalog.json"
    ref_cat.write_text(json.dumps([{"id": "F-001", "status": "claimed"}]))
    before, sig = ref_cat.read_text(), _stat_sig(ref_cat)
    with pytest.raises(CatalogEntryNotFoundError) as ei:
        mark_shipped(ref_cat, "F-999", release_version="1.1")
    assert "F-999" in str(ei.value)
    assert str(ref_cat) in str(ei.value)
    # File left completely untouched — no rewrite of unchanged content.
    assert ref_cat.read_text() == before
    assert _stat_sig(ref_cat) == sig


def test_mark_promoted_unknown_id_raises(tmp_path: Path):
    idea_cat = tmp_path / "idea_catalog.json"
    idea_cat.write_text(json.dumps([{"id": "I-001", "promoted_to": None}]))
    with pytest.raises(CatalogEntryNotFoundError, match="I-999"):
        mark_promoted(idea_cat, idea_id="I-999", refined_id="F-001")
    assert json.loads(idea_cat.read_text())[0]["promoted_to"] is None


def test_mark_promoted_to_main_unknown_id_raises(tmp_path: Path):
    ref_cat = tmp_path / "ref_catalog.json"
    ref_cat.write_text(json.dumps([{"id": "F-001", "status": "shipped"}]))
    with pytest.raises(CatalogEntryNotFoundError, match="F-057"):
        mark_promoted_to_main(ref_cat, "F-057")
    assert json.loads(ref_cat.read_text())[0]["status"] == "shipped"


def test_update_entry_unknown_id_raises_and_leaves_file(tmp_path: Path):
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps([{"id": "F-001", "status": "open"}]))
    sig = _stat_sig(cat)
    with pytest.raises(CatalogEntryNotFoundError, match="F-042"):
        update_entry(cat, "F-042", lambda e: e.update(status="claimed"))
    assert _stat_sig(cat) == sig


# ── A6: id matches regardless of prior status (idempotent callers stay tolerant) ──


def test_mark_shipped_transitions_from_any_prior_state(tmp_path: Path):
    ref_cat = tmp_path / "ref_catalog.json"
    ref_cat.write_text(json.dumps([{"id": "F-001", "status": "open", "release_version": None}]))
    assert mark_shipped(ref_cat, "F-001", release_version="1.1") is True
    assert json.loads(ref_cat.read_text())[0]["status"] == "shipped"


def test_mark_promoted_to_main_from_shipped_transitions(tmp_path: Path):
    ref_cat = tmp_path / "ref_catalog.json"
    ref_cat.write_text(json.dumps([{"id": "F-001", "status": "shipped"}]))
    assert mark_promoted_to_main(ref_cat, "F-001") is True
    entry = json.loads(ref_cat.read_text())[0]
    assert entry["status"] == "promoted"
    assert entry["promoted_at"]


# ── A6 fix #2: already-in-target-state is a no-op success WITHOUT a rewrite ────


def test_mark_shipped_already_shipped_same_version_skips_rewrite(tmp_path: Path):
    ref_cat = tmp_path / "ref_catalog.json"
    ref_cat.write_text(json.dumps([{
        "id": "F-001", "status": "shipped",
        "release_version": "1.1", "shipped_at": "2026-01-01T00:00:00+00:00",
    }]))
    before, sig = ref_cat.read_text(), _stat_sig(ref_cat)
    assert mark_shipped(ref_cat, "F-001", release_version="1.1") is False
    assert ref_cat.read_text() == before  # shipped_at NOT re-stamped
    assert _stat_sig(ref_cat) == sig      # no rewrite (inode/mtime unchanged)


def test_mark_shipped_already_shipped_other_version_still_updates(tmp_path: Path):
    ref_cat = tmp_path / "ref_catalog.json"
    ref_cat.write_text(json.dumps([{
        "id": "F-001", "status": "shipped",
        "release_version": "1.0", "shipped_at": "2026-01-01T00:00:00+00:00",
    }]))
    assert mark_shipped(ref_cat, "F-001", release_version="1.1") is True
    assert json.loads(ref_cat.read_text())[0]["release_version"] == "1.1"


def test_mark_promoted_to_main_already_promoted_skips_rewrite(tmp_path: Path):
    ref_cat = tmp_path / "ref_catalog.json"
    ref_cat.write_text(json.dumps([{
        "id": "F-001", "status": "promoted", "promoted_at": "2026-01-01T00:00:00+00:00",
    }]))
    before, sig = ref_cat.read_text(), _stat_sig(ref_cat)
    assert mark_promoted_to_main(ref_cat, "F-001") is False
    assert ref_cat.read_text() == before  # promoted_at preserved
    assert _stat_sig(ref_cat) == sig


def test_mark_promoted_same_refined_id_skips_rewrite(tmp_path: Path):
    idea_cat = tmp_path / "idea_catalog.json"
    idea_cat.write_text(json.dumps([{"id": "I-001", "promoted_to": "F-001"}]))
    sig = _stat_sig(idea_cat)
    assert mark_promoted(idea_cat, idea_id="I-001", refined_id="F-001") is False
    assert _stat_sig(idea_cat) == sig
