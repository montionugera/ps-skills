package vaultsync

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"obsidian-vault-engine/pkg/vault"
)

// Outcome is the fixed last line of a save and its exit code.
type Outcome struct {
	Line   string
	Exit   int
	Detail string
}

const (
	ExitEngineError    = 1
	ExitNoteChanged    = 3
	ExitNoConnection   = 4
	ExitTooLarge       = 5
	ExitTypeNotAllowed = 6
	ExitBusy           = 7
)

func saved() Outcome { return Outcome{Line: "SAVED"} }

func refused(code string, exit int, detail string) Outcome {
	return Outcome{Line: "REFUSED " + code, Exit: exit, Detail: detail}
}

// violationOutcome maps a hub label to the fixed outcome line. The hub prints
// "engine-error" (hubFault in hub.go) when it could not read or compute
// something itself; any label this engine does not know is read as an engine
// error too, never as a success.
func violationOutcome(v *Violation) Outcome {
	switch v.Code {
	case "too-large":
		return refused("too-large", ExitTooLarge, v.Message)
	case "type-not-allowed":
		return refused("type-not-allowed", ExitTypeNotAllowed, v.Message)
	case "engine-error":
		return refused("engine-error", ExitEngineError, v.Message)
	default:
		return refused("engine-error", ExitEngineError, "the shared copy refused with an unknown label "+v.Code+": "+v.Message)
	}
}

func errorOutcome(err error) Outcome {
	var v *Violation
	switch {
	case errors.As(err, &v) && v != nil:
		return violationOutcome(v)
	case errors.Is(err, vault.ErrConflict):
		return refused("note-changed", ExitNoteChanged, err.Error())
	case errors.Is(err, ErrNoConnection):
		return refused("no-connection", ExitNoConnection, err.Error())
	case errors.Is(err, ErrLockTimeout), errors.Is(err, vault.ErrLockContention):
		return refused("busy", ExitBusy, err.Error())
	default:
		return refused("engine-error", ExitEngineError, err.Error())
	}
}

// Hooks are test seams. All are nil in production.
type Hooks struct {
	BeforePush func(attempt int)
	PushResult func(attempt int, res gitResult) gitResult
}

type pushState int

const (
	pushOK pushState = iota
	pushRace
	pushRefused
	pushUnconfirmed
)

// Syncer is the save step: get the newest version, save, send, as one locked step.
type Syncer struct {
	Repo   *Repo
	Cfg    *Config
	Engine *vault.VaultEngine
	Limits Limits
	Hooks  Hooks
}

func NewSyncer(engine *vault.VaultEngine, cfg *Config) *Syncer {
	return &Syncer{Repo: NewRepo(engine.Root, cfg), Cfg: cfg, Engine: engine, Limits: DefaultLimits()}
}

// Save runs one operation as a save step and returns the operation's own
// success message together with the fixed outcome.
func (s *Syncer) Save(op Op) (string, Outcome) {
	if op.Refuse != "" {
		return "", refused("engine-error", ExitEngineError, op.Refuse)
	}
	if op.NoFingerprint {
		return "", refused("note-changed", ExitNoteChanged, "a save in a shared folder needs the fingerprint (sha256) from read-record; read the note and save again")
	}
	release, err := s.lockFolder()
	if err != nil {
		return "", errorOutcome(err)
	}
	defer release()
	if err := s.Repo.Recover(s.Engine.RebuildIndexes); err != nil {
		return "", errorOutcome(err)
	}
	for attempt := 1; attempt <= s.Cfg.MaxRetries; attempt++ {
		msg, out, retry := s.attempt(op, attempt)
		if !retry {
			return msg, out
		}
	}
	return "", refused("busy", ExitBusy, fmt.Sprintf("the shared copy kept moving; gave up after %d tries", s.Cfg.MaxRetries))
}

// lockFolder takes the folder lock and hands it to the Repo so that git
// children inherit it. The returned function undoes both. Everything that
// changes the folder comes through here, so this is also where a folder that
// is not its own repository is refused, before the lock and before any change.
func (s *Syncer) lockFolder() (release func(), err error) {
	if err := s.Repo.ownRepository(); err != nil {
		return nil, err
	}
	lock, err := AcquireFolderLockContext(s.Repo.stopCtx(), s.Repo.Root, time.Duration(s.Cfg.LockTimeoutMS)*time.Millisecond)
	if err != nil {
		return nil, err
	}
	s.Repo.lock = lock
	return func() {
		s.Repo.lock = nil
		lock.Release()
	}, nil
}

// begin opens a marker, but never over an existing one: Begin overwrites
// silently, so a marker left by an unsettled save must be settled by Recover first.
func (s *Syncer) begin(op, actor string) (*Marker, error) {
	if s.Repo.hasMarker() {
		return nil, errors.New("a save is still unsettled in this folder; it is settled on the next command")
	}
	return s.Repo.Begin(op, actor)
}

