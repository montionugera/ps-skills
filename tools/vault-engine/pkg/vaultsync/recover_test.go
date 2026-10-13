package vaultsync

import (
	"errors"
	"os"
	"path/filepath"
	"sort"
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
	// A tracked note changed before any commit cannot be told from a hand edit: it is copied too.
	noteRel := "01_Ideas/" + filepath.Base(note)
	if got := quarantined(t, w.Mac, "mac-test", noteRel); string(got) != "half-written\n" {
		t.Errorf("changed note not copied to quarantine: %q", got)
	}
	report, _ := os.ReadFile(filepath.Join(w.Mac, "_quarantine", "mac-test", "REPORT.log"))
	if strings.Count(string(report), "QUARANTINED") != 3 {
		t.Errorf("expected three report lines, got:\n%s", report)
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
	rebuilt, markerAtRebuild := 0, false
	if err := r.Recover(func() error { rebuilt++; markerAtRebuild = r.hasMarker(); return nil }); err != nil {
		t.Fatalf("recover: %v", err)
	}
	if rebuilt != 1 || !markerAtRebuild {
		t.Fatalf("indexes must be rebuilt once, before the marker is cleared (rebuilt %d, marker present %v)", rebuilt, markerAtRebuild)
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
	rebuilt, markerAtRebuild := 0, false
	moved, err := srv.Update(func() error { rebuilt++; markerAtRebuild = srv.hasMarker(); return nil })
	if err != nil || !moved {
		t.Fatalf("update = (%v, %v), want (true, nil)", moved, err)
	}
	if rebuilt != 1 || !markerAtRebuild || srv.hasMarker() {
		t.Fatalf("rebuild must run once while the marker is present, then the marker goes (rebuilt %d, marker at rebuild %v, marker now %v)", rebuilt, markerAtRebuild, srv.hasMarker())
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

func reportLines(t *testing.T, root, place string) int {
	t.Helper()
	b, _ := os.ReadFile(filepath.Join(root, "_quarantine", place, "REPORT.log"))
	return strings.Count(string(b), "QUARANTINED")
}

func TestUndo_AHandEditToANoteNotOnTheListIsKeptInQuarantine(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	mine := fixtureNote(t, w.Mac, "IDEA-2026-000001")
	other := fixtureNote(t, w.Mac, "IDEA-2026-000002")
	origMine, _ := os.ReadFile(mine)
	origOther, _ := os.ReadFile(other)
	m, err := r.Begin("commit", "agent-olivier")
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	writeFile(t, mine, []byte("changed by the save\n"))
	writeFile(t, other, []byte("typed by a person during the save\n"))
	if err := r.Undo(m, []string{"01_Ideas/" + filepath.Base(mine)}, noRebuild); err != nil {
		t.Fatalf("undo: %v", err)
	}
	if now, _ := os.ReadFile(mine); string(now) != string(origMine) {
		t.Errorf("listed note not put back")
	}
	if now, _ := os.ReadFile(other); string(now) != string(origOther) {
		t.Errorf("unlisted note not put back")
	}
	if got := quarantined(t, w.Mac, "mac-test", "01_Ideas/"+filepath.Base(other)); string(got) != "typed by a person during the save\n" {
		t.Errorf("hand edit lost: %q", got)
	}
	if n := reportLines(t, w.Mac, "mac-test"); n != 1 {
		t.Errorf("expected exactly one report line, got %d", n)
	}
}

func TestUndo_AListedFileReplacedAfterTheCommitIsMovedNotDeleted(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	m, err := r.Begin("commit", "agent-olivier")
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	p := filepath.Join(w.Mac, "01_Ideas", "new.md")
	writeFile(t, p, []byte("what the save wrote\n"))
	if err := r.Commit([]string{"01_Ideas/new.md"}, "agent-olivier", "vault: commit", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	writeFile(t, p, []byte("a person rewrote this\n"))
	if err := r.Undo(m, []string{"01_Ideas/new.md"}, noRebuild); err != nil {
		t.Fatalf("undo: %v", err)
	}
	if _, err := os.Stat(p); !os.IsNotExist(err) {
		t.Errorf("file should have been moved out of the folder")
	}
	if got := quarantined(t, w.Mac, "mac-test", "01_Ideas/new.md"); string(got) != "a person rewrote this\n" {
		t.Errorf("rewritten text lost: %q", got)
	}
}

func TestUpdate_HandEditToANoteTheIncomingVersionAlsoChangesIsSetAside(t *testing.T) {
	w := newWorld(t)
	mac, srv := newRepo(t, w.Mac), newRepo(t, w.Srv)
	macNote := fixtureNote(t, w.Mac, "IDEA-2026-000001")
	rel := "01_Ideas/" + filepath.Base(macNote)
	writeFile(t, macNote, []byte("shared change\n"))
	if err := mac.Commit([]string{rel}, "agent-olivier", "vault: commit", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	if out, err := pushAs(t, w.Mac, "mac-test", "HEAD:refs/heads/main"); err != nil {
		t.Fatalf("push: %v\n%s", err, out)
	}
	srvNote := filepath.Join(w.Srv, filepath.FromSlash(rel))
	writeFile(t, srvNote, []byte("hand edit on the server\n"))
	lockFor(t, srv)
	if moved, err := srv.Update(noRebuild); err != nil || !moved {
		t.Fatalf("update = (%v, %v), want (true, nil)", moved, err)
	}
	if now, _ := os.ReadFile(srvNote); string(now) != "shared change\n" {
		t.Errorf("folder should be at the hub's version, got %q", now)
	}
	if got := quarantined(t, w.Srv, "srv-test", rel); string(got) != "hand edit on the server\n" {
		t.Errorf("hand edit lost: %q", got)
	}
	if a, b := mustGit(t, w.Srv, "rev-parse", "HEAD"), mustGit(t, w.Mac, "rev-parse", "HEAD"); a != b {
		t.Errorf("srv at %s, mac at %s", a, b)
	}
}

func TestRecover_EngineFilesStayPutEvenWhenGitignoreLacksTheirLines(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	writeFile(t, filepath.Join(w.Mac, ".gitignore"), []byte(".DS_Store\n"))
	if err := r.Commit([]string{".gitignore"}, "agent-olivier", "vault: gitignore", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	if _, err := r.Begin("commit", "agent-olivier"); err != nil {
		t.Fatalf("begin: %v", err)
	}
	writeFile(t, filepath.Join(w.Mac, "01_Ideas", "stray.md"), []byte("stray\n"))
	if err := r.Recover(noRebuild); err != nil {
		t.Fatalf("recover: %v", err)
	}
	for _, rel := range []string{"_meta/guards/folder.guard", "_meta/bin/sync.json"} {
		if _, err := os.Stat(filepath.Join(w.Mac, filepath.FromSlash(rel))); err != nil {
			t.Errorf("%s must stay in place: %v", rel, err)
		}
	}
	if n := reportLines(t, w.Mac, "mac-test"); n != 1 {
		t.Errorf("only the stray note may be quarantined, got %d report lines", n)
	}
	if m, _ := filepath.Glob(filepath.Join(w.Mac, "_quarantine", "mac-test", "*", "_quarantine", "*")); len(m) != 0 {
		t.Errorf("_quarantine/ was quarantined into itself: %v", m)
	}
}

func TestRecover_AFileNameStartingWithASpaceIsReadWhole(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	if _, err := r.Begin("commit", "agent-olivier"); err != nil {
		t.Fatalf("begin: %v", err)
	}
	writeFile(t, filepath.Join(w.Mac, " lead.md"), []byte("the save's file\n"))
	if err := r.Commit([]string{" lead.md"}, "agent-olivier", "vault: commit", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	writeFile(t, filepath.Join(w.Mac, "lead.md"), []byte("someone else's file\n"))
	if err := r.Recover(noRebuild); err != nil {
		t.Fatalf("recover: %v", err)
	}
	if _, err := os.Stat(filepath.Join(w.Mac, " lead.md")); !os.IsNotExist(err) {
		t.Errorf("the save's own file should be removed")
	}
	if got := quarantined(t, w.Mac, "mac-test", "lead.md"); string(got) != "someone else's file\n" {
		t.Errorf("the other file must be set aside, not deleted: %q", got)
	}
}

func TestIsAncestor_TellsNotAnAncestorFromAGitError(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	base, _ := r.Head()
	writeFile(t, filepath.Join(w.Mac, "01_Ideas", "x.md"), []byte("x\n"))
	if err := r.Commit([]string{"01_Ideas/x.md"}, "a", "s", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	head, _ := r.Head()
	if ok, err := r.isAncestor(base, head); !ok || err != nil {
		t.Errorf("base is an ancestor of head: (%v, %v)", ok, err)
	}
	if ok, err := r.isAncestor(head, base); ok || err != nil {
		t.Errorf("head is not an ancestor of base, and that is not an error: (%v, %v)", ok, err)
	}
	if _, err := r.isAncestor(head, "refs/remotes/origin/no-such-branch"); err == nil {
		t.Errorf("an unknown ref is a git error, not 'not an ancestor'")
	}
}

func sortedKeys(m map[string]string) []string {
	var out []string
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func TestUndo_ANoteEditedByHandBeforeBeginIsNotListedAndSurvivesARefusedSave(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	note := fixtureNote(t, w.Mac, "IDEA-2026-000001")
	rel := "01_Ideas/" + filepath.Base(note)
	writeFile(t, note, []byte("typed by a person before the save began\n"))
	m, err := r.Begin("commit", "agent-olivier")
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	st, err := r.changed(m)
	if err != nil {
		t.Fatalf("changed: %v", err)
	}
	if len(st) != 0 {
		t.Fatalf("a note the save did not write must not be listed: %v", sortedKeys(st))
	}
	if err := r.Undo(m, sortedKeys(st), noRebuild); err != nil {
		t.Fatalf("undo: %v", err)
	}
	if now, _ := os.ReadFile(note); string(now) != "typed by a person before the save began\n" {
		t.Errorf("hand edit lost or altered: %q", now)
	}
	if n := reportLines(t, w.Mac, "mac-test"); n != 1 { // the copy Begin made; the undo adds none
		t.Errorf("expected only Begin's report line, got %d", n)
	}
	// The next pass with no marker handles it as before.
	if err := r.End(); err != nil {
		t.Fatalf("end: %v", err)
	}
	if err := r.Recover(noRebuild); err != nil {
		t.Fatalf("recover: %v", err)
	}
	if got := quarantined(t, w.Mac, "mac-test", rel); string(got) != "typed by a person before the save began\n" {
		t.Errorf("hand edit not kept by the no-marker pass: %q", got)
	}
}

func TestRecover_AHandEditBeforeBeginIsLeftForTheNextPassAfterACrash(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	note := fixtureNote(t, w.Mac, "IDEA-2026-000001")
	writeFile(t, note, []byte("hand edit\n"))
	if _, err := r.Begin("commit", "agent-olivier"); err != nil {
		t.Fatalf("begin: %v", err)
	}
	if err := r.Recover(noRebuild); err != nil {
		t.Fatalf("recover: %v", err)
	}
	if now, _ := os.ReadFile(note); string(now) != "hand edit\n" {
		t.Errorf("hand edit lost: %q", now)
	}
}

func TestUndo_ANoteEditedByHandThenWrittenByTheSaveIsCopiedBeforeItIsPutBack(t *testing.T) {
	for _, withCommit := range []bool{false, true} {
		name := "no commit"
		if withCommit {
			name = "with commit"
		}
		t.Run(name, func(t *testing.T) {
			w := newWorld(t)
			r := newRepo(t, w.Mac)
			lockFor(t, r)
			note := fixtureNote(t, w.Mac, "IDEA-2026-000001")
			rel := "01_Ideas/" + filepath.Base(note)
			original, _ := os.ReadFile(note)
			base, _ := r.Head()
			writeFile(t, note, []byte("hand edit\n"))
			m, err := r.Begin("commit", "agent-olivier")
			if err != nil {
				t.Fatalf("begin: %v", err)
			}
			writeFile(t, note, []byte("written by the save over the hand edit\n"))
			st, err := r.changed(m)
			if err != nil || len(st) != 1 || st[rel] == "" {
				t.Fatalf("a note the save wrote over must be listed: (%v, %v)", st, err)
			}
			if withCommit {
				if err := r.Commit([]string{rel}, "agent-olivier", "vault: commit", ""); err != nil {
					t.Fatalf("commit: %v", err)
				}
			}
			if err := r.Undo(m, []string{rel}, noRebuild); err != nil {
				t.Fatalf("undo: %v", err)
			}
			if now, _ := os.ReadFile(note); string(now) != string(original) {
				t.Errorf("note not put back")
			}
			if head, _ := r.Head(); head != base {
				t.Errorf("head %s, want %s", head, base)
			}
			// Begin kept the hand text; the undo kept what the save wrote over it.
			got := copiesOf(t, w.Mac, "mac-test", rel)
			sort.Strings(got)
			if len(got) != 2 || got[0] != "hand edit\n" || got[1] != "written by the save over the hand edit\n" {
				t.Errorf("copies kept = %q", got)
			}
			if n := reportLines(t, w.Mac, "mac-test"); n != 2 {
				t.Errorf("expected two report lines, got %d", n)
			}
		})
	}
}

func TestRecover_AMarkerWrittenBeforeDirtyBeforeExistedStillLoadsAndBehavesAsBefore(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	base, _ := r.Head()
	old := `{"op":"commit","actor":"agent-olivier","place":"mac-test","pid":1,"started_at":"2026-10-10T00:00:00Z","base":"` + base + `","untracked_before":[]}`
	writeFile(t, filepath.Join(w.Mac, "_meta", "guards", "save-in-progress.json"), []byte(old))
	m, err := r.readMarker()
	if err != nil || m == nil || m.DirtyBefore != nil {
		t.Fatalf("old marker should load with a nil DirtyBefore: (%+v, %v)", m, err)
	}
	// A tracked note edited by hand: undo reads DirtyBefore (nil here) for it.
	note := fixtureNote(t, w.Mac, "IDEA-2026-000001")
	noteRel := "01_Ideas/" + filepath.Base(note)
	original, _ := os.ReadFile(note)
	writeFile(t, note, []byte("hand edit\n"))
	stray := filepath.Join(w.Mac, "01_Ideas", "stray.md")
	writeFile(t, stray, []byte("stray\n"))
	if err := r.Recover(noRebuild); err != nil {
		t.Fatalf("recover: %v", err)
	}
	if now, _ := os.ReadFile(note); string(now) != string(original) {
		t.Errorf("tracked note not put back")
	}
	if got := quarantined(t, w.Mac, "mac-test", noteRel); string(got) != "hand edit\n" {
		t.Errorf("hand edit not kept: %q", got)
	}
	if got := quarantined(t, w.Mac, "mac-test", "01_Ideas/stray.md"); string(got) != "stray\n" {
		t.Errorf("stray file not set aside: %q", got)
	}
	if r.hasMarker() {
		t.Errorf("marker should be cleared")
	}
}

// copiesOf returns the text of every copy of rel kept under _quarantine/<place>/.
func copiesOf(t *testing.T, root, place, rel string) []string {
	t.Helper()
	stamps, _ := os.ReadDir(filepath.Join(root, "_quarantine", place))
	var out []string
	for _, s := range stamps {
		if data, err := os.ReadFile(filepath.Join(root, "_quarantine", place, s.Name(), filepath.FromSlash(rel))); err == nil {
			out = append(out, string(data))
		}
	}
	return out
}

func TestBegin_CopiesAHandEditedNoteBeforeTheSaveCanOverwriteIt(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	note := fixtureNote(t, w.Mac, "IDEA-2026-000001")
	rel := "01_Ideas/" + filepath.Base(note)
	writeFile(t, note, []byte("the person's original text\n"))
	m, err := r.Begin("commit", "agent-olivier")
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	writeFile(t, note, []byte("written by the save over it\n"))
	if err := r.Undo(m, []string{rel}, noRebuild); err != nil {
		t.Fatalf("undo: %v", err)
	}
	found := false
	for _, c := range copiesOf(t, w.Mac, "mac-test", rel) {
		found = found || c == "the person's original text\n"
	}
	if !found {
		t.Errorf("the person's original text is not in quarantine: %q", copiesOf(t, w.Mac, "mac-test", rel))
	}
}

func TestBegin_FailsWithNoMarkerWhenTheCopyCannotBeKept(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	note := fixtureNote(t, w.Mac, "IDEA-2026-000001")
	writeFile(t, note, []byte("hand edit\n"))
	writeFile(t, filepath.Join(w.Mac, "_quarantine"), []byte("a file where the folder should be\n"))
	if _, err := r.Begin("commit", "agent-olivier"); err == nil {
		t.Fatalf("begin must fail when the hand edit cannot be copied")
	}
	if r.hasMarker() {
		t.Errorf("no marker may be left behind")
	}
}

func TestBegin_TwoSavesOverTheSameUnchangedHandEditKeepOneCopyAndDoNotFail(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	note := fixtureNote(t, w.Mac, "IDEA-2026-000001")
	rel := "01_Ideas/" + filepath.Base(note)
	writeFile(t, note, []byte("hand edit\n"))
	for i := 0; i < 2; i++ {
		if _, err := r.Begin("commit", "agent-olivier"); err != nil {
			t.Fatalf("begin %d: %v", i, err)
		}
		if err := r.End(); err != nil {
			t.Fatalf("end: %v", err)
		}
	}
	if err := r.Recover(noRebuild); err != nil { // the no-marker pass copies it once more
		t.Fatalf("recover: %v", err)
	}
	if c := copiesOf(t, w.Mac, "mac-test", rel); len(c) != 1 || c[0] != "hand edit\n" {
		t.Errorf("want exactly one copy of the hand edit, got %q", c)
	}
}

// A failed lookup of the committed version is not "the file is not in the
// commit": nothing is removed and the marker stays for the next lock-taker.
func TestUndo_AFailedBlobLookupRemovesNothingAndKeepsTheMarker(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	m, err := r.Begin("commit", "agent-olivier")
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	p := filepath.Join(w.Mac, "01_Ideas", "new.md")
	writeFile(t, p, []byte("what the save wrote\n"))
	if err := r.Commit([]string{"01_Ideas/new.md"}, "agent-olivier", "vault: commit", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	writeFile(t, p, []byte("a person rewrote this\n")) // so a wrong "absent" answer would delete a person's text
	r.gate = func(args []string) error {
		for _, a := range args {
			if a == "ls-tree" {
				return errors.New("git was killed")
			}
		}
		return nil
	}
	if err := r.Undo(m, []string{"01_Ideas/new.md"}, noRebuild); err == nil {
		t.Fatalf("undo must report the failed lookup")
	}
	if got, err := os.ReadFile(p); err != nil || string(got) != "a person rewrote this\n" {
		t.Fatalf("file must stay as it is: (%q, %v)", got, err)
	}
	if !r.hasMarker() {
		t.Fatalf("marker must stay")
	}
	// As in production, the next lock-taker settles it with Recover (never a
	// second direct Undo): the person's text goes to quarantine intact.
	r.gate = nil
	if err := r.Recover(noRebuild); err != nil {
		t.Fatalf("recover after the lookup works: %v", err)
	}
	if _, err := os.Stat(p); !os.IsNotExist(err) {
		t.Fatalf("file should have been moved aside by recovery")
	}
	if got := quarantined(t, w.Mac, "mac-test", "01_Ideas/new.md"); string(got) != "a person rewrote this\n" {
		t.Fatalf("rewritten text not kept byte for byte in quarantine: %q", got)
	}
	if r.hasMarker() {
		t.Fatalf("marker should be cleared after recovery")
	}
}

// A clear "not in that commit" answer still lets the undo remove a file.
func TestUndo_AListedFileNotInTheCommitIsStillRemoved(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	m, err := r.Begin("commit", "agent-olivier")
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	committed := filepath.Join(w.Mac, "01_Ideas", "committed.md")
	writeFile(t, committed, []byte("committed\n"))
	if err := r.Commit([]string{"01_Ideas/committed.md"}, "agent-olivier", "vault: commit", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	other := filepath.Join(w.Mac, "01_Ideas", "written-not-committed.md")
	writeFile(t, other, []byte("written, not committed\n"))
	if err := r.Undo(m, []string{"01_Ideas/committed.md", "01_Ideas/written-not-committed.md"}, noRebuild); err != nil {
		t.Fatalf("undo: %v", err)
	}
	for _, f := range []string{committed, other} {
		if _, err := os.Stat(f); !os.IsNotExist(err) {
			t.Errorf("%s should have been removed", f)
		}
	}
}

// A first Undo that failed after it had moved the folder back has lost its
// proof: the save's own commit is no longer there to compare with. A second
// direct Undo must therefore not trust the list. A note and a new file that a
// person rewrote in between go to quarantine; nothing is deleted or put back
// without a copy. It makes no difference whether the caller still holds the
// marker or reads it from disk again.
func TestUndo_CalledAgainAfterAFailedUndoKeepsACopyOfEverything(t *testing.T) {
	undoAfterFailedPass(t, func(r *Repo, m *Marker, list []string) error {
		return r.Undo(m, list, noRebuild)
	})
}

// The same hole through Recover: a Recover that failed after it had moved the
// folder back also lost the save's commit. A direct Undo afterwards must not
// trust the list and delete a file a person rewrote in between.
func TestUndo_CalledAfterAFailedRecoverKeepsACopyOfEverything(t *testing.T) {
	undoAfterFailedPass(t, func(r *Repo, _ *Marker, _ []string) error {
		return r.Recover(noRebuild)
	})
}

// undoAfterFailedPass runs firstPass with the commit lookup (ls-tree) killed
// after the folder was moved back, then calls Undo again, with the caller's
// marker and with the marker read from disk, and checks that everything a
// person rewrote in between was kept in quarantine.
func undoAfterFailedPass(t *testing.T, firstPass func(r *Repo, m *Marker, list []string) error) {
	for name, reread := range map[string]bool{"same marker": false, "marker read from disk again": true} {
		t.Run(name, func(t *testing.T) {
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
			fresh := filepath.Join(w.Mac, "01_Ideas", "new.md")
			writeFile(t, note, []byte("what the save wrote into the note\n"))
			writeFile(t, fresh, []byte("what the save wrote\n"))
			list := []string{noteRel, "01_Ideas/new.md"}
			if err := r.Commit(list, "agent-olivier", "vault: commit", ""); err != nil {
				t.Fatalf("commit: %v", err)
			}
			writeFile(t, note, []byte("a person rewrote the note\n"))
			writeFile(t, fresh, []byte("a person rewrote this\n"))
			r.gate = func(args []string) error {
				for _, a := range args {
					if a == "ls-tree" {
						return errors.New("git was killed")
					}
				}
				return nil
			}
			if err := firstPass(r, m, list); err == nil {
				t.Fatalf("the first pass must report the failed lookup")
			}
			r.gate = nil
			if reread {
				if m, err = r.readMarker(); err != nil || m == nil {
					t.Fatalf("marker must still be on disk: (%v, %v)", m, err)
				}
			}
			if err := r.Undo(m, list, noRebuild); err != nil {
				t.Fatalf("second undo: %v", err)
			}
			if now, _ := os.ReadFile(note); string(now) != string(original) {
				t.Errorf("the note should be back at the shared version, got %q", now)
			}
			if _, err := os.Stat(fresh); !os.IsNotExist(err) {
				t.Errorf("the new file should have been moved aside")
			}
			if got := quarantined(t, w.Mac, "mac-test", noteRel); string(got) != "a person rewrote the note\n" {
				t.Errorf("rewritten note not kept byte for byte: %q", got)
			}
			if got := quarantined(t, w.Mac, "mac-test", "01_Ideas/new.md"); string(got) != "a person rewrote this\n" {
				t.Errorf("rewritten file not kept byte for byte: %q", got)
			}
		})
	}
}

func TestWriteFileAtomic_LeavesNoTempFileWhenTheRenameFails(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "taken")
	writeFile(t, filepath.Join(target, "inside.txt"), []byte("x")) // a non-empty folder: the rename cannot replace it
	if err := writeFileAtomic(target, []byte("new")); err == nil {
		t.Fatalf("writing over a non-empty folder should fail")
	}
	if _, err := os.Stat(target + ".tmp"); !os.IsNotExist(err) {
		t.Fatalf("the temp file was left behind: %v", err)
	}
}

// A Recover that succeeds settles the save and removes the marker. An Undo
// that still holds the old marker and list must then refuse: with no record on
// disk nothing proves the list, and a listed file may be a person's by now.
func TestUndo_RefusesWhenTheMarkerFileIsGone(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	m, err := r.Begin("commit", "agent-olivier")
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	if err := r.Recover(noRebuild); err != nil {
		t.Fatalf("recover: %v", err)
	}
	if r.hasMarker() {
		t.Fatalf("a successful recover must remove the marker")
	}
	p := filepath.Join(w.Mac, "01_Ideas", "new.md")
	writeFile(t, p, []byte("typed by a person after the save was settled\n"))
	err = r.Undo(m, []string{"01_Ideas/new.md"}, noRebuild)
	if err == nil || !strings.Contains(err.Error(), "nothing was changed") {
		t.Fatalf("undo with no marker on disk must refuse and say nothing was changed, got %v", err)
	}
	if got, rerr := os.ReadFile(p); rerr != nil || string(got) != "typed by a person after the save was settled\n" {
		t.Fatalf("the listed file must stay as it is: (%q, %v)", got, rerr)
	}
	if r.hasMarker() || m.UndoStarted {
		t.Fatalf("a refused undo must not write a marker (on disk %v, in memory %v)", r.hasMarker(), m.UndoStarted)
	}
}

// A marker on disk that belongs to another save is not this save's record:
// Undo refuses whichever field differs, and changes nothing.
func TestUndo_RefusesAMarkerThatBelongsToAnotherSave(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	lockFor(t, r)
	m, err := r.Begin("commit", "agent-olivier")
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	p := filepath.Join(w.Mac, "01_Ideas", "new.md")
	writeFile(t, p, []byte("written by the save that owns the marker\n"))
	for name, change := range map[string]func(*Marker){
		"other operation":  func(o *Marker) { o.Op = "update" },
		"other actor":      func(o *Marker) { o.Actor = "agent-bestie" },
		"other base":       func(o *Marker) { o.Base = strings.Repeat("1", 40) },
		"other start time": func(o *Marker) { o.StartedAt = "2000-01-01T00:00:00Z" },
		"other process":    func(o *Marker) { o.PID++ },
	} {
		t.Run(name, func(t *testing.T) {
			other := *m
			change(&other)
			err := r.Undo(&other, []string{"01_Ideas/new.md"}, noRebuild)
			if err == nil || !strings.Contains(err.Error(), "is not the one given to undo") || !strings.Contains(err.Error(), "nothing was changed") {
				t.Fatalf("undo with another save's marker must refuse, got %v", err)
			}
			if got, rerr := os.ReadFile(p); rerr != nil || string(got) != "written by the save that owns the marker\n" {
				t.Fatalf("the listed file must stay as it is: (%q, %v)", got, rerr)
			}
			disk, derr := r.readMarker()
			if derr != nil || disk == nil || disk.UndoStarted || other.UndoStarted {
				t.Fatalf("a refused undo must not record a start: on disk (%+v, %v), in memory %v", disk, derr, other.UndoStarted)
			}
		})
	}
}
