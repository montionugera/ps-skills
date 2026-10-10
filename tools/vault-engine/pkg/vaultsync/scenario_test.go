package vaultsync

import (
	"context"
	"encoding/json"
	"fmt"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"obsidian-vault-engine/pkg/vault"
)

// newScenarioWorld is newWorld plus the first index build in both places: a
// fresh place has no index until its first save or update, and the checks
// below treat a missing index as a failure.
func newScenarioWorld(t *testing.T) world {
	t.Helper()
	w := newWorld(t)
	for _, root := range []string{w.Mac, w.Srv} {
		if _, errOut, code := engineCLI(root, "rebuild-index"); code != 0 {
			t.Fatalf("first index build in %s: %s", root, errOut)
		}
	}
	return w
}

func rounds(full, short int) int {
	if os.Getenv("VAULT_SYNC_ROUNDS") == "full" {
		return full
	}
	return short
}

// both runs one function per place at the same moment and returns the exit codes (mac, srv).
func both(w world, f func(root string) int) [2]int {
	var codes [2]int
	var wg sync.WaitGroup
	for i, root := range []string{w.Mac, w.Srv} {
		wg.Add(1)
		go func(i int, root string) {
			defer wg.Done()
			codes[i] = f(root)
		}(i, root)
	}
	wg.Wait()
	return codes
}

// wholeFolder reports the first way in which a folder is not whole: a changed
// tracked file, a missing or unreadable index, an index that lists a different
// set of notes than the folder holds, or an entry whose fingerprint is not the
// file's.
func wholeFolder(root string) string {
	out, err := exec.Command("git", "-C", root, "status", "--porcelain", "--untracked-files=no").Output()
	if err != nil || strings.TrimSpace(string(out)) != "" {
		return fmt.Sprintf("tracked files differ from the recorded version (%v):\n%s", err, out)
	}
	e := vault.NewVaultEngine(root)
	data, err := os.ReadFile(filepath.Join(root, "_meta", "indexes", "ideas.jsonl"))
	if err != nil {
		return fmt.Sprintf("the index cannot be read: %v", err)
	}
	indexed := map[string]bool{}
	for _, line := range strings.Split(strings.TrimSpace(string(data)), "\n") {
		if line == "" {
			continue
		}
		var entry vault.IndexEntry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			return "unreadable index line: " + line
		}
		indexed[filepath.ToSlash(entry.Path)] = true
		if sha, _ := e.ComputeSHA256(filepath.Join(root, entry.Path)); sha != entry.SHA256 {
			return fmt.Sprintf("index says %s for %s, file is %s", entry.SHA256, entry.Path, sha)
		}
	}
	notes, _ := filepath.Glob(filepath.Join(root, "01_Ideas", "IDEA-*.md"))
	if len(notes) == 0 {
		return "the folder holds no notes at all"
	}
	for _, n := range notes {
		rel, _ := filepath.Rel(root, n)
		if !indexed[filepath.ToSlash(rel)] {
			return "note missing from the index: " + rel
		}
		delete(indexed, filepath.ToSlash(rel))
	}
	for rel := range indexed {
		return "index lists a note that is not in the folder: " + rel
	}
	return ""
}

