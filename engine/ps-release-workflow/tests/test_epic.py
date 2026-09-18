import json
from pathlib import Path

import pytest

from lib.catalog import CatalogEntryNotFoundError
from lib.epic import (
    add_epic_entry,
    demote_epic,
    epic_completeness,
    mark_epic_failed,
    mark_epic_promoted,
    mark_epic_verified,
    set_split_approved,
    try_begin_verification,
)


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
    before = cat.read_text()
    with pytest.raises(CatalogEntryNotFoundError):
        try_begin_verification(cat, "E-999", "deadbeef")
    assert cat.read_text() == before, "a raise must leave the file untouched"


def test_verified_and_failed_clear_the_verifying_sha_breadcrumb(tmp_path):
    cat = _write(tmp_path / "epic.json", [])
    add_epic_entry(cat, "A")
    add_epic_entry(cat, "B")
    try_begin_verification(cat, "E-001", "sha1")
    verified = mark_epic_verified(cat, "E-001", "sha1", "1.1")
    assert verified["status"] == "verified"
    assert verified["verified_sha"] == "sha1"
    assert verified["verifying_sha"] is None

    try_begin_verification(cat, "E-002", "sha2")
    failed = mark_epic_failed(cat, "E-002", "1.1")
    assert failed["status"] == "failed_verification"
    assert failed["verifying_sha"] is None


def test_mark_verified_is_a_noop_when_the_epic_is_not_verifying(tmp_path):
    """Guards the CAS's exit the same way try_begin_verification guards its
    entry: a finishing run must not overwrite an epic that moved on (force-
    cleared, or already re-verified by someone else) while it was running."""
    cat = _write(tmp_path / "epic.json", [])
    add_epic_entry(cat, "A")
    # Never entered 'verifying' at all — status is still 'open'.
    result = mark_epic_verified(cat, "E-001", "stale-sha", "1.1")
    assert result["status"] == "open"
    assert result["verified_sha"] is None


def test_demote_epic_clears_in_flight_and_release_breadcrumbs(tmp_path):
    cat = _write(tmp_path / "epic.json", [])
    add_epic_entry(cat, "A")
    try_begin_verification(cat, "E-001", "sha1")
    mark_epic_verified(cat, "E-001", "sha1", "1.1")
    demoted = demote_epic(cat, "E-001")
    assert demoted["status"] == "open"
    assert demoted["verified_sha"] is None
    assert demoted["verified_at"] is None
    assert demoted["verifying_sha"] is None
    assert demoted["release_version"] is None


def test_force_reclaims_a_verified_epic_in_one_atomic_step(tmp_path):
    """G-E3's re-run path: a 'verified' epic whose sha is stale must be
    re-claimable directly, not via a separate demote-then-CAS with a gap
    between the two lock acquisitions."""
    cat = _write(tmp_path / "epic.json", [])
    add_epic_entry(cat, "A")
    try_begin_verification(cat, "E-001", "sha1")
    mark_epic_verified(cat, "E-001", "sha1", "1.1")

    assert try_begin_verification(cat, "E-001", "sha2") is False, \
        "without force, a verified epic must not be reclaimable"
    assert try_begin_verification(cat, "E-001", "sha2", force=True) is True
    entry = json.loads(cat.read_text())[0]
    assert entry["status"] == "verifying"
    assert entry["verifying_sha"] == "sha2"


def test_force_clears_a_stale_verifying_run(tmp_path):
    """`psrw epic verify --force` clearing a crashed run."""
    cat = _write(tmp_path / "epic.json", [])
    add_epic_entry(cat, "A")
    try_begin_verification(cat, "E-001", "crashed-sha")
    assert try_begin_verification(cat, "E-001", "new-sha", force=True) is True
    entry = json.loads(cat.read_text())[0]
    assert entry["verifying_sha"] == "new-sha"


def test_unknown_epic_id_raises_on_every_mutator_not_just_the_cas(tmp_path):
    cat = _write(tmp_path / "epic.json", [])
    add_epic_entry(cat, "A")
    for mutator in (
        lambda: mark_epic_promoted(cat, "E-999"),
        lambda: set_split_approved(cat, "E-999", "alice"),
        lambda: demote_epic(cat, "E-999"),
    ):
        with pytest.raises(CatalogEntryNotFoundError):
            mutator()
