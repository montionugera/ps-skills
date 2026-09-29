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
