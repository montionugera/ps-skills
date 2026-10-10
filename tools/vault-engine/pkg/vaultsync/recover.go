package vaultsync

import (
	"bytes"
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
	// DirtyBefore maps every tracked path that was already modified or deleted
	// when the operation began to the hash of its content then ("" for a
	// deleted file). Markers written before this field existed load with a nil
	// map and behave as if no note was dirty.
	DirtyBefore map[string]string `json:"dirty_before,omitempty"`
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
		if localOnly(p) {
			continue
		}
		if code == "??" {
			m.UntrackedBefore = append(m.UntrackedBefore, p)
			continue
		}
		h, err := r.workHash(p)
		if err != nil {
			return nil, err
		}
		if m.DirtyBefore == nil {
			m.DirtyBefore = map[string]string{}
		}
		m.DirtyBefore[p] = h
	}
	sort.Strings(m.UntrackedBefore)
	// Keep the text of every hand-edited note now, before the operation can
	// write over it. A failure here stops the save before any marker exists.
	dirty := make([]string, 0, len(m.DirtyBefore))
	for p, h := range m.DirtyBefore {
		if h != "" { // a deleted note has no text to keep
			dirty = append(dirty, p)
		}
	}
	sort.Strings(dirty)
	for _, p := range dirty {
		if err := r.setAside(p, "hand edit found before a "+op+" began", false); err != nil {
			return nil, err
		}
	}
	data, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(filepath.Dir(r.markerPath()), 0755); err != nil {
		return nil, err
	}
	if err := writeFileAtomic(r.markerPath(), data); err != nil {
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

// workHash is the git hash of the file on disk, "" when there is no file.
func (r *Repo) workHash(p string) (string, error) {
	if _, err := os.Lstat(filepath.Join(r.Root, filepath.FromSlash(p))); os.IsNotExist(err) {
		return "", nil
	}
	return r.local("hash-object", "--", p)
}

// unchangedSinceBegin reports whether p was already modified or deleted when
// the operation began and still holds exactly that content: a hand edit the
// operation did not touch.
func (r *Repo) unchangedSinceBegin(m *Marker, p string) (bool, error) {
	was, dirty := m.DirtyBefore[p]
	if !dirty {
		return false, nil
	}
	now, err := r.workHash(p)
	return err == nil && now == was, err
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
	// A note that was already hand-edited at Begin and still holds that text
	// was not written by the operation: it is not part of this save.
	for p := range m.DirtyBefore {
		if _, listed := st[p]; !listed {
			continue
		}
		same, err := r.unchangedSinceBegin(m, p)
		if err != nil {
			return nil, err
		}
		if same {
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

// localOnly reports whether rel lies under a prefix that belongs to this place
// alone (the hub never accepts it). Recovery must never move such a file,
// whatever the vault's .gitignore says.
func localOnly(rel string) bool {
	for _, d := range DefaultLimits().DeniedPrefixes {
		if strings.HasPrefix(rel, d) {
			return true
		}
	}
	return false
}

// names runs a git command that prints NUL-separated paths and returns them
// exactly (Repo.local trims white space, which would damage a first name that
// starts with a space).
func (r *Repo) names(args ...string) ([]string, error) {
	res := r.run(localTimeout, args...)
	if res.Err != nil {
		return nil, fmt.Errorf("git %s: %w: %s", args[0], res.Err, strings.TrimSpace(res.Stderr))
	}
	var out []string
	for _, n := range strings.Split(res.Stdout, "\x00") {
		if n != "" {
			out = append(out, n)
		}
	}
	return out, nil
}

// blobAt returns the id of p in rev and whether rev has p. Only a clear answer
// from git counts: ls-tree succeeds with no entry when the path is not in the
// commit, and fails (error) for anything else - a killed or timed-out git, an
// unknown rev. The caller must treat an error as "do not know", never as absent.
func (r *Repo) blobAt(rev, p string) (string, bool, error) {
	res := r.run(localTimeout, "ls-tree", "-z", rev, "--", p)
	if res.Err != nil {
		return "", false, fmt.Errorf("git ls-tree %s: %w: %s", rev, res.Err, strings.TrimSpace(res.Stderr))
	}
	for _, rec := range strings.Split(res.Stdout, "\x00") {
		meta, name, ok := strings.Cut(rec, "\t")
		if !ok || name != p {
			continue
		}
		if f := strings.Fields(meta); len(f) == 3 {
			return f[2], true, nil
		}
	}
	return "", false, nil
}

// sameAs reports whether the file on disk holds exactly what rev holds for p
// (both absent counts as the same). Only a failed lookup of rev's version is
// an error; any doubt about the file on disk answers false (callers then keep a copy).
func (r *Repo) sameAs(p, rev string) (bool, error) {
	want, inRev, err := r.blobAt(rev, p)
	if err != nil {
		return false, err
	}
	if _, err := os.Lstat(filepath.Join(r.Root, filepath.FromSlash(p))); os.IsNotExist(err) {
		return !inRev, nil
	}
	have, err := r.local("hash-object", "--", p)
	if err != nil {
		return false, nil // doubt about the file's content: not the same; the caller keeps a copy
	}
	return inRev && have == want, nil
}

// restoreHandEdit copies a note changed outside the engine to quarantine and
// puts it back to the version in HEAD.
func (r *Repo) restoreHandEdit(p, code, why string) error {
	if err := r.setAside(p, why+" (git status "+strings.TrimSpace(code)+")", false); err != nil {
		return err
	}
	if strings.Contains(code, "A") { // staged by hand, not in the shared version
		_, err := r.local("rm", "--quiet", "--cached", "--", p)
		return err
	}
	_, err := r.local("checkout", "--quiet", "HEAD", "--", p)
	return err
}

// undo puts the folder back to the marker's starting point. A tracked note is
// put back without a copy only when its content is proven to be the save's
// own: it is on the caller's list and (if the save committed) equals the
// commit's version, or the operation is an update and it equals the incoming
// version. Anything else may be a hand edit and is copied to quarantine first.
func (r *Repo) undo(m *Marker, mine []string, sweep bool, rebuild func() error) error {
	preHead, err := r.Head()
	if err != nil {
		return err
	}
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
	committed := preHead != m.Base
	paths := make([]string, 0, len(st))
	for p := range st {
		if !localOnly(p) {
			paths = append(paths, p)
		}
	}
	sort.Strings(paths)
	for _, p := range paths {
		switch {
		case st[p] != "??": // a note the save changed or deleted: back to the start
			same, err := r.unchangedSinceBegin(m, p)
			if err != nil {
				return err
			}
			if same {
				// A hand edit that was already there at Begin and was not written
				// over: left exactly as it is. The next pass with no marker
				// (Recover -> quarantineHandEdits) copies it and puts the note back.
				continue
			}
			proven := false
			_, dirtyBefore := m.DirtyBefore[p]
			switch {
			case dirtyBefore:
				// Hand-edited at Begin, written over since: never proven; copy first.
			case m.Op == "update":
				if proven, err = r.sameAs(p, r.remoteRef()); err != nil {
					return err
				}
			case !sweep && wrote[p]:
				if committed {
					if proven, err = r.sameAs(p, preHead); err != nil {
						return err
					}
				} else {
					proven = true
				}
			}
			if !proven {
				if err := r.setAside(p, "changed during an interrupted "+m.Op+"; not proven to be written by it (git status "+strings.TrimSpace(st[p])+")", false); err != nil {
					return err
				}
			}
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
			if committed {
				_, inCommit, err := r.blobAt(preHead, p)
				if err != nil {
					return err
				}
				same := true
				if inCommit {
					if same, err = r.sameAs(p, preHead); err != nil {
						return err
					}
				}
				if inCommit && !same {
					if err := r.setAside(p, "no longer holds what the "+m.Op+" wrote; kept, not deleted", true); err != nil {
						return err
					}
					continue
				}
			}
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
		onHub, err := r.isAncestor(head, r.remoteRef())
		if err != nil {
			return err // a git failure is not an answer; decide nothing, keep the marker
		}
		if onHub {
			// The hub has it and the files are whole. The indexes may not be:
			// an update can stop after its fast-forward and before its rebuild.
			if err := rebuild(); err != nil {
				return err
			}
			return r.End()
		}
		// The local commit is the proof of what the save wrote.
		proven, err = r.names("diff", "-z", "--name-only", "--no-renames", m.Base, head)
		if err != nil {
			return err
		}
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
		if code != "??" && !localOnly(p) {
			paths = append(paths, p)
		}
	}
	sort.Strings(paths)
	for _, p := range paths {
		if err := r.restoreHandEdit(p, st[p], "changed outside the engine"); err != nil {
			return err
		}
	}
	return nil
}

// hasCopy reports whether _quarantine/<place>/ already holds a copy of rel
// with exactly this content.
func (r *Repo) hasCopy(rel string, data []byte) bool {
	dir := filepath.Join(r.Root, "_quarantine", r.Place)
	stamps, _ := os.ReadDir(dir)
	for _, st := range stamps {
		if old, err := os.ReadFile(filepath.Join(dir, st.Name(), filepath.FromSlash(rel))); err == nil && bytes.Equal(old, data) {
			return true
		}
	}
	return false
}

// writeFileAtomic writes data to path through a temp file, fsync and rename,
// so a crash leaves either the old file or the whole new one.
func writeFileAtomic(path string, data []byte) error {
	tmp := path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0644)
	if err != nil {
		return err
	}
	_, werr := f.Write(data)
	if serr := f.Sync(); werr == nil {
		werr = serr
	}
	if cerr := f.Close(); werr == nil {
		werr = cerr
	}
	if werr != nil {
		_ = os.Remove(tmp)
		return werr
	}
	return os.Rename(tmp, path)
}

// freshTarget makes the folder for dst and refuses a dst that already exists.
func freshTarget(dst string) error {
	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return err
	}
	if _, err := os.Lstat(dst); err == nil {
		return fmt.Errorf("quarantine target %s already exists", dst)
	}
	return nil
}

// setAside copies (or moves) a file into _quarantine/<place>/ and writes one
// report line. _quarantine/ is local to the place and never synced.
func (r *Repo) setAside(rel, why string, move bool) error {
	src := filepath.Join(r.Root, filepath.FromSlash(rel))
	dir := filepath.Join(r.Root, "_quarantine", r.Place)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}
	dst := filepath.Join(dir, time.Now().UTC().Format("20060102T150405.000000000"), filepath.FromSlash(rel))
	if move {
		if err := freshTarget(dst); err != nil {
			return err
		}
		if err := os.Rename(src, dst); err != nil {
			return err
		}
	} else if data, err := os.ReadFile(src); err == nil {
		// A copy of this exact text for this path is already kept (a second save
		// or the later no-marker pass over the same unchanged edit): keep one.
		if r.hasCopy(rel, data) {
			why += " (identical copy already in quarantine)"
		} else if err := freshTarget(dst); err != nil {
			return err
		} else if err := writeFileAtomic(dst, data); err != nil {
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
	// A note edited by hand that the incoming version also touches would block
	// the fast-forward: keep the edit in quarantine and put the note back.
	touched, err := r.names("diff", "-z", "--name-only", "--no-renames", head, hub)
	if err != nil {
		return false, err
	}
	st, err := r.Status()
	if err != nil {
		return false, err
	}
	for _, p := range touched {
		if code := st[p]; code != "" && code != "??" && !localOnly(p) {
			if err := r.restoreHandEdit(p, code, "changed outside the engine; an incoming version replaces it"); err != nil {
				return false, err
			}
		}
	}
	// An untracked local file with the name of an incoming file would block the
	// fast-forward. Identical content is a leftover of an interrupted update and
	// is dropped; different content is someone's unsent file and is set aside.
	added, err := r.names("diff", "-z", "--name-only", "--no-renames", "--diff-filter=A", head, hub)
	if err != nil {
		return false, err
	}
	if st, err = r.Status(); err != nil {
		return false, err
	}
	for _, p := range added {
		if st[p] != "??" {
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
