package vaultsync

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const markerRel = "_meta/guards/save-in-progress.json"

// Marker is the "save in progress" note. Whoever takes the folder lock next
// looks for it first: present means the previous holder was interrupted.
type Marker struct {
	Op              string   `json:"op"`
	Actor           string   `json:"actor"`
	Place           string   `json:"place"`
	PID             int      `json:"pid"`
	StartedAt       string   `json:"started_at"`
	Base            string   `json:"base"`
	UntrackedBefore []string `json:"untracked_before"`
}

func (r *Repo) markerPath() string { return filepath.Join(r.Root, filepath.FromSlash(markerRel)) }

func (r *Repo) hasMarker() bool {
	_, err := os.Stat(r.markerPath())
	return err == nil
}

func (r *Repo) readMarker() (*Marker, error) {
	data, err := os.ReadFile(r.markerPath())
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var m Marker
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, fmt.Errorf("unreadable save marker %s: %w", markerRel, err)
	}
	return &m, nil
}

// Begin writes the marker before anything is changed. It records where the
// folder stood and which files were already untracked, so that a save never
// sends a file that was lying there before it started.
func (r *Repo) Begin(op, actor string) (*Marker, error) {
	base, err := r.Head()
	if err != nil {
		return nil, err
	}
	st, err := r.Status()
	if err != nil {
		return nil, err
	}
	m := &Marker{Op: op, Actor: actor, Place: r.Place, PID: os.Getpid(),
		StartedAt: time.Now().UTC().Format(time.RFC3339), Base: base}
	for p, code := range st {
		if code == "??" {
			m.UntrackedBefore = append(m.UntrackedBefore, p)
		}
	}
	sort.Strings(m.UntrackedBefore)
	data, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return nil, err
	}
	// Temp file + fsync + rename, as CommitRecord does for notes.
	if err := os.MkdirAll(filepath.Dir(r.markerPath()), 0755); err != nil {
		return nil, err
	}
	tmp := r.markerPath() + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0644)
	if err != nil {
		return nil, err
	}
	if _, err := f.Write(data); err != nil {
		_ = f.Close()
		return nil, err
	}
	if err := f.Sync(); err != nil {
		_ = f.Close()
		return nil, err
	}
	_ = f.Close()
	if err := os.Rename(tmp, r.markerPath()); err != nil {
		return nil, err
	}
	return m, nil
}

func (r *Repo) End() error {
	err := os.Remove(r.markerPath())
	if os.IsNotExist(err) {
		return nil
	}
	return err
}

// changed lists what differs from the marker's starting point. It leaves out
// files that were already untracked then, and untracked files under _inbox/
// (drops that arrived meanwhile): neither was written by the operation.
func (r *Repo) changed(m *Marker) (map[string]string, error) {
	st, err := r.Status()
	if err != nil {
		return nil, err
	}
	for _, p := range m.UntrackedBefore {
		if st[p] == "??" {
			delete(st, p)
		}
	}
	for p, code := range st {
		if code == "??" && strings.HasPrefix(p, "_inbox/") {
			delete(st, p)
		}
	}
	return st, nil
}

// Undo takes back one save whose written files are known (a refused send, a
// lost race): the local commit (if any), changed notes, and exactly the
// untracked files in written. No other untracked file is touched.
func (r *Repo) Undo(m *Marker, written []string, rebuild func() error) error {
	return r.undo(m, written, false, rebuild)
}

// undoUnproven takes back a save whose written files are not known (a crash,
// or an operation that failed half-way). Only proven files - those of the
// save's own local commit - are removed. Every other untracked file outside
// _inbox/ is moved to _quarantine/<place>/ and reported: it cannot be proven
// that the save wrote it, so it is never deleted.
func (r *Repo) undoUnproven(m *Marker, proven []string, rebuild func() error) error {
	return r.undo(m, proven, true, rebuild)
}

func (r *Repo) undo(m *Marker, mine []string, sweep bool, rebuild func() error) error {
	if _, err := r.local("reset", "--quiet", "--mixed", m.Base); err != nil {
		return err
	}
	st, err := r.Status()
	if err != nil {
		return err
	}
	before := make(map[string]bool, len(m.UntrackedBefore))
	for _, p := range m.UntrackedBefore {
		before[p] = true
	}
	wrote := make(map[string]bool, len(mine))
	for _, p := range mine {
		wrote[p] = true
	}
	paths := make([]string, 0, len(st))
	for p := range st {
		paths = append(paths, p)
	}
	sort.Strings(paths)
	for _, p := range paths {
		switch {
		case st[p] != "??": // a note the save changed or deleted: back to the start
			if _, err := r.local("checkout", "--quiet", m.Base, "--", p); err != nil {
				return err
			}
		case strings.HasPrefix(p, "_inbox/"): // a drop is never removed or moved by an undo
		case wrote[p] && before[p]:
			// The file was lying there before the save started, so the save's
			// claim to have written it cannot be trusted: keep it.
			if err := r.setAside(p, "was already untracked before the "+m.Op+" started; kept, not deleted", true); err != nil {
				return err
			}
		case wrote[p]:
			if err := os.Remove(filepath.Join(r.Root, filepath.FromSlash(p))); err != nil && !os.IsNotExist(err) {
				return err
			}
		case sweep && m.Op != "update":
			// An interrupted update leaves only copies of incoming files; the
			// next Update compares them with the shared copy itself.
			if err := r.setAside(p, "found outside _inbox/ after an interrupted "+m.Op+"; not proven to be written by it", true); err != nil {
				return err
			}
		}
	}
	return rebuild()
}

