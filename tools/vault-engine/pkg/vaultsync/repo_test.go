package vaultsync

import (
	"bufio"
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"obsidian-vault-engine/pkg/vault"
)

func TestRepo_StatusKeepsLeadingSpaceCodes(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	note, _ := filepath.Glob(filepath.Join(w.Mac, "01_Ideas", "IDEA-2026-000001--*.md"))
	writeFile(t, note[0], []byte("changed by hand\n"))
	writeFile(t, filepath.Join(w.Mac, "_inbox", "human", "drop one.md"), []byte("hello\n"))
	st, err := r.Status()
	if err != nil {
		t.Fatalf("status: %v", err)
	}
	rel, _ := filepath.Rel(w.Mac, note[0])
	if st[filepath.ToSlash(rel)] != " M" {
		t.Errorf("tracked edit: expected \" M\", got %q (all: %v)", st[filepath.ToSlash(rel)], st)
	}
	if st["_inbox/human/drop one.md"] != "??" {
		t.Errorf("untracked drop: expected \"??\", got %q (all: %v)", st["_inbox/human/drop one.md"], st)
	}
	if len(st) != 2 {
		t.Errorf("ignored files must not appear: %v", st)
	}
}

func TestRepo_CommitStagesOnlyTheGivenPathsAsActorAtPlace(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	writeFile(t, filepath.Join(w.Mac, "01_Ideas", "mine.md"), []byte("mine\n"))
	writeFile(t, filepath.Join(w.Mac, "01_Ideas", "stray.md"), []byte("stray\n"))
	if err := r.Commit([]string{"01_Ideas/mine.md"}, "agent olivier!", "vault: commit", "ingest:x"); err != nil {
		t.Fatalf("commit: %v", err)
	}
	if got := mustGit(t, w.Mac, "log", "-1", "--format=%an|%s|%b"); got != "agentolivier@mac-test|vault: commit by agentolivier@mac-test|Vault-Op-Key: ingest:x" {
		t.Errorf("unexpected commit: %q", got)
	}
	if files := mustGit(t, w.Mac, "show", "--name-only", "--format=", "HEAD"); files != "01_Ideas/mine.md" {
		t.Errorf("commit should hold exactly one file, got %q", files)
	}
	if st, _ := r.Status(); st["01_Ideas/stray.md"] != "??" {
		t.Errorf("stray file must stay untracked: %v", st)
	}
}

func TestRepo_FetchReportsNoConnection(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	if err := r.Fetch(); err != nil {
		t.Fatalf("fetch with hub present: %v", err)
	}
	if hub, err := r.RemoteHead(); err != nil || hub != mustGit(t, w.Mac, "rev-parse", "HEAD") {
		t.Fatalf("RemoteHead = (%q, %v)", hub, err)
	}
	if err := os.Rename(w.Hub, w.Hub+".off"); err != nil {
		t.Fatalf("rename hub: %v", err)
	}
	if err := r.Fetch(); !errors.Is(err, ErrNoConnection) {
		t.Fatalf("expected ErrNoConnection, got %v", err)
	}
	if _, err := r.RemoteHead(); !errors.Is(err, ErrNoConnection) {
		t.Fatalf("expected ErrNoConnection from RemoteHead, got %v", err)
	}
}

