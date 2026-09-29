package vault

type CategoryTrack string

const (
	CategoryProduct CategoryTrack = "product_feature"
	CategoryProcess CategoryTrack = "process_workflow"
	CategoryThesis  CategoryTrack = "knowledge_thesis"
)

type LifecyclePhase string

const (
	PhaseGenerate  LifecyclePhase = "idea_generate"
	PhaseRefine    LifecyclePhase = "refine_go_nogo"
	PhaseImplement LifecyclePhase = "implement"
	PhaseLearn     LifecyclePhase = "learn_unlearn"
)

type RecordKind string

const (
	KindIdea     RecordKind = "idea"
	KindProject  RecordKind = "project"
	KindTask     RecordKind = "task"
	KindDecision RecordKind = "decision"
	KindResearch RecordKind = "research"
	KindSource   RecordKind = "source"
	KindDaily    RecordKind = "daily"
)

type FrontmatterContract struct {
	Schema   string         `yaml:"schema" json:"schema"`
	ID       string         `yaml:"id" json:"id"`
	Category CategoryTrack  `yaml:"category" json:"category"`
	Phase    LifecyclePhase `yaml:"phase" json:"phase"`
	Title    string         `yaml:"title" json:"title"`
	Created  string         `yaml:"created" json:"created"`
	Updated  string         `yaml:"updated" json:"updated"`
	Tags     []string       `yaml:"tags,omitempty" json:"tags,omitempty"`
}
