from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

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

@dataclass
class FrontmatterContract:
    id: str
    category: CategoryTrack
    phase: LifecyclePhase
    title: str
    created: str
    updated: str
    schema_version: str = "vault-record-v1"
    tags: List[str] = field(default_factory=list)

    def __init__(
        self,
        id: str,
        category: CategoryTrack | str,
        phase: LifecyclePhase | str,
        title: str,
        created: str,
        updated: str,
        tags: Optional[List[str]] = None,
        **kwargs,
    ):
        self.id = id
        self.category = CategoryTrack(category) if isinstance(category, str) else category
        self.phase = LifecyclePhase(phase) if isinstance(phase, str) else phase
        self.title = title
        self.created = created
        self.updated = updated
        self.tags = list(tags) if tags is not None else []
        self.schema_version = kwargs.get("schema", kwargs.get("schema_version", "vault-record-v1"))
