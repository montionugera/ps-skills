package vaultsync

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"obsidian-vault-engine/pkg/vault"
)

func newDaemon(t *testing.T, root string) *Daemon {
	t.Helper()
	cfg, err := LoadConfig(root)
	if err != nil || cfg == nil {
		t.Fatalf("sync config: (%v, %v)", cfg, err)
	}
	d := NewDaemon(vault.NewVaultEngine(root), cfg)
	d.Log = io.Discard
	return d
}

// quietDrop writes an inbox file that has been untouched for longer than the quiet period.
func quietDrop(t *testing.T, root, rel string, data []byte) string {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(rel))
	writeFile(t, path, data)
	old := time.Now().Add(-time.Minute)
	if err := os.Chtimes(path, old, old); err != nil {
		t.Fatalf("chtimes: %v", err)
	}
	return path
}

func TestDaemon_BringsIncomingChangeAndRebuildsTheIndex(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	if _, out := mac.Save(commitOp(mac, note1, readSHA(t, w.Mac, note1), 5)); out.Exit != 0 {
		t.Fatalf("mac save: %+v", out)
	}
	srv := newDaemon(t, w.Srv)
	if err := srv.Tick(); err != nil {
		t.Fatalf("tick: %v", err)
	}
	want := readSHA(t, w.Mac, note1)
	if got := readSHA(t, w.Srv, note1); got != want {
		t.Fatalf("srv note fingerprint %s, want %s", got, want)
	}
	index, _ := os.ReadFile(filepath.Join(w.Srv, "_meta", "indexes", "ideas.jsonl"))
	if !strings.Contains(string(index), want) {
		t.Fatalf("srv index does not carry the new fingerprint:\n%s", index)
	}
	if err := srv.Tick(); err != nil { // nothing new: a pass costs one small request
		t.Fatalf("idle tick: %v", err)
	}
}

// Spec tests 9 (second half) and 14 (second half).
func TestDaemon_SendsQuietInboxDropsAndQuarantinesOversizedOnes(t *testing.T) {
	w := newWorld(t)
	quietDrop(t, w.Mac, "_inbox/human/hello.md", []byte("exactly these bytes\n"))
	quietDrop(t, w.Mac, "_inbox/agent/agent-olivier/mac-test-big.md", make([]byte, 5<<20))
	fresh := filepath.Join(w.Mac, "_inbox", "human", "still-being-written.md")
	writeFile(t, fresh, []byte("half\n"))
	soon := time.Now().Add(time.Minute) // "modified just now" for the whole test, however slow the machine
	if err := os.Chtimes(fresh, soon, soon); err != nil {
		t.Fatalf("chtimes: %v", err)
	}

	mac := newDaemon(t, w.Mac)
	// One pass sends the good drop, moves the oversized one aside and reports it.
	if err := mac.Tick(); err == nil || !strings.Contains(err.Error(), "max_file_bytes=1048576") {
		t.Fatalf("mac tick should report the oversized drop, got %v", err)
	}
	if err := newDaemon(t, w.Srv).Tick(); err != nil {
		t.Fatalf("srv tick: %v", err)
	}
	if got, _ := os.ReadFile(filepath.Join(w.Srv, "_inbox", "human", "hello.md")); string(got) != "exactly these bytes\n" {
		t.Fatalf("drop should arrive as it is, got %q", got)
	}
	moved, _ := filepath.Glob(filepath.Join(w.Mac, "_quarantine", "mac-test", "*", "_inbox", "agent", "agent-olivier", "mac-test-big.md"))
	if len(moved) != 1 {
		t.Fatalf("oversized drop should be in _quarantine/mac-test/, found %v", moved)
	}
	if _, err := os.Stat(filepath.Join(w.Srv, "_inbox", "agent", "agent-olivier", "mac-test-big.md")); !os.IsNotExist(err) {
		t.Fatalf("oversized drop must not reach the other place")
	}
	if st := mustGit(t, w.Mac, "status", "--porcelain"); st != "?? _inbox/human/still-being-written.md" {
		t.Fatalf("the file still being written must wait:\n%s", st)
	}
}

