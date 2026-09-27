package workflow

import (
	"errors"
	"testing"
)

func TestWorkflowRunner_SequentialProgression(t *testing.T) {
	storageDir := t.TempDir()
	wf := &WorkflowDAG{
		WorkflowID:   "seq-pipeline",
		Version:      "1.0.0",
		InitialState: "step_1",
		States: map[string]WorkflowStep{
			"step_1": {
				Type:    StepTypeHandler,
				Handler: "task_one",
				Next:    "step_2",
			},
			"step_2": {
				Type:    StepTypeHandler,
				Handler: "task_two",
				Next:    "completed",
			},
		},
	}

	runner := NewWorkflowRunner(wf, storageDir)
	runner.RegisterHandler("task_one", func(inst *WorkflowInstance, step WorkflowStep) (map[string]interface{}, error) {
		return map[string]interface{}{"value_1": "done"}, nil
	})
	runner.RegisterHandler("task_two", func(inst *WorkflowInstance, step WorkflowStep) (map[string]interface{}, error) {
		return map[string]interface{}{"value_2": "done"}, nil
	})

	inst := NewWorkflowInstance(wf, "inst-seq-001", map[string]interface{}{"input": "start"}, storageDir)
	if err := runner.RunUntilTerminal(inst, 10); err != nil {
		t.Fatalf("unexpected runner error: %v", err)
	}

	if inst.Status != StatusCompleted {
		t.Fatalf("expected status completed, got %s", inst.Status)
	}
	if inst.Artifacts["value_1"] != "done" || inst.Artifacts["value_2"] != "done" {
		t.Errorf("missing expected artifacts: %v", inst.Artifacts)
	}
	if len(inst.Attempts) != 2 {
		t.Errorf("expected 2 attempts, got %d", len(inst.Attempts))
	}

	// Verify persistence & reload
	loaded, err := LoadWorkflowInstance(storageDir, "inst-seq-001")
	if err != nil {
		t.Fatalf("failed to load saved instance: %v", err)
	}
	if loaded.Status != StatusCompleted {
		t.Errorf("expected reloaded status completed, got %s", loaded.Status)
	}
}

func TestWorkflowRunner_ParallelJoin(t *testing.T) {
	storageDir := t.TempDir()
	wf := &WorkflowDAG{
		WorkflowID:   "par-pipeline",
		Version:      "1.0.0",
		InitialState: "parallel_step",
		States: map[string]WorkflowStep{
			"parallel_step": {
				Type: StepTypeParallel,
				Branches: []ParallelBranch{
					{Agent: "agent-bestie", Task: "market_research"},
					{Agent: "agent-philip", Task: "tech_audit"},
				},
				Next: "completed",
			},
		},
	}

	runner := NewWorkflowRunner(wf, storageDir)
	runner.RegisterHandler("market_research", func(inst *WorkflowInstance, step WorkflowStep) (map[string]interface{}, error) {
		return map[string]interface{}{"roi": "high"}, nil
	})
	runner.RegisterHandler("tech_audit", func(inst *WorkflowInstance, step WorkflowStep) (map[string]interface{}, error) {
		return map[string]interface{}{"feasible": true}, nil
	})

	inst := NewWorkflowInstance(wf, "inst-par-001", nil, storageDir)
	if err := runner.RunUntilTerminal(inst, 5); err != nil {
		t.Fatalf("unexpected runner error: %v", err)
	}

	if inst.Status != StatusCompleted {
		t.Fatalf("expected status completed, got %s", inst.Status)
	}
	if inst.Artifacts["agent-bestie:roi"] != "high" {
		t.Errorf("missing bestie output: %v", inst.Artifacts)
	}
	if inst.Artifacts["agent-philip:feasible"] != true {
		t.Errorf("missing philip output: %v", inst.Artifacts)
	}
}

func TestWorkflowRunner_MissingHandlerQuarantine(t *testing.T) {
	storageDir := t.TempDir()
	wf := &WorkflowDAG{
		WorkflowID:   "bad-pipeline",
		Version:      "1.0.0",
		InitialState: "missing_step",
		States: map[string]WorkflowStep{
			"missing_step": {
				Type:    StepTypeHandler,
				Handler: "unregistered_task",
				Next:    "completed",
			},
		},
	}

	runner := NewWorkflowRunner(wf, storageDir)
	inst := NewWorkflowInstance(wf, "inst-bad-001", nil, storageDir)

	err := runner.Step(inst)
	if err == nil {
		t.Fatal("expected error for unregistered handler")
	}
	if inst.Status != StatusQuarantined {
		t.Errorf("expected quarantined status, got %s", inst.Status)
	}
}

func TestWorkflowRunner_FailureHandling(t *testing.T) {
	storageDir := t.TempDir()
	wf := &WorkflowDAG{
		WorkflowID:   "failing-pipeline",
		Version:      "1.0.0",
		InitialState: "failing_step",
		States: map[string]WorkflowStep{
			"failing_step": {
				Type:    StepTypeHandler,
				Handler: "will_fail",
				Next:    "completed",
			},
		},
	}

	runner := NewWorkflowRunner(wf, storageDir)
	runner.RegisterHandler("will_fail", func(inst *WorkflowInstance, step WorkflowStep) (map[string]interface{}, error) {
		return nil, errors.New("simulated network failure")
	})

	inst := NewWorkflowInstance(wf, "inst-fail-001", nil, storageDir)
	err := runner.Step(inst)
	if err == nil {
		t.Fatal("expected step failure")
	}
	if inst.Status != StatusFailed {
		t.Errorf("expected failed status, got %s", inst.Status)
	}
}
