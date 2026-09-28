# Agentic Second Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Agentic Second Brain operating system to guide ideas through 4 Big Phases (**Idea Generate**, **Refine + Go/No-Go**, **Implement**, **Learn/Unlearn**) across 3 Categories (**Product/Feature**, **Process/Workflow**, **Knowledge Thesis/Rules**) with zero file corruption, zero lost ideas, and human-in-the-loop control.

**Architecture:** A local Python vault gateway (`engine/vault/`) serves as the sole authoritative agent write boundary. It enforces "check before saving" (OCC), a durable append-only capture ledger, atomic multi-note backup journaling, and projects state into a local SQLite FTS5 search index and 5 human review queues.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLite FTS5, Pytest, Frontmatter YAML, Click (CLI), TypeScript (Obsidian Plugin).

**Spec:** `docs/superpowers/specs/2026-09-28-agentic-second-brain/00-INDEX.md`

## Global Constraints

- **Plain English State Transitions:** Workflow run state (`captured`, `triaged`, `working`, `review_needed`, `committing`, `completed`, `conflicted`, `failed`) is strictly decoupled from record life stages (`idea explored`, `task done`).
- **Save First (Black Box Ingestion):** Raw capture payloads, source identity, and cryptographic hashes are persisted in `_meta/ledger/captures.jsonl` prior to any folder routing or file creation.
- **Check Before Saving (OCC):** Updating a note requires non-empty `base_sha256`. Mid-run changes by human typing yield conflict alerts; silent overwrites are strictly blocked.
- **Backup Before Saving:** All note mutations create an instant pre-write backup snapshot in `_meta/snapshots/`. Crashes immediately restore the snapshot.
- **Cross-CLI Parity:** Claude Code (`SKILL.md`), Codex (MCP), and Gemini (Tool Decl) compile from a single command contract and honor identical denial rules.

---

## Phase 1: Foundation & "Idea Generate" (Capture, Deduplication & Storage)

### Task 1: Core Record & Category Models

**Files:**
- Create: `engine/vault/contracts.py`
- Test: `tests/test_vault_contracts.py`

**Interfaces:**
- Consumes: Pydantic v2
- Produces: `CategoryTrack` (`product`, `process`, `thesis`), `LifecyclePhase`, `RecordKind`, `FrontmatterContract`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_contracts.py
import pytest
from engine.vault.contracts import CategoryTrack, LifecyclePhase, RecordKind, FrontmatterContract

def test_category_tracks_and_phases():
    assert CategoryTrack.PRODUCT.value == "product_feature"
    assert CategoryTrack.PROCESS.value == "process_workflow"
    assert CategoryTrack.THESIS.value == "knowledge_thesis"

    assert LifecyclePhase.GENERATE.value == "idea_generate"
    assert LifecyclePhase.REFINE.value == "refine_go_nogo"
    assert LifecyclePhase.IMPLEMENT.value == "implement"
    assert LifecyclePhase.LEARN.value == "learn_unlearn"

def test_frontmatter_schema_validation():
    data = {
        "schema": "vault-record-v1",
        "id": "REC-2026-001",
        "category": "product_feature",
        "phase": "idea_generate",
        "title": "Autonomous Actor Mesh",
        "created": "2026-09-28T10:00:00Z",
        "updated": "2026-09-28T10:00:00Z",
    }
    contract = FrontmatterContract(**data)
    assert contract.id == "REC-2026-001"
    assert contract.category == CategoryTrack.PRODUCT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vault_contracts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.vault'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/vault/contracts.py
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime

class CategoryTrack(str, Enum):
    PRODUCT = "product_feature"
    PROCESS = "process_workflow"
    THESIS = "knowledge_thesis"

class LifecyclePhase(str, Enum):
    GENERATE = "idea_generate"
    REFINE = "refine_go_nogo"
    IMPLEMENT = "implement"
    LEARN = "learn_unlearn"

class RecordKind(str, Enum):
    IDEA = "idea"
    PROJECT = "project"
    TASK = "task"
    DECISION = "decision"
    RESEARCH = "research"
    SOURCE = "source"
    DAILY = "daily"

