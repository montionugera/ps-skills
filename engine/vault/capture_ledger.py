import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from engine.vault.contracts import CategoryTrack

class ConflictPayloadError(Exception):
    """Raised when an idempotency key is reused with a different raw payload."""
    pass

@dataclass
class CaptureEntry:
    run_id: str
    idempotency_key: str
    category: CategoryTrack
    source_origin: str
    payload_sha256: str
    raw_payload_path: str
    timestamp: str

    def __init__(
        self,
        run_id: str,
        idempotency_key: str,
        category: CategoryTrack | str,
        source_origin: str,
        payload_sha256: str,
        raw_payload_path: str,
        timestamp: str,
        **kwargs,
    ):
        self.run_id = run_id
        self.idempotency_key = idempotency_key
        self.category = CategoryTrack(category) if isinstance(category, str) else category
        self.source_origin = source_origin
        self.payload_sha256 = payload_sha256
        self.raw_payload_path = raw_payload_path
        self.timestamp = timestamp

    def model_dump(self):
        d = asdict(self)
        if isinstance(self.category, CategoryTrack):
            d["category"] = self.category.value
        return d

class CaptureLedger:
    def __init__(self, ledger_dir: Path):
        self.ledger_dir = ledger_dir
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_file = self.ledger_dir / "captures.jsonl"
        self.raw_dir = self.ledger_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def record_capture(self, idempotency_key: str, category: CategoryTrack, source_origin: str, raw_payload: str) -> CaptureEntry:
        payload_hash = self._hash(raw_payload)

        if self.ledger_file.exists():
            with open(self.ledger_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if item["idempotency_key"] == idempotency_key:
                        if item["payload_sha256"] != payload_hash:
                            raise ConflictPayloadError(f"Idempotency key {idempotency_key} reused with changed payload")
                        return CaptureEntry(**item)

        run_id = f"RUN-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
        raw_path = self.raw_dir / f"{run_id}.raw"
        raw_path.write_text(raw_payload, encoding="utf-8")

        entry = CaptureEntry(
            run_id=run_id,
            idempotency_key=idempotency_key,
            category=category,
            source_origin=source_origin,
            payload_sha256=payload_hash,
            raw_payload_path=str(raw_path),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        with open(self.ledger_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.model_dump()) + "\n")

        return entry
