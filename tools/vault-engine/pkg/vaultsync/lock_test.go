package vaultsync

import (
	"bufio"
	"errors"
	"os"
	"os/exec"
	"testing"
	"time"
)

func TestFolderLock_ExcludesAndTimesOut(t *testing.T) {
	root := t.TempDir()
	first, err := AcquireFolderLock(root, time.Second)
	if err != nil {
		t.Fatalf("first acquire: %v", err)
	}
	start := time.Now()
	if _, err := AcquireFolderLock(root, 150*time.Millisecond); !errors.Is(err, ErrLockTimeout) {
		t.Fatalf("expected ErrLockTimeout while held, got %v", err)
	}
	if waited := time.Since(start); waited < 150*time.Millisecond || waited > 2*time.Second {
		t.Fatalf("waited %v, expected about 150ms", waited)
	}
	first.Release()
	second, err := AcquireFolderLock(root, time.Second)
	if err != nil {
		t.Fatalf("acquire after release: %v", err)
	}
	second.Release()
	second.Release() // releasing twice is harmless
}

func TestFolderLock_ReleasedWhenTheHolderIsKilled(t *testing.T) {
	root := t.TempDir()
	holder := exec.Command(os.Args[0])
	holder.Env = append(os.Environ(), "VAULTSYNC_HOLD_LOCK="+root)
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
	if _, err := AcquireFolderLock(root, 100*time.Millisecond); !errors.Is(err, ErrLockTimeout) {
		t.Fatalf("expected the lock to be held by the other process, got %v", err)
	}
	_ = holder.Process.Kill() // SIGKILL: no cleanup code runs
	_ = holder.Wait()
	lock, err := AcquireFolderLock(root, 2*time.Second)
	if err != nil {
		t.Fatalf("the kernel should have released the lock: %v", err)
	}
	lock.Release()
}
