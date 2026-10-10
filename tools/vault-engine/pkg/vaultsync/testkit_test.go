package vaultsync

import (
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// engineBin is the engine built once per test run. Every CLI call through the
// helpers sets VAULT_ROOT, because main.go falls back to the real vault without it.
var engineBin string

func TestMain(m *testing.M) {
	_ = os.Unsetenv("VAULT_ROOT")
	_ = os.Unsetenv("VAULT_PLACE")
	dir, err := os.MkdirTemp("", "vault-engine-bin-")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	engineBin = filepath.Join(dir, "vault-engine")
	if out, err := exec.Command("go", "build", "-o", engineBin, "obsidian-vault-engine/cmd/vault-engine").CombinedOutput(); err != nil {
		fmt.Fprintf(os.Stderr, "building engine: %v\n%s", err, out)
		os.Exit(1)
	}
	os.Exit(m.Run())
}

func gitIn(t *testing.T, dir string, env []string, args ...string) (string, error) {
	t.Helper()
	full := append([]string{"-c", "user.name=test", "-c", "user.email=test@test.invalid", "-c", "commit.gpgsign=false"}, args...)
	cmd := exec.Command("git", full...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), env...)
	out, err := cmd.CombinedOutput()
	return string(out), err
}

func mustGit(t *testing.T, dir string, args ...string) string {
	t.Helper()
	out, err := gitIn(t, dir, nil, args...)
	if err != nil {
		t.Fatalf("git %v in %s: %v\n%s", args, dir, err, out)
	}
	return strings.TrimSpace(out)
}

func writeFile(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatalf("mkdir for %s: %v", path, err)
	}
	if err := os.WriteFile(path, data, 0644); err != nil {
		t.Fatalf("write %s: %v", path, err)
	}
}

func newHub(t *testing.T) string {
	t.Helper()
	hub := filepath.Join(t.TempDir(), "hub.git")
	out, err := exec.Command("sh", filepath.Join("..", "..", "hub", "create-hub.sh"), hub, engineBin).CombinedOutput()
	if err != nil {
		t.Fatalf("create-hub: %v\n%s", err, out)
	}
	return hub
}

func pushAs(t *testing.T, dir, place, refspec string, extra ...string) (string, error) {
	t.Helper()
	args := append([]string{"push", "--porcelain"}, extra...)
	return gitIn(t, dir, []string{"VAULT_HUB_PLACE=" + place}, append(args, "origin", refspec)...)
}

// seededClone returns a working copy whose first commit is already on the hub.
func seededClone(t *testing.T, hub string) string {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "place")
	writeFile(t, filepath.Join(dir, "README.md"), []byte("seed\n"))
	mustGit(t, dir, "init", "--quiet", "--initial-branch=main")
	mustGit(t, dir, "remote", "add", "origin", hub)
	mustGit(t, dir, "add", "-A")
	mustGit(t, dir, "commit", "--quiet", "-m", "seed")
	if out, err := pushAs(t, dir, "seed", "HEAD:refs/heads/main"); err != nil {
		t.Fatalf("seed push: %v\n%s", err, out)
	}
	return dir
}

// commitFiles writes zero-filled files of the given sizes and commits them.
func commitFiles(t *testing.T, dir string, files map[string]int) {
	t.Helper()
	for rel, size := range files {
		writeFile(t, filepath.Join(dir, filepath.FromSlash(rel)), make([]byte, size))
	}
	mustGit(t, dir, "add", "-A")
	mustGit(t, dir, "commit", "--quiet", "-m", "test commit")
}

func dirSize(t *testing.T, dir string) int64 {
	t.Helper()
	var total int64
	_ = filepath.WalkDir(dir, func(_ string, d fs.DirEntry, err error) error {
		if err == nil && !d.IsDir() {
			if info, ierr := d.Info(); ierr == nil {
				total += info.Size()
			}
		}
		return nil
	})
	return total
}

type world struct{ Root, Hub, Mac, Srv string }

// newWorld builds a hub and two test places from the synthetic fixture.
func newWorld(t *testing.T) world {
	t.Helper()
	root := t.TempDir()
	cmd := exec.Command("bash", filepath.Join("..", "..", "scripts", "sync-harness.sh"), "setup", root, engineBin)
	cmd.Env = append(os.Environ(), "POLL_MS=200", "QUIET_MS=300")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("harness setup: %v\n%s", err, out)
	}
	return world{Root: root, Hub: filepath.Join(root, "hub.git"), Mac: filepath.Join(root, "mac-test"), Srv: filepath.Join(root, "srv-test")}
}