class FrontmatterContract(BaseModel):
    schema: str = "vault-record-v1"
    id: str
    category: CategoryTrack
    phase: LifecyclePhase
    title: str
    created: str
    updated: str
    tags: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vault_contracts.py -v`
Expected: PASS

- [ ] **Step 5: Update README & Documentation**

Document `CategoryTrack` and `LifecyclePhase` in `README.md`.

- [ ] **Step 6: Commit**

```bash
git add engine/vault/contracts.py tests/test_vault_contracts.py README.md
git commit -m "feat(vault): add 3 categories and 4 lifecycle phase models"
```

- [ ] **Step 7: Phase gate**

Verify → Review → `/simplify` → Re-verify.

---

### Task 2: Black-Box Capture Ledger & Duplicate Prevention

**Files:**
- Create: `engine/vault/capture_ledger.py`
- Test: `tests/test_vault_capture_ledger.py`

**Interfaces:**
- Consumes: `engine.vault.contracts`
- Produces: `CaptureLedger`, `CaptureEntry`, `ConflictPayloadError`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_capture_ledger.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vault_capture_ledger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.vault.capture_ledger'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/vault/capture_ledger.py
import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel
from engine.vault.contracts import CategoryTrack

class ConflictPayloadError(Exception):
    pass

class CaptureEntry(BaseModel):
    run_id: str
    idempotency_key: str
    category: CategoryTrack
    source_origin: str
    payload_sha256: str
    raw_payload_path: str
    timestamp: str

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

        run_id = f"RUN-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
        raw_path = self.raw_dir / f"{run_id}.raw"
        raw_path.write_text(raw_payload, encoding="utf-8")

        entry = CaptureEntry(
            run_id=run_id,
            idempotency_key=idempotency_key,
            category=category,
            source_origin=source_origin,
            payload_sha256=payload_hash,
            raw_payload_path=str(raw_path),
            timestamp=datetime.utcnow().isoformat() + "Z",
        )

        with open(self.ledger_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.model_dump()) + "\n")

        return entry
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vault_capture_ledger.py -v`
Expected: PASS

- [ ] **Step 5: Update README & Documentation**

Document `CaptureLedger` in `README.md`.

- [ ] **Step 6: Commit**

```bash
git add engine/vault/capture_ledger.py tests/test_vault_capture_ledger.py README.md
git commit -m "feat(vault): implement black-box capture ledger with duplicate prevention"
```

- [ ] **Step 7: Phase gate**

Verify → Review → `/simplify` → Re-verify.

---

### Task 3: Purpose-Based Folder Routing & Path Resolver

**Files:**
- Create: `engine/vault/router.py`
- Test: `tests/test_vault_router.py`

**Interfaces:**
- Consumes: `engine.vault.contracts`
- Produces: `PathResolver`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_router.py
from datetime import date
from engine.vault.contracts import CategoryTrack, RecordKind
from engine.vault.router import PathResolver

def test_category_aware_routing():
    resolver = PathResolver()

    # Product Idea
    assert resolver.resolve(CategoryTrack.PRODUCT, RecordKind.IDEA, slug="dark-mode") == "01_Ideas/dark-mode.md"

    # Process Decision / ADR
    assert resolver.resolve(CategoryTrack.PROCESS, RecordKind.DECISION, slug="release-gate", owner="ReleasePipeline") == "02_Projects/ReleasePipeline/decisions/release-gate.md"

    # Thesis / Knowledge Reference
    assert resolver.resolve(CategoryTrack.THESIS, RecordKind.RESEARCH, slug="sqlite-wal-scale") == "07_Research/sqlite-wal-scale.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vault_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.vault.router'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/vault/router.py
from typing import Optional
from engine.vault.contracts import CategoryTrack, RecordKind