// Spec test 14, first half.
func TestDaemon_HandEditIsSetAsideAndNotSent(t *testing.T) {
	w := newWorld(t)
	note := fixtureNote(t, w.Mac, note1)
	original, _ := os.ReadFile(note)
	writeFile(t, note, []byte("typed straight into the file\n"))
	hubBefore := mustGit(t, w.Hub, "rev-parse", "refs/heads/main")
	if err := newDaemon(t, w.Mac).Tick(); err != nil {
		t.Fatalf("tick: %v", err)
	}
	if now, _ := os.ReadFile(note); string(now) != string(original) {
		t.Fatalf("note not put back")
	}
	if hub := mustGit(t, w.Hub, "rev-parse", "refs/heads/main"); hub != hubBefore {
		t.Fatalf("a hand edit must never be sent")
	}
	report, _ := os.ReadFile(filepath.Join(w.Mac, "_quarantine", "mac-test", "REPORT.log"))
	if !strings.Contains(string(report), "QUARANTINED 01_Ideas/") {
		t.Fatalf("no report line:\n%s", report)
	}
}

// Spec test 14: a file created by hand outside an inbox.
func TestDaemon_StrayFileOutsideTheInboxIsQuarantinedAndNotSent(t *testing.T) {
	w := newWorld(t)
	stray := quietDrop(t, w.Mac, "01_Ideas/made-by-hand.md", []byte("typed straight into a new file\n"))
	fresh := filepath.Join(w.Mac, "02_Projects", "still-being-written.md")
	writeFile(t, fresh, []byte("half\n"))
	soon := time.Now().Add(time.Minute) // "modified just now" for the whole test
	if err := os.Chtimes(fresh, soon, soon); err != nil {
		t.Fatalf("chtimes: %v", err)
	}
	hubBefore := mustGit(t, w.Hub, "rev-parse", "refs/heads/main")
	if err := newDaemon(t, w.Mac).Tick(); err != nil {
		t.Fatalf("tick: %v", err)
	}
	if _, err := os.Stat(stray); !os.IsNotExist(err) {
		t.Fatalf("the stray file should have been moved out of 01_Ideas/")
	}
	if got := quarantined(t, w.Mac, "mac-test", "01_Ideas/made-by-hand.md"); string(got) != "typed straight into a new file\n" {
		t.Fatalf("quarantined bytes differ: %q", got)
	}
	if hub := mustGit(t, w.Hub, "rev-parse", "refs/heads/main"); hub != hubBefore {
		t.Fatalf("a stray file must never be sent")
	}
	report, _ := os.ReadFile(filepath.Join(w.Mac, "_quarantine", "mac-test", "REPORT.log"))
	if !strings.Contains(string(report), "QUARANTINED 01_Ideas/made-by-hand.md") {
		t.Fatalf("no report line:\n%s", report)
	}
	if st := mustGit(t, w.Mac, "status", "--porcelain"); st != "?? 02_Projects/still-being-written.md" {
		t.Fatalf("the file still being written must wait:\n%s", st)
	}
}

// Spec test 17.
func TestDaemon_DropSurvivesAKillAndARefusedSend(t *testing.T) {
	w := newWorld(t)
	drop := quietDrop(t, w.Mac, "_inbox/agent/agent-olivier/mac-test-keep.md", []byte("keep me\n"))
	mac := newDaemon(t, w.Mac)

	// 1. The program dies after recording the drop locally, before sending.
	mac.S.Hooks.BeforePush = func(int) { panic("simulated kill") }
	func() {
		defer func() { _ = recover() }()
		_ = mac.Tick()
	}()
	mac.S.Hooks = Hooks{}
	if !mac.S.Repo.hasMarker() {
		t.Fatalf("expected a marker after the kill")
	}

	// 2. The next send is refused by the hub (allowance used up).
	settings := filepath.Join(w.Hub, "hooks", "vault-limits.json")
	original, _ := os.ReadFile(settings)
	tight := strings.Replace(string(original), `"daily_bytes_per_place": 52428800`, `"daily_bytes_per_place": 1`, 1)
	if err := os.WriteFile(settings, []byte(tight), 0644); err != nil {
		t.Fatalf("write settings: %v", err)
	}
	if err := mac.Tick(); err == nil || !strings.Contains(err.Error(), "daily_bytes_per_place=1") {
		t.Fatalf("expected the refusal to be reported, got %v", err)
	}
	if text, err := os.ReadFile(drop); err != nil || string(text) != "keep me\n" {
		t.Fatalf("the drop must still be on disk: (%q, %v)", text, err)
	}
	if st := mustGit(t, w.Mac, "status", "--porcelain"); st != "?? _inbox/agent/agent-olivier/mac-test-keep.md" {
		t.Fatalf("the drop should be an ordinary unsent file again:\n%s", st)
	}

	// 3. Next try with the limit restored: it arrives.
	if err := os.WriteFile(settings, original, 0644); err != nil {
		t.Fatalf("restore settings: %v", err)
	}
	if err := mac.Tick(); err != nil {
		t.Fatalf("tick: %v", err)
	}
	if text := mustGit(t, w.Hub, "show", "refs/heads/main:_inbox/agent/agent-olivier/mac-test-keep.md"); text != "keep me" {
		t.Fatalf("drop not on the hub: %q", text)
	}
}

