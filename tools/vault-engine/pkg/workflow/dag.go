package workflow

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
)

type StepType string

const (
	StepTypeHandler  StepType = "handler"
	StepTypeParallel StepType = "parallel_join"
	StepTypeSwitch   StepType = "switch"
	StepTypeTerminal StepType = "terminal"
)

type ParallelBranch struct {
	Agent string `json:"agent"`
	Task  string `json:"task"`
}

type WorkflowStep struct {
	Type     StepType          `json:"type"`
	Handler  string            `json:"handler,omitempty"`
	Agent    string            `json:"agent,omitempty"`
	Task     string            `json:"task,omitempty"`
	Branches []ParallelBranch  `json:"branches,omitempty"`
	Next     string            `json:"next,omitempty"`
	Cases    map[string]string `json:"cases,omitempty"`
	Eval     string            `json:"eval,omitempty"`
}

type WorkflowDAG struct {
	WorkflowID   string                  `json:"workflow_id"`
	Version      string                  `json:"version"`
	InitialState string                  `json:"initial_state"`
	States       map[string]WorkflowStep `json:"states"`
}

func LoadWorkflow(path string) (*WorkflowDAG, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var wf WorkflowDAG
	if err := json.Unmarshal(data, &wf); err != nil {
		return nil, fmt.Errorf("parsing workflow json: %w", err)
	}
	return &wf, nil
}

func (wf *WorkflowDAG) Validate() error {
	if wf.WorkflowID == "" {
		return errors.New("workflow_id is required")
	}
	if wf.Version == "" {
		return errors.New("version is required")
	}
	if wf.InitialState == "" {
		return errors.New("initial_state is required")
	}
	if _, exists := wf.States[wf.InitialState]; !exists {
		return fmt.Errorf("initial_state '%s' does not exist in states", wf.InitialState)
	}

	// 1. Build adjacency list and in-degree map for Kahn's algorithm (Cycle Detection)
	inDegree := make(map[string]int)
	adj := make(map[string][]string)

	for stateName := range wf.States {
		inDegree[stateName] = 0
		adj[stateName] = []string{}
	}

	for fromName, step := range wf.States {
		var targets []string
		if step.Next != "" {
			targets = append(targets, step.Next)
		}
		for _, target := range step.Cases {
			targets = append(targets, target)
		}

		for _, toName := range targets {
			if toName == "completed" || toName == "terminal" {
				continue
			}
			if _, exists := wf.States[toName]; !exists {
				return fmt.Errorf("state '%s' transitions to undefined state '%s'", fromName, toName)
			}
			adj[fromName] = append(adj[fromName], toName)
			inDegree[toName]++
		}
	}

	// Kahn's algorithm
	var queue []string
	for stateName, deg := range inDegree {
		if deg == 0 {
			queue = append(queue, stateName)
		}
	}

	visitedCount := 0
	for len(queue) > 0 {
		curr := queue[0]
		queue = queue[1:]
		visitedCount++

		for _, neighbor := range adj[curr] {
			inDegree[neighbor]--
			if inDegree[neighbor] == 0 {
				queue = append(queue, neighbor)
			}
		}
	}

	if visitedCount != len(wf.States) {
		return fmt.Errorf("cycle detected in workflow DAG: states visited (%d) != total states (%d)", visitedCount, len(wf.States))
	}

	return nil
}
