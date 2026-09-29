package workflow

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type InstanceStatus string

const (
	StatusRunning     InstanceStatus = "running"
	StatusCompleted   InstanceStatus = "completed"
	StatusFailed      InstanceStatus = "failed"
	StatusQuarantined InstanceStatus = "quarantined"
)

type NodeAttempt struct {
	StateName  string                 `json:"state_name"`
	AttemptNum int                    `json:"attempt_num"`
	Status     string                 `json:"status"` // "success", "failed"
	StartedAt  string                 `json:"started_at"`
	EndedAt    string                 `json:"ended_at"`
	Output     map[string]interface{} `json:"output,omitempty"`
	Error      string                 `json:"error,omitempty"`
}

type WorkflowInstance struct {
	InstanceID   string                 `json:"instance_id"`
	WorkflowID   string                 `json:"workflow_id"`
	Version      string                 `json:"version"`
	CurrentState string                 `json:"current_state"`
	Status       InstanceStatus         `json:"status"`
	Payload      map[string]interface{} `json:"payload"`
	Artifacts    map[string]interface{} `json:"artifacts"`
	Attempts     []NodeAttempt          `json:"attempts"`
	CreatedAt    string                 `json:"created_at"`
	UpdatedAt    string                 `json:"updated_at"`
	StorageDir   string                 `json:"-"`
	mu           sync.Mutex             `json:"-"`
}

func NewWorkflowInstance(wf *WorkflowDAG, instanceID string, initialPayload map[string]interface{}, storageDir string) *WorkflowInstance {
	now := time.Now().UTC().Format(time.RFC3339)
	return &WorkflowInstance{
		InstanceID:   instanceID,
		WorkflowID:   wf.WorkflowID,
		Version:      wf.Version,
		CurrentState: wf.InitialState,
		Status:       StatusRunning,
		Payload:      initialPayload,
		Artifacts:    make(map[string]interface{}),
		Attempts:     []NodeAttempt{},
		CreatedAt:    now,
		UpdatedAt:    now,
		StorageDir:   storageDir,
	}
}

func (inst *WorkflowInstance) Save() error {
	inst.mu.Lock()
	defer inst.mu.Unlock()

	if inst.StorageDir == "" {
		return nil
	}
	if err := os.MkdirAll(inst.StorageDir, 0755); err != nil {
		return err
	}
	inst.UpdatedAt = time.Now().UTC().Format(time.RFC3339)

	data, err := json.MarshalIndent(inst, "", "  ")
	if err != nil {
		return err
	}
	targetPath := filepath.Join(inst.StorageDir, fmt.Sprintf("%s.json", inst.InstanceID))
	tmpPath := fmt.Sprintf("%s.%d.tmp", targetPath, os.Getpid())
	if err := os.WriteFile(tmpPath, data, 0644); err != nil {
		return err
	}
	return os.Rename(tmpPath, targetPath)
}

func LoadWorkflowInstance(storageDir, instanceID string) (*WorkflowInstance, error) {
	targetPath := filepath.Join(storageDir, fmt.Sprintf("%s.json", instanceID))
	data, err := os.ReadFile(targetPath)
	if err != nil {
		return nil, err
	}
	var inst WorkflowInstance
	if err := json.Unmarshal(data, &inst); err != nil {
		return nil, err
	}
	inst.StorageDir = storageDir
	return &inst, nil
}

type StepHandlerFunc func(inst *WorkflowInstance, step WorkflowStep) (map[string]interface{}, error)

type WorkflowRunner struct {
	Workflow   *WorkflowDAG
	Handlers   map[string]StepHandlerFunc
	StorageDir string
}

func NewWorkflowRunner(wf *WorkflowDAG, storageDir string) *WorkflowRunner {
	return &WorkflowRunner{
		Workflow:   wf,
		Handlers:   make(map[string]StepHandlerFunc),
		StorageDir: storageDir,
	}
}

func (r *WorkflowRunner) RegisterHandler(name string, h StepHandlerFunc) {
	r.Handlers[name] = h
}

