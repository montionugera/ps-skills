# Vault sync: fix the 32 open review findings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fix the 32 open findings from the vault sync review notes, as a feature in release 1.12, tested and reviewed, without changing anything on the main branch.

**Architecture:** No component, flow or data shape changes. Five small behaviour changes land in the sync package (`recover.go`, `hub.go`, `syncer.go`), each written test-first; everything else is test, script and wording fixes in the same few files. The work is six ordered tasks so that engine changes land before the tests that lean on them, and the full sync harness runs once at the end.

**Tech Stack:** Go 1.27 (module `obsidian-vault-engine` in `tools/vault-engine/`), the standard library only, `git` on the command line, bash for the two scripts.

**Spec:** `/Users/pasitnusso/workspace/docs/superpowers/specs/2026-10-13-vault-sync-fix-later-findings-design.md`

**Item list:** `.claude/idea_backlog/I-032-triage-the-vault-sync-fix-later-review-n/open-findings.md` (items A1 to A32).

## Global Constraints

- **Worktree, the only place to work:** `/Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin` (branch `feat/F-025`). Never edit, commit on or push to the main branch.
- **Scope:** only files under `tools/vault-engine/`, and the rules text `templates/vault-rules/AGENTS.section.md`. That file lives inside the engine folder: its real path is `tools/vault-engine/templates/vault-rules/AGENTS.section.md` (there is no top-level `templates/vault-rules/`).
- **The nine "not a defect" findings stay closed** (they are listed in `triage.md` of idea I-032). Do not "fix" them.
- **Never touch `/Users/pasitnusso/workspace/agentic-vault`** (the real vault). Not to read, not to write, not as a test folder.
- **Do not run `test_e2e.sh`.**
- **Do not redirect `HOME` for tests** (no `HOME=...` in a command, no `t.Setenv("HOME", ...)`).
- **No `git commit --amend`.** Every fix is a new commit on top.
- **No drive-by refactors.** Change only what an item names. A real problem found outside the items becomes one line in the task report, not a change.
- **Every commit message names the items it addresses**, for example `fix(vault-engine): A4 Undo refuses when the marker file is missing`. If your harness prescribes an attribution trailer, end the message with it.
- **Always pass `-timeout 40m` to `go test`.**
- Paths in this plan are relative to the worktree root unless they start with `/`. Go commands run from `tools/vault-engine/`. The main package is `pkg/vaultsync/`.
- Baseline: `cd tools/vault-engine && go vet ./...` is clean before any change. `gofmt -l pkg/vaultsync cmd scripts` prints nothing; keep it that way (`gofmt -l .` also lists two old files in `pkg/vault/`, which are not ours to touch).
- Every code block in this plan was compiled and run against a copy of the module on 2026-10-13 (Go 1.27.2, darwin/arm64). "Expected" lines quote what that run printed.

**How each task ends (the phase gate).** After the last commit of a task: (1) run the task's `verify-cmd`; (2) get an independent review of the task's diff (`git diff <commit before the task>..HEAD`) from a reviewer that did not write it: the `code-reviewer` agent plus the `golang-reviewer` agent; (3) fix every finding in new commits, each naming its item; (4) run the `verify-cmd` again. Only then start the next task. This is not a permission stop; do it and move on.

---

## Task 1: Recovery and undo (A4, A5, A6, A7, A15, A16, A17, A18)

**Files:**
- Modify: `tools/vault-engine/pkg/vaultsync/recover.go`
- Test: `tools/vault-engine/pkg/vaultsync/recover_test.go`

**Interfaces (as they are in the code now):**
- `func (r *Repo) Undo(m *Marker, written []string, rebuild func() error) error` (recover.go:197). Behaviour changes (A4); signature stays.
- `func (r *Repo) undo(m *Marker, mine []string, sweep bool, rebuild func() error) error` (recover.go:316). Error text changes (A6).
- `func (r *Repo) writeMarker(m *Marker) error` (recover.go:113). Error text changes (A6).
- `func (r *Repo) Update(rebuild func() error) (bool, error)` (recover.go:591). Behaviour changes (A5).
- `func writeFileAtomic(path string, data []byte) error` (recover.go:516). Behaviour changes (A7). Callers: `writeMarker`, `setAside` (recover.go:572), `chargeDaily` (hub.go:237).
- New: `var syncDir = func(dir string) error` (A7).
- Relied on: `func (r *Repo) readMarker() (*Marker, error)`, `func (r *Repo) hasMarker() bool`, `func (r *Repo) markerPath() string`, `func (r *Repo) Begin(op, actor string) (*Marker, error)`, `func (r *Repo) Recover(rebuild func() error) error`, `func (r *Repo) Commit(paths []string, actor, subject, key string) error`, `func (r *Repo) Head() (string, error)`, the test seam `Repo.gate func(args []string) error`, `var ErrStopped`.
- Test helpers that already exist: `newWorld(t)` (returns `world{Root, Hub, Mac, Srv}`), `newRepo(t, root)`, `lockFor(t, r)`, `noRebuild`, `writeFile(t, path, data)`, `fixtureNote(t, root, id)`, `quarantined(t, root, place, rel)`, `reportLines(t, root, place)`, `pushAs(t, dir, place, refspec)`.

**Worker brief**
- `cwd`: `/Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin`
- `verify-cmd`:
  ```bash
  cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestUndo_|TestRecover_|TestUpdate_|TestBegin_|TestWriteFileAtomic_|TestChargeDaily_|TestSave_' && test "$(grep -c -E '^func (TestUndo_RefusesWhenTheMarkerFileIsGone|TestUndo_RefusesAMarkerThatBelongsToAnotherSave|TestUndo_WhenTheUndoStartCannotBeRecordedNothingIsChanged|TestUpdate_AnInterruptedCompareLeavesTheClashingFileWhereItIs|TestUpdate_AClashingFileThatCannotBeHashedIsStillSetAside|TestWriteFileAtomic_SyncsTheFolderAfterTheRenameAndReturnsItsError)\(' pkg/vaultsync/recover_test.go)" -eq 6 && test "$(grep -c 'original, _ := os.ReadFile' pkg/vaultsync/recover_test.go)" -eq 3
  ```
- `acceptance`:
  1. `Undo` returns an error and changes nothing when no marker file is on disk, and when the marker on disk belongs to another save.
  2. An `Update` whose file comparison is cut by a stop (`ErrStopped`) leaves the local file in place, writes no REPORT line, and returns the stop error. A comparison that fails for any other reason still moves the file aside, as today.
  3. `writeFileAtomic` syncs the parent folder after the rename and returns a folder-sync error.
  4. No `os.ReadFile` error is dropped at the six places A17 names; `undoAfterFailedPass` asserts that the folder was moved back.

### A4 and half of A16: Undo refuses when the marker file is missing

- [ ] **Step 1: Check who calls Undo without a marker on disk. STOP if a production caller does.**

  Run from the worktree root:
  ```bash
  grep -rn '\.Undo(' tools/vault-engine --include='*.go'
  grep -rn 'r\.End()\|\.End()' tools/vault-engine/pkg/vaultsync/syncer.go
  ```
  Expected: two production calls, both in `pkg/vaultsync/syncer.go` (`:217`, inside `attempt`, and `:417`, inside `sendDrops`), and twelve calls in `pkg/vaultsync/recover_test.go`.

  Read each one and answer: is `_meta/guards/save-in-progress.json` on disk when `Undo` runs?
  - `syncer.go:217`: the marker `m` comes from `s.begin` at `:185` in the same locked step; every `r.End()` in `attempt` comes after the undo. Marker is on disk.
  - `syncer.go:417`: the marker comes from `s.begin("inbox", "inbox")` at `:407`; `r.End()` at `:420` comes after the undo. Marker is on disk.
  - Tests: every one calls `r.Begin` first and calls neither `r.End()` nor a `Recover` that succeeds before its `Undo`.

  **If you find a production caller (not a test) that can reach `Undo` after the marker file was removed: STOP. Change nothing. Report the file, the line and the path that leads there.** If only a test does, list it in your report and carry on (the test is then updated as part of this item).

- [ ] **Step 2: Write the failing test.** Append to `pkg/vaultsync/recover_test.go`:
  ```go
  // A Recover that succeeds settles the save and removes the marker. An Undo
  // that still holds the old marker and list must then refuse: with no record on
  // disk nothing proves the list, and a listed file may be a person's by now.
  func TestUndo_RefusesWhenTheMarkerFileIsGone(t *testing.T) {
  	w := newWorld(t)
  	r := newRepo(t, w.Mac)
  	lockFor(t, r)
  	m, err := r.Begin("commit", "agent-olivier")
  	if err != nil {
  		t.Fatalf("begin: %v", err)
  	}
  	if err := r.Recover(noRebuild); err != nil {
  		t.Fatalf("recover: %v", err)
  	}
  	if r.hasMarker() {
  		t.Fatalf("a successful recover must remove the marker")
  	}
  	p := filepath.Join(w.Mac, "01_Ideas", "new.md")
  	writeFile(t, p, []byte("typed by a person after the save was settled\n"))
  	err = r.Undo(m, []string{"01_Ideas/new.md"}, noRebuild)
  	if err == nil || !strings.Contains(err.Error(), "nothing was changed") {
  		t.Fatalf("undo with no marker on disk must refuse and say nothing was changed, got %v", err)
  	}
  	if got, rerr := os.ReadFile(p); rerr != nil || string(got) != "typed by a person after the save was settled\n" {
  		t.Fatalf("the listed file must stay as it is: (%q, %v)", got, rerr)
  	}
  	if r.hasMarker() || m.UndoStarted {
  		t.Fatalf("a refused undo must not write a marker (on disk %v, in memory %v)", r.hasMarker(), m.UndoStarted)
  	}
  }
  ```

- [ ] **Step 3: Run it and see it fail.**
  ```bash
  cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestUndo_RefusesWhenTheMarkerFileIsGone'
  ```
  Expected: FAIL with `undo with no marker on disk must refuse and say nothing was changed, got <nil>`.

- [ ] **Step 4: Implement.** In `pkg/vaultsync/recover.go`, inside `Undo`, replace:
  ```go
  	// The marker on disk is the record: a Recover that failed set the flag on
  	// its own copy, not on the one the caller holds. A missing file means no
  	// earlier pass recorded anything, so the caller's marker decides. A file
  	// for another operation is not this save's record: change nothing.
  	disk, err := r.readMarker()
  	if err != nil {
  		return err
  	}
  	if disk != nil {
  		if disk.Op != m.Op || disk.Actor != m.Actor || disk.Base != m.Base ||
  			disk.StartedAt != m.StartedAt || disk.PID != m.PID {
  			return fmt.Errorf("the save marker on disk (%s by %s, started %s) is not the one given to undo (%s by %s, started %s); nothing was changed",
  				disk.Op, disk.Actor, disk.StartedAt, m.Op, m.Actor, m.StartedAt)
  		}
  		m.UndoStarted = m.UndoStarted || disk.UndoStarted
  	}
  ```
  with:
  ```go
  	// The marker on disk is the record: a Recover that failed set the flag on
  	// its own copy, not on the one the caller holds. Begin always writes the
  	// file, so a missing file means the save was already settled (a Recover
  	// that succeeded removes it): the caller's list is stale, change nothing.
  	// A file for another operation is not this save's record: change nothing.
  	disk, err := r.readMarker()
  	if err != nil {
  		return err
  	}
  	if disk == nil {
  		return fmt.Errorf("there is no save marker on disk for the %s by %s (started %s): that save was already settled; nothing was changed",
  			m.Op, m.Actor, m.StartedAt)
  	}
  	if disk.Op != m.Op || disk.Actor != m.Actor || disk.Base != m.Base ||
  		disk.StartedAt != m.StartedAt || disk.PID != m.PID {
  		return fmt.Errorf("the save marker on disk (%s by %s, started %s) is not the one given to undo (%s by %s, started %s); nothing was changed",
  			disk.Op, disk.Actor, disk.StartedAt, m.Op, m.Actor, m.StartedAt)
  	}
  	m.UndoStarted = m.UndoStarted || disk.UndoStarted
  ```
  Leave the two lines that follow (`if m.UndoStarted { return r.undo(m, nil, true, rebuild) }` and `return r.undo(m, written, false, rebuild)`) as they are.

- [ ] **Step 5: Run and expect PASS, with every other Undo test and every save test.**
  ```bash
  cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestUndo_|TestSave_'
  ```
  Expected: `ok  	obsidian-vault-engine/pkg/vaultsync`.

- [ ] **Step 6: Commit.**
  ```bash
  git add tools/vault-engine/pkg/vaultsync/recover.go tools/vault-engine/pkg/vaultsync/recover_test.go
  git commit -m "fix(vault-engine): A4 A16 Undo refuses when the marker file is missing"
  ```

### A16 (other half): test the foreign-marker refusal

- [ ] **Step 7: Add the test.** Append to `pkg/vaultsync/recover_test.go`:
  ```go
  // A marker on disk that belongs to another save is not this save's record:
  // Undo refuses whichever field differs, and changes nothing.
  func TestUndo_RefusesAMarkerThatBelongsToAnotherSave(t *testing.T) {
  	w := newWorld(t)
  	r := newRepo(t, w.Mac)
  	lockFor(t, r)
  	m, err := r.Begin("commit", "agent-olivier")
  	if err != nil {
  		t.Fatalf("begin: %v", err)
  	}
  	p := filepath.Join(w.Mac, "01_Ideas", "new.md")
  	writeFile(t, p, []byte("written by the save that owns the marker\n"))
  	for name, change := range map[string]func(*Marker){
  		"other operation":  func(o *Marker) { o.Op = "update" },
  		"other actor":      func(o *Marker) { o.Actor = "agent-bestie" },
  		"other base":       func(o *Marker) { o.Base = strings.Repeat("1", 40) },
  		"other start time": func(o *Marker) { o.StartedAt = "2000-01-01T00:00:00Z" },
  		"other process":    func(o *Marker) { o.PID++ },
  	} {
  		t.Run(name, func(t *testing.T) {
  			other := *m
  			change(&other)
  			err := r.Undo(&other, []string{"01_Ideas/new.md"}, noRebuild)
  			if err == nil || !strings.Contains(err.Error(), "is not the one given to undo") || !strings.Contains(err.Error(), "nothing was changed") {
  				t.Fatalf("undo with another save's marker must refuse, got %v", err)
  			}
  			if got, rerr := os.ReadFile(p); rerr != nil || string(got) != "written by the save that owns the marker\n" {
  				t.Fatalf("the listed file must stay as it is: (%q, %v)", got, rerr)
  			}
  			disk, derr := r.readMarker()
  			if derr != nil || disk == nil || disk.UndoStarted || other.UndoStarted {
  				t.Fatalf("a refused undo must not record a start: on disk (%+v, %v), in memory %v", disk, derr, other.UndoStarted)
  			}
  		})
  	}
  }
  ```

