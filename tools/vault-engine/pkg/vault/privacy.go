package vault

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

var requiredQuarantinePatterns = []string{
	"_inbox/private/",
	"_meta/locks/",
	"_meta/snapshots/",
	"_meta/ledger/raw/",
	"*.raw",
}

func CheckGitPrivacy(vaultRoot string) error {
	gitignorePath := filepath.Join(vaultRoot, ".gitignore")
	data, err := os.ReadFile(gitignorePath)
	if err != nil {
		return fmt.Errorf(".gitignore not found: %w", err)
	}

	content := string(data)
	var missing []string

	for _, pattern := range requiredQuarantinePatterns {
		if !strings.Contains(content, pattern) {
			missing = append(missing, pattern)
		}
	}

	if len(missing) > 0 {
		return fmt.Errorf("git privacy quarantine violation: missing patterns in .gitignore: %s", strings.Join(missing, ", "))
	}

	return nil
}