func (r *WorkflowRunner) Step(inst *WorkflowInstance) error {
	if inst.Status != StatusRunning {
		return fmt.Errorf("cannot step workflow in status '%s'", inst.Status)
	}

	step, exists := r.Workflow.States[inst.CurrentState]
	if !exists {
		inst.Status = StatusQuarantined
		_ = inst.Save()
		return fmt.Errorf("state '%s' does not exist in workflow DAG", inst.CurrentState)
	}

	attempt := NodeAttempt{
		StateName:  inst.CurrentState,
		AttemptNum: len(inst.Attempts) + 1,
		StartedAt:  time.Now().UTC().Format(time.RFC3339),
	}

	switch step.Type {
	case StepTypeTerminal:
		attempt.Status = "success"
		attempt.EndedAt = time.Now().UTC().Format(time.RFC3339)
		inst.Attempts = append(inst.Attempts, attempt)
		inst.Status = StatusCompleted
		return inst.Save()

	case StepTypeHandler:
		handlerName := step.Handler
		if handlerName == "" {
			handlerName = step.Task
		}
		handler, ok := r.Handlers[handlerName]
		if !ok {
			attempt.Status = "failed"
			attempt.Error = fmt.Sprintf("no handler registered for '%s'", handlerName)
			attempt.EndedAt = time.Now().UTC().Format(time.RFC3339)
			inst.Attempts = append(inst.Attempts, attempt)
			inst.Status = StatusQuarantined
			_ = inst.Save()
			return fmt.Errorf("unregistered handler '%s'", handlerName)
		}

		out, err := handler(inst, step)
		attempt.EndedAt = time.Now().UTC().Format(time.RFC3339)
		if err != nil {
			attempt.Status = "failed"
			attempt.Error = err.Error()
			inst.Attempts = append(inst.Attempts, attempt)
			inst.Status = StatusFailed
			_ = inst.Save()
			return err
		}

		attempt.Status = "success"
		attempt.Output = out
		inst.Attempts = append(inst.Attempts, attempt)
		for k, v := range out {
			inst.Artifacts[k] = v
		}

		// Advance state
		if step.Next == "completed" || step.Next == "" {
			inst.Status = StatusCompleted
		} else {
			inst.CurrentState = step.Next
		}
		return inst.Save()

	case StepTypeParallel:
		// Execute parallel branches
		var wg sync.WaitGroup
		var branchMu sync.Mutex
		branchOutputs := make(map[string]interface{})
		var branchErr error

		for _, b := range step.Branches {
			wg.Add(1)
			go func(branch ParallelBranch) {
				defer wg.Done()
				handlerName := branch.Task
				handler, ok := r.Handlers[handlerName]
				if !ok {
					branchMu.Lock()
					branchErr = fmt.Errorf("no handler for parallel task '%s'", handlerName)
					branchMu.Unlock()
					return
				}
				out, err := handler(inst, WorkflowStep{Task: branch.Task, Agent: branch.Agent})
				branchMu.Lock()
				defer branchMu.Unlock()
				if err != nil && branchErr == nil {
					branchErr = err
				} else {
					for k, v := range out {
						branchOutputs[fmt.Sprintf("%s:%s", branch.Agent, k)] = v
					}
				}
			}(b)
		}
		wg.Wait()

		attempt.EndedAt = time.Now().UTC().Format(time.RFC3339)
		if branchErr != nil {
			attempt.Status = "failed"
			attempt.Error = branchErr.Error()
			inst.Attempts = append(inst.Attempts, attempt)
			inst.Status = StatusFailed
			_ = inst.Save()
			return branchErr
		}

		attempt.Status = "success"
		attempt.Output = branchOutputs
		inst.Attempts = append(inst.Attempts, attempt)
		for k, v := range branchOutputs {
			inst.Artifacts[k] = v
		}

		if step.Next == "completed" || step.Next == "" {
			inst.Status = StatusCompleted
		} else {
			inst.CurrentState = step.Next
		}
		return inst.Save()

	default:
		inst.Status = StatusQuarantined
		_ = inst.Save()
		return fmt.Errorf("unsupported step type '%s'", step.Type)
	}
}

func (r *WorkflowRunner) RunUntilTerminal(inst *WorkflowInstance, maxSteps int) error {
	for i := 0; i < maxSteps; i++ {
		if inst.Status != StatusRunning {
			return nil
		}
		if err := r.Step(inst); err != nil {
			return err
		}
	}
	if inst.Status == StatusRunning {
		return fmt.Errorf("exceeded maxSteps (%d) without reaching terminal status", maxSteps)
	}
	return nil
}
