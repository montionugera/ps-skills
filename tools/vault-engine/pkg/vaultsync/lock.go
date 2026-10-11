package vaultsync

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"syscall"
	"time"
)

var ErrLockTimeout = errors.New("folder lock: timed out waiting for another save or update to finish")

// FolderLock is one lock for the whole vault folder in this place. It is a
// kernel flock on an open file (same technique as the per-record guards in
// vault.go and the daemon guard in watcher.go): when the process ends for any
// reason the kernel releases it, so a leftover file can never block the folder.
// Git children started through Repo.run inherit the descriptor. The safety
// flags in gitSafetyFlags disable git's own hooks, file-system monitor and
// automatic gc / maintenance for those children, so after an unclean engine
// exit the folder normally stays locked only until the git command that was
// running has finished or been killed. This does not stop a credential-helper
// daemon started by git, or the hub's hooks, which could hold the descriptor
// longer.
type FolderLock struct{ f *os.File }

func AcquireFolderLock(vaultRoot string, timeout time.Duration) (*FolderLock, error) {
	return AcquireFolderLockContext(context.Background(), vaultRoot, timeout)
}

// AcquireFolderLockContext is AcquireFolderLock with a way to give up early:
// when ctx is cancelled while waiting, it returns ErrStopped at once.
func AcquireFolderLockContext(ctx context.Context, vaultRoot string, timeout time.Duration) (*FolderLock, error) {
	guardsDir := filepath.Join(vaultRoot, "_meta", "guards")
	if err := os.MkdirAll(guardsDir, 0755); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(filepath.Join(guardsDir, "folder.guard"), os.O_CREATE|os.O_RDWR, 0644)
	if err != nil {
		return nil, fmt.Errorf("opening folder guard: %w", err)
	}
	deadline := time.Now().Add(timeout)
	for {
		err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
		if err == nil {
			return &FolderLock{f: f}, nil
		}
		if err != syscall.EWOULDBLOCK {
			_ = f.Close()
			return nil, fmt.Errorf("locking folder guard: %w", err)
		}
		if time.Now().After(deadline) {
			_ = f.Close()
			return nil, ErrLockTimeout
		}
		select {
		case <-ctx.Done():
			_ = f.Close()
			return nil, ErrStopped
		case <-time.After(20 * time.Millisecond):
		}
	}
}

// Release unlocks the folder. flock locks belong to the open file description,
// so this also unlocks it for any git child that inherited the descriptor:
// call it only when no git child is running. The crash protection described
// on FolderLock applies only when the engine dies WITHOUT calling Release.
func (l *FolderLock) Release() {
	if l == nil || l.f == nil {
		return
	}
	_ = syscall.Flock(int(l.f.Fd()), syscall.LOCK_UN)
	_ = l.f.Close()
	l.f = nil
}