- [ ] **Step 8: Run and expect PASS** (the refusal already exists; this test pins it).
  ```bash
  cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestUndo_RefusesAMarkerThatBelongsToAnotherSave'
  ```
  Expected: `ok`, five sub-tests.

- [ ] **Step 9: Commit.**
  ```bash
  git add tools/vault-engine/pkg/vaultsync/recover_test.go
  git commit -m "test(vault-engine): A16 Undo refuses a marker that belongs to another save"
  ```

### A6 and A15: name the step in marker-write errors, and test the branch where the undo start cannot be recorded

- [ ] **Step 10: Write the test (it fails until A6 names the step).** Append to `pkg/vaultsync/recover_test.go`:
  ```go
  // The record "an undo was started" is written before the folder is moved back.
  // When it cannot be written, nothing is changed: not the folder, not the
  // marker on disk, not the marker the caller holds.
  func TestUndo_WhenTheUndoStartCannotBeRecordedNothingIsChanged(t *testing.T) {
  	w := newWorld(t)
  	r := newRepo(t, w.Mac)
  	lockFor(t, r)
  	m, err := r.Begin("commit", "agent-olivier")
  	if err != nil {
  		t.Fatalf("begin: %v", err)
  	}
  	p := filepath.Join(w.Mac, "01_Ideas", "new.md")
  	writeFile(t, p, []byte("what the save wrote\n"))
  	if err := r.Commit([]string{"01_Ideas/new.md"}, "agent-olivier", "vault: commit", ""); err != nil {
  		t.Fatalf("commit: %v", err)
  	}
  	head, err := r.Head()
  	if err != nil {
  		t.Fatalf("head: %v", err)
  	}
  	// A folder sits where the marker's temp file must go: the marker cannot be rewritten.
  	if err := os.Mkdir(r.markerPath()+".tmp", 0755); err != nil {
  		t.Fatalf("mkdir: %v", err)
  	}
  	err = r.Undo(m, []string{"01_Ideas/new.md"}, noRebuild)
  	if err == nil || !strings.Contains(err.Error(), "record undo start") {
  		t.Fatalf("undo must fail and name the step that failed, got %v", err)
  	}
  	if m.UndoStarted {
  		t.Fatalf("the caller's marker must not say an undo was started")
  	}
  	if now, herr := r.Head(); herr != nil || now != head {
  		t.Fatalf("the folder must not have been moved back: head (%s, %v), want %s", now, herr, head)
  	}
  	if got, rerr := os.ReadFile(p); rerr != nil || string(got) != "what the save wrote\n" {
  		t.Fatalf("the save's file must stay as it is: (%q, %v)", got, rerr)
  	}
  	disk, derr := r.readMarker()
  	if derr != nil || disk == nil || disk.UndoStarted {
  		t.Fatalf("the marker on disk must be as Begin wrote it: (%+v, %v)", disk, derr)
  	}
  }
  ```

- [ ] **Step 11: Run it and see it fail on the error text only.**
  ```bash
  cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestUndo_WhenTheUndoStartCannotBeRecordedNothingIsChanged'
  ```
  Expected: FAIL with `undo must fail and name the step that failed, got open ...save-in-progress.json.tmp: is a directory` (the bare error A6 is about).

- [ ] **Step 12: Implement A6.** In `pkg/vaultsync/recover.go`, replace the body of `writeMarker`:
  ```go
  	data, err := json.MarshalIndent(m, "", "  ")
  	if err != nil {
  		return err
  	}
  	if err := os.MkdirAll(filepath.Dir(r.markerPath()), 0755); err != nil {
  		return err
  	}
  	return writeFileAtomic(r.markerPath(), data)
  }
  ```
  with:
  ```go
  	data, err := json.MarshalIndent(m, "", "  ")
  	if err != nil {
  		return fmt.Errorf("write save marker %s: %w", markerRel, err)
  	}
  	if err := os.MkdirAll(filepath.Dir(r.markerPath()), 0755); err != nil {
  		return fmt.Errorf("write save marker %s: %w", markerRel, err)
  	}
  	if err := writeFileAtomic(r.markerPath(), data); err != nil {
  		return fmt.Errorf("write save marker %s: %w", markerRel, err)
  	}
  	return nil
  }
  ```
  and inside `undo` replace:
  ```go
  		if err := r.writeMarker(m); err != nil {
  			m.UndoStarted = false
  			return err
  		}
  ```
  with:
  ```go
  		if err := r.writeMarker(m); err != nil {
  			m.UndoStarted = false
  			return fmt.Errorf("record undo start: %w", err)
  		}
  ```

- [ ] **Step 13: Run and expect PASS.**
  ```bash
  cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestUndo_|TestBegin_'
  ```
  Expected: `ok`.

- [ ] **Step 14: Commit.**
  ```bash
  git add tools/vault-engine/pkg/vaultsync/recover.go tools/vault-engine/pkg/vaultsync/recover_test.go
  git commit -m "fix(vault-engine): A6 A15 marker-write errors name their step; test the undo start that cannot be recorded"
  ```

### A5: a comparison cut by a stop is "unknown", not "different"

Narrowed on purpose (see the design, row A5): only a stop (`errors.Is(err, ErrStopped)`) is "unknown". A comparison that fails for any other reason keeps today's behaviour, so a file git can never hash (a link that points nowhere) cannot block every update in a place.

- [ ] **Step 15: Write the failing test, and a second test that guards today's behaviour.** Append both to `pkg/vaultsync/recover_test.go`:
  ```go
  // A stop that cuts the comparison of an untracked file with the incoming
  // file of the same name is not an answer: the file stays where it is, no
  // report line is written, the stop is returned, and the next pass decides.
  func TestUpdate_AnInterruptedCompareLeavesTheClashingFileWhereItIs(t *testing.T) {
  	w := newWorld(t)
  	mac, srv := newRepo(t, w.Mac), newRepo(t, w.Srv)
  	writeFile(t, filepath.Join(w.Mac, "_inbox", "human", "same-name.md"), []byte("from mac\n"))
  	if err := mac.Commit([]string{"_inbox/human/same-name.md"}, "inbox", "vault: inbox drop", ""); err != nil {
  		t.Fatalf("commit: %v", err)
  	}
  	if out, err := pushAs(t, w.Mac, "mac-test", "HEAD:refs/heads/main"); err != nil {
  		t.Fatalf("push: %v\n%s", err, out)
  	}
  	local := filepath.Join(w.Srv, "_inbox", "human", "same-name.md")
  	writeFile(t, local, []byte("from srv, different\n"))
  	lockFor(t, srv)
  	srv.gate = func(args []string) error {
  		for _, a := range args {
  			if a == "hash-object" {
  				return ErrStopped
  			}
  		}
  		return nil
  	}
  	moved, err := srv.Update(noRebuild)
  	if moved || !errors.Is(err, ErrStopped) {
  		t.Fatalf("update = (%v, %v), want (false, an error that wraps ErrStopped)", moved, err)
  	}
  	if text, rerr := os.ReadFile(local); rerr != nil || string(text) != "from srv, different\n" {
  		t.Fatalf("the local file must stay where it is: (%q, %v)", text, rerr)
  	}
  	if _, serr := os.Stat(filepath.Join(w.Srv, "_quarantine")); !os.IsNotExist(serr) {
  		t.Fatalf("an interrupted compare must set nothing aside and report nothing (stat _quarantine: %v)", serr)
  	}
  	// The next pass, with git working again, decides: the two differ.
  	srv.gate = nil
  	if err := srv.Recover(noRebuild); err != nil {
  		t.Fatalf("recover: %v", err)
  	}
  	if moved, err := srv.Update(noRebuild); err != nil || !moved {
  		t.Fatalf("second update = (%v, %v), want (true, nil)", moved, err)
  	}
  	if text, rerr := os.ReadFile(local); rerr != nil || string(text) != "from mac\n" {
  		t.Fatalf("incoming version should be in place: (%q, %v)", text, rerr)
  	}
  	if got := quarantined(t, w.Srv, "srv-test", "_inbox/human/same-name.md"); string(got) != "from srv, different\n" {
  		t.Fatalf("the local file was not kept: %q", got)
  	}
  	if n := reportLines(t, w.Srv, "srv-test"); n != 1 {
  		t.Fatalf("expected one report line, from the pass that could compare; got %d", n)
  	}
  }

  // A comparison that fails for a reason other than a stop is not "unknown": a
  // file git cannot hash (here a link that points nowhere) with the name of an
  // incoming file is still moved aside, so the update is never blocked by it.
  func TestUpdate_AClashingFileThatCannotBeHashedIsStillSetAside(t *testing.T) {
  	w := newWorld(t)
  	mac, srv := newRepo(t, w.Mac), newRepo(t, w.Srv)
  	writeFile(t, filepath.Join(w.Mac, "_inbox", "human", "same-name.md"), []byte("from mac\n"))
  	if err := mac.Commit([]string{"_inbox/human/same-name.md"}, "inbox", "vault: inbox drop", ""); err != nil {
  		t.Fatalf("commit: %v", err)
  	}
  	if out, err := pushAs(t, w.Mac, "mac-test", "HEAD:refs/heads/main"); err != nil {
  		t.Fatalf("push: %v\n%s", err, out)
  	}
  	local := filepath.Join(w.Srv, "_inbox", "human", "same-name.md")
  	if err := os.Symlink("nowhere", local); err != nil {
  		t.Fatalf("symlink: %v", err)
  	}
  	lockFor(t, srv)
  	if moved, err := srv.Update(noRebuild); err != nil || !moved {
  		t.Fatalf("update = (%v, %v), want (true, nil)", moved, err)
  	}
  	if text, rerr := os.ReadFile(local); rerr != nil || string(text) != "from mac\n" {
  		t.Fatalf("incoming version should be in place: (%q, %v)", text, rerr)
  	}
  	kept, _ := filepath.Glob(filepath.Join(w.Srv, "_quarantine", "srv-test", "*", "_inbox", "human", "same-name.md"))
  	if len(kept) != 1 {
  		t.Fatalf("the local link must be set aside, found %v", kept)
  	}
  	if target, lerr := os.Readlink(kept[0]); lerr != nil || target != "nowhere" {
  		t.Fatalf("the link was not kept as it was: (%q, %v)", target, lerr)
  	}
  	if n := reportLines(t, w.Srv, "srv-test"); n != 1 {
  		t.Fatalf("expected one report line for the link that was set aside, got %d", n)
  	}
  }
  ```

- [ ] **Step 16: Run both. The stop test fails; the guard test already passes.**
  ```bash
  cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestUpdate_AnInterruptedCompare|TestUpdate_AClashingFileThatCannotBeHashed' -v 2>&1 | grep -E '^(--- |ok|FAIL)|_test.go'
  ```
  Expected: `--- FAIL: TestUpdate_AnInterruptedCompareLeavesTheClashingFileWhereItIs` with `update = (true, <nil>), want (false, an error that wraps ErrStopped)`, and `--- PASS: TestUpdate_AClashingFileThatCannotBeHashedIsStillSetAside` (it describes behaviour that must not change).

