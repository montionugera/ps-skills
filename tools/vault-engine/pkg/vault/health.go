package vault

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

var (
	wikilinkRegex = regexp.MustCompile(`\[\[([^\]|]+)(?:\|[^\]]+)?\]\]`)
)

type AuditReport struct {
	BrokenLinks []string `json:"broken_links"`
	StaleClaims []string `json:"stale_claims"`
}

func AuditVault(vaultRoot string) (*AuditReport, error) {
	report := &AuditReport{
		BrokenLinks: make([]string, 0),
		StaleClaims: make([]string, 0),
	}

	knownNotes := make(map[string]bool)

	// Step 1: Index all existing note names (without .md)
	_ = filepath.WalkDir(vaultRoot, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return nil
		}
		if strings.HasSuffix(d.Name(), ".md") {
			baseName := strings.TrimSuffix(d.Name(), ".md")
			knownNotes[baseName] = true
			knownNotes[d.Name()] = true

			relPath, _ := filepath.Rel(vaultRoot, path)
			relPath = filepath.ToSlash(relPath)
			relNoExt := strings.TrimSuffix(relPath, ".md")
			knownNotes[relPath] = true
			knownNotes[relNoExt] = true
		}
		return nil
	})

	now := time.Now()
	staleThreshold := 90 * 24 * time.Hour

	// Step 2: Check for broken links and stale claims
	err := filepath.WalkDir(vaultRoot, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return nil
		}
		if !strings.HasSuffix(d.Name(), ".md") {
			return nil
		}

		relPath, _ := filepath.Rel(vaultRoot, path)
		if strings.HasPrefix(relPath, "_meta/") {
			return nil
		}

		// Check stale claims in 04_Knowledge
		if strings.HasPrefix(relPath, "04_Knowledge/") {
			info, statErr := d.Info()
			if statErr == nil {
				if now.Sub(info.ModTime()) > staleThreshold {
					report.StaleClaims = append(report.StaleClaims, relPath)
				}
			}
		}

		// Scan content for [[wikilinks]]
		content, readErr := os.ReadFile(path)
		if readErr == nil {
			matches := wikilinkRegex.FindAllStringSubmatch(string(content), -1)
			for _, m := range matches {
				if len(m) > 1 {
					target := strings.TrimSpace(m[1])
					if !knownNotes[target] && !knownNotes[target+".md"] {
						brokenRef := fmt.Sprintf("%s -> [[%s]]", relPath, target)
						report.BrokenLinks = append(report.BrokenLinks, brokenRef)
					}
				}
			}
		}

		return nil
	})

	if err != nil {
		return nil, fmt.Errorf("failed to audit vault: %w", err)
	}

	return report, nil
}