func TestRepo_TimedOutGitIsKilledAndReportedAsNoConnection(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	pidFile := filepath.Join(t.TempDir(), "pid")
	mustGit(t, w.Mac, "config", "protocol.ext.allow", "always")
	script := filepath.Join(t.TempDir(), "slow.sh")
	writeFile(t, script, []byte("#!/bin/sh\necho $$ > \""+pidFile+"\"\nexec sleep 30\n"))
	if err := os.Chmod(script, 0755); err != nil {
		t.Fatalf("chmod: %v", err)
	}
	mustGit(t, w.Mac, "config", "remote.slow.url", "ext::"+script)
	r.Remote = "slow"
	r.NetTimeout = 1500 * time.Millisecond
	start := time.Now()
	if err := r.Fetch(); !errors.Is(err, ErrNoConnection) {
		t.Fatalf("expected ErrNoConnection, got %v", err)
	}
	if took := time.Since(start); took > 5*time.Second {
		t.Fatalf("fetch took %v, expected about the 400ms limit", took)
	}
	raw, err := os.ReadFile(pidFile)
	if err != nil {
		t.Fatalf("slow helper never started: %v", err)
	}
	pid, _ := strconv.Atoi(strings.TrimSpace(string(raw)))
	deadline := time.Now().Add(2 * time.Second)
	for syscall.Kill(pid, 0) == nil && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if syscall.Kill(pid, 0) == nil {
		t.Fatalf("helper process %d is still running after the timeout", pid)
	}
}

// D10: a git child inherits the folder-lock descriptor. When the engine is
// killed, the lock stays held until the git child has finished.
func TestRepo_GitChildKeepsTheFolderLockAfterTheEngineDies(t *testing.T) {
	root := t.TempDir()
	mustGit(t, root, "init", "-q")
	holder := exec.Command(os.Args[0])
	holder.Env = append(os.Environ(), "VAULTSYNC_HOLD_GIT_CHILD="+root)
	out, err := holder.StdoutPipe()
	if err != nil {
		t.Fatalf("pipe: %v", err)
	}
	if err := holder.Start(); err != nil {
		t.Fatalf("start holder: %v", err)
	}
	if line, _ := bufio.NewReader(out).ReadString('\n'); line != "locked\n" {
		t.Fatalf("holder did not take the lock, said %q", line)
	}
	_ = holder.Process.Kill() // SIGKILL: the engine is gone, its git child is not
	_ = holder.Wait()
	if _, err := AcquireFolderLock(root, 300*time.Millisecond); !errors.Is(err, ErrLockTimeout) {
		t.Fatalf("a running git child should still hold the lock, got %v", err)
	}
	lock, err := AcquireFolderLock(root, 5*time.Second)
	if err != nil {
		t.Fatalf("lock should be free once the child ended: %v", err)
	}
	lock.Release()
}

func TestRepo_SignalKillsTheGitGroupAndEndsTheEngine(t *testing.T) {
	root := t.TempDir()
	mustGit(t, root, "init", "-q")
	pidFile := filepath.Join(t.TempDir(), "pid")
	holder := exec.Command(os.Args[0])
	holder.Env = append(os.Environ(), "VAULTSYNC_SIGNAL_CHILD="+root, "VAULTSYNC_SIGNAL_PID="+pidFile)
	out, err := holder.StdoutPipe()
	if err != nil {
		t.Fatalf("pipe: %v", err)
	}
	if err := holder.Start(); err != nil {
		t.Fatalf("start holder: %v", err)
	}
	if line, _ := bufio.NewReader(out).ReadString('\n'); line != "started\n" {
		_ = holder.Process.Kill() // without this the helper would idle for an hour
		_ = holder.Wait()
		t.Fatalf("holder did not start its git child, said %q", line)
	}
	raw, err := os.ReadFile(pidFile)
	if err != nil {
		_ = holder.Process.Kill()
		t.Fatalf("git child never started: %v", err)
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(raw)))
	if err != nil {
		_ = holder.Process.Kill()
		_ = holder.Wait()
		t.Fatalf("pid file of the git child holds %q: %v", raw, err)
	}
	_ = holder.Process.Signal(syscall.SIGTERM)
	err = holder.Wait()
	var ee *exec.ExitError
	if !errors.As(err, &ee) || ee.ExitCode() != 143 {
		t.Fatalf("expected exit status 143, got %v", err)
	}
	if syscall.Kill(pid, 0) == nil {
		t.Fatalf("git helper %d is still running after SIGTERM", pid)
	}
	lock, err := AcquireFolderLock(root, 500*time.Millisecond)
	if err != nil {
		t.Fatalf("lock should be free right after the signal: %v", err)
	}
	lock.Release()
}

