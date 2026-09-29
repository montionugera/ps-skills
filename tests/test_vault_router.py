import unittest
from engine.vault.contracts import CategoryTrack, RecordKind
from engine.vault.router import PathResolver

class TestVaultRouter(unittest.TestCase):
    def test_category_aware_routing(self):
        resolver = PathResolver()

        # Product Idea
        self.assertEqual(resolver.resolve(CategoryTrack.PRODUCT, RecordKind.IDEA, slug="dark-mode"), "01_Ideas/dark-mode.md")

        # Process Decision / ADR
        self.assertEqual(resolver.resolve(CategoryTrack.PROCESS, RecordKind.DECISION, slug="release-gate", owner="ReleasePipeline"), "02_Projects/ReleasePipeline/decisions/release-gate.md")

        # Thesis / Knowledge Reference
        self.assertEqual(resolver.resolve(CategoryTrack.THESIS, RecordKind.RESEARCH, slug="sqlite-wal-scale"), "07_Research/sqlite-wal-scale.md")

if __name__ == "__main__":
    unittest.main()
