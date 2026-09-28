import pytest
from pathlib import Path
from engine.vault.capture_ledger import CaptureLedger, ConflictPayloadError
from engine.vault.contracts import CategoryTrack

def test_capture_ledger_preserves_and_deduplicates(tmp_path: Path):
    ledger = CaptureLedger(ledger_dir=tmp_path / "_meta" / "ledger")
    entry1 = ledger.record_capture(
        idempotency_key="clip-101",
        category=CategoryTrack.PRODUCT,
        source_origin="web_clipper",
        raw_payload="User feedback: Add dark mode export",
    )
    assert entry1.run_id.startswith("RUN-")

    # Identical replay returns existing entry without duplicate
    entry2 = ledger.record_capture(
        idempotency_key="clip-101",
        category=CategoryTrack.PRODUCT,
        source_origin="web_clipper",
        raw_payload="User feedback: Add dark mode export",
    )
    assert entry2.run_id == entry1.run_id

    # Changed payload with same key raises ConflictPayloadError
    with pytest.raises(ConflictPayloadError):
        ledger.record_capture(
            idempotency_key="clip-101",
            category=CategoryTrack.PRODUCT,
            source_origin="web_clipper",
            raw_payload="Modified content",
        )
