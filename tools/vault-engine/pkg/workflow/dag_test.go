package workflow

import (
	"testing"
)

func TestWorkflowDAG_ValidationAcyclic(t *testing.T) {
	wf := &WorkflowDAG{
		WorkflowID:   "test-pipeline",
		Version:      "1.0.0",
		InitialState: "step_a",
		States: map[string]WorkflowStep{
			"step_a": {
				Type: StepTypeHandler,
				Next: "step_b",
			},
			"step_b": {
				Type: StepTypeParallel,
				Next: "step_c",
			},
			"step_c": {
				Type: StepTypeTerminal,
				Next: "completed",
			},
		},
	}

	if err := wf.Validate(); err != nil {
		t.Fatalf("expected valid acyclic DAG, got error: %v", err)
	}
}

func TestWorkflowDAG_ValidationCycleDetection(t *testing.T) {
	wf := &WorkflowDAG{
		WorkflowID:   "cyclic-pipeline",
		Version:      "1.0.0",
		InitialState: "step_a",
		States: map[string]WorkflowStep{
			"step_a": {
				Type: StepTypeHandler,
				Next: "step_b",
			},
			"step_b": {
				Type: StepTypeHandler,
				Next: "step_c",
			},
			"step_c": {
				Type: StepTypeHandler,
				Next: "step_a", // Creates cycle!
			},
		},
	}

	err := wf.Validate()
	if err == nil {
		t.Fatal("expected cycle detection error, got nil")
	}
	if err.Error() == "" {
		t.Fatal("expected non-empty error message")
	}
}
