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
