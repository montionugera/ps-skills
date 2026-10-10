package vaultsync

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// plainVault is a folder with no sync config and no git, as vaults are today.
func plainVault(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	for _, d := range []string{"_inbox/human", "_meta/indexes", "_meta/events", "01_Ideas", "02_Projects", "03_Areas", "04_Knowledge"} {
		if err := os.MkdirAll(filepath.Join(root, d), 0755); err != nil {
			t.Fatalf("mkdir: %v", err)
		}
	}
	return root
}

func TestCLI_WithoutSyncConfigOutputIsExactlyAsBefore(t *testing.T) {
	root := plainVault(t)
	drop := filepath.Join(root, "_inbox", "human", "idea.md")
	writeFile(t, drop, []byte("---\ntitle: Plain idea\n---\nBody\n"))

	out, errOut, code := engineCLI(root, "ingest", drop)
	if code != 0 || errOut != "" || !regexp.MustCompile(`^Ingested note as IDEA-\d{4}-000001\n$`).MatchString(out) {
		t.Fatalf("ingest: exit %d, stdout %q, stderr %q", code, out, errOut)
	}
	id := strings.TrimSpace(strings.TrimPrefix(out, "Ingested note as "))

	out, errOut, code = engineCLI(root, "commit", id, "stale-fake-hash-0000", "agent-bestie", `{"status":"committed"}`)
	wantErr := regexp.MustCompile(`^Commit FAILED: conflict: expected sha does not match current record sha: expected stale-fake-hash-0000 but current is [0-9a-f]{64}\n$`)
	if code != 1 || out != "" || !wantErr.MatchString(errOut) {
		t.Fatalf("stale commit: exit %d, stdout %q, stderr %q", code, out, errOut)
	}

	// Today an empty fingerprint skips the check. That stays so without a sync config.
	out, errOut, code = engineCLI(root, "commit", id, "", "agent-olivier", `{"impact":5}`)
	if code != 0 || errOut != "" || out != "Commit SUCCESS for "+id+" by agent-olivier (OCC validated)\n" {
		t.Fatalf("commit: exit %d, stdout %q, stderr %q", code, out, errOut)
	}

	out, _, code = engineCLI(root, "capture", "key-1", "product_feature", "cli", "Captured text")
	if code != 0 || !strings.HasPrefix(out, `{"run_id":"RUN-`) || !strings.HasSuffix(out, "}\n") || strings.Count(out, "\n") != 1 {
		t.Fatalf("capture: exit %d, stdout %q", code, out)
	}

	if out, _, code = engineCLI(root, "route", "product_feature", "idea", "dark-mode"); code != 0 || out != "01_Ideas/dark-mode.md\n" {
		t.Fatalf("route: exit %d, stdout %q", code, out)
	}

	_, errOut, code = engineCLI(root, "whoami")
	if code != 1 || !strings.Contains(errOut, "this folder is not shared") {
		t.Fatalf("whoami without config: exit %d, stderr %q", code, errOut)
	}
	if _, err := os.Stat(filepath.Join(root, "_meta", "guards", "folder.guard")); !os.IsNotExist(err) {
		t.Fatalf("no folder lock may be taken without a sync config")
	}
}

func TestCLI_SyncedVaultEndsEverySaveWithAFixedLine(t *testing.T) {
	w := newWorld(t)

	if out, _, code := engineCLI(w.Mac, "whoami"); code != 0 || out != "mac-test\n" {
		t.Fatalf("whoami: exit %d, %q", code, out)
	}

	drop := filepath.Join(w.Mac, "_inbox", "agent", "agent-olivier", "mac-test-1.md")
	writeFile(t, drop, []byte("---\ntitle: Synced idea\n---\nBody\n"))
	out, errOut, code := engineCLI(w.Mac, "ingest", drop)
	if code != 0 || lastLine(out) != "SAVED" || !strings.HasPrefix(out, "Ingested note as IDEA-") {
		t.Fatalf("ingest: exit %d, stdout %q, stderr %q", code, out, errOut)
	}

	stale := readSHA(t, w.Srv, note1)
	if out, errOut, code := engineCLI(w.Mac, "commit", note1, readSHA(t, w.Mac, note1), "agent-olivier", `{"impact":5}`); code != 0 || lastLine(out) != "SAVED" {
		t.Fatalf("commit on mac: exit %d, stdout %q, stderr %q", code, out, errOut)
	}
	out, errOut, code = engineCLI(w.Srv, "commit", note1, stale, "agent-bestie", `{"impact":1}`)
	if code != 3 || lastLine(out) != "REFUSED note-changed" || !strings.Contains(errOut, "Commit FAILED: conflict: expected sha does not match current record sha") {
		t.Fatalf("stale commit on srv: exit %d, stdout %q, stderr %q", code, out, errOut)
	}

	out, errOut, code = engineCLI(w.Srv, "commit", note1, "", "agent-bestie", `{"impact":1}`)
	if code != 3 || lastLine(out) != "REFUSED note-changed" || !strings.Contains(errOut, "fingerprint") {
		t.Fatalf("commit without fingerprint: exit %d, stdout %q, stderr %q", code, out, errOut)
	}

	out, errOut, code = engineCLI(w.Mac, "commit", "IDEA-2026-999999", "abc", "agent-olivier", `{"impact":5}`)
	if code != 1 || lastLine(out) != "REFUSED engine-error" || !strings.Contains(errOut, "record not found") {
		t.Fatalf("unknown record: exit %d, stdout %q, stderr %q", code, out, errOut)
	}

	for _, cmd := range [][]string{{"daemon", "--once"}, {"run-workflow", "x.json"}} {
		out, _, code := engineCLI(w.Mac, cmd...)
		if code != 1 || lastLine(out) != "REFUSED engine-error" {
			t.Fatalf("%v in a synced vault: exit %d, stdout %q", cmd, code, out)
		}
	}

	if out, _, code := engineCLI(w.Mac, "capture", "key-1", "product_feature", "cli", "Captured text"); code != 0 || lastLine(out) != "SAVED" {
		t.Fatalf("capture: exit %d, %q", code, out)
	}
	if out, _, code := engineCLI(w.Mac, "route", "product_feature", "idea", "dark-mode"); code != 0 || out != "01_Ideas/dark-mode.md\n" {
		t.Fatalf("route must stay a plain lookup: exit %d, %q", code, out)
	}
	if st := mustGit(t, w.Mac, "status", "--porcelain"); st != "" {
		t.Fatalf("mac is not clean:\n%s", st)
	}
}
