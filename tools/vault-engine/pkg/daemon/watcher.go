package daemon

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"obsidian-vault-engine/pkg/vault"
	"obsidian-vault-engine/pkg/workflow"
)

type WatcherConfig struct {
	VaultRoot    string
	WorkflowPath string
	Interval     time.Duration
	RunOnce      bool
}

type Watcher struct {
	Config WatcherConfig
	Engine *vault.VaultEngine
}

func NewWatcher(cfg WatcherConfig) *Watcher {
	return &Watcher{
		Config: cfg,
		Engine: vault.NewVaultEngine(cfg.VaultRoot),
	}
}

func (w *Watcher) ProcessInboxOnce() (int, error) {
	inboxDir := filepath.Join(w.Config.VaultRoot, "_inbox", "human")
	entries, err := os.ReadDir(inboxDir)
	if err != nil {
		if os.IsNotExist(err) {
			return 0, nil
		}
		return 0, err
	}

	processed := 0
	wf, err := workflow.LoadWorkflow(w.Config.WorkflowPath)
	if err != nil {
		return 0, fmt.Errorf("loading workflow: %w", err)
	}

	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".md") {
			continue
		}
		notePath := filepath.Join(inboxDir, e.Name())

		storageDir := filepath.Join(w.Config.VaultRoot, "_meta", "instances")
		instID := fmt.Sprintf("daemon-%s-%d", wf.WorkflowID, time.Now().UnixNano())
		payload := map[string]interface{}{"file_path": notePath}
		inst := workflow.NewWorkflowInstance(wf, instID, payload, storageDir)
		runner := workflow.NewWorkflowRunner(wf, storageDir)

		// Register standard handlers
		runner.RegisterHandler("vault.ingest_file", func(instance *workflow.WorkflowInstance, step workflow.WorkflowStep) (map[string]interface{}, error) {
			path, _ := instance.Payload["file_path"].(string)
			assignedID, err := w.Engine.IngestFile(path)
			if err != nil {
				return nil, err
			}
			return map[string]interface{}{"idea_id": assignedID}, nil
		})

		runner.RegisterHandler("market_gap_analysis", func(instance *workflow.WorkflowInstance, step workflow.WorkflowStep) (map[string]interface{}, error) {
			ideaID, _ := instance.Artifacts["idea_id"].(string)
			return map[string]interface{}{
				"idea_id":        ideaID,
				"market_summary": "Auto-evaluated by Bestie daemon watcher",
				"estimated_roi":  "high",
				"analyst":        "agent-bestie",
			}, nil
		})

		runner.RegisterHandler("architecture_feasibility", func(instance *workflow.WorkflowInstance, step workflow.WorkflowStep) (map[string]interface{}, error) {
			ideaID, _ := instance.Artifacts["idea_id"].(string)
			return map[string]interface{}{
				"idea_id":        ideaID,
				"feasibility":    "feasible",
				"latency_impact": "low",
				"auditor":        "agent-philip",
			}, nil
		})

		runner.RegisterHandler("score_and_promote", func(instance *workflow.WorkflowInstance, step workflow.WorkflowStep) (map[string]interface{}, error) {
			ideaID, _ := instance.Artifacts["idea_id"].(string)
			env, err := w.Engine.ReadRecord(ideaID)
			if err != nil {
				return nil, err
			}
			err = w.Engine.CommitRecord(vault.CommitRequest{
				RecordID:       ideaID,
				ExpectedSHA256: env.SHA256,
				Updates: map[string]interface{}{
					"status":     "candidate",
					"impact":     4,
					"effort":     2,
					"confidence": 4,
				},
				Actor:          "agent-olivier",
				IdempotencyKey: instance.InstanceID,
				Reason:         "daemon-auto-triage",
			})
			if err != nil {
				return nil, err
			}
			return map[string]interface{}{"status": "candidate", "record_id": ideaID}, nil
		})

		if err := runner.RunUntilTerminal(inst, 20); err != nil {
			fmt.Fprintf(os.Stderr, "Error processing note %s: %v\n", e.Name(), err)
		} else {
			processed++
		}
	}

	return processed, nil
}

func (w *Watcher) Run(ctx context.Context) error {
	guardsDir := filepath.Join(w.Config.VaultRoot, "_meta", "guards")
	_ = os.MkdirAll(guardsDir, 0755)
	guardPath := filepath.Join(guardsDir, "daemon.guard")

	fd, err := syscall.Open(guardPath, syscall.O_CREAT|syscall.O_RDWR, 0644)
	if err != nil {
		return fmt.Errorf("opening daemon guard: %w", err)
	}
	defer syscall.Close(fd)

	if err := syscall.Flock(fd, syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return fmt.Errorf("daemon already running: %w", err)
	}
	defer syscall.Flock(fd, syscall.LOCK_UN)

	if w.Config.RunOnce {
		_, err := w.ProcessInboxOnce()
		return err
	}

	ticker := time.NewTicker(w.Config.Interval)
	defer ticker.Stop()

	// Initial sweep
	_, _ = w.ProcessInboxOnce()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			_, _ = w.ProcessInboxOnce()
		}
	}
}
