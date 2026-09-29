package vault

import (
	"os"
	"path/filepath"
	"testing"
)

func TestCaptureLedger_DeduplicationAndConflict(t *testing.T) {
	tmpDir, err := os.MkdirTemp("", "vault-ledger-test-*")
	if err != nil {
		t.Fatalf("failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	ledger := NewCaptureLedger(tmpDir)

	// 1. Initial capture
	entry1, err := ledger.RecordCapture(
		"clip-101",
		CategoryProduct,
		"web_clipper",
		"User feedback: Add dark mode export",
	)
	if err != nil {
		t.Fatalf("initial capture failed: %v", err)
	}
	if entry1.RunID == "" {
		t.Errorf("expected non-empty RunID")
	}

	// 2. Identical replay returns same entry without duplication
	entry2, err := ledger.RecordCapture(
		"clip-101",
		CategoryProduct,
		"web_clipper",
		"User feedback: Add dark mode export",
	)
	if err != nil {
		t.Fatalf("replay capture failed: %v", err)
	}
	if entry2.RunID != entry1.RunID {
		t.Errorf("expected duplicate replay to return run_id %s, got %s", entry1.RunID, entry2.RunID)
	}

	// 3. Changed payload with same key returns ErrConflictPayload
	_, err = ledger.RecordCapture(
		"clip-101",
		CategoryProduct,
		"web_clipper",
		"Modified payload content",
	)
	if err == nil {
		t.Errorf("expected ErrConflictPayload when key is reused with changed payload, got nil")
	}

	// 4. Verify raw payload persisted on disk
	rawPath := filepath.Join(tmpDir, "raw", entry1.RunID+".raw")
	data, err := os.ReadFile(rawPath)
	if err != nil {
		t.Fatalf("failed to read raw payload file: %v", err)
	}
	if string(data) != "User feedback: Add dark mode export" {
		t.Errorf("unexpected raw payload content: %s", string(data))
	}
}