func (s *Syncer) attempt(op Op, attempt int) (string, Outcome, bool) {
	r := s.Repo
	if _, err := r.Update(s.Engine.RebuildIndexes); err != nil {
		return "", errorOutcome(err), false
	}
	key := op.Key
	if op.KeyFn != nil {
		var err error
		if key, err = op.KeyFn(r); err != nil {
			return "", errorOutcome(err), false // never a shortened key: it could match another save
		}
	}
	if key != "" {
		done, err := s.alreadySaved(key)
		if err != nil {
			return "", errorOutcome(err), false // never guess: a second create would duplicate
		}
		if done {
			return "Already saved by an earlier try\n", saved(), false
		}
	}
	if op.Drop != "" {
		if out, ok := s.checkDropVisible(op.Drop); !ok {
			return "", out, false
		}
		switch state, out := s.sendDrops([]string{op.Drop}, attempt); state {
		case pushOK:
		case pushRace:
			return "", Outcome{}, true
		default:
			return "", out, false
		}
	}
	m, err := s.begin(op.Name, op.Actor)
	if err != nil {
		return "", errorOutcome(err), false
	}
	// Until the list of written files exists, an undo proves nothing about
	// the files it finds: it moves them aside instead of removing them.
	undo := func() error { return r.undoUnproven(m, nil, s.Engine.RebuildIndexes) }
	fail := func(out Outcome) (string, Outcome, bool) {
		if err := undo(); err != nil {
			return "", errorOutcome(err), false // the marker stays; the next command recovers
		}
		_ = r.End()
		return "", out, false
	}
	msg, opErr := op.Run()
	if opErr != nil {
		return fail(errorOutcome(opErr))
	}
	ch, err := r.changed(m)
	if err != nil {
		return fail(errorOutcome(err))
	}
	if len(ch) == 0 { // e.g. a capture that was already recorded
		_ = r.End()
		return msg, saved(), false
	}
	written := make([]string, 0, len(ch))
	for p := range ch {
		written = append(written, p)
	}
	sort.Strings(written)
	// From here on the undo removes exactly these files and no other.
	undo = func() error { return r.Undo(m, written, s.Engine.RebuildIndexes) }
	if v := s.precheck(written); v != nil {
		return fail(violationOutcome(v))
	}
	state, out := s.record(written, op.Actor, "vault: "+op.Name, key, m, attempt)
	switch state {
	case pushOK:
		_ = r.End()
		return msg, saved(), false
	case pushUnconfirmed:
		return "", out, false // marker and local commit stay until the hub can be asked
	case pushRace:
		if err := undo(); err != nil {
			return "", errorOutcome(err), false
		}
		_ = r.End()
		return "", Outcome{}, true
	default:
		return fail(out)
	}
}

// alreadySaved looks for the one-time key in what the hub accepted during the
// last 24 hours. The folder is up to date when this is called.
func (s *Syncer) alreadySaved(key string) (bool, error) {
	out, err := s.Repo.local("log", "-1", "--format=%H", "--since=24.hours.ago", "--fixed-strings",
		"--grep=Vault-Op-Key: "+key, s.Repo.remoteRef())
	if err != nil {
		return false, err
	}
	return out != "", nil
}

// checkDropVisible refuses an ingest whose inbox file git cannot see (ignored,
// or not a regular file): ingest deletes its source, so an unseen file would
// be lost for good if the save were undone. A file already gone passes (a
// retry of a save that arrived).
func (s *Syncer) checkDropVisible(rel string) (Outcome, bool) {
	r := s.Repo
	if _, err := os.Lstat(filepath.Join(r.Root, filepath.FromSlash(rel))); err != nil {
		return Outcome{}, true
	}
	st, err := r.Status()
	if err != nil {
		return errorOutcome(err), false
	}
	if st[rel] != "" {
		return Outcome{}, true
	}
	tracked, err := r.local("ls-files", "--", rel)
	if err != nil {
		return errorOutcome(err), false
	}
	if tracked == "" {
		return refused("engine-error", ExitEngineError, ingestOutsideInbox), false
	}
	return Outcome{}, true
}

// precheck is the early version of the hub's door check, on what was written.
func (s *Syncer) precheck(paths []string) *Violation {
	if len(paths) > s.Limits.MaxFilesPerPush {
		return &Violation{"too-large", fmt.Sprintf("the save changes %d files; limit max_files_per_push=%d", len(paths), s.Limits.MaxFilesPerPush)}
	}
	for _, p := range paths {
		info, err := os.Stat(filepath.Join(s.Repo.Root, filepath.FromSlash(p)))
		if err != nil {
			continue // deleted by the operation
		}
		if v := s.Limits.CheckFile(p, info.Size()); v != nil {
			return v
		}
	}
	return nil
}