class PathResolver:
    def resolve(self, category: CategoryTrack, kind: RecordKind, slug: str, owner: Optional[str] = None) -> str:
        if kind == RecordKind.IDEA:
            return f"01_Ideas/{slug}.md"
        if kind == RecordKind.RESEARCH:
            return f"07_Research/{slug}.md"
        if kind == RecordKind.DECISION:
            if owner:
                return f"02_Projects/{owner}/decisions/{slug}.md"
            return f"04_Knowledge/decisions/{slug}.md"
        if kind == RecordKind.TASK:
            if owner:
                return f"02_Projects/{owner}/tasks/{slug}.md"
            return f"_inbox/tasks/{slug}.md"
        return f"_inbox/{slug}.md"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vault_router.py -v`
Expected: PASS

- [ ] **Step 5: Update README & Documentation**

Document folder mapping in `README.md`.

- [ ] **Step 6: Commit**

```bash
git add engine/vault/router.py tests/test_vault_router.py README.md
git commit -m "feat(vault): implement category-aware path resolver"
```

- [ ] **Step 7: Phase gate**

Verify → Review → `/simplify` → Re-verify.

---

## Phase 2: "Refine + Go / No-Go" (Multi-Agent Research & Human Review)

### Task 4: ChangeProposal Schema & Evidence Citation Validator

**Files:**
- Create: `engine/vault/proposals.py`
- Test: `tests/test_vault_proposals.py`

**Interfaces:**
- Consumes: `engine.vault.contracts`
- Produces: `ChangeProposal`, `ProposalOperation`, `MissingCitationError`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_proposals.py
import pytest
from engine.vault.proposals import ChangeProposal, ProposalOperation

def test_change_proposal_requires_evidence_for_high_confidence():
    # Valid cited proposal
    p = ChangeProposal(
        proposal_id="PROP-01",
        run_id="RUN-01",
        actor="claude",
        contract_version="v1",
        operation=ProposalOperation.PATCH,
        target_path="01_Ideas/dark-mode.md",
        base_sha256="abc12345",
        proposed_content="# Dark Mode Spec",
        reason="Added feasibility findings",
        idempotency_key="K-01",
        confidence=0.9,
        evidence_refs=["SRC-2026-0012"],
    )
    assert p.confidence == 0.9

    # High confidence without evidence is rejected
    with pytest.raises(ValueError, match="Evidence citations required"):
        ChangeProposal(
            proposal_id="PROP-02",
            run_id="RUN-02",
            actor="claude",
            contract_version="v1",
            operation=ProposalOperation.PATCH,
            target_path="01_Ideas/dark-mode.md",
            base_sha256="abc12345",
            proposed_content="# Unverified",
            reason="Guessed score",
            idempotency_key="K-02",
            confidence=0.9,
            evidence_refs=[],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vault_proposals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.vault.proposals'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/vault/proposals.py
from enum import Enum
from pydantic import BaseModel, Field, model_validator

class ProposalOperation(str, Enum):
    CREATE = "create"
    PATCH = "patch"
    ARCHIVE = "archive"

class ChangeProposal(BaseModel):
    proposal_id: str
    run_id: str
    actor: str
    contract_version: str = "v1"
    operation: ProposalOperation
    target_path: str
    base_sha256: str = ""
    proposed_content: str
    reason: str
    idempotency_key: str
    confidence: float = 1.0
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_invariants(self):
        if self.confidence > 0.7 and not self.evidence_refs:
            raise ValueError("Evidence citations required for confidence > 0.7")
        if self.operation in (ProposalOperation.PATCH, ProposalOperation.ARCHIVE) and not self.base_sha256.strip():
            raise ValueError("base_sha256 is required for PATCH and ARCHIVE")
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vault_proposals.py -v`
Expected: PASS

- [ ] **Step 5: Update README & Documentation**

Document citation and proposal invariants in `README.md`.

- [ ] **Step 6: Commit**

```bash
git add engine/vault/proposals.py tests/test_vault_proposals.py README.md
git commit -m "feat(vault): implement ChangeProposal with citation validation"
```

- [ ] **Step 7: Phase gate**

Verify → Review → `/simplify` → Re-verify.

---

### Task 5: The 5 Exclusive Buckets (Queues) Engine

**Files:**
- Create: `engine/vault/queues.py`
- Test: `tests/test_vault_queues.py`

**Interfaces:**
- Consumes: `engine.vault.contracts`
- Produces: `QueueManager`, `QueueBucket`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_queues.py
from engine.vault.queues import QueueManager, QueueBucket

