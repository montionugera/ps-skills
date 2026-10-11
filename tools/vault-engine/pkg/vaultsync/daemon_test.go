package vaultsync

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
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

	// 3. Next try with the limit restored: it arrives once the short wait is over.
	for mac.skip > 0 {
		_ = mac.Tick()
	}
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

// signalWriter reports each log line on a channel, so a test waits on the
// daemon's own words instead of sleeping.
type signalWriter struct {
	lines chan string
}

func (w *signalWriter) Write(p []byte) (int, error) {
	select {
	case w.lines <- string(p):
	default:
	}
	return len(p), nil
}

func TestDaemon_RunStopsCleanlyOnCancelAndFollowsTheHub(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	srv := newDaemon(t, w.Srv)
	sw := &signalWriter{lines: make(chan string, 64)}
	srv.Log = sw
	srv.S.Cfg.PollIntervalMS = 50
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- srv.Run(ctx) }()
	stopped := false
	stop := func() error { // idempotent: every path ends with Run returned
		if !stopped {
			stopped = true
			cancel()
			select {
			case err := <-done:
				return err
			case <-time.After(30 * time.Second):
				return fmt.Errorf("Run did not return after cancel")
			}
		}
		return nil
	}
	t.Cleanup(func() { _ = stop() })

	if _, out := mac.Save(commitOp(mac, note1, readSHA(t, w.Mac, note1), 5)); out.Exit != 0 {
		t.Fatalf("mac save: %+v", out)
	}
	want := readSHA(t, w.Mac, note1)
	timeout := time.After(30 * time.Second)
wait:
	for {
		select {
		case line := <-sw.lines:
			if strings.Contains(line, "updated to the newest version") {
				break wait
			}
		case <-timeout:
			t.Fatalf("running daemon never reported the update")
		}
	}
	if err := stop(); err != nil {
		t.Fatalf("Run after cancel: %v", err)
	}
	if got := readSHA(t, w.Srv, note1); got != want {
		t.Fatalf("srv note fingerprint %s, want %s", got, want)
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

// tightHub makes the hub refuse every send (allowance of 1 byte) and returns a
// function that restores the original limits.
func tightHub(t *testing.T, hub string) (restore func()) {
	t.Helper()
	settings := filepath.Join(hub, "hooks", "vault-limits.json")
	original, _ := os.ReadFile(settings)
	tight := strings.Replace(string(original), `"daily_bytes_per_place": 52428800`, `"daily_bytes_per_place": 1`, 1)
	if tight == string(original) {
		t.Fatalf("settings not changed")
	}
	if err := os.WriteFile(settings, []byte(tight), 0644); err != nil {
		t.Fatalf("write settings: %v", err)
	}
	return func() {
		if err := os.WriteFile(settings, original, 0644); err != nil {
			t.Fatalf("restore settings: %v", err)
		}
	}
}

func TestDaemon_BacksOffAfterARefusedSendButKeepsUpdating(t *testing.T) {
	w := newWorld(t)
	quietDrop(t, w.Mac, "_inbox/agent/agent-olivier/mac-test-refused.md", []byte("refused\n"))
	restore := tightHub(t, w.Hub)
	mac := newDaemon(t, w.Mac)
	log := &bytes.Buffer{}
	mac.Log = log
	attempts := 0
	mac.S.Hooks.BeforePush = func(int) { attempts++ }

	// Waits of 1, 2, 4, 8 passes: sends on passes 0, 2, 5, 10, 19; passes 6-9
	// are certainly waiting ones.
	const passes = 20
	stray := filepath.Join(w.Mac, "01_Ideas", "stray-in-wait.md")
	for i := 0; i < passes; i++ {
		if i == 7 || i == 8 {
			if mac.skip == 0 {
				t.Fatalf("pass %d should be a waiting pass", i)
			}
		}
		if i == 7 { // someone else saves while the daemon waits to send
			restore()
			srv := newSyncer(t, w.Srv)
			if _, out := srv.Save(commitOp(srv, note2, readSHA(t, w.Srv, note2), 4)); out.Exit != 0 {
				t.Fatalf("srv save: %+v", out)
			}
			restore = tightHub(t, w.Hub)
		}
		if i == 8 {
			quietDrop(t, w.Mac, "01_Ideas/stray-in-wait.md", []byte("made by hand\n"))
		}
		err := mac.Tick()
		if i == 7 && readSHA(t, w.Mac, note2) != readSHA(t, w.Srv, note2) {
			t.Fatalf("pass %d (err %v): update must still run on a waiting pass", i, err)
		}
		if i == 8 {
			if _, serr := os.Stat(stray); !os.IsNotExist(serr) {
				t.Fatalf("pass %d (err %v): a stray file must be set aside on a waiting pass", i, err)
			}
			if got := quarantined(t, w.Mac, "mac-test", "01_Ideas/stray-in-wait.md"); string(got) != "made by hand\n" {
				t.Fatalf("quarantined bytes differ: %q", got)
			}
		}
	}
	if attempts < 3 || attempts > 6 {
		t.Fatalf("%d send attempts in %d passes; the wait should grow", attempts, passes)
	}
	if n := strings.Count(log.String(), "waiting"); n > attempts {
		t.Fatalf("more wait lines (%d) than refusals (%d):\n%s", n, attempts, log)
	}

	// An accepted send resets the wait: a new drop goes out on the very next pass.
	restore()
	for i := 0; i < 100 && mac.skip > 0; i++ {
		_ = mac.Tick()
	}
	if err := mac.Tick(); err != nil {
		t.Fatalf("tick after the wait: %v", err)
	}
	if mac.skip != 0 || mac.refusals != 0 {
		t.Fatalf("wait not reset: skip=%d refusals=%d", mac.skip, mac.refusals)
	}
	quietDrop(t, w.Mac, "_inbox/human/after-reset.md", []byte("after\n"))
	if err := mac.Tick(); err != nil {
		t.Fatalf("tick: %v", err)
	}
	if text := mustGit(t, w.Hub, "show", "refs/heads/main:_inbox/human/after-reset.md"); text != "after" {
		t.Fatalf("drop not on the hub right after the reset: %q", text)
	}
}

// A signal that stops a git command must end the daemon quietly (exit 0), not
// with 128+signal as for the other commands.
func TestDaemon_StopSignalDuringGitIsAQuietStop(t *testing.T) {
	w := newWorld(t)
	quietDrop(t, w.Mac, "_inbox/human/hi.md", []byte("hi\n"))
	mac := newDaemon(t, w.Mac)
	mac.S.Cfg.PollIntervalMS = 50
	var once sync.Once
	mac.S.Hooks.BeforePush = func(int) { once.Do(func() { exitOnSignal(143) }) }
	done := make(chan error, 1)
	go func() { done <- mac.Run(context.Background()) }()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
	case <-time.After(30 * time.Second):
		t.Fatalf("Run did not stop")
	}
}