// converge is the check the spec demands after every scenario: both copies
// identical to the shared copy, clean, valid and healthy. It never rebuilds
// the indexes itself, so a stale index left by a save, an update or a recovery
// fails the scenario.
func converge(t *testing.T, w world) {
	t.Helper()
	for pass := 0; pass < 2; pass++ {
		for _, root := range []string{w.Mac, w.Srv} {
			if _, errOut, code := engineCLI(root, "sync-daemon", "--once"); code != 0 {
				t.Fatalf("sync pass in %s failed: %s", root, errOut)
			}
		}
	}
	hub := mustGit(t, w.Hub, "rev-parse", "refs/heads/main")
	for _, root := range []string{w.Mac, w.Srv} {
		if head := mustGit(t, root, "rev-parse", "HEAD"); head != hub {
			t.Fatalf("%s is at %s, the shared copy at %s", root, head, hub)
		}
		if st := mustGit(t, root, "status", "--porcelain"); st != "" {
			t.Fatalf("%s is not clean:\n%s", root, st)
		}
		// No rebuild-index here: the indexes must already be right, or searches are stale.
		if msg := wholeFolder(root); msg != "" {
			t.Fatalf("%s: %s", root, msg)
		}
		notes, _ := filepath.Glob(filepath.Join(root, "01_Ideas", "IDEA-*.md"))
		for _, n := range notes {
			if out, _, code := engineCLI(root, "validate", n); code != 0 {
				t.Fatalf("validate %s: %s", n, out)
			}
		}
		out, _, code := engineCLI(root, "audit-health")
		var report struct {
			BrokenLinks []string `json:"broken_links"`
			StaleClaims []string `json:"stale_claims"`
		}
		if err := json.Unmarshal([]byte(out), &report); code != 0 || err != nil || len(report.BrokenLinks)+len(report.StaleClaims) != 0 {
			t.Fatalf("audit-health in %s not clean (exit %d, %v): %s", root, code, err, out)
		}
	}
}

func saveImpact(root, id string, impact int) int {
	out, _, code := engineCLI(root, "read-record", id)
	var env vault.RecordEnvelope
	if code != 0 || json.Unmarshal([]byte(out), &env) != nil {
		return -1
	}
	_, _, code = engineCLI(root, "commit", id, env.SHA256, "agent-olivier", fmt.Sprintf(`{"impact":%d}`, impact))
	return code
}

func TestScenario01_DifferentNotesAtTheSameMoment(t *testing.T) {
	w := newScenarioWorld(t)
	n := rounds(100, 5)
	for i := 0; i < n; i++ {
		codes := both(w, func(root string) int {
			if root == w.Mac {
				return saveImpact(root, note1, i%5+1)
			}
			return saveImpact(root, note2, i%5+1)
		})
		if codes != [2]int{0, 0} {
			t.Fatalf("round %d: exit codes %v, want both 0", i, codes)
		}
	}
	converge(t, w)
	if got := mustGit(t, w.Hub, "rev-list", "--count", "refs/heads/main"); got != fmt.Sprint(1+2*n) {
		t.Fatalf("shared copy holds %s commits, want %d (seed + every save)", got, 1+2*n)
	}
}

func TestScenario02_SameNoteAtTheSameMoment(t *testing.T) {
	w := newScenarioWorld(t)
	n := rounds(100, 5)
	for i := 0; i < n; i++ {
		converge(t, w)
		sha := readSHA(t, w.Mac, note1) // both places read the same version
		before := mustGit(t, w.Hub, "rev-list", "--count", "refs/heads/main")
		codes := both(w, func(root string) int {
			impact, actor := i%5+1, "agent-olivier"
			if root == w.Srv {
				impact, actor = (i+2)%5+1, "agent-bestie"
			}
			_, _, code := engineCLI(root, "commit", note1, sha, actor, fmt.Sprintf(`{"impact":%d}`, impact))
			return code
		})
		got := []int{codes[0], codes[1]}
		sort.Ints(got)
		if got[0] != 0 || got[1] != ExitNoteChanged {
			t.Fatalf("round %d: exit codes %v, want exactly one 0 and one %d", i, codes, ExitNoteChanged)
		}
		if after := mustGit(t, w.Hub, "rev-list", "--count", "refs/heads/main"); after != fmt.Sprint(atoi(t, before)+1) {
			t.Fatalf("round %d: shared copy went from %s to %s commits; exactly one save may be stored", i, before, after)
		}
	}
	converge(t, w)
}

func atoi(t *testing.T, s string) int {
	t.Helper()
	var n int
	if _, err := fmt.Sscan(s, &n); err != nil {
		t.Fatalf("not a number: %q", s)
	}
	return n
}