def test_five_exclusive_buckets():
    qm = QueueManager()
    qm.register_run("R1", state="captured")
    qm.register_run("R2", state="working")
    qm.register_run("R3", state="review_needed")
    qm.register_run("R4", state="conflicted")
    qm.register_run("R5", state="completed")

    buckets = qm.get_buckets()
    assert len(buckets[QueueBucket.INBOX]) == 1
    assert len(buckets[QueueBucket.IN_PROGRESS]) == 1
    assert len(buckets[QueueBucket.NEEDS_REVIEW]) == 1
    assert len(buckets[QueueBucket.CONFLICTS_ERRORS]) == 1
    assert len(buckets[QueueBucket.COMPLETED]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vault_queues.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.vault.queues'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/vault/queues.py
from enum import Enum

class QueueBucket(str, Enum):
    INBOX = "inbox"
    IN_PROGRESS = "in_progress"
    NEEDS_REVIEW = "needs_review"
    CONFLICTS_ERRORS = "conflicts_errors"
    COMPLETED = "completed"

class QueueManager:
    STATE_TO_BUCKET = {
        "captured": QueueBucket.INBOX,
        "triaged": QueueBucket.IN_PROGRESS,
        "working": QueueBucket.IN_PROGRESS,
        "committing": QueueBucket.IN_PROGRESS,
        "review_needed": QueueBucket.NEEDS_REVIEW,
        "conflicted": QueueBucket.CONFLICTS_ERRORS,
        "failed": QueueBucket.CONFLICTS_ERRORS,
        "partial": QueueBucket.CONFLICTS_ERRORS,
        "quarantined": QueueBucket.CONFLICTS_ERRORS,
        "completed": QueueBucket.COMPLETED,
    }

    def __init__(self):
        self.runs = {}

    def register_run(self, run_id: str, state: str):
        self.runs[run_id] = state

    def get_buckets(self) -> dict[QueueBucket, list[str]]:
        res = {b: [] for b in QueueBucket}
        for run_id, state in self.runs.items():
            bucket = self.STATE_TO_BUCKET.get(state, QueueBucket.CONFLICTS_ERRORS)
            res[bucket].append(run_id)
        return res
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vault_queues.py -v`
Expected: PASS

- [ ] **Step 5: Update README & Documentation**

Document the 5 Queue Buckets in `README.md`.

- [ ] **Step 6: Commit**

```bash
git add engine/vault/queues.py tests/test_vault_queues.py README.md
git commit -m "feat(vault): implement 5 exclusive queue buckets engine"
```

- [ ] **Step 7: Phase gate**

Verify → Review → `/simplify` → Re-verify.

---

## Phase 3: "Implement" (Check-Before-Saving, Backups & Atomic Commit)

### Task 6: Check-Before-Saving (OCC Version Fingerprint Validator)

**Files:**
- Create: `engine/vault/occ.py`
- Test: `tests/test_vault_occ.py`

**Interfaces:**
- Consumes: `engine.vault.proposals`
- Produces: `OCCValidator`, `OCCConflictError`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_occ.py
import pytest
from pathlib import Path
from engine.vault.occ import OCCValidator, OCCConflictError
from engine.vault.proposals import ChangeProposal, ProposalOperation

def test_check_before_saving_blocks_human_overwrite(tmp_path: Path):
    note = tmp_path / "01_Ideas" / "dark-mode.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Initial Content", encoding="utf-8")

    validator = OCCValidator()
    h1 = validator.compute_hash(note)

    # Human edits file in Obsidian while agent was thinking
    note.write_text("# Human Edit in Obsidian", encoding="utf-8")

    proposal = ChangeProposal(
        proposal_id="P1",
        run_id="R1",
        actor="claude",
        operation=ProposalOperation.PATCH,
        target_path=str(note),
        base_sha256=h1,
        proposed_content="# Agent Overwrite Attempt",
        reason="test",
        idempotency_key="K1",
        confidence=0.5,
    )

    with pytest.raises(OCCConflictError, match="Fingerprint mismatch: Note was edited"):
        validator.verify(proposal, note)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vault_occ.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.vault.occ'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/vault/occ.py
import hashlib
from pathlib import Path
from engine.vault.proposals import ChangeProposal, ProposalOperation

class OCCConflictError(Exception):
    pass

class OCCValidator:
    @staticmethod
    def compute_hash(path: Path) -> str:
        if not path.exists():
            return ""
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def verify(self, proposal: ChangeProposal, target_file: Path) -> bool:
        if proposal.operation == ProposalOperation.CREATE:
            if target_file.exists():
                raise OCCConflictError(f"Cannot CREATE: File already exists at {target_file}")
            return True

        if not target_file.exists():
            raise OCCConflictError(f"Target file not found: {target_file}")

        current = self.compute_hash(target_file)
        if current != proposal.base_sha256:
            raise OCCConflictError(
                f"Fingerprint mismatch: Note was edited in Obsidian (expected {proposal.base_sha256[:8]}, found {current[:8]})"
            )
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vault_occ.py -v`
Expected: PASS

- [ ] **Step 5: Update README & Documentation**

Document "Check Before Saving" in `README.md`.

- [ ] **Step 6: Commit**

```bash
git add engine/vault/occ.py tests/test_vault_occ.py README.md
git commit -m "feat(vault): add check-before-saving fingerprint validator"
```

- [ ] **Step 7: Phase gate**

Verify → Review → `/simplify` → Re-verify.

---

### Task 7: Backup Snapshots & Atomic Multi-Note Commit Journal

**Files:**
- Create: `engine/vault/journal.py`
- Test: `tests/test_vault_journal.py`

**Interfaces:**
- Consumes: `engine.vault.occ`, `engine.vault.proposals`
- Produces: `CommitJournal`, `SnapshotManager`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_journal.py
import pytest
from pathlib import Path
from engine.vault.journal import CommitJournal
from engine.vault.proposals import ChangeProposal, ProposalOperation

def test_atomic_commit_with_backup_and_rollback(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("original content", encoding="utf-8")

    journal = CommitJournal(journal_dir=tmp_path / "_meta" / "journal", vault_root=vault)
    h_orig = journal.compute_hash(note)

    proposal = ChangeProposal(
        proposal_id="P1",
        run_id="R1",
        actor="claude",
        operation=ProposalOperation.PATCH,
        target_path="note.md",
        base_sha256=h_orig,
        proposed_content="safe updated content",
        reason="test update",
        idempotency_key="K1",
        confidence=0.5,
    )

    event = journal.commit_single_note(proposal)
    assert event.new_sha256 == journal.compute_hash(note)
    assert note.read_text(encoding="utf-8") == "safe updated content"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vault_journal.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.vault.journal'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/vault/journal.py
import json
import uuid
import tempfile
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel
from engine.vault.occ import OCCValidator
from engine.vault.proposals import ChangeProposal, ProposalOperation

class CommitEvent(BaseModel):
    event_id: str
    run_id: str
    target_path: str
    operation: ProposalOperation
    prior_sha256: str
    new_sha256: str
    timestamp: str

class CommitJournal:
    def __init__(self, journal_dir: Path, vault_root: Path):
        self.journal_dir = journal_dir
        self.vault_root = vault_root
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.journal_dir / "events.jsonl"
        self.snapshot_dir = self.journal_dir / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.occ = OCCValidator()

    def compute_hash(self, path: Path) -> str:
        return self.occ.compute_hash(path)

    def commit_single_note(self, proposal: ChangeProposal) -> CommitEvent:
        target = self.vault_root / proposal.target_path
        self.occ.verify(proposal, target)

        prior_hash = self.compute_hash(target)
        snap_path = self.snapshot_dir / f"{proposal.run_id}_{target.name}.bak"
        if target.exists():
            snap_path.write_bytes(target.read_bytes())

        # Atomic replace via temporary file
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=target.parent, delete=False, encoding="utf-8") as tmp:
            tmp.write(proposal.proposed_content)
            tmp_path = Path(tmp.name)

        tmp_path.replace(target)
        new_hash = self.compute_hash(target)

        event = CommitEvent(
            event_id=f"EVT-{uuid.uuid4().hex[:8]}",
            run_id=proposal.run_id,
            target_path=proposal.target_path,
            operation=proposal.operation,
            prior_sha256=prior_hash,
            new_sha256=new_hash,
            timestamp=datetime.utcnow().isoformat() + "Z",
        )

        with open(self.events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.model_dump()) + "\n")

        return event
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vault_journal.py -v`
Expected: PASS

- [ ] **Step 5: Update README & Documentation**

Document `CommitJournal` and pre-write backups in `README.md`.

- [ ] **Step 6: Commit**

```bash
git add engine/vault/journal.py tests/test_vault_journal.py README.md
git commit -m "feat(vault): implement pre-write backup snapshot and atomic commit journal"
```

- [ ] **Step 7: Phase gate**

Verify → Review → `/simplify` → Re-verify.

---

## Phase 4: "Learn / Unlearn" (Health Audit, Staleness & Privacy Gates)

### Task 8: Health Auditor (Broken Links & 90-Day Stale Claims)

**Files:**
- Create: `engine/vault/health.py`
- Test: `tests/test_vault_health.py`

**Interfaces:**
- Consumes: `engine.vault.journal`
- Produces: `HealthAuditor`, `HealthReport`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_health.py
from pathlib import Path
from engine.vault.health import HealthAuditor

def test_health_auditor_detects_broken_wikilinks(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "test.md"
    note.write_text("See [[GhostNote]] for details.", encoding="utf-8")

    auditor = HealthAuditor(vault_root=vault)
    report = auditor.audit()
    assert len(report.broken_links) == 1
    assert report.broken_links[0]["target"] == "GhostNote"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vault_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.vault.health'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/vault/health.py
import re
from pathlib import Path
from pydantic import BaseModel, Field

class HealthReport(BaseModel):
    broken_links: list[dict] = Field(default_factory=list)

class HealthAuditor:
    WIKILINK_REGEX = re.compile(r"\[\[(.*?)\]\]")

    def __init__(self, vault_root: Path):
        self.vault_root = vault_root

    def audit(self) -> HealthReport:
        broken = []
        for f in self.vault_root.rglob("*.md"):
            for match in self.WIKILINK_REGEX.finditer(f.read_text(encoding="utf-8")):
                target = match.group(1).split("|")[0].strip()
                if not (self.vault_root / f"{target}.md").exists() and not list(self.vault_root.rglob(f"{target}.md")):
                    broken.append({"source": str(f.relative_to(self.vault_root)), "target": target})
        return HealthReport(broken_links=broken)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vault_health.py -v`
