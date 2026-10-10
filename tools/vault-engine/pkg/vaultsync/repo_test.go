package vaultsync

import (
	"bufio"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
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
