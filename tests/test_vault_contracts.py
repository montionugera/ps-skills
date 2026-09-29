import unittest
from engine.vault.contracts import CategoryTrack, LifecyclePhase, RecordKind, FrontmatterContract

class TestVaultContracts(unittest.TestCase):
    def test_category_tracks_and_phases(self):
        self.assertEqual(CategoryTrack.PRODUCT.value, "product_feature")
        self.assertEqual(CategoryTrack.PROCESS.value, "process_workflow")
        self.assertEqual(CategoryTrack.THESIS.value, "knowledge_thesis")

        self.assertEqual(LifecyclePhase.GENERATE.value, "idea_generate")
        self.assertEqual(LifecyclePhase.REFINE.value, "refine_go_nogo")
        self.assertEqual(LifecyclePhase.IMPLEMENT.value, "implement")
        self.assertEqual(LifecyclePhase.LEARN.value, "learn_unlearn")

    def test_frontmatter_schema_validation(self):
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
        self.assertEqual(contract.id, "REC-2026-001")
        self.assertEqual(contract.category, CategoryTrack.PRODUCT)

if __name__ == "__main__":
    unittest.main()
