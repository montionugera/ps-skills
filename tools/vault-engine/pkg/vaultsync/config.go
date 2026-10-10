package vaultsync

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
)

// ConfigRelPath is where a place keeps its sync settings. The file is never
// synced: _meta/bin/ is on the hub's never-accepted list.
const ConfigRelPath = "_meta/bin/sync.json"

var (
	ErrConfig  = errors.New("sync config error")
	placeRegex = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,62}$`)
)

type Config struct {
	Place          string `json:"place"`
	Remote         string `json:"remote"`
	Branch         string `json:"branch"`
	PollIntervalMS int    `json:"poll_interval_ms"`
	InboxQuietMS   int    `json:"inbox_quiet_ms"`
	NetTimeoutMS   int    `json:"net_timeout_ms"`
	LockTimeoutMS  int    `json:"lock_timeout_ms"`
	MaxRetries     int    `json:"max_retries"`
}

// LoadConfig returns (nil, nil) when the vault has no sync config: the vault
// is then not shared and every command behaves as it did before this package.
func LoadConfig(vaultRoot string) (*Config, error) {
	data, err := os.ReadFile(filepath.Join(vaultRoot, filepath.FromSlash(ConfigRelPath)))
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("%w: reading %s: %v", ErrConfig, ConfigRelPath, err)
	}
	cfg := &Config{Remote: "origin", Branch: "main", PollIntervalMS: 3000, InboxQuietMS: 3000,
		NetTimeoutMS: 10000, LockTimeoutMS: 15000, MaxRetries: 5}
	if err := json.Unmarshal(data, cfg); err != nil {
		return nil, fmt.Errorf("%w: parsing %s: %v", ErrConfig, ConfigRelPath, err)
	}
	if env := os.Getenv("VAULT_PLACE"); env != "" {
		cfg.Place = env
	}
	if !placeRegex.MatchString(cfg.Place) {
		return nil, fmt.Errorf("%w: place name %q must match %s", ErrConfig, cfg.Place, placeRegex)
	}
	for _, f := range []struct {
		name string
		ok   bool
	}{
		{"remote", cfg.Remote != ""}, {"branch", cfg.Branch != ""},
		{"poll_interval_ms", cfg.PollIntervalMS > 0}, {"inbox_quiet_ms", cfg.InboxQuietMS > 0},
		{"net_timeout_ms", cfg.NetTimeoutMS > 0}, {"lock_timeout_ms", cfg.LockTimeoutMS > 0},
		{"max_retries", cfg.MaxRetries > 0},
	} {
		if !f.ok {
			return nil, fmt.Errorf("%w: %s must be set and positive", ErrConfig, f.name)
		}
	}
	return cfg, nil
}
