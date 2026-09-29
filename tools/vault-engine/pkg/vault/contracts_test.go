package vault

import (
	"testing"
)

func TestCategoryTracksAndPhases(t *testing.T) {
	if CategoryProduct != "product_feature" {
		t.Errorf("expected product_feature, got %s", CategoryProduct)
	}
	if CategoryProcess != "process_workflow" {
		t.Errorf("expected process_workflow, got %s", CategoryProcess)
	}
	if CategoryThesis != "knowledge_thesis" {
		t.Errorf("expected knowledge_thesis, got %s", CategoryThesis)
	}

	if PhaseGenerate != "idea_generate" {
		t.Errorf("expected idea_generate, got %s", PhaseGenerate)
	}
	if PhaseRefine != "refine_go_nogo" {
		t.Errorf("expected refine_go_nogo, got %s", PhaseRefine)
	}
	if PhaseImplement != "implement" {
		t.Errorf("expected implement, got %s", PhaseImplement)
	}
	if PhaseLearn != "learn_unlearn" {
		t.Errorf("expected learn_unlearn, got %s", PhaseLearn)
	}
}