// record commits exactly paths and sends them. An empty list is refused by
// Repo.Commit itself (ErrNothingToCommit). On pushRace and pushRefused the
// caller must undo; on pushUnconfirmed the caller must leave everything as it is.
func (s *Syncer) record(paths []string, actor, subject, key string, m *Marker, attempt int) (pushState, Outcome) {
	r := s.Repo
	if err := r.Commit(paths, actor, subject, key); err != nil {
		return pushRefused, errorOutcome(err)
	}
	if s.Hooks.BeforePush != nil {
		s.Hooks.BeforePush(attempt)
	}
	res := r.run(r.NetTimeout, "push", "--porcelain", r.Remote, "HEAD:refs/heads/"+r.Branch)
	if s.Hooks.PushResult != nil {
		res = s.Hooks.PushResult(attempt, res)
	}
	if res.Err == nil {
		return pushOK, saved()
	}
	all := res.Stdout + res.Stderr
	if i := strings.Index(all, "vault-hub: REFUSED "); i >= 0 {
		line, _, _ := strings.Cut(all[i+len("vault-hub: REFUSED "):], "\n")
		code, text, _ := strings.Cut(line, ": ")
		return pushRefused, violationOutcome(&Violation{Code: code, Message: strings.TrimSpace(text)})
	}
	if strings.Contains(all, "pack exceeds maximum allowed size") {
		return pushRefused, refused("too-large", ExitTooLarge, "the upload is larger than the shared copy accepts (max_input_bytes)")
	}
	if strings.Contains(all, "\t[rejected]") {
		return pushRace, Outcome{}
	}
	// Two sends at the same instant: git words the lost race differently. The
	// shared copy took nothing in, so it is tried again like any lost race.
	// Every other [remote rejected] reason stays an unclear answer. The status
	// line is read from git's own output only, never from what a hook printed.
	if strings.Contains(res.Stdout, "\t[remote rejected]") &&
		(strings.Contains(all, "incorrect old value provided") || strings.Contains(all, "cannot lock ref")) {
		time.Sleep(500 * time.Millisecond) // the other send may still hold the lock
		return pushRace, Outcome{}
	}
	// Unclear answer: never guess, ask the shared copy. If it does not show our
	// commit the send may still be accepted a moment later (a time limit, a cut
	// connection), so it is never answered as refused: the marker and the local
	// commit stay and the next command settles it.
	timedOut := errors.Is(res.Err, ErrTimedOut)
	// From here the commit may be on the hub: a git failure while asking is
	// not an answer, so nothing is undone (pushUnconfirmed keeps the marker).
	head, err := r.Head()
	if err != nil {
		return pushUnconfirmed, errorOutcome(err)
	}
	for try := 0; try < 3; try++ {
		if err := r.Fetch(); err != nil {
			if errors.Is(err, ErrStopped) {
				break // the program is stopping: asking again cannot help; the answer stays "not confirmed"
			}
			time.Sleep(500 * time.Millisecond)
			continue
		}
		onHub, err := r.isAncestor(head, r.remoteRef())
		if err != nil {
			return pushUnconfirmed, errorOutcome(err)
		}
		if onHub {
			return pushOK, saved()
		}
		hub, err := r.local("rev-parse", r.remoteRef())
		if err != nil {
			return pushUnconfirmed, errorOutcome(err)
		}
		if hub != m.Base {
			return pushRace, Outcome{}
		}
		break // the shared copy did not move and does not show the commit
	}
	why := "the connection broke while sending"
	if timedOut {
		why = "the send ran into its time limit"
	}
	if text := strings.TrimSpace(res.Stderr); text != "" {
		why += " (git said: " + text + ")"
	}
	return pushUnconfirmed, refused("no-connection", ExitNoConnection,
		why+" ["+res.Err.Error()+"]; whether it arrived is settled on the next command")
}

// sendDrops sends inbox files the shared copy does not have yet. A file that
// breaks a limit is moved to _quarantine/<place>/. A drop is never deleted: on
// any failure it stays on disk as an ordinary file.
func (s *Syncer) sendDrops(drops []string, attempt int) (pushState, Outcome) {
	r := s.Repo
	st, err := r.Status()
	if err != nil {
		return pushRefused, errorOutcome(err)
	}
	var send []string
	var bad *Violation
	for _, p := range drops {
		if st[p] != "??" {
			continue // already sent, or gone
		}
		info, err := os.Stat(filepath.Join(r.Root, filepath.FromSlash(p)))
		if err != nil {
			continue
		}
		if v := s.Limits.CheckFile(p, info.Size()); v != nil {
			if err := r.setAside(p, "inbox drop refused: "+v.Message, true); err != nil {
				return pushRefused, errorOutcome(err)
			}
			bad = v
			continue
		}
		send = append(send, p)
	}
	if len(send) > s.Limits.MaxFilesPerPush {
		send = send[:s.Limits.MaxFilesPerPush] // the rest goes with the next pass
	}
	if len(send) > 0 {
		m, err := s.begin("inbox", "inbox")
		if err != nil {
			return pushRefused, errorOutcome(err)
		}
		state, out := s.record(send, "inbox", "vault: inbox drop", "", m, attempt)
		if state == pushUnconfirmed {
			return state, out
		}
		if state != pushOK {
			// Undo never removes a file under _inbox/: the drops stay on disk.
			if err := r.Undo(m, send, s.Engine.RebuildIndexes); err != nil {
				return pushRefused, errorOutcome(err)
			}
			_ = r.End()
			return state, out
		}
		_ = r.End()
	}
	if bad != nil {
		return pushRefused, violationOutcome(bad)
	}
	return pushOK, saved()
}
