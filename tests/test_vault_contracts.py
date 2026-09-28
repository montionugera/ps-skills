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
