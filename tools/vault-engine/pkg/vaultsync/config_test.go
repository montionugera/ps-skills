package vaultsync

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func writeSyncConfig(t *testing.T, root, body string) {
	t.Helper()
	dir := filepath.Join(root, "_meta", "bin")
	if err := os.MkdirAll(dir, 0755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "sync.json"), []byte(body), 0644); err != nil {
		t.Fatalf("write sync.json: %v", err)
	}
}

func TestLoadConfig_AbsentMeansNotSynced(t *testing.T) {
	cfg, err := LoadConfig(t.TempDir())
	if cfg != nil || err != nil {
		t.Fatalf("expected (nil, nil), got (%v, %v)", cfg, err)
	}
}

func TestLoadConfig_DefaultsAndEnvOverride(t *testing.T) {
	root := t.TempDir()
	writeSyncConfig(t, root, `{"place":"mac-test"}`)
	cfg, err := LoadConfig(root)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if cfg.Place != "mac-test" || cfg.Remote != "origin" || cfg.Branch != "main" || cfg.PollIntervalMS != 3000 ||
		cfg.InboxQuietMS != 3000 || cfg.NetTimeoutMS != 10000 || cfg.LockTimeoutMS != 15000 || cfg.MaxRetries != 5 {
		t.Fatalf("unexpected defaults: %+v", cfg)
	}
	t.Setenv("VAULT_PLACE", "pod-7")
	cfg, err = LoadConfig(root)
	if err != nil || cfg.Place != "pod-7" {
		t.Fatalf("expected VAULT_PLACE to win, got (%+v, %v)", cfg, err)
	}
}

func TestLoadConfig_RejectsBadPlace(t *testing.T) {
	root := t.TempDir()
	writeSyncConfig(t, root, `{"place":"Mac 1"}`)
	if _, err := LoadConfig(root); !errors.Is(err, ErrConfig) {
		t.Fatalf("expected ErrConfig, got %v", err)
	}
}
