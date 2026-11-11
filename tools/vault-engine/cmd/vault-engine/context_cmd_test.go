package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"obsidian-vault-engine/pkg/vault"
)

func captureStdout(t *testing.T, fn func()) string {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	origStdout := os.Stdout
	os.Stdout = w
	outC := make(chan string)
	go func() {
		var buf bytes.Buffer
		_, _ = io.Copy(&buf, r)
		outC <- buf.String()
	}()

	fn()

	_ = w.Close()
	os.Stdout = origStdout
	out := <-outC
	_ = r.Close()
	return out
}

func countNoteLines(out string) int {
	lines := 0
	for _, line := range strings.Split(out, "\n") {
		if strings.HasPrefix(line, "- ") {
			lines++
		}
	}
	return lines
}

func TestRunContext_CwdNoteCap(t *testing.T) {
	root := t.TempDir()
	indexDir := filepath.Join(root, "_meta", "indexes")
	if err := os.MkdirAll(indexDir, 0755); err != nil {
		t.Fatal(err)
	}
	engine := vault.NewVaultEngine(root)

	targetDir := t.TempDir()
	repoTag := "repo:" + filepath.Base(targetDir)

	var entries []vault.IndexEntry
	for i := 1; i <= 8; i++ {
		entries = append(entries, vault.IndexEntry{
			ID:      fmt.Sprintf("CONCEPT-%02d", i),
			Title:   fmt.Sprintf("Note %d", i),
			Status:  "active",
			Path:    fmt.Sprintf("04_Knowledge/concepts/n%d.md", i),
			Tags:    []string{repoTag},
			Updated: fmt.Sprintf("2026-11-01T00:00:%02dZ", i),
			Summary: fmt.Sprintf("Summary %d", i),
		})
	}
	var buf bytes.Buffer
	for _, e := range entries {
		data, _ := json.Marshal(e)
		buf.Write(data)
		buf.WriteByte('\n')
	}
	if err := os.WriteFile(filepath.Join(indexDir, "knowledge.jsonl"), buf.Bytes(), 0644); err != nil {
		t.Fatal(err)
	}

	// Default mode: context --cwd should output exactly 3 note lines
	outDefault := captureStdout(t, func() {
		runContext(engine, []string{"--cwd", targetDir})
	})
	if n := countNoteLines(outDefault); n != 3 {
		t.Fatalf("expected exactly 3 note lines by default, got %d in:\n%s", n, outDefault)
	}

	// With --limit 6: context --cwd --limit 6 should output exactly 6 note lines
	outLimit6 := captureStdout(t, func() {
		runContext(engine, []string{"--cwd", targetDir, "--limit", "6"})
	})
	if n := countNoteLines(outLimit6); n != 6 {
		t.Fatalf("expected exactly 6 note lines with --limit 6, got %d in:\n%s", n, outLimit6)
	}
}

func TestRunContext_QueryNoteCap(t *testing.T) {
	root := t.TempDir()
	indexDir := filepath.Join(root, "_meta", "indexes")
	if err := os.MkdirAll(indexDir, 0755); err != nil {
		t.Fatal(err)
	}
	engine := vault.NewVaultEngine(root)

	var entries []vault.IndexEntry
	for i := 1; i <= 8; i++ {
		entries = append(entries, vault.IndexEntry{
			ID:      fmt.Sprintf("CONCEPT-%02d", i),
			Title:   fmt.Sprintf("Database Optimization Note %d", i),
			Status:  "active",
			Path:    fmt.Sprintf("04_Knowledge/concepts/db%d.md", i),
			Terms:   []string{"database", "optimization"},
			Updated: fmt.Sprintf("2026-11-01T00:00:%02dZ", i),
			Summary: fmt.Sprintf("Summary %d", i),
		})
	}
	var buf bytes.Buffer
	for _, e := range entries {
		data, _ := json.Marshal(e)
		buf.Write(data)
		buf.WriteByte('\n')
	}
	if err := os.WriteFile(filepath.Join(indexDir, "knowledge.jsonl"), buf.Bytes(), 0644); err != nil {
		t.Fatal(err)
	}

	// Default mode: context --query should output 5 notes
	outDefault := captureStdout(t, func() {
		runContext(engine, []string{"--query", "database optimization"})
	})
	if n := countNoteLines(outDefault); n != 5 {
		t.Fatalf("expected exactly 5 note lines by default, got %d in:\n%s", n, outDefault)
	}

	// With --limit 2: context --query --limit 2 should output 2 notes
	outLimit2 := captureStdout(t, func() {
		runContext(engine, []string{"--query", "database optimization", "--limit", "2"})
	})
	if n := countNoteLines(outLimit2); n != 2 {
		t.Fatalf("expected exactly 2 note lines with --limit 2, got %d in:\n%s", n, outLimit2)
	}
}