func TestScenario04_NewNotesNeverShareANumber(t *testing.T) {
	w := newScenarioWorld(t)
	n := rounds(100, 5)
	for i := 0; i < n; i++ {
		codes := both(w, func(root string) int {
			place := filepath.Base(root)
			drop := filepath.Join(root, "_inbox", "agent", "agent-olivier", fmt.Sprintf("%s-round-%04d.md", place, i))
			body := fmt.Sprintf("---\ntitle: Round %d from %s\n---\nSynthetic.\n", i, place)
			if err := os.WriteFile(drop, []byte(body), 0644); err != nil {
				return -1
			}
			out, _, code := engineCLI(root, "ingest", drop)
			if code == 0 && lastLine(out) != "SAVED" {
				return -2
			}
			return code
		})
		if codes != [2]int{0, 0} {
			t.Fatalf("round %d: exit codes %v, want both 0", i, codes)
		}
	}
	converge(t, w)
	notes, _ := filepath.Glob(filepath.Join(w.Mac, "01_Ideas", "IDEA-*.md"))
	ids := map[string]bool{}
	for _, p := range notes {
		ids[filepath.Base(p)[:len("IDEA-2026-000001")]] = true
	}
	if len(notes) != 2+2*n || len(ids) != len(notes) {
		t.Fatalf("%d notes with %d different numbers, want %d of each", len(notes), len(ids), 2+2*n)
	}
}

// daemonProc is a sync-daemon the test has started and must stop.
type daemonProc struct {
	cmd    *exec.Cmd
	cancel context.CancelFunc
	done   chan struct{}
	once   sync.Once
}

func startDaemon(t *testing.T, root string) *daemonProc {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	cmd := exec.CommandContext(ctx, engineBin, "sync-daemon")
	cmd.Cancel = func() error { return cmd.Process.Signal(syscall.SIGTERM) } // a stop signal, so it exits 0 and releases its lock
	cmd.WaitDelay = 10 * time.Second
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "VAULT_ROOT="+root)
	if err := cmd.Start(); err != nil {
		cancel()
		t.Fatalf("sync-daemon did not start in %s: %v", root, err)
	}
	d := &daemonProc{cmd: cmd, cancel: cancel, done: make(chan struct{})}
	go func() { _ = cmd.Wait(); close(d.done) }()
	return d
}

// stop ends the daemon with SIGTERM and fails the test unless it was still
// running and exits with status 0. Safe to call more than once.
func (d *daemonProc) stop(t *testing.T) {
	t.Helper()
	d.once.Do(func() {
		select {
		case <-d.done:
			t.Errorf("sync-daemon had already stopped before the test ended")
		default:
		}
		d.cancel()
		<-d.done
		if st := d.cmd.ProcessState; st == nil || st.ExitCode() != 0 {
			t.Errorf("sync-daemon did not exit 0 on the stop signal: %v", st)
		}
	})
}

func TestScenario05_SaveRacesIncomingUpdate(t *testing.T) {
	w := newScenarioWorld(t)
	n := rounds(1000, 20)
	// 1,000 saves from one place add up to more than the real daily allowance
	// (about 70 KB per save was counted), so this race test raises it; the
	// allowance itself is tested in Scenario18.
	settings := filepath.Join(w.Hub, "hooks", "vault-limits.json")
	original, _ := os.ReadFile(settings)
	roomy := strings.Replace(string(original), `"daily_bytes_per_place": 52428800`, `"daily_bytes_per_place": 52428800000`, 1)
	if roomy == string(original) {
		t.Fatalf("could not raise the allowance in %s", settings)
	}
	if err := os.WriteFile(settings, []byte(roomy), 0644); err != nil {
		t.Fatalf("write settings: %v", err)
	}
	daemon := startDaemon(t, w.Srv) // srv keeps receiving while it also saves
	defer daemon.stop(t)

	problems := make(chan string, 1)
	observed := make(chan int, 1)
	stopObserver := make(chan struct{})
	var stopOnce sync.Once
	finalLooks := 0
	endObserver := func() int { // safe to call twice
		stopOnce.Do(func() {
			close(stopObserver)
			finalLooks = <-observed
		})
		return finalLooks
	}
	go func() { // whoever holds the lock must always see a whole folder
		looks := 0
		defer func() { observed <- looks }()
		for {
			select {
			case <-stopObserver:
				return
			default:
			}
			lock, err := AcquireFolderLock(w.Srv, 5*time.Second)
			if err != nil {
				time.Sleep(5 * time.Millisecond)
				continue
			}
			msg := ""
			if _, err := os.Stat(filepath.Join(w.Srv, "_meta", "guards", "save-in-progress.json")); os.IsNotExist(err) {
				msg = wholeFolder(w.Srv)
			}
			lock.Release()
			looks++
			if msg != "" {
				select {
				case problems <- msg:
				default:
				}
			}
			time.Sleep(5 * time.Millisecond)
		}
	}()
	defer func() { _ = endObserver() }()

	for i := 0; i < n; i++ {
		codes := both(w, func(root string) int {
			if root == w.Mac {
				return saveImpact(root, note1, i%5+1)
			}
			return saveImpact(root, note2, i%5+1)
		})
		if codes != [2]int{0, 0} {
			t.Fatalf("round %d: exit codes %v, want both 0", i, codes)
		}
	}
	looks := endObserver()
	daemon.stop(t)
	select {
	case msg := <-problems:
		t.Fatalf("the folder was seen half-updated: %s", msg)
	default:
	}
	if looks < n/10 {
		t.Fatalf("the observer looked only %d times in %d rounds", looks, n)
	}
	converge(t, w)
}

