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
    model_config = {"populate_by_name": True}

    schema_version: str = Field(default="vault-record-v1", alias="schema")
    id: str
    category: CategoryTrack
    phase: LifecyclePhase
    title: str
    created: str
    updated: str
    tags: list[str] = Field(default_factory=list)
