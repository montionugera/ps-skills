// Package vaultsync keeps a vault folder identical in several places through
// one shared git repository. It wraps the existing engine operations; it does
// not change them.
package vaultsync

import (
	"encoding/json"
	"fmt"
	"os"
	"path"
	"slices"
	"strings"
)

// Limits are the safeguards against bloat. The hub reads them from the
// settings file beside its hook; a place uses DefaultLimits for the early check.
type Limits struct {
	Ref                string            `json:"ref"`
	MaxInputBytes      int64             `json:"max_input_bytes"`
	MaxFileBytes       int64             `json:"max_file_bytes"`
	MaxImageBytes      int64             `json:"max_image_bytes"`
	MaxFilesPerPush    int               `json:"max_files_per_push"`
	DailyBytesPerPlace int64             `json:"daily_bytes_per_place"`
	AllowedExt         []string          `json:"allowed_ext"`
	ImageExt           []string          `json:"image_ext"`
	AllowedNames       []string          `json:"allowed_names"`
	ExtUnderPrefix     map[string]string `json:"ext_under_prefix"`
	DeniedPrefixes     []string          `json:"denied_prefixes"`
}

func DefaultLimits() Limits {
	return Limits{
		Ref:                "refs/heads/main",
		MaxInputBytes:      20971520,
		MaxFileBytes:       1048576,
		MaxImageBytes:      307200,
		MaxFilesPerPush:    500,
		DailyBytesPerPlace: 52428800,
		AllowedExt:         []string{".md", ".json", ".jsonl", ".yaml", ".yml", ".txt", ".csv"},
		ImageExt:           []string{".png", ".jpg", ".svg"},
		AllowedNames:       []string{".gitignore", ".gitkeep"},
		ExtUnderPrefix:     map[string]string{".sh": "_meta/scripts/", ".raw": "_meta/ledger/raw/"},
		DeniedPrefixes: []string{".obsidian/", "_tmp/", "_quarantine/", "_meta/bin/", "_meta/locks/",
			"_meta/guards/", "_meta/logs/", "_meta/indexes/", "graft/"},
	}
}

func LoadLimits(file string) (Limits, error) {
	var l Limits
	data, err := os.ReadFile(file)
	if err != nil {
		return l, fmt.Errorf("reading limits: %w", err)
	}
	if err := json.Unmarshal(data, &l); err != nil {
		return l, fmt.Errorf("parsing limits: %w", err)
	}
	if l.Ref == "" || l.MaxInputBytes <= 0 || len(l.DeniedPrefixes) == 0 || l.MaxFileBytes <= 0 || l.MaxImageBytes <= 0 || l.MaxFilesPerPush <= 0 ||
		l.DailyBytesPerPlace <= 0 || len(l.AllowedExt) == 0 {
		return l, fmt.Errorf("limits file %s is incomplete", file)
	}
	return l, nil
}

// Violation is one broken limit. Code is "too-large" or "type-not-allowed".
type Violation struct {
	Code    string
	Message string
}

func (v *Violation) Error() string { return "REFUSED " + v.Code + ": " + v.Message }

// CheckFile checks one vault-relative, slash-separated path and its size in bytes.
func (l Limits) CheckFile(p string, size int64) *Violation {
	// Letter case is ignored here: on a Mac, ".Obsidian/x" lands in ".obsidian/".
	lower := strings.ToLower(p)
	for _, d := range l.DeniedPrefixes {
		if strings.HasPrefix(lower, strings.ToLower(d)) {
			return &Violation{"type-not-allowed", fmt.Sprintf("%s is under a never-accepted path (denied_prefixes: %s)", p, d)}
		}
	}
	ext := strings.ToLower(path.Ext(p))
	limit, name := l.MaxFileBytes, "max_file_bytes"
	switch {
	case slices.Contains(l.AllowedNames, path.Base(p)):
	case slices.Contains(l.AllowedExt, ext):
	case slices.Contains(l.ImageExt, ext):
		limit, name = l.MaxImageBytes, "max_image_bytes"
	case l.ExtUnderPrefix[ext] != "" && strings.HasPrefix(p, l.ExtUnderPrefix[ext]):
	default:
		return &Violation{"type-not-allowed", fmt.Sprintf("%s has a file type that is not accepted (allowed_ext: %s; image_ext: %s)",
			p, strings.Join(l.AllowedExt, " "), strings.Join(l.ImageExt, " "))}
	}
	if size > limit {
		return &Violation{"too-large", fmt.Sprintf("%s is %d bytes; limit %s=%d", p, size, name, limit)}
	}
	return nil
}
