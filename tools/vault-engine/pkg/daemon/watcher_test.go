package daemon

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func setupDaemonTestVault(t *testing.T) (string, string) {
	tmp := t.TempDir()
	dirs := []string{
		"_inbox/human",
		"_meta/indexes",
		"_meta/instances",
		"_meta/guards",
		"_meta/events",
		"_meta/workflows",
		"01_Ideas",
	}
	for _, d := range dirs {
		_ = os.MkdirAll(filepath.Join(tmp, d), 0755)
	}

	wfPath := filepath.Join(tmp, "_meta/workflows/test-wf.json")
	wfContent := `{
  "workflow_id": "test-wf",
  "version": "1.0.0",
  "initial_state": "inbox_ingest",
  "states": {
    "inbox_ingest": {
      "type": "handler",
      "handler": "vault.ingest_file",
      "next": "parallel_research"
    },
    "parallel_research": {
      "type": "parallel_join",
      "branches": [
        {"agent": "agent-bestie", "task": "market_gap_analysis"},
        {"agent": "agent-philip", "task": "architecture_feasibility"}
      ],
      "next": "score_and_promote"
    },
    "score_and_promote": {
      "type": "handler",
      "handler": "score_and_promote",
      "next": "completed"
    }
  }
}`
	_ = os.WriteFile(wfPath, []byte(wfContent), 0644)
	return tmp, wfPath
}

func TestWatcher_ProcessInboxOnce(t *testing.T) {
	vaultRoot, wfPath := setupDaemonTestVault(t)

	// Drop note in inbox
	inboxFile := filepath.Join(vaultRoot, "_inbox/human/daemon-test.md")
	_ = os.WriteFile(inboxFile, []byte("---\ntitle: Daemon Test Idea\n---\nBody text"), 0644)

	watcher := NewWatcher(WatcherConfig{
		VaultRoot:    vaultRoot,
		WorkflowPath: wfPath,
		RunOnce:      true,
	})

	count, err := watcher.ProcessInboxOnce()
	if err != nil {
		t.Fatalf("process inbox failed: %v", err)
	}
	if count != 1 {
		t.Fatalf("expected 1 processed note, got %d", count)
	}

	// Verify note was moved out of inbox
	if _, err := os.Stat(inboxFile); !os.IsNotExist(err) {
		t.Errorf("expected inbox file to be removed after ingest")
	}

	// Verify idea created in 01_Ideas
	ideas, _ := filepath.Glob(filepath.Join(vaultRoot, "01_Ideas", "IDEA-*.md"))
	if len(ideas) != 1 {
		t.Fatalf("expected 1 idea note, got %d", len(ideas))
	}
}

func TestWatcher_SingletonGuard(t *testing.T) {
	vaultRoot, wfPath := setupDaemonTestVault(t)

	watcher1 := NewWatcher(WatcherConfig{
		VaultRoot:    vaultRoot,
		WorkflowPath: wfPath,
		Interval:     100 * time.Millisecond,
	})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go func() {
		_ = watcher1.Run(ctx)
	}()

	time.Sleep(50 * time.Millisecond)

	// Second watcher should fail to acquire guard
	watcher2 := NewWatcher(WatcherConfig{
		VaultRoot:    vaultRoot,
		WorkflowPath: wfPath,
		RunOnce:      true,
	})
	err := watcher2.Run(context.Background())
	if err == nil {
		t.Fatal("expected second daemon instance to fail with lock contention")
	}
}
