package vaultsync

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"obsidian-vault-engine/pkg/vault"
)

// I3: a failing log is not "not saved yet".
func TestAlreadySaved_AGitFailureIsAnErrorNotAnAnswer(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	if _, err := mac.alreadySaved("some-key"); err != nil {
		t.Fatalf("a healthy folder must answer: %v", err)
	}
	mac.Repo.Remote = "no-such-remote"
	if done, err := mac.alreadySaved("some-key"); err == nil || done {
		t.Fatalf("a git failure must be an error, got (%v, %v)", done, err)
	}
}

// Without a sync config main.go calls op.Run() directly: it must work for any
// source and behave as IngestFile always has.
func TestIngestOp_RunWorksOnAnOutsideSourceWithoutASyncer(t *testing.T) {
	w := newWorld(t)
	e := vault.NewVaultEngine(w.Mac)
	src := filepath.Join(t.TempDir(), "plain.md")
	writeFile(t, src, []byte("---\ntitle: Plain outside\n---\nBody\n"))
	op := IngestOp(e, src, "agent-olivier")
	if op.Run == nil {
		t.Fatal("Run must always be set")
	}
	msg, err := op.Run()
	if err != nil || !strings.HasPrefix(msg, "Ingested note as IDEA-") {
		t.Fatalf("Run = (%q, %v)", msg, err)
	}
	if _, err := os.Stat(src); !os.IsNotExist(err) {
		t.Errorf("ingest has always removed its source")
	}
	if m, _ := filepath.Glob(filepath.Join(w.Mac, "01_Ideas", "IDEA-*--plain-outside.md")); len(m) != 1 {
		t.Errorf("expected the note, got %v", m)
	}
}

func TestIngestOp_RunGivesTheCallersOwnPathToTheEngine(t *testing.T) {
	w := newWorld(t)
	e := vault.NewVaultEngine(w.Mac)
	dir := t.TempDir()
	target := filepath.Join(dir, "target.md")
	writeFile(t, target, []byte("---\ntitle: Via link\n---\nBody\n"))
	link := filepath.Join(dir, "link.md")
	if err := os.Symlink(target, link); err != nil {
		t.Fatal(err)
	}
	if _, err := IngestOp(e, link, "a").Run(); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if _, err := os.Lstat(link); !os.IsNotExist(err) {
		t.Errorf("the path the caller gave is the one removed")
	}
	if _, err := os.Stat(target); err != nil {
		t.Errorf("the link's target is not what the engine removes: %v", err)
	}
}

func TestIngestOp_RunOnAMissingSourceGivesTheEnginesOwnError(t *testing.T) {
	w := newWorld(t)
	e := vault.NewVaultEngine(w.Mac)
	missing := filepath.Join(t.TempDir(), "nope.md")
	_, want := e.IngestFile(missing)
	if want == nil {
		t.Fatal("the engine should fail on a missing file")
	}
	for _, p := range []string{missing, filepath.Join(w.Mac, "_inbox", "human", "nope.md")} {
		_, want := e.IngestFile(p)
		if _, got := IngestOp(e, p, "a").Run(); got == nil || got.Error() != want.Error() {
			t.Errorf("%s: error = %v, want the engine's own: %v", p, got, want)
		}
	}
}