func TestScenario06_DelayBetweenPlaces(t *testing.T) {
	w := newScenarioWorld(t)
	n := rounds(50, 3)
	// The real interval, not the fast one the other tests use.
	cfg := `{"place":"srv-test","poll_interval_ms":3000,"inbox_quiet_ms":3000}` + "\n"
	if err := os.WriteFile(filepath.Join(w.Srv, "_meta", "bin", "sync.json"), []byte(cfg), 0644); err != nil {
		t.Fatalf("write sync.json: %v", err)
	}
	daemon := startDaemon(t, w.Srv)
	defer daemon.stop(t)
	srvNote := fixtureNote(t, w.Srv, note1)
	e := vault.NewVaultEngine(w.Srv)

	var delays []time.Duration
	for i := 0; i < n; i++ {
		if code := saveImpact(w.Mac, note1, i%5+1); code != 0 {
			t.Fatalf("run %d: save exit %d", i, code)
		}
		saved := time.Now() // the agent has just been told SAVED
		want := readSHA(t, w.Mac, note1)
		for {
			if got, _ := e.ComputeSHA256(srvNote); got == want {
				break
			}
			if time.Since(saved) > 20*time.Second {
				t.Fatalf("run %d: the change did not reach srv-test within 20 s", i)
			}
			time.Sleep(10 * time.Millisecond)
		}
		delays = append(delays, time.Since(saved))
		time.Sleep(time.Duration(rand.Intn(1500)) * time.Millisecond) // do not save in step with the poll
	}
	daemon.stop(t)
	sort.Slice(delays, func(i, j int) bool { return delays[i] < delays[j] })
	median, worst := delays[len(delays)/2], delays[len(delays)-1]
	fmt.Printf("LATENCY runs=%d median=%dms worst=%dms target_worst<5000ms\n", n, median.Milliseconds(), worst.Milliseconds())
	if worst >= 5*time.Second {
		t.Fatalf("worst delay %v is not under the 5 s target", worst)
	}
	converge(t, w)
}

// waitFor polls f every millisecond until it is true or the time is up.
func waitFor(limit time.Duration, f func() bool) bool {
	for deadline := time.Now().Add(limit); time.Now().Before(deadline); time.Sleep(time.Millisecond) {
		if f() {
			return true
		}
	}
	return false
}

func headOf(root string) string {
	out, _ := exec.Command("git", "-C", root, "rev-parse", "HEAD").Output()
	return strings.TrimSpace(string(out))
}

// killWhen starts an engine command in root, waits until the folder shows the
// operation has begun to change things (its marker is on disk AND changed()
// is true), kills it with SIGKILL at once, and reports whether the marker was
// still there afterwards, which proves the kill landed before the operation
// ended.
func killWhen(t *testing.T, root string, changed func() bool, args ...string) bool {
	t.Helper()
	cmd := exec.Command(engineBin, args...)
	cmd.Dir, cmd.Env = root, append(os.Environ(), "VAULT_ROOT="+root)
	if err := cmd.Start(); err != nil {
		t.Fatalf("start %v: %v", args, err)
	}
	marker := filepath.Join(root, "_meta", "guards", "save-in-progress.json")
	waitFor(5*time.Second, func() bool {
		if _, err := os.Stat(marker); err != nil {
			return false
		}
		return changed()
	})
	_ = cmd.Process.Kill()
	_ = cmd.Wait()
	_, err := os.Stat(marker)
	return err == nil
}

