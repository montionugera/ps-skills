package vaultsync

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func noRebuild() error { return nil }

func fixtureNote(t *testing.T, root, id string) string {
	t.Helper()
	m, _ := filepath.Glob(filepath.Join(root, "01_Ideas", id+"--*.md"))
	if len(m) != 1 {
		t.Fatalf("note %s not found in %s", id, root)
	}
	return m[0]
}

func lockFor(t *testing.T, r *Repo) {
	t.Helper()
	l, err := AcquireFolderLock(r.Root, time.Second)
	if err != nil {
		t.Fatalf("lock: %v", err)
	}
	r.lock = l
	t.Cleanup(func() { r.lock = nil; l.Release() })
}

// quarantined returns the bytes of the one copy of rel under _quarantine/<place>/.
func quarantined(t *testing.T, root, place, rel string) []byte {
	t.Helper()
	m, _ := filepath.Glob(filepath.Join(root, "_quarantine", place, "*", filepath.FromSlash(rel)))
	if len(m) != 1 {
		t.Fatalf("expected one copy of %s in _quarantine/%s/, found %v", rel, place, m)
	}
	data, err := os.ReadFile(m[0])
	if err != nil {
		t.Fatalf("read %s: %v", m[0], err)
	}
	return data
}

func TestRecover_InterruptedSaveMovesUnprovenFilesToQuarantineAndNeverTouchesAnInboxFile(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	note := fixtureNote(t, w.Mac, "IDEA-2026-000001")
	original, _ := os.ReadFile(note)
	stray := filepath.Join(w.Mac, "01_Ideas", "was-here-before.md")
	writeFile(t, stray, []byte("untracked before the save started\n"))

	if _, err := r.Begin("commit", "agent-olivier"); err != nil {
		t.Fatalf("begin: %v", err)
	}
	// The save wrote these, then the process died (no End).
	writeFile(t, note, []byte("half-written\n"))
	leftover := filepath.Join(w.Mac, "_meta", "events", "2026", "10", "1-agent-olivier.json")
	writeFile(t, leftover, []byte("{}"))
	drop := filepath.Join(w.Mac, "_inbox", "agent", "agent-olivier", "mac-test-20261010T000000.md")
	writeFile(t, drop, []byte("arrived while the save ran\n"))

	rebuilt := false
	if err := r.Recover(func() error { rebuilt = true; return nil }); err != nil {
		t.Fatalf("recover: %v", err)
	}
	if now, _ := os.ReadFile(note); string(now) != string(original) {
		t.Errorf("note was not put back")
	}
	// After a crash nothing proves who wrote an untracked file: it is moved, never deleted.
	for rel, want := range map[string]string{
		"_meta/events/2026/10/1-agent-olivier.json": "{}",
		"01_Ideas/was-here-before.md":               "untracked before the save started\n",
	} {
		if _, err := os.Stat(filepath.Join(w.Mac, filepath.FromSlash(rel))); !os.IsNotExist(err) {
			t.Errorf("%s should have been moved out of the folder", rel)
		}
		if got := quarantined(t, w.Mac, "mac-test", rel); string(got) != want {
			t.Errorf("%s in quarantine = %q, want %q", rel, got, want)
		}
	}
	report, _ := os.ReadFile(filepath.Join(w.Mac, "_quarantine", "mac-test", "REPORT.log"))
	if strings.Count(string(report), "QUARANTINED") != 2 {
		t.Errorf("expected two report lines, got:\n%s", report)
	}
	if text, err := os.ReadFile(drop); err != nil || string(text) != "arrived while the save ran\n" {
		t.Errorf("the inbox drop must stay where it is, untouched: %q, %v", text, err)
	}
	if r.hasMarker() || !rebuilt {
		t.Errorf("marker should be cleared (%v) and indexes rebuilt (%v)", r.hasMarker(), rebuilt)
	}
}

