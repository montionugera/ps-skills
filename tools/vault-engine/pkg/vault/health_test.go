package vault

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestHealthAuditor_BrokenLinksAndStaleClaims(t *testing.T) {
	tmpDir, err := os.MkdirTemp("", "vault-health-test-*")
	if err != nil {
		t.Fatalf("failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	knowledgeDir := filepath.Join(tmpDir, "04_Knowledge")
	_ = os.MkdirAll(knowledgeDir, 0755)

	// 1. Create a note with a broken wikilink
	note1Path := filepath.Join(tmpDir, "01_Ideas", "test-idea.md")
	_ = os.MkdirAll(filepath.Dir(note1Path), 0755)
	_ = os.WriteFile(note1Path, []byte("Here is a link to [[NonExistentNote]] and [[ExistingNote]]."), 0644)

	// 2. Create the existing note target
	note2Path := filepath.Join(tmpDir, "01_Ideas", "ExistingNote.md")
	_ = os.WriteFile(note2Path, []byte("# Existing Note Content"), 0644)

	// 3. Create a stale knowledge claim (>90 days old)
	staleNotePath := filepath.Join(knowledgeDir, "ancient-rule.md")
	_ = os.WriteFile(staleNotePath, []byte("---\ntitle: Ancient Rule\nupdated: 2025-01-01\n---\nOld rule text."), 0644)
	oldTime := time.Now().Add(-100 * 24 * time.Hour)
	_ = os.Chtimes(staleNotePath, oldTime, oldTime)

	report, err := AuditVault(tmpDir)
	if err != nil {
		t.Fatalf("AuditVault failed: %v", err)
	}

	if len(report.BrokenLinks) != 1 {
		t.Errorf("expected 1 broken link, got %d: %v", len(report.BrokenLinks), report.BrokenLinks)
	}
	if len(report.StaleClaims) != 1 {
		t.Errorf("expected 1 stale claim, got %d: %v", len(report.StaleClaims), report.StaleClaims)
	}
}
