package vault

import (
	"os"
	"path/filepath"
	"testing"
)

func TestJournal_CrashRecoveryAndRollback(t *testing.T) {
	tmpDir, err := os.MkdirTemp("", "vault-journal-test-*")
	if err != nil {
		t.Fatalf("failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	// Create test note
	notePath := filepath.Join(tmpDir, "note.md")
	if err := os.WriteFile(notePath, []byte("Original Content"), 0644); err != nil {
		t.Fatalf("failed to create note: %v", err)
	}

	journal := NewJournal(filepath.Join(tmpDir, "_meta", "snapshots"))

	// 1. Begin transaction & snapshot
	tx, err := journal.BeginTx("tx-001")
	if err != nil {
		t.Fatalf("BeginTx failed: %v", err)
	}

	if err := tx.Snapshot(notePath); err != nil {
		t.Fatalf("Snapshot failed: %v", err)
	}

	// 2. Modify note (simulating in-flight crash before commit)
	if err := os.WriteFile(notePath, []byte("Corrupted / Half-written Content"), 0644); err != nil {
		t.Fatalf("failed to corrupt note: %v", err)
	}

	// 3. Rollback
	if err := tx.Rollback(); err != nil {
		t.Fatalf("Rollback failed: %v", err)
	}

	// 4. Verify note restored
	restored, err := os.ReadFile(notePath)
	if err != nil {
		t.Fatalf("failed to read restored note: %v", err)
	}
	if string(restored) != "Original Content" {
		t.Errorf("expected 'Original Content', got '%s'", string(restored))
	}

	// 5. Test Commit
	tx2, err := journal.BeginTx("tx-002")
	if err != nil {
		t.Fatalf("BeginTx tx-002 failed: %v", err)
	}
	// Non-existent file should be a no-op snapshot
	if err := tx2.Snapshot(filepath.Join(tmpDir, "nonexistent.md")); err != nil {
		t.Errorf("expected snapshot of nonexistent file to succeed without error")
	}
	if err := tx2.Snapshot(notePath); err != nil {
		t.Fatalf("snapshot of notePath failed: %v", err)
	}
	if err := tx2.Commit(); err != nil {
		t.Fatalf("commit failed: %v", err)
	}
	if _, err := os.Stat(tx2.TxDir); !os.IsNotExist(err) {
		t.Errorf("expected tx dir to be cleaned up after commit")
	}
}
