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

	// Back-off after a refused send (see tick). Only the send step waits.
	refusals int // refused sends in a row
	skip     int // passes left in which the send step is skipped
}

func NewDaemon(engine *vault.VaultEngine, cfg *Config) *Daemon {
	return &Daemon{S: NewSyncer(engine, cfg), Log: os.Stderr}
}

// Run makes one pass at start-up and then one every poll interval. Only one
// daemon runs per place (same guard technique as the engine's inbox watcher).
// Passes run on the calling goroutine, so when Run returns nothing of it is
// left running: no goroutine, no git child, no lock. A cancel is noticed
// between the steps of a pass, kills a git command that is running, and ends
// a wait for the folder lock.
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
	// A stop signal that lands while a git command runs must end the daemon
	// quietly (exit 0), not with the 128+signal that the other commands use:
	// the hook turns it into a cancel, and Run returns nil.
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	// After a stop no further git command is started (the one place all of them
	// pass through is the Repo's gate). Passes run on this goroutine only.
	r := d.S.Repo
	prevGate := r.gate
	r.gate = func(args []string) error {
		if ctx.Err() != nil {
			return ErrStopped
		}
		if prevGate != nil {
			return prevGate(args)
		}
		return nil
	}
	defer func() { r.gate = prevGate }()
	// The same cancel also cuts short a git command that is already running
	// and a wait for the folder lock.
	prevStop := r.stop
	r.stop = ctx
	defer func() { r.stop = prevStop }()
	prevExit := exitOnSignal
	exitOnSignal = func(int) { cancel() }
	defer func() { exitOnSignal = prevExit }()
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

// maxWaitPasses caps the back-off after refused sends.
const maxWaitPasses = 100

func (d *Daemon) tick(ctx context.Context) error {
	r := d.S.Repo
	// After a refused send only the send step waits (1, 2, 4 ... passes);
	// update, recovery and stray handling run every pass.
	waiting := d.skip > 0
	if waiting {
		d.skip--
	}
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
	if waiting {
		drops = nil
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
	if waiting {
		drops = nil
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
			d.refusals, d.skip = 0, 0
			return nil
		case state == pushRace && attempt < d.S.Cfg.MaxRetries && ctx.Err() == nil:
			// The shared copy moved while sending: catch up, then send again.
			if _, err := r.Update(d.S.Engine.RebuildIndexes); err != nil {
				return err
			}
		case state == pushRace:
			return fmt.Errorf("inbox files not sent yet (they stay on disk): the shared copy kept moving")
		default:
			if err := ctx.Err(); err != nil {
				return err // stopped: end the pass quietly, nothing was refused
			}
			if state == pushRefused {
				d.backOff()
			}
			return fmt.Errorf("inbox files not sent yet (they stay on disk): %s %s", out.Line, out.Detail)
		}
	}
}

// backOff doubles the number of passes the send step waits after a refusal
// and logs one line when the wait changes. A lost push race does not come here.
func (d *Daemon) backOff() {
	d.refusals++
	d.skip = waitAfter(d.refusals)
	if d.skip != waitAfter(d.refusals-1) {
		fmt.Fprintf(d.Log, "vault-sync: send refused; waiting %d passes before the next try\n", d.skip)
	}
}

// waitAfter is the number of passes to wait after n refusals in a row:
// 1, 2, 4 ... capped at maxWaitPasses (0 before any refusal).
func waitAfter(n int) int {
	if n <= 0 {
		return 0
	}
	if n > 8 { // 1<<7 = 128 is already past the cap
		return maxWaitPasses
	}
	return min(1<<(n-1), maxWaitPasses)
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