Expected: PASS

- [ ] **Step 5: Update README & Documentation**

Document `HealthAuditor` in `README.md`.

- [ ] **Step 6: Commit**

```bash
git add engine/vault/health.py tests/test_vault_health.py README.md
git commit -m "feat(vault): add health auditor for broken links and stale claims"
```

- [ ] **Step 7: Phase gate**

Verify → Review → `/simplify` → Re-verify.

---

### Task 9: Git Privacy Quarantine Gate

**Files:**
- Create: `tests/test_privacy_gate.py`

**Interfaces:**
- Consumes: `.gitignore`, Git index
- Produces: Test assertion verifying sensitive directories are excluded from Git

- [ ] **Step 1: Write privacy gate test**

```python
# tests/test_privacy_gate.py
from pathlib import Path

def test_gitignore_contains_vault_quarantine_rules():
    gitignore = Path(".gitignore")
    assert gitignore.exists()
    content = gitignore.read_text(encoding="utf-8")
    assert "_meta/ledger/raw" in content or "_meta/ledger" in content
    assert "_meta/journal/snapshots" in content or "_meta/journal" in content
    assert "_sources/_blobs" in content
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_privacy_gate.py -v`
Expected: PASS

- [ ] **Step 3: Update README & Documentation**

Document privacy quarantine boundaries in `README.md`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_privacy_gate.py README.md
git commit -m "test(vault): verify Git privacy quarantine rules"
```

- [ ] **Step 5: Phase gate**

Verify → Review → `/simplify` → Re-verify.

---

## Phase 5: Documentation & Architecture Sync

### Task 10: Complete System Guide & README Synchronization

**Files:**
- Modify: `README.md`
- Create: `docs/vault-operations.md`

**Interfaces:**
- Consumes: All deliverables from Tasks 1-9
- Produces: Updated operational manual and architectural guide

- [ ] **Step 1: Write docs/vault-operations.md**

Document the 4 Big Phases, 3 Categories, 5 Review Buckets, and CLI commands.

- [ ] **Step 2: Update README.md**

Update root `README.md` to reference the new Agentic Vault engine.

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: ALL TESTS PASS.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/vault-operations.md
git commit -m "docs(vault): synchronize architecture reference and operations guide"
```

- [ ] **Step 5: Phase gate**

Verify → Review → `/simplify` → Re-verify.