func TestDaemon_OnlyOneRunsPerPlace(t *testing.T) {
	w := newWorld(t)
	// Another daemon of this place holds the guard. It is taken here directly,
	// so the test depends on no timing.
	guardsDir := filepath.Join(w.Mac, "_meta", "guards")
	if err := os.MkdirAll(guardsDir, 0755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	guard, err := os.OpenFile(filepath.Join(guardsDir, "sync-daemon.guard"), os.O_CREATE|os.O_RDWR, 0644)
	if err != nil {
		t.Fatalf("open guard: %v", err)
	}
	defer guard.Close()
	if err := syscall.Flock(int(guard.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		t.Fatalf("take guard: %v", err)
	}
	// A time limit: a daemon that wrongly starts is stopped and fails the test, instead of running forever.
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := newDaemon(t, w.Mac).Run(ctx); err == nil || !strings.Contains(err.Error(), "already running") {
		t.Fatalf("expected the second daemon to refuse, got %v", err)
	}
}

func TestDaemon_RunStopsCleanlyOnCancelAndFollowsTheHub(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	srv := newDaemon(t, w.Srv)
	srv.S.Cfg.PollIntervalMS = 50
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- srv.Run(ctx) }()

	if _, out := mac.Save(commitOp(mac, note1, readSHA(t, w.Mac, note1), 5)); out.Exit != 0 {
		cancel()
		t.Fatalf("mac save: %+v", out)
	}
	want := readSHA(t, w.Mac, note1)
	deadline := time.Now().Add(20 * time.Second)
	for readSHA(t, w.Srv, note1) != want {
		if time.Now().After(deadline) {
			cancel()
			<-done
			t.Fatalf("running daemon never brought the change")
		}
		time.Sleep(20 * time.Millisecond)
	}
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Run after cancel: %v", err)
		}
	case <-time.After(20 * time.Second):
		t.Fatalf("Run did not return after cancel")
	}
	// Run has returned: the folder lock and the guard are free again.
	lock, err := AcquireFolderLock(w.Srv, time.Second)
	if err != nil {
		t.Fatalf("folder lock still held after stop: %v", err)
	}
	lock.Release()
	ctx2, cancel2 := context.WithCancel(context.Background())
	cancel2()
	if err := newDaemon(t, w.Srv).Run(ctx2); err != nil {
		t.Fatalf("guard still held after stop: %v", err)
	}
}

// A hub that moves between the first look and the send must not lose or
// duplicate a drop: the daemon updates and sends again.
func TestDaemon_DropIsSentAfterARace(t *testing.T) {
	w := newWorld(t)
	quietDrop(t, w.Mac, "_inbox/human/raced.md", []byte("raced\n"))
	srv := newSyncer(t, w.Srv)
	mac := newDaemon(t, w.Mac)
	mac.S.Hooks.BeforePush = func(attempt int) {
		if attempt == 1 {
			if _, out := srv.Save(commitOp(srv, note2, readSHA(t, w.Srv, note2), 4)); out.Exit != 0 {
				t.Errorf("srv save: %+v", out)
			}
		}
	}
	if err := mac.Tick(); err != nil {
		t.Fatalf("tick: %v", err)
	}
	if text := mustGit(t, w.Hub, "show", "refs/heads/main:_inbox/human/raced.md"); text != "raced" {
		t.Fatalf("drop not on the hub: %q", text)
	}
	if readSHA(t, w.Mac, note2) != readSHA(t, w.Srv, note2) {
		t.Fatalf("the race did not happen or the daemon did not catch up")
	}
}