// Recover settles what the previous lock holder left. Marker present: the
// holder was interrupted; if it had made a commit, the hub is asked whether
// that commit arrived. No marker but changed notes: someone edited by hand.
func (r *Repo) Recover(rebuild func() error) error {
	// A killed git may have left its own lock file; we hold the folder lock.
	_ = os.Remove(filepath.Join(r.Root, ".git", "index.lock"))
	m, err := r.readMarker()
	if err != nil {
		return err
	}
	if m == nil {
		return r.quarantineHandEdits()
	}
	head, err := r.Head()
	if err != nil {
		return err
	}
	var proven []string
	if head != m.Base {
		if err := r.Fetch(); err != nil {
			return err // cannot know yet whether it arrived; decide nothing
		}
		if r.isAncestor(head, r.remoteRef()) {
			// The hub has it and the files are whole. The indexes may not be:
			// an update can stop after its fast-forward and before its rebuild.
			if err := rebuild(); err != nil {
				return err
			}
			return r.End()
		}
		// The local commit is the proof of what the save wrote.
		names, err := r.local("diff", "-z", "--name-only", "--no-renames", m.Base, head)
		if err != nil {
			return err
		}
		proven = strings.Split(names, "\x00")
	}
	if err := r.undoUnproven(m, proven, rebuild); err != nil {
		return err
	}
	return r.End()
}

// quarantineHandEdits keeps a copy of every note that was changed outside the
// engine and puts the note back to the shared version.
func (r *Repo) quarantineHandEdits() error {
	st, err := r.Status()
	if err != nil {
		return err
	}
	var paths []string
	for p, code := range st {
		if code != "??" {
			paths = append(paths, p)
		}
	}
	sort.Strings(paths)
	for _, p := range paths {
		if err := r.setAside(p, "changed outside the engine (git status "+strings.TrimSpace(st[p])+")", false); err != nil {
			return err
		}
		if strings.Contains(st[p], "A") { // staged by hand, not in the shared version
			if _, err := r.local("rm", "--quiet", "--cached", "--", p); err != nil {
				return err
			}
			continue
		}
		if _, err := r.local("checkout", "--quiet", "HEAD", "--", p); err != nil {
			return err
		}
	}
	return nil
}

// setAside copies (or moves) a file into _quarantine/<place>/ and writes one
// report line. _quarantine/ is local to the place and never synced.
func (r *Repo) setAside(rel, why string, move bool) error {
	src := filepath.Join(r.Root, filepath.FromSlash(rel))
	dir := filepath.Join(r.Root, "_quarantine", r.Place)
	dst := filepath.Join(dir, time.Now().UTC().Format("20060102T150405.000000000"), filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return err
	}
	if _, err := os.Lstat(dst); err == nil {
		return fmt.Errorf("quarantine target %s already exists", dst)
	}
	if move {
		if err := os.Rename(src, dst); err != nil {
			return err
		}
	} else if data, err := os.ReadFile(src); err == nil {
		if err := os.WriteFile(dst, data, 0644); err != nil {
			return err
		}
	} else if !os.IsNotExist(err) {
		return err // cannot keep the text, so the caller must not overwrite the note
	} // a deleted note has no text to keep; the report line still records it
	line := fmt.Sprintf("%s QUARANTINED %s: %s\n", time.Now().UTC().Format(time.RFC3339), rel, why)
	fmt.Fprint(os.Stderr, "vault-sync: "+line)
	f, err := os.OpenFile(filepath.Join(dir, "REPORT.log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = f.WriteString(line)
	return err
}

// Update brings the folder to the hub's newest version in one fast-forward.
// It reports whether the folder moved, and rebuilds the indexes if it did.
func (r *Repo) Update(rebuild func() error) (bool, error) {
	if err := r.Fetch(); err != nil {
		return false, err
	}
	head, err := r.Head()
	if err != nil {
		return false, err
	}
	hub, err := r.local("rev-parse", r.remoteRef())
	if err != nil {
		return false, err
	}
	if head == hub {
		return false, nil
	}
	if _, err := r.Begin("update", "sync"); err != nil {
		return false, err
	}
	// An untracked local file with the name of an incoming file would block the
	// fast-forward. Identical content is a leftover of an interrupted update and
	// is dropped; different content is someone's unsent file and is set aside.
	added, err := r.local("diff", "-z", "--name-only", "--no-renames", "--diff-filter=A", head, hub)
	if err != nil {
		return false, err
	}
	st, err := r.Status()
	if err != nil {
		return false, err
	}
	for _, p := range strings.Split(added, "\x00") {
		if p == "" || st[p] != "??" {
			continue
		}
		mine, err1 := r.local("hash-object", "--", p)
		theirs, err2 := r.local("rev-parse", hub+":"+p)
		if err1 == nil && err2 == nil && mine == theirs {
			if err := os.Remove(filepath.Join(r.Root, filepath.FromSlash(p))); err != nil {
				return false, err
			}
			continue
		}
		if err := r.setAside(p, "an incoming file has the same name", true); err != nil {
			return false, err
		}
	}
	if _, err := r.local("merge", "--ff-only", "--quiet", hub); err != nil {
		return false, err
	}
	// The indexes are rebuilt before the marker is cleared: if this run stops
	// here, the next lock holder finds the marker and rebuilds them (Recover).
	if err := rebuild(); err != nil {
		return false, err
	}
	return true, r.End()
}