- [ ] **Step 17: Implement.** In `pkg/vaultsync/recover.go`, add `"errors"` to the import block (between `"encoding/json"` and `"fmt"`). Then, inside `Update`, replace:
  ```go
  		mine, err1 := r.local("hash-object", "--", p)
  		theirs, err2 := r.local("rev-parse", hub+":"+p)
  		if err1 == nil && err2 == nil && mine == theirs {
  ```
  with:
  ```go
  		mine, err1 := r.local("hash-object", "--", p)
  		theirs, err2 := r.local("rev-parse", hub+":"+p)
  		// A comparison cut by a stop is not an answer: the file stays where it
  		// is and nothing is reported; the next pass decides. Any other failure
  		// (a file git cannot hash) is treated as "differs", as before.
  		for _, err := range []error{err1, err2} {
  			if errors.Is(err, ErrStopped) {
  				return false, fmt.Errorf("compare %s with the incoming file of the same name: %w", p, err)
  			}
  		}
  		if err1 == nil && err2 == nil && mine == theirs {
  ```
  Nothing else in the loop changes: the `os.Remove` for identical content and the `r.setAside(p, "an incoming file has the same name", true)` call stay as they are. A stop reaches this code as `ErrStopped` wrapped by `Repo.local` (from `Repo.run` when `Repo.stop` is cancelled, or from the daemon's gate), so `errors.Is` sees it.

- [ ] **Step 18: Run and expect PASS.**
  ```bash
  cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestUpdate_'
  ```
  Expected: vet prints nothing; `ok` (both new tests and the three older `TestUpdate_` tests pass).

- [ ] **Step 19: Commit.**
  ```bash
  git add tools/vault-engine/pkg/vaultsync/recover.go tools/vault-engine/pkg/vaultsync/recover_test.go
  git commit -m "fix(vault-engine): A5 a compare cut by a stop leaves the file in place and reports nothing"
  ```

### A7: writeFileAtomic syncs the parent folder

- [ ] **Step 20: Write the failing test.** Append to `pkg/vaultsync/recover_test.go`:
  ```go
  func TestWriteFileAtomic_SyncsTheFolderAfterTheRenameAndReturnsItsError(t *testing.T) {
  	dir := t.TempDir()
  	target := filepath.Join(dir, "file.json")
  	prev := syncDir
  	t.Cleanup(func() { syncDir = prev })

  	var synced []string
  	inPlace := false
  	syncDir = func(d string) error {
  		synced = append(synced, d)
  		got, err := os.ReadFile(target)
  		inPlace = err == nil && string(got) == "new"
  		return nil
  	}
  	if err := writeFileAtomic(target, []byte("new")); err != nil {
  		t.Fatalf("write: %v", err)
  	}
  	if len(synced) != 1 || synced[0] != dir || !inPlace {
  		t.Fatalf("the folder must be synced once, after the rename: synced %v, new file in place at that moment %v", synced, inPlace)
  	}

  	// A folder sync that fails is reported, although the new file is in place.
  	failed := errors.New("folder sync failed")
  	syncDir = func(string) error { return failed }
  	if err := writeFileAtomic(target, []byte("newer")); !errors.Is(err, failed) {
  		t.Fatalf("a failed folder sync must be returned, got %v", err)
  	}
  	if got, err := os.ReadFile(target); err != nil || string(got) != "newer" {
  		t.Fatalf("the rename had already happened: (%q, %v)", got, err)
  	}
  	if _, err := os.Stat(target + ".tmp"); !os.IsNotExist(err) {
  		t.Fatalf("the temp file was left behind: %v", err)
  	}

  	// The real folder sync works on an ordinary folder.
  	syncDir = prev
  	if err := writeFileAtomic(target, []byte("real")); err != nil {
  		t.Fatalf("write with the real folder sync: %v", err)
  	}
  }
  ```

- [ ] **Step 21: Run it and see it fail.**
  ```bash
  cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestWriteFileAtomic_'
  ```
  Expected: the package does not build: `undefined: syncDir`.

- [ ] **Step 22: Implement.** In `pkg/vaultsync/recover.go` replace:
  ```go
  // writeFileAtomic writes data to path through a temp file, fsync and rename,
  // so a crash leaves either the old file or the whole new one.
  func writeFileAtomic(path string, data []byte) error {
  ```
  with:
  ```go
  // syncDir flushes a folder's own record to disk, so that a rename inside it
  // survives a power cut. A variable so a test can watch it or make it fail.
  var syncDir = func(dir string) error {
  	d, err := os.Open(dir)
  	if err != nil {
  		return fmt.Errorf("sync folder %s: %w", dir, err)
  	}
  	serr := d.Sync()
  	if cerr := d.Close(); serr == nil {
  		serr = cerr
  	}
  	if serr != nil {
  		return fmt.Errorf("sync folder %s: %w", dir, serr)
  	}
  	return nil
  }

  // writeFileAtomic writes data to path through a temp file, fsync and rename,
  // then syncs the folder, so a crash leaves either the old file or the whole
  // new one and a power cut cannot lose the rename. A folder sync that fails is
  // returned although the new file is already in place; a caller must treat
  // that like a crash right after the rename.
  //
  // The temp name is fixed (path + ".tmp"), so two writers of the same path
  // would share it: every caller must hold a lock that covers path (the folder
  // lock for the marker and for quarantine copies, usage.guard for the hub's
  // usage file).
  func writeFileAtomic(path string, data []byte) error {
  ```
  and at the end of the same function replace:
  ```go
  	if werr != nil {
  		_ = os.Remove(tmp)
  	}
  	return werr
  }
  ```
  with:
  ```go
  	if werr != nil {
  		_ = os.Remove(tmp)
  		return werr
  	}
  	return syncDir(filepath.Dir(path))
  }
  ```

- [ ] **Step 23: Run and expect PASS** (both `writeFileAtomic` tests, and the callers: marker, quarantine copies, the hub's usage file).
  ```bash
  cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestWriteFileAtomic_|TestBegin_|TestUndo_|TestChargeDaily_'
  ```
  Expected: `ok`.

- [ ] **Step 24: Commit.**
  ```bash
  git add tools/vault-engine/pkg/vaultsync/recover.go tools/vault-engine/pkg/vaultsync/recover_test.go
  git commit -m "fix(vault-engine): A7 writeFileAtomic syncs the parent folder and states its lock rule"
  ```

### A17 and A18: recover tests stop dropping read errors and assert their premise

- [ ] **Step 25: A17, six places in `pkg/vaultsync/recover_test.go`.**

  (a) In `TestRecover_InterruptedSaveMovesUnprovenFilesToQuarantineAndNeverTouchesAnInboxFile` replace `original, _ := os.ReadFile(note)` (the line before `stray := ...`) with:
  ```go
  	original, err := os.ReadFile(note)
  	if err != nil {
  		t.Fatalf("read %s: %v", note, err)
  	}
  ```
  (b) In `TestUndo_RemovesExactlyTheListedFilesAndLeavesAHandMadeFileAlone` replace `original, _ := os.ReadFile(note)` (the line before `m, err := r.Begin(...)`) with the same four lines.

  (c) In those two functions replace each of the two occurrences of:
  ```go
  	if now, _ := os.ReadFile(note); string(now) != string(original) {
  		t.Errorf("note was not put back")
  	}
  ```
  with:
  ```go
  	if now, err := os.ReadFile(note); err != nil || string(now) != string(original) {
  		t.Errorf("note was not put back: (%q, %v)", now, err)
  	}
  ```
  (d) In `undoAfterFailedPass` replace `original, _ := os.ReadFile(note)` with (note the extra tab of indentation, it is inside `t.Run`):
  ```go
  			original, err := os.ReadFile(note)
  			if err != nil {
  				t.Fatalf("read %s: %v", note, err)
  			}
  ```
  (e) In `undoAfterFailedPass` replace:
  ```go
  			if now, _ := os.ReadFile(note); string(now) != string(original) {
  				t.Errorf("the note should be back at the shared version, got %q", now)
  			}
  ```
  with:
  ```go
  			if now, err := os.ReadFile(note); err != nil || string(now) != string(original) {
  				t.Errorf("the note should be back at the shared version, got (%q, %v)", now, err)
  			}
  ```

- [ ] **Step 26: A18.** In `undoAfterFailedPass` replace:
  ```go
  				t.Fatalf("the first pass must report the failed lookup")
  			}
  			r.gate = nil
  ```
  with:
  ```go
  				t.Fatalf("the first pass must report the failed lookup")
  			}
  			r.gate = nil
  			// The premise of this test: the first pass failed after it had moved
  			// the folder back, so the save's commit is gone.
  			if head, err := r.Head(); err != nil || head != m.Base {
  				t.Fatalf("the first pass must have failed after the folder was moved back: head (%s, %v), base %s", head, err, m.Base)
  			}
  ```

- [ ] **Step 27: Run and expect PASS.**
  ```bash
  cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestRecover_|TestUndo_'
  ```
  Expected: vet prints nothing; `ok`.

- [ ] **Step 28: Commit.**
  ```bash
  git add tools/vault-engine/pkg/vaultsync/recover_test.go
  git commit -m "test(vault-engine): A17 A18 recover tests check read errors and assert the folder was moved back"
  ```

- [ ] **Step 29: Phase gate: verify, independent review, fix, re-verify.** Run the `verify-cmd` above. Have `code-reviewer` and `golang-reviewer` review the diff of this task. Ask them to look hardest at: any path that can still reach `Undo` with no marker; what `Update` leaves on disk when a stop cuts the compare (the `update` marker stays, and `Recover` clears it next pass), and that every non-stop failure still moves the file aside; every caller of `writeFileAtomic` when the folder sync fails after the rename. Fix findings in new commits. Run the `verify-cmd` again.

---

## Task 2: Hub (A8, A12, A13, A24)

**Files:**
- Modify: `tools/vault-engine/pkg/vaultsync/hub.go`
- Modify: `tools/vault-engine/cmd/vault-engine/main.go` (one call site, line 42)
- Test: `tools/vault-engine/pkg/vaultsync/hub_test.go`

**Interfaces (as they are in the code now, and what they become):**
- `func hubGit(stdin string, args ...string) (string, error)` (hub.go:32) becomes `func hubGit(dir, stdin string, args ...string) (string, error)` (A13).
- `func batchCheck(input, format, gitFail string, visit func(word string, size int64) (code, msg string)) (string, string)` (hub.go:47) becomes `func batchCheck(dir, input, format, gitFail string, visit func(word string, size int64) (code, msg string)) (string, string)` (A13).
- `func PreReceive(stdin io.Reader, stderr io.Writer, limitsFile, place string, now time.Time) int` (hub.go:72) becomes `func PreReceive(dir string, stdin io.Reader, stderr io.Writer, limitsFile, place string, now time.Time) int` (A13). Its one production caller, `cmd/vault-engine/main.go:42`, passes `""`: the hook's own working folder, which is what it uses today.
- `func chargeDaily(dir, place string, now time.Time, add, limit int64) (int64, bool, error)` (hub.go:206). Unchanged; A24 tests it.
- Relied on: `const hubFault = "engine-error"`, `var gitLocationVars map[string]bool` (repo.go:95), `func violationOutcome(v *Violation) Outcome` (syncer.go:41).
- Relied on for the exit-code test: `const ExitTypeNotAllowed = 6` (syncer.go:27), `func (s *Syncer) Save(op Op) (string, Outcome)`, the test seam `Hooks.PushResult func(attempt int, res gitResult) gitResult`.
- Test helpers that already exist: `newHub(t)`, `seededClone(t, hub)`, `mustGit(t, dir, args...)`, `pushAs(t, dir, place, refspec)`, `writeFile(t, path, data)`, `hubLimitsCopy(t)`, `newWorld(t)`, `newSyncer(t, root)`, `commitOp(s, id, sha, impact)`, `readSHA(t, root, id)`, the constant `note1`.

**Worker brief**
- `cwd`: `/Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin`
- `verify-cmd`:
  ```bash
  cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestPreReceive_|TestChargeDaily_|TestHub|TestSave_ATreeOrBlobRefusal|TestSave_PushAnswersAreReadFromTheirText|TestViolationOutcome_' && test "$(grep -c -E '^func (TestPreReceive_ATreeOrBlobAsTheNewTipIsTypeNotAllowed|TestChargeDaily_AUsageFileThatCannotBeWrittenChargesNothing|TestHub_UsageFileThatCannotBeWrittenRefusesTheSendAndChargesNothing|TestSave_ATreeOrBlobRefusalFromTheHubEndsWithExitSix|hubRepo)\(' pkg/vaultsync/hub_test.go)" -eq 5 && grep -q 'func hubGit(dir, stdin string' pkg/vaultsync/hub.go && grep -q 'code != 1 || !strings.HasPrefix(stderr.String(), "vault-hub: REFUSED engine-error: cannot check' pkg/vaultsync/hub_test.go
  ```
- `acceptance`:
  1. A send whose new tip is a tree or a blob, onto a hub that already has a tip, is refused with `vault-hub: REFUSED type-not-allowed: ...` and exit code 1 from `PreReceive`; the sending place answers `REFUSED type-not-allowed` with exit code 6 (it was `REFUSED engine-error`, exit 1), and a test asserts the 6.
  2. An ancestor check on objects the hub does not have is still `engine-error`, and the test asserts exit code 1.
  3. No test in `hub_test.go` lets `PreReceive` or `batchCheck` run git in the source checkout: each passes a temp bare repository as `dir`.
  4. `hubGit` does not touch its environment (no `cmd.Env` assignment).

### A13: hubGit gets a working-folder argument

- [ ] **Step 1: Change the three functions.** In `pkg/vaultsync/hub.go` replace:
  ```go
  // hubGit runs git inside the hook: cwd is the bare repository and the
  // environment (including git's quarantine variables) is inherited untouched.
  func hubGit(stdin string, args ...string) (string, error) {
  	cmd := exec.Command("git", args...)
  ```
  with:
  ```go
  // hubGit runs git for the hook in the folder dir; "" is the working folder of
  // this process, which is the bare repository when git runs the hook. The
  // environment (including git's quarantine variables) is inherited untouched:
  // the hook needs it to see the objects of the send it is checking.
  func hubGit(dir, stdin string, args ...string) (string, error) {
  	cmd := exec.Command("git", args...)
  	cmd.Dir = dir
  ```
  Do **not** set `cmd.Env`.

  Replace:
  ```go
  func batchCheck(input, format, gitFail string, visit func(word string, size int64) (code, msg string)) (string, string) {
  	out, err := hubGit(input, "cat-file", "--batch-check="+format)
  ```
  with:
  ```go
  func batchCheck(dir, input, format, gitFail string, visit func(word string, size int64) (code, msg string)) (string, string) {
  	out, err := hubGit(dir, input, "cat-file", "--batch-check="+format)
  ```
  Replace:
  ```go
  // "too-large" or "type-not-allowed" for a broken rule (the message names the
  // limit) and hubFault for a fault of the hub itself.
  func PreReceive(stdin io.Reader, stderr io.Writer, limitsFile, place string, now time.Time) int {
  ```
  with:
  ```go
  // "too-large" or "type-not-allowed" for a broken rule (the message names the
  // limit) and hubFault for a fault of the hub itself. dir is the folder its git
  // commands run in; the hook passes "" (its own working folder, the bare
  // repository).
  func PreReceive(dir string, stdin io.Reader, stderr io.Writer, limitsFile, place string, now time.Time) int {
  ```
  Inside `PreReceive` pass `dir` on at all six call sites:
  - `hubGit("", "merge-base", ...` becomes `hubGit(dir, "", "merge-base", ...`
  - `hubGit("", "rev-list", newSHA, ...` becomes `hubGit(dir, "", "rev-list", newSHA, ...`
  - `hubGit("", "diff-tree", ...` becomes `hubGit(dir, "", "diff-tree", ...`
  - `hubGit("", append(append([]string{"rev-list", "--objects"}, ...` becomes `hubGit(dir, "", append(append([]string{"rev-list", "--objects"}, ...`
  - `batchCheck(in.String(), "%(objectname) %(objectsize)", ...` becomes `batchCheck(dir, in.String(), "%(objectname) %(objectsize)", ...`
  - `batchCheck(in.String(), "%(objecttype) %(objectsize)", ...` becomes `batchCheck(dir, in.String(), "%(objecttype) %(objectsize)", ...`

  In `cmd/vault-engine/main.go` (line 42) replace `vaultsync.PreReceive(os.Stdin, os.Stderr, os.Args[2], ...` with `vaultsync.PreReceive("", os.Stdin, os.Stderr, os.Args[2], ...` (the rest of the line is unchanged).

- [ ] **Step 2: Give the tests a repository of their own.** In `pkg/vaultsync/hub_test.go`, add this helper directly above `hubLimitsCopy`:
  ```go
  // hubRepo returns an empty bare repository for PreReceive's git commands, and
  // clears git's own location variables for the length of the test. Without it
  // those commands would run in the source checkout, or in whatever repository
  // the test runner exported (GIT_DIR in a git hook, `git rebase --exec`).
  func hubRepo(t *testing.T) string {
  	t.Helper()
  	for name := range gitLocationVars {
  		if _, set := os.LookupEnv(name); set {
  			t.Setenv(name, "") // registers the restore for the end of the test
  			_ = os.Unsetenv(name)
  		}
  	}
  	dir := filepath.Join(t.TempDir(), "hub.git")
  	mustGit(t, t.TempDir(), "init", "--quiet", "--bare", "--initial-branch=main", dir)
  	return dir
  }
  ```
  Then update the seven existing calls:
  - In `TestPreReceive_RefusesInputItCannotRead`: add the line `dir := hubRepo(t)` right after `zero := strings.Repeat("0", 40)`, and change `PreReceive(in, &stderr, limits, "mac-test", time.Now())` to `PreReceive(dir, in, &stderr, limits, "mac-test", time.Now())`.
  - In `TestPreReceive_OwnFaultsAreEngineErrors`: add the line `dir := hubRepo(t)` right after `zero, unknown := strings.Repeat("0", 40), strings.Repeat("1", 40)`. Put `dir, ` as the new first argument of all four `PreReceive(` calls in that function (two with `strings.NewReader("")`, one with `strings.NewReader(zero+" "+unknown+" refs/heads/main\n")`, one with `strings.NewReader(c.line)`), and change `batchCheck(unknown+"\n", ...` to `batchCheck(dir, unknown+"\n", ...`.
  - In `TestPreReceive_AncestorCheckThatCannotRunIsAnEngineError`: change `PreReceive(strings.NewReader(older+" "+newer+" refs/heads/main\n"), &stderr, ...` to `PreReceive(hubRepo(t), strings.NewReader(older+" "+newer+" refs/heads/main\n"), &stderr, ...`.

- [ ] **Step 3: Run and expect PASS** (same behaviour, new argument).
  ```bash
  cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestPreReceive_|TestHub'
  ```
  Expected: vet prints nothing; `ok`.

- [ ] **Step 4: Commit.**
  ```bash
  git add tools/vault-engine/pkg/vaultsync/hub.go tools/vault-engine/pkg/vaultsync/hub_test.go tools/vault-engine/cmd/vault-engine/main.go
  git commit -m "refactor(vault-engine): A13 hubGit takes a working folder; hub tests use a temp repository"
  ```

### A12: the engine-error test pins the exit code

- [ ] **Step 5: Tighten the assertion.** In `TestPreReceive_AncestorCheckThatCannotRunIsAnEngineError` replace `if code == 0 || !strings.HasPrefix(stderr.String(), "vault-hub: REFUSED engine-error: cannot check that refs/heads/main only moves forward") {` with:
  ```go
  	if code != 1 || !strings.HasPrefix(stderr.String(), "vault-hub: REFUSED engine-error: cannot check that refs/heads/main only moves forward") {
  ```

- [ ] **Step 6: Run and expect PASS, then commit.**
  ```bash
  cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestPreReceive_AncestorCheck'
  git add tools/vault-engine/pkg/vaultsync/hub_test.go
  git commit -m "test(vault-engine): A12 the ancestor-check test asserts exit code 1"
  ```
  Run the `git` lines from the worktree root.

### A8: a tree or blob as the new tip is "type not allowed"

- [ ] **Step 7: Check what reads the refusal reason. STOP if anything but tests reads the reason text.**

  Run from the worktree root:
  ```bash
  grep -rn 'only moves forward\|cannot check that' tools/vault-engine --include='*.go' --include='*.sh' --include='*.md'
  grep -rn 'vault-hub: REFUSED' tools/vault-engine --include='*.go' --include='*.sh' | grep -v '_test.go'
  ```
  Expected, first command: `pkg/vaultsync/hub.go` (the message itself) and `pkg/vaultsync/hub_test.go` only. Expected, second command: `hub.go` (comment and `refuse`) and `pkg/vaultsync/syncer.go:312-315`.

  `syncer.go:312-315` is the one production reader, and it is the intended one: it cuts the refusal line into the **label** (`too-large`, `type-not-allowed`, `engine-error`) and the message, and hands the label to `violationOutcome`, which already knows all three. It never looks inside the message. So after this change a place that receives this refusal answers `REFUSED type-not-allowed` (exit 6) where it answered `REFUSED engine-error` (exit 1). The design accepts that change (row A8), and Step 8 pins it with a test.

  **If you find any non-test code or script that matches on the message text (for example on "only moves forward" or on "engine-error" together with this case): STOP. Change nothing. Report the file and line.**

- [ ] **Step 8: Write the failing tests** (the hub's label, and the exit code the sending place makes of it). Append both to `pkg/vaultsync/hub_test.go`:
  ```go
  // A send that points the main line at a tree or a blob breaks a rule: the
  // forward-only question cannot even be asked about it. That is the sender's
  // doing, so the label is type-not-allowed, not the hub's own engine-error.
  func TestPreReceive_ATreeOrBlobAsTheNewTipIsTypeNotAllowed(t *testing.T) {
  	hub := newHub(t)
  	seededClone(t, hub)
  	tip := mustGit(t, hub, "rev-parse", "refs/heads/main")
  	for kind, object := range map[string]string{
  		"tree": mustGit(t, hub, "rev-parse", "refs/heads/main^{tree}"),
  		"blob": mustGit(t, hub, "rev-parse", "refs/heads/main:README.md"),
  	} {
  		t.Run(kind, func(t *testing.T) {
  			var stderr strings.Builder
  			code := PreReceive(hub, strings.NewReader(tip+" "+object+" refs/heads/main\n"), &stderr, hubLimitsCopy(t), "mac-test", time.Now())
  			want := "vault-hub: REFUSED type-not-allowed: refs/heads/main may only point at a commit; this send points it at a " + kind
  			if code != 1 || !strings.HasPrefix(stderr.String(), want) {
  				t.Fatalf("code=%d stderr=%q, want code 1 and %q", code, stderr.String(), want)
  			}
  		})
  	}
  }

  // The same refusal as the sending place sees it. The place reads the hub's
  // line from what git prints and answers with the exit code of the label: 6
  // for type-not-allowed (it was 1, engine-error, before the label was fixed).
  func TestSave_ATreeOrBlobRefusalFromTheHubEndsWithExitSix(t *testing.T) {
  	hub := newHub(t)
  	seededClone(t, hub)
  	tip := mustGit(t, hub, "rev-parse", "refs/heads/main")
  	tree := mustGit(t, hub, "rev-parse", "refs/heads/main^{tree}")
  	var stderr strings.Builder
  	if code := PreReceive(hub, strings.NewReader(tip+" "+tree+" refs/heads/main\n"), &stderr, hubLimitsCopy(t), "mac-test", time.Now()); code != 1 {
  		t.Fatalf("the hub must refuse a tree as the new tip, code=%d stderr=%q", code, stderr.String())
  	}
  	w := newWorld(t)
  	mac := newSyncer(t, w.Mac)
  	mac.Hooks.PushResult = func(_ int, _ gitResult) gitResult {
  		return gitResult{Stderr: "remote: " + stderr.String(), Err: errors.New("exit status 1")}
  	}
  	_, out := mac.Save(commitOp(mac, note1, readSHA(t, w.Mac, note1), 5))
  	if out.Line != "REFUSED type-not-allowed" || out.Exit != 6 {
  		t.Fatalf("outcome = %+v, want REFUSED type-not-allowed with exit 6", out)
  	}
  }
  ```

- [ ] **Step 9: Run them and see them fail.**
  ```bash
  cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestPreReceive_ATreeOrBlob|TestSave_ATreeOrBlobRefusal'
  ```
  Expected: both sub-tests FAIL with `code=1 stderr="vault-hub: REFUSED engine-error: cannot check that refs/heads/main only moves forward: git merge-base: exit status 128: error: object ... is a tree, not a commit` (and `is a blob, not a commit`). `TestSave_ATreeOrBlobRefusalFromTheHubEndsWithExitSix` FAILs with `outcome = {Line:REFUSED engine-error Exit:1 ...}, want REFUSED type-not-allowed with exit 6`.

- [ ] **Step 10: Implement.** In `pkg/vaultsync/hub.go`, inside `PreReceive`, replace:
  ```go
  					return refuse("type-not-allowed", "rewriting the history of %s is never accepted", ref)
  				}
  				return refuse(hubFault, "cannot check that %s only moves forward: %v", ref, err)
  ```
  with:
  ```go
  					return refuse("type-not-allowed", "rewriting the history of %s is never accepted", ref)
  				}
  				// The question cannot be asked about a tree or a blob. Sending one
  				// as the new tip is a rule the sender broke, not a fault of the hub.
  				if typ, terr := hubGit(dir, "", "cat-file", "-t", newSHA); terr == nil && strings.TrimSpace(typ) != "commit" {
  					return refuse("type-not-allowed", "%s may only point at a commit; this send points it at a %s", ref, strings.TrimSpace(typ))
  				}
  				return refuse(hubFault, "cannot check that %s only moves forward: %v", ref, err)
  ```
  An object the hub does not have makes `cat-file -t` fail, so that case stays `engine-error` (the A12 test covers it).

- [ ] **Step 11: Run and expect PASS.**
  ```bash
  cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestPreReceive_|TestHub|TestSave_ATreeOrBlobRefusal'
  ```
  Expected: `ok`.

- [ ] **Step 12: Commit.**
  ```bash
  git add tools/vault-engine/pkg/vaultsync/hub.go tools/vault-engine/pkg/vaultsync/hub_test.go
  git commit -m "fix(vault-engine): A8 a tree or blob as the new tip is refused as type-not-allowed (the place exits 6)"
  ```

### A24: a usage file that cannot be written charges nothing

- [ ] **Step 13: Add two tests.** Append to `pkg/vaultsync/hub_test.go`:
  ```go
  func TestChargeDaily_AUsageFileThatCannotBeWrittenChargesNothing(t *testing.T) {
  	now := time.Date(2026, 10, 10, 12, 0, 0, 0, time.UTC)
  	dir := t.TempDir()
  	file := filepath.Join(dir, "2026-10-10.json")
  	writeFile(t, file, []byte(`{"mac-test":5}`))
  	// A folder sits where the temp file of the write must go.
  	if err := os.Mkdir(file+".tmp", 0755); err != nil {
  		t.Fatal(err)
  	}
  	used, ok, err := chargeDaily(dir, "mac-test", now, 10, 1000)
  	if err == nil || ok || used != 0 || !strings.Contains(err.Error(), "writing usage file") {
  		t.Fatalf("chargeDaily = (%d, %v, %v), want (0, false, an error about writing the usage file)", used, ok, err)
  	}
  	data, rerr := os.ReadFile(file)
  	if rerr != nil || string(data) != `{"mac-test":5}` {
  		t.Fatalf("nothing may be charged when the write fails: (%s, %v)", data, rerr)
  	}
  }

  // The same through a real send: refused as the hub's own fault, nothing taken
  // in, and no usage file written for the day.
  func TestHub_UsageFileThatCannotBeWrittenRefusesTheSendAndChargesNothing(t *testing.T) {
  	hub := newHub(t)
  	usage := filepath.Join(hub, "vault-usage")
  	// The hook reads the clock itself: cover today and, for a run at midnight, tomorrow (UTC).
  	var days []string
  	for _, at := range []time.Time{time.Now().UTC(), time.Now().UTC().Add(time.Hour)} {
  		day := filepath.Join(usage, at.Format("2006-01-02")+".json")
  		days = append(days, day)
  		if err := os.MkdirAll(day+".tmp", 0755); err != nil {
  			t.Fatal(err)
  		}
  	}
  	dir := filepath.Join(t.TempDir(), "place")
  	writeFile(t, filepath.Join(dir, "README.md"), []byte("seed\n"))
  	mustGit(t, dir, "init", "--quiet", "--initial-branch=main")
  	mustGit(t, dir, "remote", "add", "origin", hub)
  	mustGit(t, dir, "add", "-A")
  	mustGit(t, dir, "commit", "--quiet", "-m", "seed")
  	out, err := pushAs(t, dir, "mac-test", "HEAD:refs/heads/main")
  	if err == nil || !strings.Contains(out, "vault-hub: REFUSED engine-error: daily allowance cannot be recorded: writing usage file") {
  		t.Fatalf("expected an engine-error refusal about the usage file, got err=%v\n%s", err, out)
  	}
  	if refs := mustGit(t, hub, "for-each-ref"); refs != "" {
  		t.Fatalf("the hub must not have taken the send:\n%s", refs)
  	}
  	for _, day := range days {
  		if _, serr := os.Stat(day); !os.IsNotExist(serr) {
  			t.Fatalf("no usage may be recorded for a refused send: %s exists (%v)", day, serr)
  		}
  	}
  }
  ```

- [ ] **Step 14: Run and expect PASS, then commit.**
  ```bash
  cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestChargeDaily_|TestHub_Usage|TestHub_Unwritable'
  ```
  Expected: `ok`. Then, from the worktree root:
  ```bash
  git add tools/vault-engine/pkg/vaultsync/hub_test.go
  git commit -m "test(vault-engine): A24 a usage file that cannot be written refuses the send and charges nothing"
  ```

- [ ] **Step 15: Phase gate: verify, independent review, fix, re-verify.** Run the `verify-cmd` above. Have `code-reviewer` and `golang-reviewer` review the diff of this task. Ask them to look hardest at: that the hook (`main.go:42`) still runs git exactly as before (`dir == ""`, environment untouched); that no refusal that was the hub's own fault now reads as a broken rule; a tag object as the new tip. Fix findings in new commits. Run the `verify-cmd` again.

---

## Task 3: Sync engine and repo (A1 code, A21, A25, A27, A32)

**Files:**
- Modify: `tools/vault-engine/pkg/vaultsync/syncer.go`
- Test: `tools/vault-engine/pkg/vaultsync/syncer_test.go`
- Test: `tools/vault-engine/pkg/vaultsync/repo_test.go`
- Test: `tools/vault-engine/pkg/vaultsync/testkit_test.go` (the helper mode inside `TestMain`)

**Interfaces (as they are in the code now):**
- `func (s *Syncer) record(paths []string, actor, subject, key string, m *Marker, attempt int) (pushState, Outcome)` (syncer.go:296). The confirm loop at `:343-363` changes (A1); signature stays.
- `func (r *Repo) Fetch() error` (repo.go:225). Unchanged. It wraps its cause with `%w`, so `errors.Is(err, ErrStopped)` is true for a fetch that was stopped.
- `func (r *Repo) run(timeout time.Duration, args ...string) gitResult` (repo.go:147). Unchanged; A21 tests the `ErrStopped` mapping at `:187-192`.
- `func (r *Repo) RemoteHead() (string, error)` (repo.go:234). Unchanged; A25 pins its message.
- Relied on: `type Hooks struct { BeforePush func(attempt int); PushResult func(attempt int, res gitResult) gitResult }`, `Repo.gate`, `Repo.stop context.Context`, `type gitResult struct { Stdout, Stderr string; Err error }`, `var ErrStopped`, `const ExitNoConnection = 4`, `const localTimeout`.
- Test helpers that already exist: `newWorld(t)`, `newSyncer(t, root)`, `readSHA(t, root, id)`, `commitOp(s, id, sha, impact)`, `cleanExceptIgnored(t, root)`, the constants `note1`, `note2`, `mustGit(t, dir, args...)`, `waitFor(limit, f)` (scenario_test.go:424).

**Worker brief**
- `cwd`: `/Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin`
- `verify-cmd`:
  ```bash
  cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestSave_|TestRepoRun_|TestRepo_NoConnectionErrorsKeepTheirCause|TestRepo_SignalKillsTheGitGroupAndEndsTheEngine' && grep -q '^func TestSave_StopDuringTheConfirmFetchAsksOnceAndStaysUnconfirmed(' pkg/vaultsync/syncer_test.go && test "$(grep -c -E '^func (TestRepoRun_CancelDuringASlowCommandGivesErrStopped|TestRepoRun_ACommandThatEndedWellKeepsItsResultWhenStopIsAlreadyCancelled)\(' pkg/vaultsync/repo_test.go)" -eq 2 && grep -q 'has no refs/heads/' pkg/vaultsync/repo_test.go && grep -q 'os.Exit(4)' pkg/vaultsync/testkit_test.go
  ```
- `acceptance`:
  1. After an unconfirmed send, a confirmation fetch that ends with `ErrStopped` is not retried; the outcome is still `REFUSED no-connection` and the marker stays.
  2. Two tests pin `Repo.run`: a cancel during a running command gives `ErrStopped`; a command that ended well keeps `Err == nil` when `stop` is already cancelled.
  3. The signal test's helper exits non-zero when its pid file never appears, and the parent test kills the helper before it fails and checks the pid it parsed.

### A1 (code): the confirm loop leaves when the daemon is stopping

- [ ] **Step 1: Write the failing test.** Append to `pkg/vaultsync/syncer_test.go`:
  ```go
  // A stop that lands on the confirmation fetch ends the asking at once: one
  // fetch, no retries, and the answer is still "not confirmed".
  func TestSave_StopDuringTheConfirmFetchAsksOnceAndStaysUnconfirmed(t *testing.T) {
  	w := newWorld(t)
  	mac := newSyncer(t, w.Mac)
  	sha := readSHA(t, w.Mac, note1)
  	stopping, fetches := false, 0
  	mac.Hooks.PushResult = func(_ int, res gitResult) gitResult {
  		stopping = true // the send arrived, its answer was lost, and the daemon is told to stop
  		return gitResult{Err: errors.New("simulated: connection reset")}
  	}
  	mac.Repo.gate = func(args []string) error {
  		if stopping && len(args) > 0 && args[0] == "fetch" {
  			fetches++
  			return ErrStopped
  		}
  		return nil
  	}
  	if _, out := mac.Save(commitOp(mac, note1, sha, 5)); out.Line != "REFUSED no-connection" || out.Exit != ExitNoConnection {
  		t.Fatalf("outcome = %+v, want REFUSED no-connection (the send is not confirmed)", out)
  	}
  	if fetches != 1 {
  		t.Fatalf("the confirm loop asked the shared copy %d times after the stop, want 1", fetches)
  	}
  	if !mac.Repo.hasMarker() {
  		t.Fatalf("the marker must stay until the hub can be asked")
  	}
  	// The next command settles it: the first try did arrive.
  	mac.Hooks, mac.Repo.gate = Hooks{}, nil
  	if _, out := mac.Save(commitOp(mac, note1, sha, 5)); out.Line != "REFUSED note-changed" {
  		t.Fatalf("retry = %+v, want REFUSED note-changed because the first try arrived", out)
  	}
  	if mac.Repo.hasMarker() {
  		t.Fatalf("marker should be settled")
  	}
  	cleanExceptIgnored(t, w.Mac)
  }
  ```

- [ ] **Step 2: Run it and see it fail.**
  ```bash
  cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestSave_StopDuringTheConfirmFetch'
  ```
  Expected: FAIL with `the confirm loop asked the shared copy 3 times after the stop, want 1`.

- [ ] **Step 3: Implement.** In `pkg/vaultsync/syncer.go`, inside `record`, replace:
  ```go
  		if r.Fetch() != nil {
  			time.Sleep(500 * time.Millisecond)
  			continue
  		}
  ```
  with:
  ```go
  		if err := r.Fetch(); err != nil {
  			if errors.Is(err, ErrStopped) {
  				break // the program is stopping: asking again cannot help; the answer stays "not confirmed"
  			}
  			time.Sleep(500 * time.Millisecond)
  			continue
  		}
  ```
  (`break` leaves the `for try := 0; try < 3; try++` loop; the code after it builds the same `pushUnconfirmed` answer as before.)

- [ ] **Step 4: Run and expect PASS.**
  ```bash
  cd tools/vault-engine && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestSave_'
  ```
  Expected: `ok`.

- [ ] **Step 5: Commit.** (The README sentence for A1 is changed in Task 6.)
  ```bash
  git add tools/vault-engine/pkg/vaultsync/syncer.go tools/vault-engine/pkg/vaultsync/syncer_test.go
  git commit -m "fix(vault-engine): A1 the confirm loop stops asking when the daemon is stopping"
  ```

### A21: two tests for the ErrStopped mapping in Repo.run

- [ ] **Step 6: Add the tests.** In `pkg/vaultsync/repo_test.go` add `"context"` to the import block, between `"bufio"` and `"errors"`, then append:
  ```go
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
  ```
  Why `stoppedButSilent` works: its `Done()` is the nil channel of `context.Background()`, so nothing ever kills the command; only `stop.Err()` (read at repo.go:188) says "cancelled". That is exactly the state after a cancel that came too late to matter.

- [ ] **Step 7: Run and expect PASS** (the mapping exists; these tests pin it).
  ```bash
  cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestRepoRun_'
  ```
  Expected: vet prints nothing; `ok`.

  Prove the tests bite: in `pkg/vaultsync/repo.go` temporarily change `case err != nil && stop.Err() != nil:` to `case false:`, run the same command, and see `TestRepoRun_CancelDuringASlowCommandGivesErrStopped` fail; then change it to `case stop.Err() != nil:` and see `TestRepoRun_ACommandThatEndedWellKeepsItsResultWhenStopIsAlreadyCancelled` fail. Restore the line (`git diff --stat tools/vault-engine/pkg/vaultsync/repo.go` must print nothing).

- [ ] **Step 8: Commit.**
  ```bash
  git add tools/vault-engine/pkg/vaultsync/repo_test.go
  git commit -m "test(vault-engine): A21 pin the ErrStopped mapping of Repo.run"
  ```

### A25: the empty-hub test asserts the positive text

- [ ] **Step 9: Edit.** In `TestRepo_NoConnectionErrorsKeepTheirCause` (`pkg/vaultsync/repo_test.go`) replace:
  ```go
  	if _, err := r.RemoteHead(); !errors.Is(err, ErrNoConnection) || strings.Contains(err.Error(), "<nil>") {
  ```
  with:
  ```go
  	if _, err := r.RemoteHead(); !errors.Is(err, ErrNoConnection) || strings.Contains(err.Error(), "<nil>") ||
  		!strings.Contains(err.Error(), "has no refs/heads/") {
  ```

### A27 and A32: the signal test's helper and parent fail clearly

- [ ] **Step 10: A27, the helper.** In `pkg/vaultsync/testkit_test.go`, inside `TestMain` (the `VAULTSYNC_SIGNAL_CHILD` helper mode), replace:
  ```go
  		for deadline := time.Now().Add(30 * time.Second); time.Now().Before(deadline); time.Sleep(10 * time.Millisecond) {
  			if data, err := os.ReadFile(os.Getenv("VAULTSYNC_SIGNAL_PID")); err == nil && len(bytes.TrimSpace(data)) > 0 {
  				break
  			}
  		}
  		fmt.Println("started")
  ```
  with:
  ```go
  		started := false
  		for deadline := time.Now().Add(30 * time.Second); time.Now().Before(deadline); time.Sleep(10 * time.Millisecond) {
  			if data, err := os.ReadFile(os.Getenv("VAULTSYNC_SIGNAL_PID")); err == nil && len(bytes.TrimSpace(data)) > 0 {
  				started = true
  				break
  			}
  		}
  		if !started {
  			fmt.Fprintln(os.Stderr, "the git child never wrote its pid file")
  			os.Exit(4)
  		}
  		fmt.Println("started")
  ```

- [ ] **Step 11: A32 and the Atoi half of A27, the parent.** In `TestRepo_SignalKillsTheGitGroupAndEndsTheEngine` (`pkg/vaultsync/repo_test.go`) replace:
  ```go
  	if line, _ := bufio.NewReader(out).ReadString('\n'); line != "started\n" {
  		t.Fatalf("holder did not start its git child, said %q", line)
  	}
  ```
  with:
  ```go
  	if line, _ := bufio.NewReader(out).ReadString('\n'); line != "started\n" {
  		_ = holder.Process.Kill() // without this the helper would idle for an hour
  		_ = holder.Wait()
  		t.Fatalf("holder did not start its git child, said %q", line)
  	}
  ```
  and replace:
  ```go
  	pid, _ := strconv.Atoi(strings.TrimSpace(string(raw)))
  	_ = holder.Process.Signal(syscall.SIGTERM)
  ```
  with:
  ```go
  	pid, err := strconv.Atoi(strings.TrimSpace(string(raw)))
  	if err != nil {
  		_ = holder.Process.Kill()
  		_ = holder.Wait()
  		t.Fatalf("pid file of the git child holds %q: %v", raw, err)
  	}
  	_ = holder.Process.Signal(syscall.SIGTERM)
  ```
  (There are two `pid, _ := strconv.Atoi(` lines in this file. Change only the one followed by `holder.Process.Signal`; the one in `TestRepo_TimedOutGitIsKilledAndReportedAsNoConnection` is not an item.)

- [ ] **Step 12: Run and expect PASS.**
  ```bash
  cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestRepo_NoConnectionErrorsKeepTheirCause|TestRepo_SignalKillsTheGitGroupAndEndsTheEngine'
  ```
  Expected: vet prints nothing; `ok`.

- [ ] **Step 13: Commit.**
  ```bash
  git add tools/vault-engine/pkg/vaultsync/repo_test.go tools/vault-engine/pkg/vaultsync/testkit_test.go
  git commit -m "test(vault-engine): A25 A27 A32 empty-hub text asserted; signal helper and parent fail clearly"
  ```

- [ ] **Step 14: Phase gate: verify, independent review, fix, re-verify.** Run the `verify-cmd` above. Have `code-reviewer` and `golang-reviewer` review the diff of this task. Ask them to look hardest at: that the outcome of an unconfirmed send is unchanged except for the missing wait; that the new `Repo.run` tests cannot leave a `sleep 30` running. Fix findings in new commits. Run the `verify-cmd` again.

---

## Task 4: Daemon tests (A19, A20, A22)

Tests only. No file outside `daemon_test.go` changes in this task.

**Files:**
- Test: `tools/vault-engine/pkg/vaultsync/daemon_test.go`

**Interfaces (as they are in the code now):**
- `func (d *Daemon) Run(ctx context.Context) error` (daemon.go:38) and `func (d *Daemon) Tick() error` (daemon.go:94). Unchanged.
- `func AcquireFolderLockContext(ctx context.Context, vaultRoot string, timeout time.Duration) (*FolderLock, error)` (lock.go:34). Unchanged. A22 looks for this function's name on the goroutine stacks of the test binary.
- `func runAndCancel(t *testing.T, d *Daemon, ready <-chan struct{}) time.Duration` (daemon_test.go:528). The 200 ms sleep goes (A22); signature stays.
- Relied on: `Daemon.S *Syncer`, `Syncer.Repo *Repo`, `Syncer.Cfg *Config` (`PollIntervalMS`, `LockTimeoutMS`), `Repo.gate`, `func (r *Repo) hasMarker() bool`. `Run` wraps the test's gate: it asks the test's gate only while its own context is not cancelled, and puts the test's gate back when it returns.
- Test helpers that already exist: `newWorld(t)`, `newDaemon(t, root)`, `newSyncer(t, root)`, `quietDrop(t, root, rel, data)`, `commitOp`, `readSHA`, `note1`, `mustGit`, `cleanExceptIgnored(t, root)`, `waitFor(limit, f)`.
- New test helpers in this task: `closedWhen(t *testing.T, cond func() bool) <-chan struct{}`, `waitingForFolderLock() bool`, `cancelledAt(t *testing.T, d *Daemon, word string)`.

**Worker brief**
- `cwd`: `/Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin`
- `verify-cmd`:
  ```bash
  cd tools/vault-engine && go vet ./... && go test -count=3 -race -timeout 40m ./pkg/vaultsync/ -run 'TestDaemon_Cancel' && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestDaemon_' && test "$(grep -c -E '^func (closedWhen|waitingForFolderLock|cancelledAt|TestDaemon_CancelWithoutASignalAtMergeOrCommitIsSettledByTheNextPass)\(' pkg/vaultsync/daemon_test.go)" -eq 4 && ! grep -q 'let it settle into the wait' pkg/vaultsync/daemon_test.go && test -z "$(cd ../.. && git status --porcelain -- tools/vault-engine | grep -v 'daemon_test.go')"
  ```
- `acceptance`:
  1. No goroutine started by `daemon_test.go` can outlive its test: the pid-file poller ends when the test ends.
  2. `runAndCancel` has no fixed sleep; the lock test cancels only once a goroutine is really inside `AcquireFolderLockContext`.
  3. A new test cancels the context (no signal) at `git merge` and at `git commit`, checks the marker is left, and checks the next pass settles everything.
  4. The three cancel tests pass three times in a row under `-race`.

### A19 and A22: a poller that ends, a checked pid, and a real signal instead of a sleep

- [ ] **Step 1: Add two helpers.** In `pkg/vaultsync/daemon_test.go` add `"runtime"` to the import block (between `"path/filepath"` and `"strconv"`). Then replace:
  ```go
  // runAndCancel starts Run, waits for ready, cancels, and returns how long Run
  // took to return after the cancel. Run is always waited for before the test's
  // folders are removed.
  func runAndCancel(
  ```
  with:
  ```go
  // closedWhen returns a channel that is closed once cond is true. Its polling
  // goroutine ends then, or when the test ends, whichever comes first.
  func closedWhen(t *testing.T, cond func() bool) <-chan struct{} {
  	t.Helper()
  	ready, stop := make(chan struct{}), make(chan struct{})
  	t.Cleanup(func() { close(stop) })
  	go func() {
  		for !cond() {
  			select {
  			case <-stop:
  				return
  			case <-time.After(5 * time.Millisecond):
  			}
  		}
  		close(ready)
  	}()
  	return ready
  }

  // waitingForFolderLock reports whether a goroutine of this test binary is
  // inside AcquireFolderLockContext at this moment. A test that itself holds the
  // lock uses it to know that the daemon has really reached the wait.
  func waitingForFolderLock() bool {
  	buf := make([]byte, 1<<20)
  	return bytes.Contains(buf[:runtime.Stack(buf, true)], []byte("vaultsync.AcquireFolderLockContext("))
  }

  // runAndCancel starts Run, waits for ready, cancels at once, and returns how
  // long Run took to return after the cancel. ready must be a real sign that the
  // daemon is in the step under test; no settle time is added. Run is always
  // waited for before the test's folders are removed.
  func runAndCancel(
  ```

- [ ] **Step 2: A22, remove the settle sleep.** Inside `runAndCancel` replace:
  ```go
  	time.Sleep(200 * time.Millisecond) // let it settle into the wait
  	cancel()
  ```
  with:
  ```go
  	cancel()
  ```

- [ ] **Step 3: A19, the pid-file poller.** In `TestDaemon_CancelCutsARunningGitCommandShort` replace:
  ```go
  	ready := make(chan struct{})
  	go func() { // the helper writes its pid once git has started it
  		for {
  			if _, err := os.Stat(pidFile); err == nil {
  				close(ready)
  				return
  			}
  			time.Sleep(10 * time.Millisecond)
  		}
  	}()
  	took := runAndCancel(t, srv, ready)
  ```
  with:
  ```go
  	// The helper writes its pid as its first act, once git has started it. The
  	// file is only "there" when it holds the pid: the cancel follows at once.
  	ready := closedWhen(t, func() bool {
  		data, err := os.ReadFile(pidFile)
  		return err == nil && len(bytes.TrimSpace(data)) > 0
  	})
  	took := runAndCancel(t, srv, ready)
  ```
  (The poller must wait for a pid in the file, not just for the file: with the sleep gone, a cancel right after the file was created could kill the helper before it wrote its pid.)

  In the same test replace:
  ```go
  	pid, _ := strconv.Atoi(strings.TrimSpace(string(raw)))
  	if waitFor(2*time.Second, func() bool { return syscall.Kill(pid, 0) != nil }); syscall.Kill(pid, 0) == nil {
  ```
  with:
  ```go
  	pid, err := strconv.Atoi(strings.TrimSpace(string(raw)))
  	if err != nil {
  		t.Fatalf("pid file holds %q: %v", raw, err)
  	}
  	if waitFor(2*time.Second, func() bool { return syscall.Kill(pid, 0) != nil }); syscall.Kill(pid, 0) == nil {
  ```

- [ ] **Step 4: A22, the lock test waits for the real thing.** In `TestDaemon_CancelEndsTheWaitForTheFolderLock` replace:
  ```go
  	ready := make(chan struct{})
  	var once sync.Once
  	srv.S.Repo.gate = func(args []string) error {
  		for _, a := range args {
  			if a == "--show-toplevel" { // the last git command before the lock is asked for
  				once.Do(func() { close(ready) })
  			}
  		}
  		return nil
  	}
  	took := runAndCancel(t, srv, ready)
  ```
  with:
  ```go
  	// This test holds the lock, so a goroutine inside the lock function is the
  	// daemon waiting for it.
  	took := runAndCancel(t, srv, closedWhen(t, waitingForFolderLock))
  ```
  Keep the `"sync"` import: `TestDaemon_StopSignalDuringGitIsAQuietStop` still uses `sync.Once`.

- [ ] **Step 5: Run three times and expect PASS.**
  ```bash
  cd tools/vault-engine && go vet ./... && go test -count=3 -race -timeout 40m ./pkg/vaultsync/ -run 'TestDaemon_CancelCutsARunningGitCommandShort|TestDaemon_CancelEndsTheWaitForTheFolderLock' -v 2>&1 | grep -E '^(--- |ok|FAIL|panic)|Run returned'
  ```
  Expected: six `--- PASS` lines, `ok`, and `Run returned ... after the cancel` lines of a few milliseconds or less.

- [ ] **Step 6: Commit.**
  ```bash
  git add tools/vault-engine/pkg/vaultsync/daemon_test.go
  git commit -m "test(vault-engine): A19 A22 daemon test pollers end with the test; the lock test waits for the real lock wait"
  ```

### A20: a cancel without a signal during a merge or a commit is settled by the next pass

- [ ] **Step 7: Add the test.** Append to `pkg/vaultsync/daemon_test.go`:
  ```go
  // cancelledAt runs the daemon with a context that is cancelled, without any
  // signal, at the moment git is asked for the command named word. Repo.run then
  // reports that command as ErrStopped. The pass ends there, under the folder
  // lock, with the save marker still on disk.
  func cancelledAt(t *testing.T, d *Daemon, word string) {
  	t.Helper()
  	ctx, cancel := context.WithCancel(context.Background())
  	defer cancel()
  	hit := false
  	d.S.Repo.gate = func(args []string) error {
  		for _, a := range args {
  			if a == word {
  				hit = true
  				cancel()
  			}
  		}
  		return nil
  	}
  	done := make(chan error, 1)
  	go func() { done <- d.Run(ctx) }()
  	select {
  	case err := <-done:
  		if err != nil {
  			t.Fatalf("Run: %v", err)
  		}
  	case <-time.After(30 * time.Second):
  		t.Fatalf("Run did not stop")
  	}
  	d.S.Repo.gate = nil
  	if !hit {
  		t.Fatalf("the pass never reached git %s", word)
  	}
  	if !d.S.Repo.hasMarker() {
  		t.Fatalf("a pass cancelled at git %s should leave its marker for the next pass", word)
  	}
  }

  // A cancel that is not a signal can land while a pass is changing the folder
  // under the lock. Whatever it leaves, the next pass settles it.
  func TestDaemon_CancelWithoutASignalAtMergeOrCommitIsSettledByTheNextPass(t *testing.T) {
  	t.Run("merge of an incoming update", func(t *testing.T) {
  		w := newWorld(t)
  		mac := newSyncer(t, w.Mac)
  		if _, out := mac.Save(commitOp(mac, note1, readSHA(t, w.Mac, note1), 5)); out.Exit != 0 {
  			t.Fatalf("mac save: %+v", out) // srv now has an update to bring in
  		}
  		srv := newDaemon(t, w.Srv)
  		srv.S.Cfg.PollIntervalMS = 50
  		cancelledAt(t, srv, "merge")
  		if readSHA(t, w.Srv, note1) == readSHA(t, w.Mac, note1) {
  			t.Fatalf("the update should not have gone through in the cancelled pass")
  		}
  		if err := srv.Tick(); err != nil {
  			t.Fatalf("next pass: %v", err)
  		}
  		if srv.S.Repo.hasMarker() {
  			t.Fatalf("the next pass must settle the marker")
  		}
  		if readSHA(t, w.Srv, note1) != readSHA(t, w.Mac, note1) {
  			t.Fatalf("the next pass must bring the update in")
  		}
  		cleanExceptIgnored(t, w.Srv)
  		if _, err := os.Stat(filepath.Join(w.Srv, "_quarantine")); !os.IsNotExist(err) {
  			t.Fatalf("nothing was edited by hand, so nothing may be set aside (stat _quarantine: %v)", err)
  		}
  	})
  	t.Run("commit of an inbox drop", func(t *testing.T) {
  		w := newWorld(t)
  		quietDrop(t, w.Mac, "_inbox/human/hi.md", []byte("hi\n"))
  		mac := newDaemon(t, w.Mac)
  		mac.S.Cfg.PollIntervalMS = 50
  		cancelledAt(t, mac, "commit")
  		if st := mustGit(t, w.Mac, "status", "--porcelain"); st != "A  _inbox/human/hi.md" {
  			t.Fatalf("the cancelled pass should have left the drop staged and not committed, got %q", st)
  		}
  		if err := mac.Tick(); err != nil {
  			t.Fatalf("next pass: %v", err)
  		}
  		if mac.S.Repo.hasMarker() {
  			t.Fatalf("the next pass must settle the marker")
  		}
  		if text := mustGit(t, w.Hub, "show", "refs/heads/main:_inbox/human/hi.md"); text != "hi" {
  			t.Fatalf("the drop is not on the hub: %q", text)
  		}
  		if n := mustGit(t, w.Hub, "rev-list", "--count", "refs/heads/main"); n != "2" {
  			t.Fatalf("the hub should hold the seed and one send of the drop, has %s commits", n)
  		}
  		cleanExceptIgnored(t, w.Mac)
  		if _, err := os.Stat(filepath.Join(w.Mac, "_quarantine")); !os.IsNotExist(err) {
  			t.Fatalf("a drop is never set aside by a cancelled pass (stat _quarantine: %v)", err)
  		}
  	})
  }
  ```
  How the cancel reaches git: the test's gate cancels the context and returns nil, so `Repo.run` goes on to start the command with `stop` already cancelled and reports it as `ErrStopped` (repo.go:188, "killed by the cancel, or never started because of it"). For `merge`, the `update` marker and the fetched objects are left. For `commit`, `git add` has already staged the drop and the `inbox` marker is left.

- [ ] **Step 8: Run three times and expect PASS.**
  ```bash
  cd tools/vault-engine && go vet ./... && go test -count=3 -race -timeout 40m ./pkg/vaultsync/ -run 'TestDaemon_CancelWithoutASignal'
  ```
  Expected: vet prints nothing; `ok`.

- [ ] **Step 9: Commit.**
  ```bash
  git add tools/vault-engine/pkg/vaultsync/daemon_test.go
  git commit -m "test(vault-engine): A20 a cancel without a signal at merge or commit is settled by the next pass"
  ```

- [ ] **Step 10: Phase gate: verify, independent review, fix, re-verify.** Run the `verify-cmd` above. Have `code-reviewer` and `golang-reviewer` review the diff of this task. Ask them to look hardest at: goroutines or channels that can outlive a test; whether `waitingForFolderLock` can be true for any goroutine other than the daemon's in these tests; data races on `hit`. Fix findings in new commits. Run the `verify-cmd` again.

---

## Task 5: Build script and its tests (A9, A10, A14, A26, A28, A29, A30, A31)

**Files:**
- Modify: `tools/vault-engine/scripts/build-release.sh`
- Modify: `tools/vault-engine/scripts/sync-harness.sh` (the `fixture_git` function and its three calls only)
- Test: `tools/vault-engine/pkg/vaultsync/build_release_test.go`
- Test: `tools/vault-engine/pkg/vaultsync/testkit_test.go` (`gitIn`)
- Test: `tools/vault-engine/pkg/vaultsync/harness_test.go`

**Interfaces (as they are in the code now, and what they become):**
- `func gitIn(t *testing.T, dir string, env []string, args ...string) (string, error)` (testkit_test.go:77). Its environment changes (A14); signature stays.
- `func runBuild(t *testing.T, dir string) (string, error)` (build_release_test.go:39) becomes `func runBuild(t *testing.T, dir string, extra ...string) (string, error)` (A14, A28, A30). Existing calls `runBuild(t, dir)` keep compiling.
- `func releaseSet(t *testing.T, dir string) string` (build_release_test.go:52). A31 checks one error; signature stays.
- Shell: `fixture_git()` in `scripts/sync-harness.sh:18-20`, today called as `fixture_git -C "$root/seed" <git arguments>`, becomes `fixture_git <dir> <git arguments>` (A14).
- Relied on: `func placeEnv(root string) []string` (repo.go:104): this process's environment without the names in `gitLocationVars`, plus `GIT_CEILING_DIRECTORIES=<parent of root>`. `var gitLocationVars map[string]bool` (repo.go:95).
- Test helpers that already exist: `buildFixture(t)`, `commitAll(t, dir, msg)`, `builtVersion(t, out)`, `mustGit(t, dir, args...)`, `writeFile(t, path, data)`, `otherRepo(t, dir) (state func() string)` (repo_test.go:264).

**Worker brief**
- `cwd`: `/Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin`
- `verify-cmd`:
  ```bash
  cd tools/vault-engine && bash -n scripts/build-release.sh && bash -n scripts/sync-harness.sh && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestBuildRelease_|TestHarness_|TestGitIn_|TestHub_|TestRepo_' && test "$(grep -c -E '^func (TestBuildRelease_TheRealEngineStillHasTheStampedVariable|TestBuildRelease_AnExplicitVersionIsUsedAsGiven)\(' pkg/vaultsync/build_release_test.go)" -eq 2 && test "$(grep -c -E '^func (TestHarness_FixtureGitDropsEveryGitLocationVariable|TestGitIn_IgnoresAnExportedGitDir)\(' pkg/vaultsync/harness_test.go)" -eq 2 && grep -q 'changes="$(git status --porcelain -- .)"' scripts/build-release.sh && grep -q 'echo "built $name"' scripts/build-release.sh && ! grep -q 'sums, _ := os.ReadFile' pkg/vaultsync/build_release_test.go
  ```
- `acceptance`:
  1. `build-release.sh` stops when `git status` fails, and its per-target line reads `built <name>` with no folder.
  2. With `GIT_DIR` exported, `gitIn` works on the folder it is given and leaves the exported repository untouched; `runBuild` and `fixture_git` drop the same variables.
  3. `runBuild` cannot hang past its time limit; an explicit `VERSION` is used as given; the real `main.go` is checked for `var version`.
  4. Build test step 4 can tell the in-file check from the host-run check.

### A9 and A10: the build script

- [ ] **Step 1: Edit `scripts/build-release.sh`.** Replace:
  ```bash
      [ -z "$(git status --porcelain -- .)" ] || VERSION="$VERSION.dirty"
  ```
  with:
  ```bash
      # Assigned first: a git status that fails then stops the script (set -e)
      # instead of reading as a clean tree.
      changes="$(git status --porcelain -- .)"
      [ -z "$changes" ] || VERSION="$VERSION.dirty"
  ```
  and replace:
  ```bash
      echo "built $OUT/$name"
  ```
  with:
  ```bash
      echo "built $name"
  ```
  (The file is still in the staging folder at that point; naming `bin/release/` there was wrong.)

- [ ] **Step 2: Check and commit.**
  ```bash
  cd tools/vault-engine && bash -n scripts/build-release.sh && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestBuildRelease_'
  ```
  Expected: `ok` (about 10 to 30 seconds). From the worktree root:
  ```bash
  git add tools/vault-engine/scripts/build-release.sh
  git commit -m "fix(vault-engine): A9 A10 build script stops on a failing git status and names only the binary it built"
  ```

### A14: fixtures do not pass git's location variables on

- [ ] **Step 3: Write the tests first.** Append to `pkg/vaultsync/harness_test.go`:
  ```go
  // The harness script must drop every variable the product drops.
  func TestHarness_FixtureGitDropsEveryGitLocationVariable(t *testing.T) {
  	script, err := os.ReadFile(filepath.Join("..", "..", "scripts", "sync-harness.sh"))
  	if err != nil {
  		t.Fatalf("read the harness script: %v", err)
  	}
  	for name := range gitLocationVars {
  		if name == "GIT_CEILING_DIRECTORIES" {
  			continue // set, not dropped
  		}
  		if !strings.Contains(string(script), "-u "+name+" ") {
  			t.Errorf("fixture_git in scripts/sync-harness.sh does not drop %s", name)
  		}
  	}
  	if !strings.Contains(string(script), `GIT_CEILING_DIRECTORIES="$(dirname "$dir")"`) {
  		t.Errorf("fixture_git does not stop git from looking above the fixture folder")
  	}
  }

  // With GIT_DIR and friends exported by the runner, the test helpers still act
  // on the folder they are given, never on the exported repository.
  func TestGitIn_IgnoresAnExportedGitDir(t *testing.T) {
  	other := filepath.Join(t.TempDir(), "other")
  	state := otherRepo(t, other)
  	before := state()
  	t.Setenv("GIT_DIR", filepath.Join(other, ".git"))
  	t.Setenv("GIT_WORK_TREE", other)
  	dir := filepath.Join(t.TempDir(), "fixture")
  	writeFile(t, filepath.Join(dir, "a.md"), []byte("a\n"))
  	mustGit(t, dir, "init", "--quiet", "--initial-branch=main")
  	mustGit(t, dir, "add", "-A")
  	mustGit(t, dir, "commit", "--quiet", "-m", "fixture")
  	if top := mustGit(t, dir, "rev-parse", "--show-toplevel"); filepath.Base(top) != "fixture" {
  		t.Fatalf("the helper worked on %s, not on the fixture folder", top)
  	}
  	if after := state(); after != before {
  		t.Fatalf("the exported repository was changed:\nbefore:\n%s\nafter:\n%s", before, after)
  	}
  }
  ```
  Both repositories in the second test are temp folders made by the test; nothing outside them is touched, before or after the fix.

- [ ] **Step 4: Run them and see them fail.**
  ```bash
  cd tools/vault-engine && go test -count=1 -timeout 40m ./pkg/vaultsync/ -run 'TestHarness_FixtureGit|TestGitIn_'
  ```
  Expected: `TestGitIn_IgnoresAnExportedGitDir` FAILs with `the helper worked on .../other, not on the fixture folder`; `TestHarness_FixtureGitDropsEveryGitLocationVariable` FAILs with thirteen `does not drop GIT_...` lines and the ceiling line.

- [ ] **Step 5: Implement in `gitIn`.** In `pkg/vaultsync/testkit_test.go` replace:
  ```go
  	cmd.Dir = dir
  	cmd.Env = append(os.Environ(), env...)
  	out, err := cmd.CombinedOutput()
  ```
  with:
  ```go
  	cmd.Dir = dir
  	// Like a place (placeEnv): git's location variables are not passed on and
  	// git may not look for a repository above dir, so a runner that exports
  	// GIT_DIR cannot turn a fixture command onto another repository.
  	cmd.Env = append(placeEnv(dir), env...)
  	out, err := cmd.CombinedOutput()
  ```

- [ ] **Step 6: Implement in `fixture_git`.** In `scripts/sync-harness.sh` replace:
  ```bash
  fixture_git() {
      git -c user.name=fixture -c user.email=fixture@test.invalid -c commit.gpgsign=false "$@"
  }
  ```
  with:
  ```bash
  # Runs git in <dir> for the fixture. Like a place (gitLocationVars in
  # pkg/vaultsync/repo.go), it does not pass on the variables with which a
  # caller points git at another repository, and git may not look above <dir>.
  fixture_git() { # <dir> <git arguments...>
      local dir=$1
      shift
      env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_COMMON_DIR \
          -u GIT_OBJECT_DIRECTORY -u GIT_ALTERNATE_OBJECT_DIRECTORIES -u GIT_QUARANTINE_PATH \
          -u GIT_NAMESPACE -u GIT_PREFIX -u GIT_IMPLICIT_WORK_TREE -u GIT_SHALLOW_FILE \
          -u GIT_GRAFT_FILE -u GIT_REPLACE_REF_BASE \
          GIT_CEILING_DIRECTORIES="$(dirname "$dir")" \
          git -C "$dir" -c user.name=fixture -c user.email=fixture@test.invalid -c commit.gpgsign=false "$@"
  }
  ```
  and replace its three calls in `setup`:
  ```bash
      fixture_git -C "$root/seed" init --quiet --initial-branch=main
      fixture_git -C "$root/seed" add -A
      fixture_git -C "$root/seed" commit --quiet -m "fixture: synthetic seed"
  ```
  with:
  ```bash
      fixture_git "$root/seed" init --quiet --initial-branch=main
      fixture_git "$root/seed" add -A
      fixture_git "$root/seed" commit --quiet -m "fixture: synthetic seed"
  ```
  Change nothing else in this script. (`runBuild` gets the same environment in Step 9, together with its time limit.)

- [ ] **Step 7: Run and expect PASS, with every test that goes through `gitIn` or the harness script.**
  ```bash
  cd tools/vault-engine && bash -n scripts/sync-harness.sh && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestHarness_|TestGitIn_|TestHub_|TestRepo_'
  ```
  Expected: `ok` (about a minute).

- [ ] **Step 8: Commit.**
  ```bash
  git add tools/vault-engine/pkg/vaultsync/testkit_test.go tools/vault-engine/pkg/vaultsync/harness_test.go tools/vault-engine/scripts/sync-harness.sh
  git commit -m "test(vault-engine): A14 gitIn and fixture_git drop git's location variables"
  ```

### A28, A30, A31, A26, A29 (and the runBuild part of A14): the build test

- [ ] **Step 9: A28 and A14, `runBuild` gets a time limit and a filtered environment.** In `pkg/vaultsync/build_release_test.go` replace the import block with:
  ```go
  import (
  	"context"
  	"os"
  	"os/exec"
  	"path/filepath"
  	"regexp"
  	"runtime"
  	"strings"
  	"syscall"
  	"testing"
  	"time"
  )
  ```
  Add directly above `func commitAll(`:
  ```go
  // buildTimeout bounds one run of the build script (three cross-builds; about
  // ten seconds warm, a few minutes on a cold build cache).
  const buildTimeout = 15 * time.Minute
  ```
  Replace the whole of `runBuild`:
  ```go
  func runBuild(t *testing.T, dir string) (string, error) {
  	t.Helper()
  	cmd := exec.Command("bash", filepath.Join(dir, "scripts", "build-release.sh"))
  	cmd.Env = os.Environ()
  	for _, drop := range []string{"VERSION", "GOOS", "GOARCH", "GOFLAGS"} {
  		cmd.Env = append(cmd.Env, drop+"=")
  	}
  	out, err := cmd.CombinedOutput()
  	return string(out), err
  }
  ```
  with:
  ```go
  // runBuild runs the build script in dir with VERSION, GOOS, GOARCH and GOFLAGS
  // emptied; extra ("NAME=value") is set after that. git's location variables
  // are not passed on (placeEnv). A build that hangs is killed, with every
  // process it started, after buildTimeout.
  func runBuild(t *testing.T, dir string, extra ...string) (string, error) {
  	t.Helper()
  	ctx, cancel := context.WithTimeout(context.Background(), buildTimeout)
  	defer cancel()
  	cmd := exec.CommandContext(ctx, "bash", filepath.Join(dir, "scripts", "build-release.sh"))
  	cmd.Env = placeEnv(dir)
  	for _, drop := range []string{"VERSION", "GOOS", "GOARCH", "GOFLAGS"} {
  		cmd.Env = append(cmd.Env, drop+"=")
  	}
  	cmd.Env = append(cmd.Env, extra...)
  	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
  	cmd.Cancel = func() error { return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) }
  	cmd.WaitDelay = 10 * time.Second
  	out, err := cmd.CombinedOutput()
  	if ctx.Err() != nil {
  		t.Fatalf("the build script did not finish within %v:\n%s", buildTimeout, out)
  	}
  	return string(out), err
  }
  ```

- [ ] **Step 10: A31.** In `releaseSet` replace:
  ```go
  	sums, _ := os.ReadFile(filepath.Join(rel, "SHA256SUMS"))
  	return string(sums)
  ```
  with:
  ```go
  	sums, err := os.ReadFile(filepath.Join(rel, "SHA256SUMS"))
  	if err != nil {
  		t.Fatalf("read the checksum file: %v", err)
  	}
  	return string(sums)
  ```

- [ ] **Step 11: A26.** In `TestBuildRelease_StampsChecksAndKeepsTheOldSetOnFailure`, step 4, replace:
  ```go
  	out, err = runBuild(t, dir)
  	if err == nil || !strings.Contains(out, "does not carry version") {
  		t.Fatalf("a build whose stamp did not take must fail and say so: err=%v\n%s", err, out)
  	}
  ```
  with:
  ```go
  	// The check that looks inside the file names the first target and stops the
  	// build there. The later check, which runs this machine's binary, adds
  	// "(it says: ...)": seeing that would mean the in-file check did not bite.
  	out, err = runBuild(t, dir)
  	if err == nil || !strings.Contains(out, "build-release: vault-engine-darwin-amd64 does not carry version") ||
  		strings.Contains(out, "it says:") {
  		t.Fatalf("a build whose stamp did not take must be stopped by the in-file check on the first target: err=%v\n%s", err, out)
  	}
  ```

- [ ] **Step 12: A29 and A30.** Append to `pkg/vaultsync/build_release_test.go`:
  ```go
  // The fixture has its own main.go, so the test above proves the script, not
  // the script together with the real engine. This pins the one name the script
  // stamps (-X main.version). The fixture's program also ignores its arguments,
  // so the "version" argument the script passes to this machine's binary is not
  // checked by any test.
  func TestBuildRelease_TheRealEngineStillHasTheStampedVariable(t *testing.T) {
  	src, err := os.ReadFile(filepath.Join("..", "..", "cmd", "vault-engine", "main.go"))
  	if err != nil {
  		t.Fatalf("read the engine's main.go: %v", err)
  	}
  	if !strings.Contains(string(src), "\nvar version = \"") {
  		t.Fatalf("cmd/vault-engine/main.go no longer declares `var version = \"...\"`; scripts/build-release.sh stamps main.version")
  	}
  }

  func TestBuildRelease_AnExplicitVersionIsUsedAsGiven(t *testing.T) {
  	dir := buildFixture(t)
  	// An uncommitted file: a version the script worked out itself would end in ".dirty".
  	writeFile(t, filepath.Join(dir, "cmd", "vault-engine", "extra.go"), []byte("package main\n\nvar extra = 1\n"))
  	out, err := runBuild(t, dir, "VERSION=9.9.9-explicit")
  	if err != nil {
  		t.Fatalf("build with an explicit version: %v\n%s", err, out)
  	}
  	if got := builtVersion(t, out); got != "9.9.9-explicit" {
  		t.Fatalf("version = %q, want the explicit one exactly as given", got)
  	}
  	releaseSet(t, dir)
  	host := filepath.Join(dir, "bin", "release", "vault-engine-"+runtime.GOOS+"-"+runtime.GOARCH)
  	if _, statErr := os.Stat(host); statErr == nil {
  		said, runErr := exec.Command(host).Output()
  		if runErr != nil || string(said) != "vault-engine 9.9.9-explicit\n" {
  			t.Fatalf("the built binary says %q (%v), want version 9.9.9-explicit", said, runErr)
  		}
  	}
  }
  ```

- [ ] **Step 13: Run and expect PASS.**
  ```bash
  cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestBuildRelease_'
  ```
  Expected: vet prints nothing; `ok` (about 20 to 60 seconds).

- [ ] **Step 14: Commit.**
  ```bash
  git add tools/vault-engine/pkg/vaultsync/build_release_test.go
  git commit -m "test(vault-engine): A14 A26 A28 A29 A30 A31 build test: time limit, clean git environment, explicit VERSION, real main.go, named check"
  ```

- [ ] **Step 15: Phase gate: verify, independent review, fix, re-verify.** Run the `verify-cmd` above. Have `code-reviewer` and `golang-reviewer` review the diff of this task. Ask them to look hardest at: that `fixture_git` lists every name in `gitLocationVars` except the ceiling; that nothing in `sync-harness.sh` changed besides `fixture_git` and its three calls; that a timed-out build leaves no `go build` running. Fix findings in new commits. Run the `verify-cmd` again.

---

## Task 6: Wording (A2, A3, A11, A23, and the README sentence for A1)

This task also brings the README in line with the A8 change made in Task 2 (Step 6); A8 itself belongs to Task 2.

Comments and text only. One assertion string in a test changes because it quotes the sentence A11 rewrites.

**Files:**
- Modify: `tools/vault-engine/pkg/vaultsync/repo.go` (comments only)
- Modify: `tools/vault-engine/pkg/vaultsync/syncer.go` (comment only)
- Modify: `tools/vault-engine/pkg/vaultsync/lock_test.go` (comment only)
- Modify: `tools/vault-engine/templates/vault-rules/AGENTS.section.md`
- Modify: `tools/vault-engine/pkg/vaultsync/harness_test.go` (the quoted sentence at line 47)
- Modify: `tools/vault-engine/README.md` (one sentence in the paragraph at line 61; one sentence added in the paragraph at line 82)

**Interfaces:** none change. Named for orientation: `type Repo struct` and its field `stop context.Context` (repo.go:35-59), `func errorOutcome(err error) Outcome` (syncer.go:54), `TestFolderLock_WaitEndsAtOnceWhenTheContextIsCancelled` (lock_test.go:61), `TestHarness_InstallsTheRulesFiles` (harness_test.go:37).

**Worker brief**
- `cwd`: `/Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin`
- `verify-cmd`:
  ```bash
  cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestHarness_InstallsTheRulesFiles|TestFolderLock_' && grep -q 'not safe for use from more than one goroutine' pkg/vaultsync/repo.go && grep -q 'The order of the cases' pkg/vaultsync/syncer.go && grep -q 'Your input is probably fine' templates/vault-rules/AGENTS.section.md && ! grep -q 'Your input is fine' templates/vault-rules/AGENTS.section.md pkg/vaultsync/harness_test.go && grep -q 'within a couple of seconds' README.md && grep -q 'something other than a commit' README.md && ! grep -q 'ends at once' README.md && ! grep -q 'or a descriptor open on it' pkg/vaultsync/lock_test.go
  ```
- `acceptance`:
  1. The `Repo` type says it is not safe for use from more than one goroutine, and `errorOutcome` says its answer depends on the order of its cases.
  2. Rule 5 case b reads "Your input is probably fine." and the rules-file test quotes the new sentence.
  3. `tools/vault-engine/README.md` says the daemon ends "within a couple of seconds" and no longer says "ends at once"; its hub paragraph says a tree or blob as the new tip is `type-not-allowed`, exit 6.
  4. No line of executable code changed in `repo.go`, `syncer.go` or `lock_test.go` (comments only).

- [ ] **Step 1: A2.** In `pkg/vaultsync/repo.go` replace:
  ```go
  // Repo is the git side of one place. The engine itself never runs git; this
  // type is the only code that does.
  type Repo struct {
  ```
  with:
  ```go
  // Repo is the git side of one place. The engine itself never runs git; this
  // type is the only code that does.
  //
  // A Repo is not safe for use from more than one goroutine: lock, gate and stop
  // are plain fields, set and read without any synchronisation.
  type Repo struct {
  ```
  and replace:
  ```go
  	// one-shot commands leave it nil. The daemon sets it for the length of Run.
  	stop context.Context
  ```
  with:
  ```go
  	// one-shot commands leave it nil. The daemon sets it for the length of Run.
  	// It is set and read on the one goroutine that uses the Repo, never from
  	// another one (see the note on Repo).
  	stop context.Context
  ```

- [ ] **Step 2: A3.** In `pkg/vaultsync/syncer.go` replace:
  ```go
  func errorOutcome(err error) Outcome {
  ```
  with:
  ```go
  // errorOutcome maps an error to the fixed outcome. The order of the cases
  // decides the answer: one error can match more than one of them (a failed
  // fetch is ErrNoConnection and also carries its cause, such as ErrStopped,
  // ErrTimedOut or an *exec.ExitError), and the first match wins. A new case
  // placed above an existing one can change what an existing error answers.
  func errorOutcome(err error) Outcome {
  ```

- [ ] **Step 3: A23.** In `pkg/vaultsync/lock_test.go` replace:
  ```go
  	// The failed wait must not have left the lock taken or a descriptor open on it.
  ```
  with:
  ```go
  	// The cancelled wait must not have left the lock taken: once the holder lets
  	// go, it can be taken again. This does not prove that the wait closed its
  	// own descriptor (a leaked one that never held the lock would not show
  	// here); the close is in the ctx.Done branch of AcquireFolderLockContext.
  ```

- [ ] **Step 4: A11.** In `templates/vault-rules/AGENTS.section.md` (rule 5, case b) replace:
  ```text
        Your input is fine. Change nothing, wait one minute, and run the same
        command again, up to 3 times. If an earlier try did arrive, the engine
        answers `SAVED` or `REFUSED note-changed` and nothing is saved twice.
  ```
  with:
  ```text
        Your input is probably fine. Change nothing, wait one minute, and run
        the same command again, up to 3 times. If an earlier try did arrive, the
        engine answers `SAVED` or `REFUSED note-changed` and nothing is saved
        twice.
  ```
  (Each of these lines starts with six spaces in the file.) In `pkg/vaultsync/harness_test.go` (line 47) replace `"hit a fault of its own", "Your input is fine",` with `"hit a fault of its own", "Your input is probably fine",`.

- [ ] **Step 5: The README sentence for A1.** In `tools/vault-engine/README.md` (the paragraph at line 61 that starts "Other commands in a shared folder") replace the sentence:
  ```text
  The stop does not wait for a time limit: a git command that is running is killed, and a wait for the folder lock ends at once.
  ```
  with:
  ```text
  The stop does not wait for a time limit: a git command that is running is killed and a wait for the folder lock is given up, so `sync-daemon` ends within a couple of seconds.
  ```
  Change nothing else in that paragraph.

- [ ] **Step 6: Bring the docs in line with A8 (tree or blob tip: `type-not-allowed`, exit 6).** Checked when the plan was written, with:
  ```bash
  grep -n 'type-not-allowed\|engine-error\|only moves forward' tools/vault-engine/README.md tools/vault-engine/templates/vault-rules/AGENTS.section.md
  ```
  What that shows:
  - `templates/vault-rules/AGENTS.section.md`: rule 4 (line 35) and rule 5 (line 43) name the two answers in general. The file gives no exit codes and says nothing about this case. **No change there.**
  - `README.md` lines 54 and 58 (the table of answers): `REFUSED engine-error` is exit 1, `REFUSED type-not-allowed` is exit 6. Both rows stay true. **No change there.**
  - `README.md` line 82 (the hub paragraph) says a git command inside the hook, "including the check that a send only moves forward", is an `engine-error`. After A8 that is no longer the whole truth for a tree or blob tip. **Change this paragraph:** replace the sentence
    ```text
    `too-large` and `type-not-allowed` mean the send broke a rule in the table above.
    ```
    with:
    ```text
    `too-large` and `type-not-allowed` mean the send broke a rule in the table above. A send that points `refs/heads/main` at something other than a commit (a tree or a blob) is also refused as `type-not-allowed`, so the place answers `REFUSED type-not-allowed` (exit 6).
    ```
    Leave the rest of the paragraph as it is.

  Run the grep again before editing; if it shows another place that describes this case, update it the same way and name it in your report.

- [ ] **Step 7: Run and expect PASS.**
  ```bash
  cd tools/vault-engine && go vet ./... && gofmt -l pkg/vaultsync cmd && go test -count=1 -race -timeout 40m ./pkg/vaultsync/ -run 'TestHarness_InstallsTheRulesFiles|TestFolderLock_'
  ```
  Expected: vet and gofmt print nothing; `ok`.

- [ ] **Step 8: Commit** (two commits, from the worktree root).
  ```bash
  git add tools/vault-engine/pkg/vaultsync/repo.go tools/vault-engine/pkg/vaultsync/syncer.go tools/vault-engine/pkg/vaultsync/lock_test.go
  git commit -m "docs(vault-engine): A2 A3 A23 comments say what Repo, errorOutcome and the lock test really promise"
  git add tools/vault-engine/templates/vault-rules/AGENTS.section.md tools/vault-engine/pkg/vaultsync/harness_test.go tools/vault-engine/README.md
  git commit -m "docs(vault-engine): A11 A1 A8 rules text says 'probably fine'; README: daemon ends within a couple of seconds, tree or blob tip is type-not-allowed"
  ```

- [ ] **Step 9: Phase gate: verify, independent review, fix, re-verify.** Run the `verify-cmd` above. Have `code-reviewer` review the diff of this task and confirm with `git diff <commit before the task>..HEAD -- '*.go'` that only comment lines and the one quoted sentence changed in Go files. Fix findings in new commits. Run the `verify-cmd` again.

---

## Final verification

Run once, on the final code, after all six phase gates. All commands from the worktree `/Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin`.

- [ ] **1. Vet and the whole test suite.**
  ```bash
  cd tools/vault-engine && go vet ./... && go test -count=1 -race -timeout 40m ./...
  ```
  Expected: vet prints nothing; one `ok` line per package with tests, no `FAIL`.

- [ ] **2. The full sync harness (about 50 minutes).** The repo's command is `bash scripts/sync-harness.sh run`, run from `tools/vault-engine/` (the script moves there itself). It builds `bin/vault-engine` (an ignored folder), runs every package once in short rounds and prints the last 12 lines of that, then runs the sync scenarios in full rounds (`VAULT_SYNC_ROUNDS=full go test ./pkg/vaultsync/ -run 'TestScenario' -count=1 -timeout 90m -v`) and prints only the lines that start with `--- `, `ok`, `FAIL`, `LATENCY`, `KILLS` or `panic`. The script runs under `set -euo pipefail`, so its exit status is 0 only when both test runs passed.

  Run it so that the exit status and the scenario count are both checked:
  ```bash
  cd tools/vault-engine && bash -c 'out="$(mktemp)"; bash scripts/sync-harness.sh run 2>&1 | tee "$out"; st=${PIPESTATUS[0]}; echo "harness exit=$st scenarios passed=$(grep -c "^--- PASS: TestScenario" "$out")"; test "$st" -eq 0 && test "$(grep -c "^--- PASS: TestScenario" "$out")" -eq 7 && ! grep -qE "^(--- FAIL|FAIL|panic)" "$out"'
  ```
  Expected: seven lines `--- PASS: TestScenario01_DifferentNotesAtTheSameMoment`, `TestScenario02_SameNoteAtTheSameMoment`, `TestScenario04_NewNotesNeverShareANumber`, `TestScenario05_SaveRacesIncomingUpdate`, `TestScenario06_DelayBetweenPlaces`, `TestScenario07_KilledMidSaveAndMidUpdate`, `TestScenario18_OnePlaceOverItsAllowance`; `LATENCY` and `KILLS` lines; a final `ok  	obsidian-vault-engine/pkg/vaultsync`; the last line `harness exit=0 scenarios passed=7`; the whole command exits 0. The harness never reads or writes the real vault, and it must not be given a redirected `HOME`.

- [ ] **3. Commits name their items.** The feature branch `feat/F-025` starts at commit `bf09d62` (`chore(catalog): claim F-025`), which is also where it left `release/1.12`.
  ```bash
  git log --format=%s b2e7798..HEAD | grep -oE 'A[0-9]+' | sort -u | wc -l
  ```
  Expected: `32`.

- [ ] **4. Nothing outside the scope changed, and the main branch is untouched.**
  ```bash
  git diff --name-only bf09d62..HEAD | grep -v '^tools/vault-engine/' | grep -v '^\.claude/'
  git branch --show-current
  ```
  Expected: no file names from the first command; `feat/F-025` from the second. No command in this plan checks out, commits on or pushes to `main`.

- [ ] **5. Every item has its task.**

| Item | Task | What proves it |
|---|---|---|
| A1 | 3 (code), 6 (README sentence) | `TestSave_StopDuringTheConfirmFetchAsksOnceAndStaysUnconfirmed`; README says "within a couple of seconds" |
| A2 | 6 | comment on `Repo` and `stop` |
| A3 | 6 | comment on `errorOutcome` |
| A4 | 1 | `TestUndo_RefusesWhenTheMarkerFileIsGone` |
| A5 | 1 | `TestUpdate_AnInterruptedCompareLeavesTheClashingFileWhereItIs` (stop: file stays); `TestUpdate_AClashingFileThatCannotBeHashedIsStillSetAside` (any other failure: still moved aside) |
| A6 | 1 | "record undo start" asserted in `TestUndo_WhenTheUndoStartCannotBeRecordedNothingIsChanged` |
| A7 | 1 | `TestWriteFileAtomic_SyncsTheFolderAfterTheRenameAndReturnsItsError`; comment on `writeFileAtomic` |
| A8 | 2 (README sentence in 6) | `TestPreReceive_ATreeOrBlobAsTheNewTipIsTypeNotAllowed`; `TestSave_ATreeOrBlobRefusalFromTheHubEndsWithExitSix` (exit 6) |
| A9 | 5 | `changes="$(git status ...)"` in `build-release.sh` |
| A10 | 5 | `echo "built $name"` in `build-release.sh` |
| A11 | 6 | "Your input is probably fine." in the rules text and in `TestHarness_InstallsTheRulesFiles` |
| A12 | 2 | `code != 1` in `TestPreReceive_AncestorCheckThatCannotRunIsAnEngineError` |
| A13 | 2 | `hubGit(dir, stdin, ...)`; `hubRepo` in the hub tests |
| A14 | 5 | `TestGitIn_IgnoresAnExportedGitDir`, `TestHarness_FixtureGitDropsEveryGitLocationVariable`; `placeEnv` in `runBuild` |
| A15 | 1 | `TestUndo_WhenTheUndoStartCannotBeRecordedNothingIsChanged` |
| A16 | 1 | `TestUndo_RefusesAMarkerThatBelongsToAnotherSave`, `TestUndo_RefusesWhenTheMarkerFileIsGone` |
| A17 | 1 | exactly 3 `original, _ := os.ReadFile` left in `recover_test.go` (lines 224, 582, 635 today: places A17 does not name, so they stay) |
| A18 | 1 | head-equals-base assertion in `undoAfterFailedPass` |
| A19 | 4 | `closedWhen`; checked `Atoi` in `TestDaemon_CancelCutsARunningGitCommandShort` |
| A20 | 4 | `TestDaemon_CancelWithoutASignalAtMergeOrCommitIsSettledByTheNextPass` |
| A21 | 3 | `TestRepoRun_CancelDuringASlowCommandGivesErrStopped`, `TestRepoRun_ACommandThatEndedWellKeepsItsResultWhenStopIsAlreadyCancelled` |
| A22 | 4 | no sleep in `runAndCancel`; `waitingForFolderLock` |
| A23 | 6 | comment in `TestFolderLock_WaitEndsAtOnceWhenTheContextIsCancelled` |
| A24 | 2 | `TestChargeDaily_AUsageFileThatCannotBeWrittenChargesNothing`, `TestHub_UsageFileThatCannotBeWrittenRefusesTheSendAndChargesNothing` |
| A25 | 3 | "has no refs/heads/" asserted in `TestRepo_NoConnectionErrorsKeepTheirCause` |
| A26 | 5 | binary name asserted in build test step 4 |
| A27 | 3 | `os.Exit(4)` in the helper; checked `Atoi` in `TestRepo_SignalKillsTheGitGroupAndEndsTheEngine` |
| A28 | 5 | `buildTimeout` in `runBuild` |
| A29 | 5 | `TestBuildRelease_TheRealEngineStillHasTheStampedVariable` |
| A30 | 5 | `TestBuildRelease_AnExplicitVersionIsUsedAsGiven` |
| A31 | 5 | checked read of `SHA256SUMS` in `releaseSet` |
| A32 | 3 | kill before `Fatalf` in `TestRepo_SignalKillsTheGitGroupAndEndsTheEngine` |

Five behaviour changes, each with a test that fails before the fix and passes after: A1, A4, A5, A7, A8.

---

## Follow-ups not in this plan

- **Git location variables, the places A14 does not name:** `git clone` in `make_place` (`scripts/sync-harness.sh:86`), `git push` in `setup` (`scripts/sync-harness.sh:126`), the `git init` / `git config` lines of `hub/create-hub.sh`, and the Go helpers `newWorld` and `newHub` (`pkg/vaultsync/testkit_test.go`), which pass `os.Environ()` to those scripts, still inherit an exported `GIT_DIR`. Decided: A14 stays as worded; this is a later item.

## Open problems found while planning

Nothing is open. Both STOP checks came out clean when the plan was written: no production caller reaches `Undo` without a marker on disk, and nothing but tests reads the text of the refusal reason.

Decisions taken on what was raised (recorded so the tasks are not second-guessed):

1. **A5 is narrowed.** Only a comparison cut by a stop (`ErrStopped`) is "unknown". Every other failure keeps today's behaviour, so a file git can never hash cannot block updates. The design's A5 row says the same.
2. **A14 stays as worded.** The wider fix is the follow-up above.
3. **A8's exit code change (1 becomes 6) is accepted**, asserted by a test in Task 2 and written into the README in Task 6. A tree or blob sent to an empty hub takes a different path (`rev-list`) and is not part of the item.
4. **A13** (a `dir` argument on `PreReceive` and `batchCheck` as well as `hubGit`), **A11** (the quoted sentence at `harness_test.go:47` changes with the rules text) and **A22** (the lock test reads its own goroutine stacks, because Task 4 is tests only) are accepted as planned.
5. **The harness script's own `go test` time limits stay untouched** (no `-timeout` on the short rounds, `-timeout 90m` on the full scenarios). If the short rounds ever run past Go's 10-minute default, report it; do not edit the script.
6. **Path of the rules file:** it is `tools/vault-engine/templates/vault-rules/AGENTS.section.md`; there is no top-level `templates/vault-rules/`.

## Appendix — audit trail
- 2026-10-13 self-grill-audit: verdict safe-with-fixes. Corrected: (1) Task 1 verify-cmd demanded zero `original, _ := os.ReadFile` in `recover_test.go`, but A17 names only lines 53, 71, 161, 179, 840, 874, so three stay (224, 582, 635); the check now expects exactly 3, and the A17 row of the final table says the same. (2) The "32 items named" count now starts after the plan commit (`b2e7798`), whose own subject says "A1-A32" and would have pre-seeded the count. Handled by the orchestrator at dispatch time, not by plan edits: every verify-cmd is saved as a script file and passed as `bash <file>` (the inline form has `$(...)` that the dispatching shell would expand in the wrong folder); each script also runs `gofmt -l pkg/vaultsync cmd scripts`; Task 5's script runs the whole `pkg/vaultsync` package because A14 changes `gitIn`, which every test group uses. Pointed out to the Task 1 reviewer: A7's branch where the folder sync fails after the rename (file already in place, error returned; `chargeDaily` then refuses a send it has charged). Not fixed (LOW): the plan says twelve `Undo` calls in `recover_test.go`, there are 11; `type Repo` is at `repo.go:37-60`; Task 4's "only daemon_test.go changed" clause checks nothing; three acceptance points have no machine check (Task 2 "no cmd.Env in hubGit", Task 6 "comments only", A9 proven by grep only) and are left to the task reviewers.
  Open: none.