func TestScenario07_KilledMidSaveAndMidUpdate(t *testing.T) {
	w := newScenarioWorld(t)
	n := rounds(30, 8)
	e := vault.NewVaultEngine(w.Mac)
	macNote := fixtureNote(t, w.Mac, note1)
	midUpdate, midSave := 0, 0
	for i := 0; i < n; i++ {
		// Mid-update: srv saves, so mac is behind the shared copy and has an
		// update to pull. The daemon on mac is killed a random moment after
		// its update has begun, and the kill counts only if the update had not ended.
		if code := saveImpact(w.Srv, note2, i%5+1); code != 0 {
			t.Fatalf("round %d: srv save exit %d", i, code)
		}
		later := func() bool { // a random moment shortly after the update has begun
			time.Sleep(time.Duration(rand.Intn(40)) * time.Millisecond)
			return true
		}
		if killWhen(t, w.Mac, later, "sync-daemon") {
			midUpdate++
		}
		converge(t, w) // after restart: healthy and identical

		// Mid-save: mac saves a note and is killed once the note or the head
		// has changed but before the save has finished.
		sha := readSHA(t, w.Mac, note1)
		headBefore := headOf(w.Mac)
		changed := func() bool {
			now, _ := e.ComputeSHA256(macNote)
			return now != sha || headOf(w.Mac) != headBefore
		}
		if killWhen(t, w.Mac, changed, "commit", note1, sha, "agent-olivier", fmt.Sprintf(`{"impact":%d}`, i%5+1)) {
			midSave++
		}
		converge(t, w)
	}
	if midSave < n/2 || midUpdate < n/2 {
		t.Fatalf("kills proven mid-operation: %d saves and %d updates out of %d rounds, want at least %d of each", midSave, midUpdate, n, n/2)
	}
	if code := saveImpact(w.Mac, note1, 3); code != 0 && code != ExitNoteChanged {
		t.Fatalf("a normal save after the kills ended with exit %d", code)
	}
	converge(t, w)
}

func TestScenario18_OnePlaceOverItsAllowance(t *testing.T) {
	w := newScenarioWorld(t)
	settings := filepath.Join(w.Hub, "hooks", "vault-limits.json")
	original, _ := os.ReadFile(settings)
	tight := strings.Replace(string(original), `"daily_bytes_per_place": 52428800`, `"daily_bytes_per_place": 3000`, 1)
	if tight == string(original) {
		t.Fatalf("could not tighten the allowance in %s", settings)
	}
	if err := os.WriteFile(settings, []byte(tight), 0644); err != nil {
		t.Fatalf("write settings: %v", err)
	}
	refusedAt := -1
	for i := 0; i < 30; i++ {
		sha := readSHA(t, w.Mac, note1)
		out, errOut, code := engineCLI(w.Mac, "commit", note1, sha, "agent-olivier", fmt.Sprintf(`{"impact":%d}`, i%5+1))
		if code == ExitTooLarge {
			if lastLine(out) != "REFUSED too-large" || !strings.Contains(errOut, "daily_bytes_per_place=3000") {
				t.Fatalf("refusal should name the limit: stdout %q stderr %q", out, errOut)
			}
			refusedAt = i
			break
		}
		if code != 0 {
			t.Fatalf("save %d: unexpected exit %d (%s)", i, code, errOut)
		}
	}
	if refusedAt < 1 {
		t.Fatalf("mac-test was never refused (or was refused at once): %d", refusedAt)
	}
	if st := mustGit(t, w.Mac, "status", "--porcelain"); st != "" {
		t.Fatalf("the refused save left something behind:\n%s", st)
	}
	if code := saveImpact(w.Srv, note2, 4); code != 0 {
		t.Fatalf("srv-test must still be able to save, exit %d", code)
	}
}
