import json
from pathlib import Path

import pytest

from lib.catalog import CatalogEntryNotFoundError
from lib.epic import add_epic_entry, epic_completeness, try_begin_verification


def _write(p: Path, data) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    return p


def test_unfanned_epic_is_not_vacuously_complete(tmp_path):
    ideas = _write(tmp_path / "idea.json", [])
    refined = _write(tmp_path / "ref.json", [])
    ok, reasons = epic_completeness(ideas, refined, "E-001", "1.1")
    assert ok is False
    assert any("no ideas" in r for r in reasons)


def test_unrefined_slice_blocks_completeness(tmp_path):
    """The blocker the first audit found: a slice still sitting as an idea."""
    ideas = _write(tmp_path / "idea.json", [
        {"id": "I-001", "title": "a", "promoted_to": "F-001", "epic": "E-001"},
        {"id": "I-002", "title": "b", "promoted_to": None, "epic": "E-001"},
    ])
    refined = _write(tmp_path / "ref.json", [
        {"id": "F-001", "from_idea": "I-001", "epic": "E-001",
         "status": "shipped", "release_version": "1.1"},
    ])
    ok, reasons = epic_completeness(ideas, refined, "E-001", "1.1")
    assert ok is False
    assert any("I-002" in r for r in reasons)


def test_unclaimed_sibling_with_stale_release_version_is_not_shipped(tmp_path):
    """unclaim.py:112-118 leaves release_version set; status must also be checked."""
    ideas = _write(tmp_path / "idea.json", [
        {"id": "I-001", "title": "a", "promoted_to": "F-001", "epic": "E-001"},
    ])
    refined = _write(tmp_path / "ref.json", [
        {"id": "F-001", "from_idea": "I-001", "epic": "E-001",
         "status": "open", "release_version": "1.1"},
    ])
    ok, reasons = epic_completeness(ideas, refined, "E-001", "1.1")
    assert ok is False
    assert any("F-001" in r for r in reasons)


def test_complete_epic(tmp_path):
    ideas = _write(tmp_path / "idea.json", [
        {"id": "I-001", "title": "a", "promoted_to": "F-001", "epic": "E-001"},
        {"id": "I-002", "title": "b", "promoted_to": "F-002", "epic": "E-001"},
    ])
    refined = _write(tmp_path / "ref.json", [
        {"id": "F-001", "from_idea": "I-001", "epic": "E-001",
         "status": "shipped", "release_version": "1.1"},
        {"id": "F-002", "from_idea": "I-002", "epic": "E-001",
         "status": "promoted", "release_version": "1.1"},
    ])
    ok, reasons = epic_completeness(ideas, refined, "E-001", "1.1")
    assert ok is True
    assert reasons == []


def test_legacy_entries_without_epic_key_are_ignored(tmp_path):
    """No migration is ever written, so the predicate must tolerate absent keys."""
    ideas = _write(tmp_path / "idea.json", [
        {"id": "I-009", "title": "legacy", "promoted_to": None},
        {"id": "I-001", "title": "a", "promoted_to": "F-001", "epic": "E-001"},
    ])
    refined = _write(tmp_path / "ref.json", [
        {"id": "F-009", "from_idea": "I-009", "status": "open", "release_version": None},
        {"id": "F-001", "from_idea": "I-001", "epic": "E-001",
         "status": "shipped", "release_version": "1.1"},
    ])
    ok, _ = epic_completeness(ideas, refined, "E-001", "1.1")
    assert ok is True


def test_cas_lets_exactly_one_caller_begin(tmp_path):
    cat = _write(tmp_path / "epic.json", [])
    add_epic_entry(cat, "Multi-account risk limits")
    assert try_begin_verification(cat, "E-001", "deadbeef") is True
    assert try_begin_verification(cat, "E-001", "deadbeef") is False
    entry = json.loads(cat.read_text())[0]
    assert entry["status"] == "verifying"


def test_cas_on_unknown_epic_id_raises_rather_than_silently_skipping(tmp_path):
    """A typo'd/drifted epic id must not read as 'someone else is verifying' —
    that is the same silent-drift class CatalogEntryNotFoundError already kills
    for the idea/refined catalogs."""
    cat = _write(tmp_path / "epic.json", [])
    add_epic_entry(cat, "Multi-account risk limits")
    with pytest.raises(CatalogEntryNotFoundError):
        try_begin_verification(cat, "E-999", "deadbeef")
