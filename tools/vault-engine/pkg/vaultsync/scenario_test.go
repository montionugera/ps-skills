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
// tracked file, or an index entry whose fingerprint is not the file's.
func wholeFolder(root string) string {
	out, err := exec.Command("git", "-C", root, "status", "--porcelain", "--untracked-files=no").Output()
	if err != nil || strings.TrimSpace(string(out)) != "" {
		return fmt.Sprintf("tracked files differ from the recorded version (%v):\n%s", err, out)
	}
	e := vault.NewVaultEngine(root)
	data, _ := os.ReadFile(filepath.Join(root, "_meta", "indexes", "ideas.jsonl"))
	for _, line := range strings.Split(strings.TrimSpace(string(data)), "\n") {
		if line == "" {
			continue
		}
		var entry vault.IndexEntry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			return "unreadable index line: " + line
		}
		if sha, _ := e.ComputeSHA256(filepath.Join(root, entry.Path)); sha != entry.SHA256 {
			return fmt.Sprintf("index says %s for %s, file is %s", entry.SHA256, entry.Path, sha)
		}
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
	w := newWorld(t)
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
	w := newWorld(t)
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
	w := newWorld(t)
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

func startDaemon(ctx context.Context, root string) *exec.Cmd {
	cmd := exec.CommandContext(ctx, engineBin, "sync-daemon")
	cmd.Cancel = func() error { return cmd.Process.Signal(syscall.SIGTERM) } // a stop signal, so it exits 0 and releases its lock
	cmd.WaitDelay = 10 * time.Second
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "VAULT_ROOT="+root)
	_ = cmd.Start()
	return cmd
}

func TestScenario05_SaveRacesIncomingUpdate(t *testing.T) {
	w := newWorld(t)
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
	ctx, cancel := context.WithCancel(context.Background())
	daemon := startDaemon(ctx, w.Srv) // srv keeps receiving while it also saves

	problems := make(chan string, 1)
	observed := make(chan int)
	go func() { // whoever holds the lock must always see a whole folder
		looks := 0
		for ctx.Err() == nil {
			lock, err := AcquireFolderLock(w.Srv, 5*time.Second)
			if err != nil {
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
		observed <- looks
	}()

	for i := 0; i < n; i++ {
		codes := both(w, func(root string) int {
			if root == w.Mac {
				return saveImpact(root, note1, i%5+1)
			}
			return saveImpact(root, note2, i%5+1)
		})
		if codes != [2]int{0, 0} {
			cancel()
			t.Fatalf("round %d: exit codes %v, want both 0", i, codes)
		}
	}
	cancel()
	looks := <-observed
	_ = daemon.Wait()
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
	w := newWorld(t)
	n := rounds(50, 3)
	// The real interval, not the fast one the other tests use.
	cfg := `{"place":"srv-test","poll_interval_ms":3000,"inbox_quiet_ms":3000}` + "\n"
	if err := os.WriteFile(filepath.Join(w.Srv, "_meta", "bin", "sync.json"), []byte(cfg), 0644); err != nil {
		t.Fatalf("write sync.json: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	daemon := startDaemon(ctx, w.Srv)
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
	cancel()
	_ = daemon.Wait()
	sort.Slice(delays, func(i, j int) bool { return delays[i] < delays[j] })
	median, worst := delays[len(delays)/2], delays[len(delays)-1]
	fmt.Printf("LATENCY runs=%d median=%dms worst=%dms target_worst<5000ms\n", n, median.Milliseconds(), worst.Milliseconds())
	if worst >= 5*time.Second {
		t.Fatalf("worst delay %v is not under the 5 s target", worst)
	}
	converge(t, w)
}

func TestScenario07_KilledMidSaveAndMidUpdate(t *testing.T) {
	w := newWorld(t)
	n := rounds(30, 8)
	midSave := 0
	for i := 0; i < n; i++ {
		// srv saves normally, so mac has an update to receive.
		if code := saveImpact(w.Srv, note2, i%5+1); code != 0 {
			t.Fatalf("round %d: srv save exit %d", i, code)
		}
		sha := readSHA(t, w.Mac, note1)
		save := exec.Command(engineBin, "commit", note1, sha, "agent-olivier", fmt.Sprintf(`{"impact":%d}`, i%5+1))
		save.Dir, save.Env = w.Mac, append(os.Environ(), "VAULT_ROOT="+w.Mac)
		update := exec.Command(engineBin, "sync-daemon")
		update.Dir, update.Env = w.Srv, append(os.Environ(), "VAULT_ROOT="+w.Srv)
		if err := save.Start(); err != nil {
			t.Fatalf("start save: %v", err)
		}
		if err := update.Start(); err != nil {
			t.Fatalf("start update: %v", err)
		}
		// Kill the save as soon as its marker shows it is mid-way; the update
		// is cut at a random moment around it.
		marker := filepath.Join(w.Mac, "_meta", "guards", "save-in-progress.json")
		for deadline := time.Now().Add(3 * time.Second); time.Now().Before(deadline); time.Sleep(time.Millisecond) {
			if _, err := os.Stat(marker); err == nil {
				midSave++
				break
			}
		}
		time.Sleep(time.Duration(rand.Intn(250)) * time.Millisecond)
		_ = save.Process.Kill() // SIGKILL mid-save
		_ = update.Process.Kill()
		_ = save.Wait()
		_ = update.Wait()
		converge(t, w) // after restart: healthy and identical
	}
	if midSave < n/2 {
		t.Fatalf("only %d of %d saves were seen mid-save when killed", midSave, n)
	}
	if code := saveImpact(w.Mac, note1, 3); code != 0 && code != ExitNoteChanged {
		t.Fatalf("a normal save after the kills ended with exit %d", code)
	}
	converge(t, w)
}

func TestScenario18_OnePlaceOverItsAllowance(t *testing.T) {
	w := newWorld(t)
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
