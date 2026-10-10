package vaultsync

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"

	"obsidian-vault-engine/pkg/vault"
)

// Daemon is the background program of one place ("vault-sync" in the design):
// it brings changes from the shared copy and sends inbox drops.
type Daemon struct {
	S   *Syncer
	Log io.Writer
}

func NewDaemon(engine *vault.VaultEngine, cfg *Config) *Daemon {
	return &Daemon{S: NewSyncer(engine, cfg), Log: os.Stderr}
}

// Run makes one pass at start-up and then one every poll interval. Only one
// daemon runs per place (same guard technique as the engine's inbox watcher).
// Passes run on the calling goroutine, so when Run returns nothing of it is
// left running: no goroutine, no git child, no lock. A cancel is noticed
// between the steps of a pass; a git command already started ends by its own
// time limit.
func (d *Daemon) Run(ctx context.Context) error {
	guardsDir := filepath.Join(d.S.Repo.Root, "_meta", "guards")
	if err := os.MkdirAll(guardsDir, 0755); err != nil {
		return err
	}
	guard, err := os.OpenFile(filepath.Join(guardsDir, "sync-daemon.guard"), os.O_CREATE|os.O_RDWR, 0644)
	if err != nil {
		return fmt.Errorf("opening sync daemon guard: %w", err)
	}
	defer guard.Close()
	if err := syscall.Flock(int(guard.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return fmt.Errorf("sync daemon already running: %w", err)
	}
	ticker := time.NewTicker(time.Duration(d.S.Cfg.PollIntervalMS) * time.Millisecond)
	defer ticker.Stop()
	for ctx.Err() == nil {
		if err := d.tick(ctx); err != nil && ctx.Err() == nil {
			fmt.Fprintf(d.Log, "vault-sync: %v\n", err)
		}
		select {
		case <-ctx.Done():
		case <-ticker.C:
		}
	}
	return nil
}

// Tick is one pass. When nothing is new, waiting or left over, it costs one
// small request to the shared copy and takes no lock.
func (d *Daemon) Tick() error { return d.tick(context.Background()) }

func (d *Daemon) tick(ctx context.Context) error {
	r := d.S.Repo
	hub, err := r.RemoteHead()
	if err != nil {
		return err
	}
	head, err := r.Head()
	if err != nil {
		return err
	}
	drops, strays, handEdit, err := d.scan()
	if err != nil {
		return err
	}
	if hub == head && !handEdit && len(drops) == 0 && len(strays) == 0 && !r.hasMarker() {
		return nil
	}
	if err := ctx.Err(); err != nil {
		return err
	}

	release, err := d.S.lockFolder()
	if err != nil {
		return err
	}
	defer release()
	held := time.Now()
	// Recovery comes first: an earlier lock holder may have left a save open.
	if err := r.Recover(d.S.Engine.RebuildIndexes); err != nil {
		return err
	}
	// Indexes are rebuilt inside Update, under the lock: RebuildIndexes does not
	// write atomically, so it must not run beside a save's own rebuild.
	moved, err := r.Update(d.S.Engine.RebuildIndexes)
	if err != nil {
		return err
	}
	if moved {
		fmt.Fprintf(d.Log, "vault-sync: updated to the newest version (lock held %d ms)\n", time.Since(held).Milliseconds())
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	// Look again now that the lock is held: recovery may have turned an
	// interrupted send back into ordinary waiting files.
	if drops, strays, _, err = d.scan(); err != nil {
		return err
	}
	// The lock is held and no save is in progress (Recover cleared the marker),
	// so a quiet untracked file outside _inbox/ was made by hand: it is not
	// sent, it is moved to _quarantine/<place>/ and reported.
	for _, p := range strays {
		if err := r.setAside(p, "created outside the engine and outside _inbox/", true); err != nil {
			return err
		}
	}
	if len(drops) == 0 {
		return nil
	}
	for attempt := 1; ; attempt++ {
		state, out := d.S.sendDrops(drops, attempt)
		switch {
		case state == pushOK:
			return nil
		case state == pushRace && attempt < d.S.Cfg.MaxRetries && ctx.Err() == nil:
			// The shared copy moved while sending: catch up, then send again.
			if _, err := r.Update(d.S.Engine.RebuildIndexes); err != nil {
				return err
			}
		case state == pushRace:
			return fmt.Errorf("inbox files not sent yet (they stay on disk): the shared copy kept moving")
		default:
			return fmt.Errorf("inbox files not sent yet (they stay on disk): %s %s", out.Line, out.Detail)
		}
	}
}

// scan lists the untracked files that have been quiet long enough to act on -
// inbox files to send (drops) and files outside _inbox/ to set aside (strays) -
// and says whether any tracked file differs from the recorded version. Files
// the engine keeps local to the place are never listed. A drop must be a plain
// file; anything else in an inbox is left where it is.
func (d *Daemon) scan() (drops, strays []string, handEdit bool, err error) {
	r := d.S.Repo
	st, err := r.Status()
	if err != nil {
		return nil, nil, false, err
	}
	quiet := time.Duration(d.S.Cfg.InboxQuietMS) * time.Millisecond
	for p, code := range st {
		if localOnly(p) {
			continue
		}
		if code != "??" {
			handEdit = true
			continue
		}
		info, err := os.Lstat(filepath.Join(r.Root, filepath.FromSlash(p)))
		if err != nil || time.Since(info.ModTime()) < quiet {
			continue // gone, or possibly still being written
		}
		if strings.HasPrefix(p, "_inbox/") {
			if info.Mode().IsRegular() {
				drops = append(drops, p)
			}
		} else {
			strays = append(strays, p)
		}
	}
	sort.Strings(drops)
	sort.Strings(strays)
	return drops, strays, handEdit, nil
}