func TestRepo_CommitWithNoPathsDoesNothing(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	writeFile(t, filepath.Join(w.Mac, "01_Ideas", "loose.md"), []byte("loose\n"))
	before := mustGit(t, w.Mac, "rev-parse", "HEAD")
	if err := r.Commit(nil, "a", "vault: commit", ""); !errors.Is(err, ErrNothingToCommit) {
		t.Fatalf("expected ErrNothingToCommit, got %v", err)
	}
	if mustGit(t, w.Mac, "rev-parse", "HEAD") != before || mustGit(t, w.Mac, "diff", "--cached", "--name-only") != "" {
		t.Fatalf("empty path list must stage and commit nothing")
	}
}

func TestRepo_CommitLeavesOtherStagedFilesStaged(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	writeFile(t, filepath.Join(w.Mac, "01_Ideas", "mine.md"), []byte("mine\n"))
	writeFile(t, filepath.Join(w.Mac, "01_Ideas", "theirs.md"), []byte("theirs\n"))
	mustGit(t, w.Mac, "add", "01_Ideas/theirs.md")
	if err := r.Commit([]string{"01_Ideas/mine.md"}, "a", "vault: commit", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	if files := mustGit(t, w.Mac, "show", "--name-only", "--format=", "HEAD"); files != "01_Ideas/mine.md" {
		t.Errorf("commit should hold only mine.md, got %q", files)
	}
	if st, _ := r.Status(); st["01_Ideas/theirs.md"] != "A " {
		t.Errorf("someone else's staged file must stay staged: %v", st)
	}
}

func TestRepo_CommitTreatsPathsLiterally(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	writeFile(t, filepath.Join(w.Mac, "01_Ideas", "a[1].md"), []byte("bracket\n"))
	writeFile(t, filepath.Join(w.Mac, "01_Ideas", "a1.md"), []byte("plain\n"))
	if err := r.Commit([]string{"01_Ideas/a[1].md"}, "a", "vault: commit", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	if files := mustGit(t, w.Mac, "show", "--name-only", "--format=", "HEAD"); files != "01_Ideas/a[1].md" {
		t.Errorf("only the literal name may be recorded, got %q", files)
	}
	if st, _ := r.Status(); st["01_Ideas/a1.md"] != "??" {
		t.Errorf("a1.md must stay untracked: %v", st)
	}
}

func TestRepo_CommitRecordsADeletion(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	note, _ := filepath.Glob(filepath.Join(w.Mac, "01_Ideas", "IDEA-2026-000001--*.md"))
	rel, _ := filepath.Rel(w.Mac, note[0])
	if err := os.Remove(note[0]); err != nil {
		t.Fatal(err)
	}
	if err := r.Commit([]string{filepath.ToSlash(rel)}, "a", "vault: commit", ""); err != nil {
		t.Fatalf("commit deletion: %v", err)
	}
	if got := mustGit(t, w.Mac, "show", "--name-status", "--format=", "HEAD"); got != "D\t"+filepath.ToSlash(rel) {
		t.Errorf("expected the deletion to be recorded, got %q", got)
	}
}

func TestRepo_CommitDoesNotRunHooks(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	marker := filepath.Join(t.TempDir(), "hook-ran")
	hook := filepath.Join(w.Mac, ".git", "hooks", "post-commit")
	writeFile(t, hook, []byte("#!/bin/sh\ntouch \""+marker+"\"\n"))
	if err := os.Chmod(hook, 0755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(w.Mac, "01_Ideas", "h.md"), []byte("h\n"))
	if err := r.Commit([]string{"01_Ideas/h.md"}, "a", "vault: commit", ""); err != nil {
		t.Fatalf("commit: %v", err)
	}
	if _, err := os.Stat(marker); err == nil {
		t.Fatalf("a git hook ran; it would inherit the folder-lock descriptor")
	}
}

// otherRepo builds a repository that has nothing to do with any place: one
// committed file with an edit that is not committed, and one untracked file.
// The returned function describes its whole state (commit, index, work tree).
func otherRepo(t *testing.T, dir string) (state func() string) {
	t.Helper()
	writeFile(t, filepath.Join(dir, "kept.md"), []byte("committed\n"))
	mustGit(t, dir, "init", "--quiet", "--initial-branch=main")
	mustGit(t, dir, "add", "-A")
	mustGit(t, dir, "commit", "--quiet", "-m", "other")
	writeFile(t, filepath.Join(dir, "kept.md"), []byte("edited, not committed\n"))
	writeFile(t, filepath.Join(dir, "loose.md"), []byte("untracked\n"))
	return func() string {
		t.Helper()
		kept, _ := os.ReadFile(filepath.Join(dir, "kept.md"))
		loose, _ := os.ReadFile(filepath.Join(dir, "loose.md"))
		return strings.Join([]string{
			mustGit(t, dir, "rev-parse", "HEAD"),
			mustGit(t, dir, "ls-files", "--stage"),
			mustGit(t, dir, "status", "--porcelain", "--untracked-files=all"),
			mustGit(t, dir, "stash", "list"),
			string(kept), string(loose),
		}, "\n--\n")
	}
}

// A caller that exports git's own repository variables (a git hook of another
// repository, `git rebase --exec`) must not turn the place's git commands onto
// that repository: recovery, the daemon and a save all work on the place.
func TestRepo_HostileGitEnvironmentLeavesTheOtherRepositoryUntouched(t *testing.T) {
	for name, vars := range map[string][]string{
		"GIT_DIR only":                 {"GIT_DIR"},
		"GIT_DIR, work tree and index": {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_PREFIX"},
	} {
		t.Run(name, func(t *testing.T) {
			w := newWorld(t)
			other := filepath.Join(t.TempDir(), "other")
			state := otherRepo(t, other)
			before := state()
			values := map[string]string{
				"GIT_DIR":              filepath.Join(other, ".git"),
				"GIT_WORK_TREE":        other,
				"GIT_INDEX_FILE":       filepath.Join(other, ".git", "index"),
				"GIT_OBJECT_DIRECTORY": filepath.Join(other, ".git", "objects"),
				"GIT_COMMON_DIR":       filepath.Join(other, ".git"),
				"GIT_PREFIX":           "",
			}
			note := fixtureNote(t, w.Mac, note1)
			original, _ := os.ReadFile(note)
			writeFile(t, note, []byte("typed straight into the file\n"))
			quietDrop(t, w.Mac, "01_Ideas/made-by-hand.md", []byte("a stray\n"))
			hubBefore := mustGit(t, w.Hub, "rev-list", "--count", "refs/heads/main")
			mac, daemon := newSyncer(t, w.Mac), newDaemon(t, w.Mac)

			for _, k := range vars {
				t.Setenv(k, values[k])
			}
			tickErr := daemon.Tick() // recovery, hand edit and stray handling
			_, out := mac.Save(commitOp(mac, note1, readSHA(t, w.Mac, note1), 5))
			for _, k := range vars { // the checks below use plain git
				_ = os.Unsetenv(k)
			}

			if after := state(); after != before {
				t.Fatalf("the other repository was touched:\n--- before\n%s\n--- after\n%s", before, after)
			}
			if tickErr != nil {
				t.Fatalf("tick: %v", tickErr)
			}
			if out.Line != "SAVED" {
				t.Fatalf("save = %+v, want SAVED", out)
			}
			if got := quarantined(t, w.Mac, "mac-test", "01_Ideas/made-by-hand.md"); string(got) != "a stray\n" {
				t.Fatalf("stray not set aside in the place: %q", got)
			}
			if hub := mustGit(t, w.Hub, "rev-list", "--count", "refs/heads/main"); hub == hubBefore {
				t.Fatalf("the save did not reach the place's own hub")
			}
			if now, _ := os.ReadFile(note); string(now) == "typed straight into the file\n" || string(now) == string(original) {
				t.Fatalf("the note should hold the save, not the hand edit or the old text")
			}
			cleanExceptIgnored(t, w.Mac)
			if _, err := os.Stat(filepath.Join(w.Mac, "kept.md")); !os.IsNotExist(err) {
				t.Fatalf("a file of the other repository appeared in the place")
			}
		})
	}
}

// A folder with a sync config but no repository of its own, sitting inside
// some other repository: git would walk up and use that one. Nothing may run.
func TestRepo_FolderInsideAnotherRepositoryIsRefusedAndThatRepositoryIsUntouched(t *testing.T) {
	outer := filepath.Join(t.TempDir(), "outer")
	state := otherRepo(t, outer)
	root := filepath.Join(outer, "vault")
	writeFile(t, filepath.Join(root, "01_Ideas", "note.md"), []byte("a note\n"))
	before := state()
	cfg := &Config{Place: "mac-test", Remote: "origin", Branch: "main", PollIntervalMS: 200, InboxQuietMS: 300,
		NetTimeoutMS: 5000, LockTimeoutMS: 1000, MaxRetries: 2}
	s := NewSyncer(vault.NewVaultEngine(root), cfg)
	ran := false
	_, out := s.Save(Op{Name: "commit", Actor: "agent-olivier", Run: func() (string, error) { ran = true; return "", nil }})
	if out.Line != "REFUSED engine-error" || out.Exit != ExitEngineError || !strings.Contains(out.Detail, "not the top level of its own git repository") {
		t.Fatalf("save = %+v, want REFUSED engine-error naming the cause", out)
	}
	if ran {
		t.Fatalf("the operation must not run")
	}
	d := NewDaemon(vault.NewVaultEngine(root), cfg)
	d.Log = io.Discard
	if err := d.Tick(); err == nil {
		t.Fatalf("a daemon pass must fail in a folder that is not its own repository")
	}
	if _, err := s.Repo.Status(); err == nil {
		t.Fatalf("no git command of the place may answer from the outer repository")
	}
	if after := state(); after != before {
		t.Fatalf("the outer repository was touched:\n--- before\n%s\n--- after\n%s", before, after)
	}
}

// Every git child of a place gets an environment with none of git's
// repository-selecting variables, and a ceiling taken from the folder's real
// path: git compares the ceiling with the real working folder, so the parent
// of a symbolic link would have no effect.
func TestPlaceEnv_DropsEveryLocationVariableAndSetsTheCeilingFromTheRealPath(t *testing.T) {
	for name := range gitLocationVars {
		t.Setenv(name, "/somewhere/else")
	}
	base, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	realRoot := filepath.Join(base, "real", "place")
	if err := os.MkdirAll(realRoot, 0755); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(base, "link")
	if err := os.Symlink(realRoot, link); err != nil {
		t.Fatal(err)
	}
	ceilings := 0
	for _, kv := range placeEnv(link) {
		name, value, _ := strings.Cut(kv, "=")
		switch {
		case name == "GIT_CEILING_DIRECTORIES":
			ceilings++
			if want := filepath.Join(base, "real"); value != want {
				t.Errorf("ceiling = %q, want the real parent %q", value, want)
			}
		case gitLocationVars[name]:
			t.Errorf("%s was passed on to git", name)
		}
	}
	if ceilings != 1 {
		t.Errorf("GIT_CEILING_DIRECTORIES set %d times, want once", ceilings)
	}
}

// The cause of a failed fetch stays readable by the program, not only as text.
func TestRepo_NoConnectionErrorsKeepTheirCause(t *testing.T) {
	w := newWorld(t)
	r := newRepo(t, w.Mac)
	stopped := errors.New("stopped by the test")
	r.gate = func([]string) error { return stopped }
	if err := r.Fetch(); !errors.Is(err, ErrNoConnection) || !errors.Is(err, stopped) {
		t.Fatalf("Fetch: want ErrNoConnection wrapping the cause, got %v", err)
	}
	if _, err := r.RemoteHead(); !errors.Is(err, ErrNoConnection) || !errors.Is(err, stopped) {
		t.Fatalf("RemoteHead: want ErrNoConnection wrapping the cause, got %v", err)
	}
	// A hub that answers but has no main line yet is still "no connection", with a plain reason.
	r.gate = nil
	empty := filepath.Join(t.TempDir(), "empty.git")
	mustGit(t, t.TempDir(), "init", "--quiet", "--bare", empty)
	mustGit(t, w.Mac, "config", "remote.empty.url", empty)
	r.Remote = "empty"
	if _, err := r.RemoteHead(); !errors.Is(err, ErrNoConnection) || strings.Contains(err.Error(), "<nil>") ||
		!strings.Contains(err.Error(), "has no refs/heads/") {
		t.Fatalf("RemoteHead on an empty hub: got %v", err)
	}
}

// A cancel of Repo.stop while a git command runs kills it, and the command is
// reported as ErrStopped (not as a plain failure, not as a time-out).
func TestRepoRun_CancelDuringASlowCommandGivesErrStopped(t *testing.T) {
	root := t.TempDir()
	mustGit(t, root, "init", "-q")
	pidFile := filepath.Join(t.TempDir(), "pid")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	r := &Repo{Root: root, Place: "test", stop: ctx}
	go func() { // cancel once the command is really running; ends by itself after 20 s at most
		waitFor(20*time.Second, func() bool {
			data, err := os.ReadFile(pidFile)
			return err == nil && strings.TrimSpace(string(data)) != ""
		})
		cancel()
	}()
	start := time.Now()
	res := r.run(time.Minute, "-c", "alias.nap=!echo $$ > '"+pidFile+"'; exec sleep 30", "nap")
	if !errors.Is(res.Err, ErrStopped) {
		t.Fatalf("a command killed by the cancel must be ErrStopped, got %v", res.Err)
	}
	if took := time.Since(start); took > 15*time.Second {
		t.Fatalf("run returned %v after it started; the cancel should have cut it short", took)
	}
	if _, err := os.Stat(pidFile); err != nil {
		t.Fatalf("the command was never running, so the cancel was not tested: %v", err)
	}
}

// stoppedButSilent reports itself cancelled without ever signalling it: what
// run sees when the cancel lands just after git has ended well.
type stoppedButSilent struct{ context.Context }

func (stoppedButSilent) Err() error { return context.Canceled }

// A command that ended well keeps its result even when stop is already
// cancelled: only a command that failed is turned into ErrStopped.
func TestRepoRun_ACommandThatEndedWellKeepsItsResultWhenStopIsAlreadyCancelled(t *testing.T) {
	root := t.TempDir()
	mustGit(t, root, "init", "-q")
	r := &Repo{Root: root, Place: "test", stop: stoppedButSilent{context.Background()}}
	res := r.run(localTimeout, "rev-parse", "--git-dir")
	if res.Err != nil || strings.TrimSpace(res.Stdout) != ".git" {
		t.Fatalf("run = (%q, %v), want (.git, nil)", res.Stdout, res.Err)
	}
	// The same state with a command that fails is a stop, not a plain failure.
	if res := r.run(localTimeout, "rev-parse", "--verify", "no-such-ref"); !errors.Is(res.Err, ErrStopped) {
		t.Fatalf("a failed command with stop cancelled must be ErrStopped, got %v", res.Err)
	}
}
