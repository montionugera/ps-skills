package vault

import (
	"os"
	"path/filepath"
	"testing"
)

func TestGitPrivacy_QuarantineRules(t *testing.T) {
	tmpDir, err := os.MkdirTemp("", "vault-privacy-test-*")
	if err != nil {
		t.Fatalf("failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	// 1. Missing .gitignore fails
	if err := CheckGitPrivacy(tmpDir); err == nil {
		t.Errorf("expected error when .gitignore is missing, got nil")
	}

	// 2. Incomplete .gitignore fails
	gitignorePath := filepath.Join(tmpDir, ".gitignore")
	_ = os.WriteFile(gitignorePath, []byte("_meta/locks/\n"), 0644)
	if err := CheckGitPrivacy(tmpDir); err == nil {
		t.Errorf("expected error when required quarantine rules are missing, got nil")
	}

	// 3. Complete .gitignore passes
	completeRules := `
_inbox/private/
_meta/locks/
_meta/snapshots/
_meta/ledger/raw/
*.raw
`
	_ = os.WriteFile(gitignorePath, []byte(completeRules), 0644)
	if err := CheckGitPrivacy(tmpDir); err != nil {
		t.Errorf("expected complete .gitignore to pass, got: %v", err)
	}
}