// Through the real program: SIGTERM while running always exits 0.
func TestDaemon_CLIExitsZeroOnSigterm(t *testing.T) {
	w := newWorld(t)
	cmd := exec.Command(engineBin, "sync-daemon")
	cmd.Dir = w.Srv
	for _, kv := range os.Environ() {
		if !strings.HasPrefix(kv, "VAULT_ROOT=") && !strings.HasPrefix(kv, "VAULT_PLACE=") {
			cmd.Env = append(cmd.Env, kv)
		}
	}
	cmd.Env = append(cmd.Env, "VAULT_ROOT="+w.Srv)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	waited := false
	t.Cleanup(func() {
		if !waited {
			_ = cmd.Process.Kill()
			_ = cmd.Wait()
		}
	})
	if _, err := bufio.NewReader(stdout).ReadString('\n'); err != nil { // "Starting vault sync ..."
		t.Fatalf("no start line: %v", err)
	}
	if err := cmd.Process.Signal(syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	waited = true
	if err := cmd.Wait(); err != nil {
		t.Fatalf("daemon should exit 0 on SIGTERM: %v", err)
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

// A stop signal that lands on the push ends the pass at once: no further git
// command is started, nothing is reported as refused, Run returns nil.
func TestDaemon_StopSignalDuringPushStartsNoFurtherGitCommand(t *testing.T) {
	w := newWorld(t)
	quietDrop(t, w.Mac, "_inbox/human/hi.md", []byte("hi\n"))
	mac := newDaemon(t, w.Mac)
	mac.S.Cfg.PollIntervalMS = 50
	log := &bytes.Buffer{}
	mac.Log = log
	// Everything below runs on Run's own goroutine, so no lock is needed.
	signalled := false
	var after []string
	mac.S.Repo.gate = func(args []string) error {
		if signalled {
			after = append(after, strings.Join(args, " "))
		}
		return nil
	}
	mac.S.Hooks.PushResult = func(_ int, res gitResult) gitResult {
		// The signal lands while the push runs: the handler fires, the push ends in error.
		signalled = true
		exitOnSignal(143)
		return gitResult{Err: errors.New("interrupted by terminated")}
	}
	done := make(chan error, 1)
	go func() { done <- mac.Run(context.Background()) }()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
	case <-time.After(30 * time.Second):
		t.Fatalf("Run did not stop")
	}
	if !signalled {
		t.Fatalf("the push never ran")
	}
	if len(after) != 0 {
		t.Fatalf("git commands asked for after the stop signal: %v", after)
	}
	if strings.Contains(log.String(), "refused") || strings.Contains(log.String(), "not sent") {
		t.Fatalf("a stop must not be reported as a refusal:\n%s", log)
	}
}

// runAndCancel starts Run, waits for ready, cancels, and returns how long Run
// took to return after the cancel. Run is always waited for before the test's
// folders are removed.
func runAndCancel(t *testing.T, d *Daemon, ready <-chan struct{}) time.Duration {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- d.Run(ctx) }()
	returned := false
	t.Cleanup(func() {
		cancel()
		if !returned {
			<-done
		}
	})
	select {
	case <-ready:
	case <-time.After(20 * time.Second):
		t.Fatalf("the daemon never reached the step under test")
	}
	time.Sleep(200 * time.Millisecond) // let it settle into the wait
	cancel()
	start := time.Now()
	select {
	case err := <-done:
		returned = true
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatalf("Run did not return within 3 s of the cancel")
	}
	return time.Since(start)
}

// A cancel that is not a signal (a test, a program that embeds the daemon)
// must cut a running git command short, not wait for its time limit.
func TestDaemon_CancelCutsARunningGitCommandShort(t *testing.T) {
	w := newWorld(t)
	pidFile := filepath.Join(t.TempDir(), "pid")
	script := filepath.Join(t.TempDir(), "slow.sh")
	writeFile(t, script, []byte("#!/bin/sh\necho $$ > \""+pidFile+"\"\nexec sleep 30\n"))
	if err := os.Chmod(script, 0755); err != nil {
		t.Fatalf("chmod: %v", err)
	}
	mustGit(t, w.Srv, "config", "protocol.ext.allow", "always")
	mustGit(t, w.Srv, "config", "remote.slow.url", "ext::"+script)
	srv := newDaemon(t, w.Srv)
	srv.S.Cfg.PollIntervalMS = 50
	srv.S.Repo.Remote = "slow"
	srv.S.Repo.NetTimeout = 20 * time.Second
	ready := make(chan struct{})
	go func() { // the helper writes its pid once git has started it
		for {
			if _, err := os.Stat(pidFile); err == nil {
				close(ready)
				return
			}
			time.Sleep(10 * time.Millisecond)
		}
	}()
	took := runAndCancel(t, srv, ready)
	t.Logf("Run returned %v after the cancel", took)
	raw, err := os.ReadFile(pidFile)
	if err != nil {
		t.Fatalf("pid file: %v", err)
	}
	pid, _ := strconv.Atoi(strings.TrimSpace(string(raw)))
	if waitFor(2*time.Second, func() bool { return syscall.Kill(pid, 0) != nil }); syscall.Kill(pid, 0) == nil {
		t.Fatalf("helper process %d is still running after the cancel", pid)
	}
}

// A daemon told to stop while it waits for the folder lock must not sit out
// the whole lock time limit.
func TestDaemon_CancelEndsTheWaitForTheFolderLock(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	if _, out := mac.Save(commitOp(mac, note1, readSHA(t, w.Mac, note1), 5)); out.Exit != 0 {
		t.Fatalf("mac save: %+v", out) // srv now has an update to pull, so its pass needs the lock
	}
	held, err := AcquireFolderLock(w.Srv, 0)
	if err != nil {
		t.Fatalf("lock: %v", err)
	}
	defer held.Release()
	srv := newDaemon(t, w.Srv)
	srv.S.Cfg.PollIntervalMS = 50
	srv.S.Cfg.LockTimeoutMS = 20000
	ready := make(chan struct{})
	var once sync.Once
	srv.S.Repo.gate = func(args []string) error {
		for _, a := range args {
			if a == "--show-toplevel" { // the last git command before the lock is asked for
				once.Do(func() { close(ready) })
			}
		}
		return nil
	}
	took := runAndCancel(t, srv, ready)
	t.Logf("Run returned %v after the cancel", took)
	if st := mustGit(t, w.Srv, "status", "--porcelain"); st != "" {
		t.Fatalf("a stopped wait must leave the folder as it was:\n%s", st)
	}
}
