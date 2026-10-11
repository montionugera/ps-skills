package vaultsync

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestHarness_BuildsHubAndTwoPlaces(t *testing.T) {
	w := newWorld(t)
	hubTip := mustGit(t, w.Hub, "rev-parse", "refs/heads/main")
	for place, root := range map[string]string{"mac-test": w.Mac, "srv-test": w.Srv} {
		if got := mustGit(t, root, "rev-parse", "HEAD"); got != hubTip {
			t.Fatalf("%s is at %s, hub at %s", place, got, hubTip)
		}
		if st := mustGit(t, root, "status", "--porcelain"); st != "" {
			t.Fatalf("%s is not clean after setup:\n%s", place, st)
		}
		cfg, err := LoadConfig(root)
		if err != nil || cfg == nil || cfg.Place != place || cfg.PollIntervalMS != 200 || cfg.InboxQuietMS != 300 {
			t.Fatalf("%s: unexpected sync config (%+v, %v)", place, cfg, err)
		}
		if _, err := os.Stat(filepath.Join(root, "_meta", "bin", "vault-engine")); err != nil {
			t.Fatalf("%s: engine not installed: %v", place, err)
		}
		for _, id := range []string{"IDEA-2026-000001", "IDEA-2026-000002"} {
			if m, _ := filepath.Glob(filepath.Join(root, "01_Ideas", id+"--*.md")); len(m) != 1 {
				t.Fatalf("%s: fixture note %s missing", place, id)
			}
		}
	}
}

func TestHarness_InstallsTheRulesFiles(t *testing.T) {
	w := newWorld(t)
	agents, err := os.ReadFile(filepath.Join(w.Mac, "AGENTS.md"))
	if err != nil {
		t.Fatalf("AGENTS.md: %v", err)
	}
	for _, want := range []string{
		"_meta/bin/vault-engine whoami", "SAVED", "REFUSED note-changed", "REFUSED no-connection",
		"REFUSED too-large", "REFUSED type-not-allowed", "REFUSED busy", "REFUSED engine-error",
		"_inbox/agent/<your-agent-id>/", "Never run git in this folder",
	} {
		if !strings.Contains(string(agents), want) {
			t.Errorf("AGENTS.md does not mention %q", want)
		}
	}
	if claude, _ := os.ReadFile(filepath.Join(w.Mac, "CLAUDE.md")); string(claude) != "@AGENTS.md\n" {
		t.Errorf("CLAUDE.md should contain only the import line, got %q", claude)
	}
	if gemini, _ := os.ReadFile(filepath.Join(w.Mac, "GEMINI.md")); string(gemini) != "@./AGENTS.md\n" {
		t.Errorf("GEMINI.md should contain only the import line, got %q", gemini)
	}
	// The rules travel with the folder: they are on the hub.
	if out := mustGit(t, w.Hub, "ls-tree", "--name-only", "refs/heads/main"); !strings.Contains(out, "AGENTS.md") ||
		!strings.Contains(out, "CLAUDE.md") || !strings.Contains(out, "GEMINI.md") {
		t.Errorf("rules files are not on the hub:\n%s", out)
	}
}

func TestHarness_RefusesAnExtraGuardedDirThroughASymlink(t *testing.T) {
	base := t.TempDir()
	guarded := filepath.Join(base, "guarded")
	inside := filepath.Join(guarded, "empty")
	if err := os.MkdirAll(inside, 0o755); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(base, "link")
	if err := os.Symlink(guarded, link); err != nil {
		t.Fatal(err)
	}
	script := filepath.Join("..", "..", "scripts", "sync-harness.sh")
	for name, guard := range map[string]string{"real-path": guarded, "symlink-path": link} {
		cmd := exec.Command("bash", script, "setup", inside, engineBin)
		cmd.Env = append(os.Environ(), "VAULT_HARNESS_EXTRA_GUARDED_DIR="+guard)
		out, err := cmd.CombinedOutput()
		if err == nil || !strings.Contains(string(out), "refusing to work inside the real vault") {
			t.Errorf("%s: want refusal, got err=%v\n%s", name, err, out)
		}
	}
	if entries, _ := os.ReadDir(inside); len(entries) != 0 {
		t.Errorf("guarded stand-in was written to: %v", entries)
	}
}

func TestHarness_RealVaultStaysGuardedWhenExtraDirIsSet(t *testing.T) {
	home := t.TempDir()
	standIn := filepath.Join(home, "workspace", "agentic-vault", "empty")
	if err := os.MkdirAll(standIn, 0o755); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("bash", filepath.Join("..", "..", "scripts", "sync-harness.sh"), "setup", standIn, engineBin)
	cmd.Env = append(os.Environ(), "HOME="+home, "VAULT_HARNESS_EXTRA_GUARDED_DIR="+t.TempDir())
	out, err := cmd.CombinedOutput()
	if err == nil || !strings.Contains(string(out), "refusing to work inside the real vault") {
		t.Errorf("want refusal, got err=%v\n%s", err, out)
	}
	if entries, _ := os.ReadDir(standIn); len(entries) != 0 {
		t.Errorf("stand-in was written to: %v", entries)
	}
}

func TestHarness_SetupNamesAMissingTargetFolder(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "not-there")
	cmd := exec.Command("bash", filepath.Join("..", "..", "scripts", "sync-harness.sh"), "setup", missing, engineBin)
	out, err := cmd.CombinedOutput()
	var ee *exec.ExitError
	if !errors.As(err, &ee) || ee.ExitCode() != 1 {
		t.Fatalf("want exit 1, got %v\n%s", err, out)
	}
	if want := "sync-harness: target folder " + missing + " does not exist\n"; string(out) != want {
		t.Fatalf("output = %q, want exactly %q", out, want)
	}
	if _, err := os.Stat(missing); !os.IsNotExist(err) {
		t.Fatalf("setup must not create the folder it was asked about: %v", err)
	}
}
