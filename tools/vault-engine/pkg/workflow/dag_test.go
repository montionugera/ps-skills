package workflow

import (
	"os"
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

func TestWorkflowDAG_LoadWorkflowAndEdgeCases(t *testing.T) {
	// 1. Missing file
	if _, err := LoadWorkflow("nonexistent-file.json"); err == nil {
		t.Errorf("expected error for nonexistent file")
	}

	// 2. Invalid JSON
	tmpFile, err := os.CreateTemp("", "bad-wf-*.json")
	if err != nil {
		t.Fatalf("temp file error: %v", err)
	}
	defer os.Remove(tmpFile.Name())
	_ = os.WriteFile(tmpFile.Name(), []byte("{bad-json"), 0644)

	if _, err := LoadWorkflow(tmpFile.Name()); err == nil {
		t.Errorf("expected error for malformed json")
	}

	// 3. Valid JSON load
	validJSON := `{
		"workflow_id": "loaded-pipeline",
		"version": "1.0",
		"initial_state": "start",
		"states": {
			"start": { "type": "terminal" }
		}
	}`
	validFile, _ := os.CreateTemp("", "good-wf-*.json")
	defer os.Remove(validFile.Name())
	_ = os.WriteFile(validFile.Name(), []byte(validJSON), 0644)

	loaded, err := LoadWorkflow(validFile.Name())
	if err != nil {
		t.Fatalf("failed to load valid workflow: %v", err)
	}
	if loaded.WorkflowID != "loaded-pipeline" {
		t.Errorf("expected loaded-pipeline, got %s", loaded.WorkflowID)
	}

	// 4. DAG validation edge cases
	if err := (&WorkflowDAG{}).Validate(); err == nil {
		t.Errorf("expected error for empty workflow_id")
	}
	if err := (&WorkflowDAG{WorkflowID: "w"}).Validate(); err == nil {
		t.Errorf("expected error for empty version")
	}
	if err := (&WorkflowDAG{WorkflowID: "w", Version: "1"}).Validate(); err == nil {
		t.Errorf("expected error for empty initial_state")
	}
	if err := (&WorkflowDAG{WorkflowID: "w", Version: "1", InitialState: "s"}).Validate(); err == nil {
		t.Errorf("expected error for missing initial state in states")
	}
	badNext := &WorkflowDAG{
		WorkflowID:   "w",
		Version:      "1",
		InitialState: "s",
		States: map[string]WorkflowStep{
			"s": {Type: StepTypeHandler, Next: "missing_step"},
		},
	}
	if err := badNext.Validate(); err == nil {
		t.Errorf("expected error for missing next state")
	}
}