func TestRecover_UnsentCommitIsUndoneAndSentCommitIsKept(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	base, _ := r.Head()

	// Not sent: commit exists only locally, marker still present.
	if _, err := r.Begin("commit", "agent-olivier"); err != nil {
		t.Fatalf("begin: %v", err)
	}
	writeFile(t, filepath.Join(w.Mac, "01_Ideas", "new.md"), []byte("new\n"))
	if err := r.Commit([]string{"01_Ideas/new.md"}, "agent-olivier", "vault: commit", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	if err := r.Recover(noRebuild); err != nil {
		t.Fatalf("recover: %v", err)
	}
	if head, _ := r.Head(); head != base {
		t.Fatalf("unsent commit should be undone: head %s, base %s", head, base)
	}
	if _, err := os.Stat(filepath.Join(w.Mac, "01_Ideas", "new.md")); !os.IsNotExist(err) {
		t.Fatalf("file of the undone commit should be gone")
	}
	// The commit proves the save wrote that file, so it is removed, not set aside.
	if _, err := os.Stat(filepath.Join(w.Mac, "_quarantine")); !os.IsNotExist(err) {
		t.Fatalf("a file of the save's own commit must not fill _quarantine/")
	}

	// Sent: the hub has the commit, only the marker removal was lost.
	if _, err := r.Begin("commit", "agent-olivier"); err != nil {
		t.Fatalf("begin: %v", err)
	}
	writeFile(t, filepath.Join(w.Mac, "01_Ideas", "sent.md"), []byte("sent\n"))
	if err := r.Commit([]string{"01_Ideas/sent.md"}, "agent-olivier", "vault: commit", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	if out, err := pushAs(t, w.Mac, "mac-test", "HEAD:refs/heads/main"); err != nil {
		t.Fatalf("push: %v\n%s", err, out)
	}
	sent, _ := r.Head()
	if err := r.Recover(noRebuild); err != nil {
		t.Fatalf("recover: %v", err)
	}
	if head, _ := r.Head(); head != sent || r.hasMarker() {
		t.Fatalf("a commit the hub has must be kept (head %s, want %s; marker %v)", head, sent, r.hasMarker())
	}
}

func TestUndo_RemovesExactlyTheListedFilesAndLeavesAHandMadeFileAlone(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	note := fixtureNote(t, w.Mac, "IDEA-2026-000001")
	noteRel := "01_Ideas/" + filepath.Base(note)
	original, _ := os.ReadFile(note)
	m, err := r.Begin("commit", "agent-olivier")
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	writeFile(t, note, []byte("changed by the save\n"))
	written := filepath.Join(w.Mac, "_meta", "events", "2026", "10", "1-agent-olivier.json")
	writeFile(t, written, []byte("{}"))
	byHand := filepath.Join(w.Mac, "01_Ideas", "made-by-hand.md")
	writeFile(t, byHand, []byte("typed by a person while the save ran\n"))
	drop := filepath.Join(w.Mac, "_inbox", "human", "drop.md")
	writeFile(t, drop, []byte("a drop\n"))

	// The save lists what it wrote. Even a listed inbox file is never removed.
	list := []string{noteRel, "_meta/events/2026/10/1-agent-olivier.json", "_inbox/human/drop.md"}
	if err := r.Undo(m, list, noRebuild); err != nil {
		t.Fatalf("undo: %v", err)
	}
	if now, _ := os.ReadFile(note); string(now) != string(original) {
		t.Errorf("note was not put back")
	}
	if _, err := os.Stat(written); !os.IsNotExist(err) {
		t.Errorf("the listed file should be gone")
	}
	if text, err := os.ReadFile(byHand); err != nil || string(text) != "typed by a person while the save ran\n" {
		t.Errorf("a file the save did not list must stay untouched: %q, %v", text, err)
	}
	if _, err := os.Stat(drop); err != nil {
		t.Errorf("an inbox file must survive an undo: %v", err)
	}
	if _, err := os.Stat(filepath.Join(w.Mac, "_quarantine")); !os.IsNotExist(err) {
		t.Errorf("an undo with a known list sets nothing aside")
	}
}

func TestRecover_WithoutConnectionLeavesAnUnknownCommitAlone(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	if _, err := r.Begin("commit", "agent-olivier"); err != nil {
		t.Fatalf("begin: %v", err)
	}
	writeFile(t, filepath.Join(w.Mac, "01_Ideas", "new.md"), []byte("new\n"))
	if err := r.Commit([]string{"01_Ideas/new.md"}, "agent-olivier", "vault: commit", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	local, _ := r.Head()
	if err := os.Rename(w.Hub, w.Hub+".off"); err != nil {
		t.Fatalf("rename hub: %v", err)
	}
	if err := r.Recover(noRebuild); !errors.Is(err, ErrNoConnection) {
		t.Fatalf("expected ErrNoConnection, got %v", err)
	}
	if head, _ := r.Head(); head != local || !r.hasMarker() {
		t.Fatalf("nothing may be decided without the hub (head %s, want %s; marker %v)", head, local, r.hasMarker())
	}
}

func TestRecover_HandEditIsSetAsideAndTheNoteIsPutBack(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	note := fixtureNote(t, w.Mac, "IDEA-2026-000001")
	original, _ := os.ReadFile(note)
	writeFile(t, note, []byte("edited in an editor\n"))
	deleted := fixtureNote(t, w.Mac, "IDEA-2026-000002")
	if err := os.Remove(deleted); err != nil {
		t.Fatalf("remove: %v", err)
	}

	if err := r.Recover(noRebuild); err != nil {
		t.Fatalf("recover: %v", err)
	}
	if now, _ := os.ReadFile(note); string(now) != string(original) {
		t.Errorf("edited note was not put back to the shared version")
	}
	if _, err := os.Stat(deleted); err != nil {
		t.Errorf("deleted note was not restored: %v", err)
	}
	kept, _ := filepath.Glob(filepath.Join(w.Mac, "_quarantine", "mac-test", "*", "01_Ideas", filepath.Base(note)))
	if len(kept) != 1 {
		t.Fatalf("expected the edited text in _quarantine/mac-test/, found %v", kept)
	}
	if text, _ := os.ReadFile(kept[0]); string(text) != "edited in an editor\n" {
		t.Errorf("quarantined text differs: %q", text)
	}
	report, _ := os.ReadFile(filepath.Join(w.Mac, "_quarantine", "mac-test", "REPORT.log"))
	if strings.Count(string(report), "QUARANTINED") != 2 {
		t.Errorf("expected two report lines, got:\n%s", report)
	}
	if st, _ := r.Status(); len(st) != 0 {
		t.Errorf("folder should be clean (quarantine is ignored): %v", st)
	}
}

func TestUpdate_FastForwardsAndSurvivesAnInterruptedEarlierUpdate(t *testing.T) {
	w := newWorld(t)
	mac, srv := newRepo(t, w.Mac), newRepo(t, w.Srv)
	writeFile(t, filepath.Join(w.Mac, "_inbox", "human", "hello.md"), []byte("hello\n"))
	writeFile(t, filepath.Join(w.Mac, "01_Ideas", "added.md"), []byte("added\n"))
	if err := mac.Commit([]string{"_inbox/human/hello.md", "01_Ideas/added.md"}, "agent-olivier", "vault: commit", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	if out, err := pushAs(t, w.Mac, "mac-test", "HEAD:refs/heads/main"); err != nil {
		t.Fatalf("push: %v\n%s", err, out)
	}
	lockFor(t, srv)

	// An earlier update died half-way: marker present, some incoming files already on disk.
	if _, err := srv.Begin("update", "sync"); err != nil {
		t.Fatalf("begin: %v", err)
	}
	writeFile(t, filepath.Join(w.Srv, "_inbox", "human", "hello.md"), []byte("hello\n"))
	writeFile(t, filepath.Join(w.Srv, "01_Ideas", "added.md"), []byte("added\n"))
	// And an unsent local drop whose name clashes with nothing.
	writeFile(t, filepath.Join(w.Srv, "_inbox", "agent", "agent-olivier", "srv-test-1.md"), []byte("mine\n"))

	if err := srv.Recover(noRebuild); err != nil {
		t.Fatalf("recover: %v", err)
	}
	moved, err := srv.Update(noRebuild)
	if err != nil || !moved {
		t.Fatalf("update = (%v, %v), want (true, nil)", moved, err)
	}
	if a, b := mustGit(t, w.Srv, "rev-parse", "HEAD"), mustGit(t, w.Mac, "rev-parse", "HEAD"); a != b {
		t.Fatalf("srv at %s, mac at %s", a, b)
	}
	st, _ := srv.Status()
	if len(st) != 1 || st["_inbox/agent/agent-olivier/srv-test-1.md"] != "??" {
		t.Fatalf("only the unsent drop may remain untracked: %v", st)
	}
	if moved, err := srv.Update(noRebuild); err != nil || moved {
		t.Fatalf("second update = (%v, %v), want (false, nil)", moved, err)
	}
}

func TestUpdate_ClashingUnsentFileIsSetAsideNotOverwritten(t *testing.T) {
	w := newWorld(t)
	mac, srv := newRepo(t, w.Mac), newRepo(t, w.Srv)
	writeFile(t, filepath.Join(w.Mac, "_inbox", "human", "same-name.md"), []byte("from mac\n"))
	if err := mac.Commit([]string{"_inbox/human/same-name.md"}, "inbox", "vault: inbox drop", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	if out, err := pushAs(t, w.Mac, "mac-test", "HEAD:refs/heads/main"); err != nil {
		t.Fatalf("push: %v\n%s", err, out)
	}
	writeFile(t, filepath.Join(w.Srv, "_inbox", "human", "same-name.md"), []byte("from srv, different\n"))
	lockFor(t, srv)
	if _, err := srv.Update(noRebuild); err != nil {
		t.Fatalf("update: %v", err)
	}
	if text, _ := os.ReadFile(filepath.Join(w.Srv, "_inbox", "human", "same-name.md")); string(text) != "from mac\n" {
		t.Errorf("incoming version should be in place, got %q", text)
	}
	kept, _ := filepath.Glob(filepath.Join(w.Srv, "_quarantine", "srv-test", "*", "_inbox", "human", "same-name.md"))
	if len(kept) != 1 {
		t.Fatalf("the unsent local file must be set aside, found %v", kept)
	}
}

func TestUndo_AListedFileThatWasAlreadyUntrackedBeforeTheSaveIsKeptNotDeleted(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	pre := filepath.Join(w.Mac, "01_Ideas", "pre-existing.md")
	writeFile(t, pre, []byte("mine, from before\n"))
	m, err := r.Begin("commit", "agent-olivier")
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	if err := r.Undo(m, []string{"01_Ideas/pre-existing.md"}, noRebuild); err != nil {
		t.Fatalf("undo: %v", err)
	}
	if got := quarantined(t, w.Mac, "mac-test", "01_Ideas/pre-existing.md"); string(got) != "mine, from before\n" {
		t.Errorf("pre-existing file lost: %q", got)
	}
}
