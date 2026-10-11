package vaultsync

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"obsidian-vault-engine/pkg/vault"
)

const note1, note2 = "IDEA-2026-000001", "IDEA-2026-000002"

func commitOp(s *Syncer, id, sha string, impact int) Op {
	return CommitOp(s.Engine, vault.CommitRequest{RecordID: id, ExpectedSHA256: sha, Actor: "agent-olivier",
		Updates: map[string]interface{}{"impact": impact}, Reason: "test"})
}

func cleanExceptIgnored(t *testing.T, root string) {
	t.Helper()
	if st := mustGit(t, root, "status", "--porcelain"); st != "" {
		t.Fatalf("%s is not clean:\n%s", root, st)
	}
}

func TestSave_SendsExactlyWhatTheOperationWrote(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	writeFile(t, filepath.Join(w.Mac, "_inbox", "agent", "agent-olivier", "mac-test-1.md"), []byte("a waiting drop\n"))

	msg, out := mac.Save(commitOp(mac, note1, readSHA(t, w.Mac, note1), 5))
	if out.Line != "SAVED" || out.Exit != 0 {
		t.Fatalf("outcome = %+v", out)
	}
	if msg != "Commit SUCCESS for IDEA-2026-000001 by agent-olivier (OCC validated)\n" {
		t.Errorf("engine message changed: %q", msg)
	}
	if author := mustGit(t, w.Hub, "log", "-1", "--format=%an", "refs/heads/main"); author != "agent-olivier@mac-test" {
		t.Errorf("author on hub = %q", author)
	}
	files := strings.Split(mustGit(t, w.Hub, "show", "--name-only", "--format=", "refs/heads/main"), "\n")
	if len(files) != 2 || !strings.HasPrefix(files[0], "01_Ideas/IDEA-2026-000001--") || !strings.HasPrefix(files[1], "_meta/events/") {
		t.Errorf("the save should hold the note and its event file, got %v", files)
	}
	if st := mustGit(t, w.Mac, "status", "--porcelain"); st != "?? _inbox/agent/agent-olivier/mac-test-1.md" {
		t.Errorf("the drop must stay untouched and unsent by a save:\n%s", st)
	}
	if mac.Repo.hasMarker() {
		t.Errorf("marker left behind")
	}
}

func TestSave_StaleFingerprintFromAnotherPlaceIsRefused(t *testing.T) {
	w := newWorld(t)
	mac, srv := newSyncer(t, w.Mac), newSyncer(t, w.Srv)
	stale := readSHA(t, w.Srv, note1) // srv reads, then mac changes the note
	if _, out := mac.Save(commitOp(mac, note1, readSHA(t, w.Mac, note1), 5)); out.Exit != 0 {
		t.Fatalf("mac save: %+v", out)
	}
	_, out := srv.Save(commitOp(srv, note1, stale, 1))
	if out.Line != "REFUSED note-changed" || out.Exit != ExitNoteChanged {
		t.Fatalf("outcome = %+v", out)
	}
	cleanExceptIgnored(t, w.Srv)
	if a, b := readSHA(t, w.Srv, note1), readSHA(t, w.Mac, note1); a != b {
		t.Fatalf("srv should now hold mac's version")
	}
}

// Spec test 15: the send loses the race 3 times in a row.
func TestSave_LosesTheRaceThreeTimesThenSaves(t *testing.T) {
	w := newWorld(t)
	mac, srv := newSyncer(t, w.Mac), newSyncer(t, w.Srv)
	drop := filepath.Join(w.Mac, "_inbox", "agent", "agent-olivier", "mac-test-race.md")
	writeFile(t, drop, []byte("---\ntitle: Race idea\n---\nBody\n"))
	if state, out := mac.sendDrops([]string{"_inbox/agent/agent-olivier/mac-test-race.md"}, 1); state != pushOK {
		t.Fatalf("sending the drop first: %+v", out)
	}
	races := 0
	mac.Hooks.BeforePush = func(attempt int) {
		if attempt <= 3 { // another place gets in first
			races++
			if _, out := srv.Save(commitOp(srv, note2, readSHA(t, w.Srv, note2), attempt)); out.Exit != 0 {
				t.Errorf("srv save during race: %+v", out)
			}
		}
	}
	msg, out := mac.Save(IngestOp(mac.Engine, drop, "agent-olivier"))
	if out.Line != "SAVED" || races != 3 {
		t.Fatalf("outcome = %+v after %d races (%s)", out, races, msg)
	}
	ideas, _ := filepath.Glob(filepath.Join(w.Mac, "01_Ideas", "IDEA-*--race-idea.md"))
	if len(ideas) != 1 {
		t.Fatalf("expected exactly one ingested note, got %v", ideas)
	}
	cleanExceptIgnored(t, w.Mac)
	if mac.Repo.hasMarker() {
		t.Errorf("marker left behind")
	}
	index, _ := os.ReadFile(filepath.Join(w.Mac, "_meta", "indexes", "ideas.jsonl"))
	if strings.Count(string(index), "Race idea") != 1 {
		t.Errorf("index should list the note once:\n%s", index)
	}
	if n := mustGit(t, w.Hub, "log", "--format=%s", "--grep=vault: ingest", "refs/heads/main"); strings.Count(n, "\n") != 0 {
		t.Errorf("hub should hold one ingest commit, got:\n%s", n)
	}
}

// A file made by hand while a save loses the race is not deleted by the undo
// and is not sent by the retry.
func TestSave_LostRaceUndoLeavesAHandMadeFileAlone(t *testing.T) {
	w := newWorld(t)
	mac, srv := newSyncer(t, w.Mac), newSyncer(t, w.Srv)
	byHand := filepath.Join(w.Mac, "01_Ideas", "made-by-hand.md")
	mac.Hooks.BeforePush = func(attempt int) {
		if attempt == 1 {
			writeFile(t, byHand, []byte("typed by a person while the save ran\n"))
			if _, out := srv.Save(commitOp(srv, note2, readSHA(t, w.Srv, note2), 4)); out.Exit != 0 {
				t.Errorf("srv save during race: %+v", out)
			}
		}
	}
	if _, out := mac.Save(commitOp(mac, note1, readSHA(t, w.Mac, note1), 5)); out.Line != "SAVED" {
		t.Fatalf("outcome = %+v", out)
	}
	if text, err := os.ReadFile(byHand); err != nil || string(text) != "typed by a person while the save ran\n" {
		t.Fatalf("the hand-made file must survive the undo untouched: %q, %v", text, err)
	}
	if _, err := gitIn(t, w.Hub, nil, "cat-file", "-e", "refs/heads/main:01_Ideas/made-by-hand.md"); err == nil {
		t.Fatalf("a hand-made file must never be sent")
	}
	if st := mustGit(t, w.Mac, "status", "--porcelain"); st != "?? 01_Ideas/made-by-hand.md" {
		t.Fatalf("only the hand-made file may remain, waiting for the sync-daemon:\n%s", st)
	}
	if _, err := os.Stat(filepath.Join(w.Mac, "_quarantine")); !os.IsNotExist(err) {
		t.Errorf("a lost race must not fill _quarantine/ with the save's own files")
	}
}

// Spec test 8.
func TestSave_NoConnectionChangesNothing(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	before := readSHA(t, w.Mac, note1)
	if err := os.Rename(w.Hub, w.Hub+".off"); err != nil {
		t.Fatalf("rename hub: %v", err)
	}
	_, out := mac.Save(commitOp(mac, note1, before, 5))
	if out.Line != "REFUSED no-connection" || out.Exit != ExitNoConnection {
		t.Fatalf("outcome = %+v", out)
	}
	if readSHA(t, w.Mac, note1) != before {
		t.Fatalf("the note changed although the save was refused")
	}
	cleanExceptIgnored(t, w.Mac)
}

// Spec test 16: the connection is cut exactly after the hub accepted.
func TestSave_LostAnswerIsConfirmedWithTheHubAndACreateIsNotRepeated(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	drop := filepath.Join(w.Mac, "_inbox", "agent", "agent-olivier", "mac-test-once.md")
	writeFile(t, drop, []byte("---\ntitle: Only once\n---\nBody\n"))
	mac.Hooks.PushResult = func(_ int, res gitResult) gitResult {
		if res.Err == nil { // the hub accepted; the answer never arrives
			return gitResult{Err: errors.New("simulated: connection reset")}
		}
		return res
	}
	op := IngestOp(mac.Engine, drop, "agent-olivier")
	if _, out := mac.Save(op); out.Line != "SAVED" {
		t.Fatalf("a save the hub has must be reported as SAVED, got %+v", out)
	}
	mac.Hooks = Hooks{}
	// The agent tries the same create again.
	msg, out := mac.Save(IngestOp(mac.Engine, drop, "agent-olivier"))
	if out.Line != "SAVED" || !strings.Contains(msg, "Already saved") {
		t.Fatalf("second try = %+v (%q)", out, msg)
	}
	ideas, _ := filepath.Glob(filepath.Join(w.Mac, "01_Ideas", "IDEA-*--only-once.md"))
	if len(ideas) != 1 {
		t.Fatalf("expected one note, got %v", ideas)
	}
}

func TestSave_UnreachableHubAfterPushLeavesTheDecisionToTheNextCommand(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	sha := readSHA(t, w.Mac, note1)
	mac.Hooks.PushResult = func(_ int, res gitResult) gitResult {
		_ = os.Rename(w.Hub, w.Hub+".off") // accepted, then everything is gone
		return gitResult{Err: errors.New("simulated: connection reset")}
	}
	if _, out := mac.Save(commitOp(mac, note1, sha, 5)); out.Line != "REFUSED no-connection" {
		t.Fatalf("outcome = %+v", out)
	}
	if !mac.Repo.hasMarker() {
		t.Fatalf("the marker must stay until the hub can be asked")
	}
	mac.Hooks = Hooks{}
	if err := os.Rename(w.Hub+".off", w.Hub); err != nil {
		t.Fatalf("rename back: %v", err)
	}
	// Rule 3: the agent runs the same command again. The first try did arrive.
	if _, out := mac.Save(commitOp(mac, note1, sha, 5)); out.Line != "REFUSED note-changed" {
		t.Fatalf("retry = %+v, want REFUSED note-changed because the first try arrived", out)
	}
	if mac.Repo.hasMarker() {
		t.Fatalf("marker should be settled")
	}
	cleanExceptIgnored(t, w.Mac)
}

// A send that hits its time limit is "not confirmed", never "refused".
func TestSave_TimedOutSendIsSettledByTheNextCommand(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	sha := readSHA(t, w.Mac, note1)
	// The hub does not take the send (allowance used up); the place only sees its own time limit.
	settings := filepath.Join(w.Hub, "hooks", "vault-limits.json")
	original, _ := os.ReadFile(settings)
	tight := strings.Replace(string(original), `"daily_bytes_per_place": 52428800`, `"daily_bytes_per_place": 1`, 1)
	if tight == string(original) {
		t.Fatalf("could not tighten the allowance in %s", settings)
	}
	if err := os.WriteFile(settings, []byte(tight), 0644); err != nil {
		t.Fatalf("write settings: %v", err)
	}
	mac.Hooks.PushResult = func(_ int, res gitResult) gitResult {
		if res.Err == nil {
			t.Errorf("the hub should not have taken this send")
		}
		return gitResult{Err: fmt.Errorf("send stalled: %w", ErrTimedOut)} // the sentinel, not the wording, counts
	}
	if _, out := mac.Save(commitOp(mac, note1, sha, 5)); out.Line != "REFUSED no-connection" || out.Exit != ExitNoConnection ||
		!strings.Contains(out.Detail, "time limit") {
		t.Fatalf("outcome = %+v, want REFUSED no-connection naming the time limit", out)
	}
	if !mac.Repo.hasMarker() {
		t.Fatalf("the marker must stay until the hub can be asked again")
	}
	mac.Hooks = Hooks{}
	if err := os.WriteFile(settings, original, 0644); err != nil {
		t.Fatalf("restore settings: %v", err)
	}
	// It had not arrived: the next command takes the unsent save back, and the same save goes through.
	if _, out := mac.Save(commitOp(mac, note1, sha, 5)); out.Line != "SAVED" {
		t.Fatalf("retry = %+v, want SAVED", out)
	}
	if mac.Repo.hasMarker() {
		t.Fatalf("marker should be settled")
	}
	cleanExceptIgnored(t, w.Mac)
	if hub := mustGit(t, w.Hub, "rev-list", "--count", "refs/heads/main"); hub != "2" {
		t.Fatalf("hub should hold the seed and one save, has %s commits", hub)
	}
}

// Spec test 9, first half.
func TestSave_OversizedOrWrongTypeIsRefusedAndNothingIsLeftBehind(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	src := filepath.Join(t.TempDir(), "big-note.md")
	writeFile(t, src, append([]byte("---\ntitle: Big\nkind: concept\n---\n"), make([]byte, 5<<20)...))
	_, out := mac.Save(PublishOp(mac.Engine, src, "process", "agent-olivier"))
	if out.Line != "REFUSED too-large" || out.Exit != ExitTooLarge || !strings.Contains(out.Detail, "max_file_bytes=1048576") {
		t.Fatalf("outcome = %+v", out)
	}
	cleanExceptIgnored(t, w.Mac)
	if left, _ := filepath.Glob(filepath.Join(w.Mac, "04_Knowledge", "*", "big-note.md")); len(left) != 0 {
		t.Fatalf("refused note left behind: %v", left)
	}
	if hub := mustGit(t, w.Hub, "rev-list", "--count", "refs/heads/main"); hub != "1" {
		t.Fatalf("hub should still hold only the seed, has %s commits", hub)
	}
}

func TestSave_UnsentDropIsSentBeforeIngestDeletesIt(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	drop := filepath.Join(w.Mac, "_inbox", "human", "from-a-person.md")
	writeFile(t, drop, []byte("---\ntitle: From a person\n---\nOriginal words\n"))
	if _, out := mac.Save(IngestOp(mac.Engine, drop, "agent-olivier")); out.Line != "SAVED" {
		t.Fatalf("outcome = %+v", out)
	}
	subjects := mustGit(t, w.Hub, "log", "--format=%s", "refs/heads/main")
	if !strings.Contains(subjects, "vault: inbox drop by inbox@mac-test") || !strings.Contains(subjects, "vault: ingest by agent-olivier@mac-test") {
		t.Fatalf("expected a drop commit and an ingest commit on the hub:\n%s", subjects)
	}
	// The original can always be recovered from the shared history.
	if text := mustGit(t, w.Hub, "show", "refs/heads/main~1:_inbox/human/from-a-person.md"); !strings.Contains(text, "Original words") {
		t.Fatalf("original drop not recoverable: %q", text)
	}
}

func TestSave_LockTimeoutIsBusy(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	mac.Cfg.LockTimeoutMS = 100
	held, err := AcquireFolderLock(w.Mac, 0)
	if err != nil {
		t.Fatalf("lock: %v", err)
	}
	defer held.Release()
	if _, out := mac.Save(commitOp(mac, note1, readSHA(t, w.Mac, note1), 5)); out.Line != "REFUSED busy" || out.Exit != ExitBusy {
		t.Fatalf("outcome = %+v", out)
	}
}

func TestViolationOutcome_EveryHubLabelHasAnExitCode(t *testing.T) {
	for _, c := range []struct {
		code string
		line string
		exit int
	}{
		{"too-large", "REFUSED too-large", ExitTooLarge},
		{"type-not-allowed", "REFUSED type-not-allowed", ExitTypeNotAllowed},
		{"engine-error", "REFUSED engine-error", ExitEngineError},
		{"something-new", "REFUSED engine-error", ExitEngineError},
	} {
		if out := violationOutcome(&Violation{Code: c.code, Message: "m"}); out.Line != c.line || out.Exit != c.exit {
			t.Errorf("%s -> %+v", c.code, out)
		}
	}
	if out := errorOutcome(errors.New("plain")); out.Exit != ExitEngineError {
		t.Errorf("plain error -> %+v", out)
	}
}

// The push answers that are read from the text git prints.
func TestSave_PushAnswersAreReadFromTheirText(t *testing.T) {
	for _, c := range []struct {
		stderr string
		line   string
		exit   int
	}{
		{"remote: vault-hub: REFUSED engine-error: settings unreadable\n", "REFUSED engine-error", ExitEngineError},
		{"remote: vault-hub: REFUSED type-not-allowed: x.exe\n", "REFUSED type-not-allowed", ExitTypeNotAllowed},
		{"fatal: pack exceeds maximum allowed size (20.00 MiB)\n", "REFUSED too-large", ExitTooLarge},
	} {
		w := newWorld(t)
		mac := newSyncer(t, w.Mac)
		mac.Hooks.PushResult = func(_ int, res gitResult) gitResult {
			return gitResult{Stderr: c.stderr, Err: errors.New("exit status 1")}
		}
		before := readSHA(t, w.Mac, note1)
		if _, out := mac.Save(commitOp(mac, note1, before, 5)); out.Line != c.line || out.Exit != c.exit {
			t.Fatalf("%q -> %+v", c.stderr, out)
		}
		if mac.Repo.hasMarker() || readSHA(t, w.Mac, note1) != before {
			t.Fatalf("a refused save must be taken back completely")
		}
		cleanExceptIgnored(t, w.Mac)
	}
}

func TestSave_BeginRefusesToOverwriteAnOpenMarker(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	if _, err := mac.Repo.Begin("commit", "someone"); err != nil {
		t.Fatalf("begin: %v", err)
	}
	if _, err := mac.begin("commit", "agent"); err == nil {
		t.Fatalf("a second marker must not be opened over an unsettled one")
	}
}

func countIdeas(t *testing.T, root string) int {
	t.Helper()
	m, _ := filepath.Glob(filepath.Join(root, "01_Ideas", "IDEA-*.md"))
	return len(m)
}

// C1: ingest deletes its source, so a source that git cannot protect is refused up front.
func TestSave_IngestOfAFileOutsideTheInboxIsRefusedAndTheFileStays(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	src := filepath.Join(t.TempDir(), "elsewhere.md")
	writeFile(t, src, []byte("---\ntitle: Elsewhere\n---\nOnly copy\n"))
	link := filepath.Join(w.Mac, "_inbox", "human", "link.md") // a link in the inbox to a file outside
	if err := os.MkdirAll(filepath.Dir(link), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(src, link); err != nil {
		t.Fatal(err)
	}
	before := countIdeas(t, w.Mac)
	for _, p := range []string{src, link, filepath.Join(w.Mac, "01_Ideas", "..", "README-not-inbox.md")} {
		_, out := mac.Save(IngestOp(mac.Engine, p, "agent-olivier"))
		if out.Line != "REFUSED engine-error" || out.Exit != ExitEngineError || !strings.Contains(out.Detail, "inbox") {
			t.Fatalf("%s -> %+v", p, out)
		}
	}
	if text, err := os.ReadFile(src); err != nil || !strings.Contains(string(text), "Only copy") {
		t.Fatalf("the source must still be there: %v", err)
	}
	if mac.Repo.hasMarker() || countIdeas(t, w.Mac) != before {
		t.Fatalf("nothing may be started or created")
	}
}

func TestIngestOp_FollowsSymlinksToTheRealInboxPath(t *testing.T) {
	w := newWorld(t)
	e := vault.NewVaultEngine(w.Mac)
	drop := filepath.Join(w.Mac, "_inbox", "human", "real.md")
	writeFile(t, drop, []byte("x\n"))
	link := filepath.Join(t.TempDir(), "via-link.md")
	if err := os.Symlink(drop, link); err != nil {
		t.Fatal(err)
	}
	if op := IngestOp(e, link, "a"); op.Refuse != "" || op.Drop != "_inbox/human/real.md" {
		t.Fatalf("a link to an inbox drop must be recognised: %+v", op)
	}
}

// C1(b) and spec: a lost race on a real inbox ingest leaves the original recoverable, and the retry saves.
func TestSave_InboxIngestLosingTheRaceKeepsTheOriginalRecoverable(t *testing.T) {
	w := newWorld(t)
	mac, srv := newSyncer(t, w.Mac), newSyncer(t, w.Srv)
	drop := filepath.Join(w.Mac, "_inbox", "human", "c1b.md")
	writeFile(t, drop, []byte("---\ntitle: C one b\n---\nOriginal words\n"))
	if state, out := mac.sendDrops([]string{"_inbox/human/c1b.md"}, 1); state != pushOK { // the race must hit the ingest, not the drop
		t.Fatalf("sending the drop first: %+v", out)
	}
	mac.Hooks.BeforePush = func(attempt int) {
		if attempt == 1 {
			if _, out := srv.Save(commitOp(srv, note2, readSHA(t, w.Srv, note2), 4)); out.Exit != 0 {
				t.Errorf("srv save: %+v", out)
			}
		}
	}
	if _, out := mac.Save(IngestOp(mac.Engine, drop, "agent-olivier")); out.Line != "SAVED" {
		t.Fatalf("outcome = %+v", out)
	}
	added := mustGit(t, w.Hub, "log", "--all", "--diff-filter=A", "--format=%H", "--", "_inbox/human/c1b.md")
	if added == "" {
		t.Fatalf("the original never reached the shared history")
	}
	if text := mustGit(t, w.Hub, "show", strings.Fields(added)[0]+":_inbox/human/c1b.md"); !strings.Contains(text, "Original words") {
		t.Fatalf("original not recoverable: %q", text)
	}
	if ideas, _ := filepath.Glob(filepath.Join(w.Mac, "01_Ideas", "IDEA-*--c-one-b.md")); len(ideas) != 1 {
		t.Fatalf("expected exactly one note, got %v", ideas)
	}
	cleanExceptIgnored(t, w.Mac)
}

// I2: an unclear answer with an unmoved hub is never a verdict.
func TestSave_UnclearAnswerWithUnmovedHubKeepsMarkerAndCommitThenRecovers(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	sha := readSHA(t, w.Mac, note1)
	settings := filepath.Join(w.Hub, "hooks", "vault-limits.json")
	original, _ := os.ReadFile(settings)
	tight := strings.Replace(string(original), `"daily_bytes_per_place": 52428800`, `"daily_bytes_per_place": 1`, 1)
	if tight == string(original) {
		t.Fatalf("could not tighten the allowance")
	}
	if err := os.WriteFile(settings, []byte(tight), 0644); err != nil {
		t.Fatal(err)
	}
	mac.Hooks.PushResult = func(_ int, res gitResult) gitResult {
		return gitResult{Stderr: "something git never says", Err: errors.New("exit status 128")}
	}
	if _, out := mac.Save(commitOp(mac, note1, sha, 5)); out.Line != "REFUSED no-connection" || out.Exit != ExitNoConnection ||
		!strings.Contains(out.Detail, "something git never says") || !strings.Contains(out.Detail, "exit status 128") {
		t.Fatalf("outcome = %+v; the Detail must carry git's own words", out)
	}
	if !mac.Repo.hasMarker() {
		t.Fatalf("marker must stay")
	}
	if n := mustGit(t, w.Mac, "rev-list", "--count", mac.Repo.remoteRef()+"..HEAD"); n != "1" {
		t.Fatalf("the local commit must stay, ahead by %s", n)
	}
	mac.Hooks = Hooks{}
	if err := os.WriteFile(settings, original, 0644); err != nil {
		t.Fatal(err)
	}
	if _, out := mac.Save(commitOp(mac, note1, sha, 5)); out.Line != "SAVED" {
		t.Fatalf("the next command must settle it and save: %+v", out)
	}
	if mac.Repo.hasMarker() {
		t.Fatalf("marker should be settled")
	}
	cleanExceptIgnored(t, w.Mac)
	if hub := mustGit(t, w.Hub, "rev-list", "--count", "refs/heads/main"); hub != "2" {
		t.Fatalf("hub should hold the seed and one save, has %s", hub)
	}
}

// G1: the shared copy keeps moving for every try.
func TestSave_FiveLostRacesEndAsBusyAndLeaveNothingBehind(t *testing.T) {
	w := newWorld(t)
	mac, srv := newSyncer(t, w.Mac), newSyncer(t, w.Srv)
	drop := filepath.Join(w.Mac, "_inbox", "human", "g1.md")
	writeFile(t, drop, []byte("---\ntitle: Gee one\n---\nOriginal g1\n"))
	if state, out := mac.sendDrops([]string{"_inbox/human/g1.md"}, 1); state != pushOK { // the race must hit the ingest, not the drop
		t.Fatalf("sending the drop first: %+v", out)
	}
	mac.Hooks.BeforePush = func(attempt int) {
		if _, out := srv.Save(commitOp(srv, note2, readSHA(t, w.Srv, note2), attempt)); out.Exit != 0 {
			t.Errorf("srv save: %+v", out)
		}
	}
	_, out := mac.Save(IngestOp(mac.Engine, drop, "agent-olivier"))
	if out.Line != "REFUSED busy" || out.Exit != ExitBusy {
		t.Fatalf("outcome = %+v", out)
	}
	if mac.Repo.hasMarker() {
		t.Errorf("marker left behind")
	}
	if n := mustGit(t, w.Mac, "rev-list", "--count", mac.Repo.remoteRef()+"..HEAD"); n != "0" {
		t.Errorf("local commit left behind: ahead by %s", n)
	}
	if ideas, _ := filepath.Glob(filepath.Join(w.Mac, "01_Ideas", "IDEA-*--gee-one.md")); len(ideas) != 0 {
		t.Errorf("the note must be undone: %v", ideas)
	}
	if text, err := os.ReadFile(drop); err != nil || !strings.Contains(string(text), "Original g1") {
		t.Errorf("the inbox original must survive: %v", err)
	}
	cleanExceptIgnored(t, w.Mac)
}

// P1: an older ingest of the same path must not make a later, unsettled one look "already saved".
func TestSave_RetryOfAnUnsettledIngestIsNotMistakenForAnOlderIngestOfTheSamePath(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	const rel = "_inbox/human/untitled.md"
	drop := filepath.Join(w.Mac, filepath.FromSlash(rel))
	writeFile(t, drop, []byte("---\ntitle: Older one\n---\nFirst\n"))
	if _, out := mac.Save(IngestOp(mac.Engine, drop, "agent-olivier")); out.Line != "SAVED" {
		t.Fatalf("older ingest: %+v", out)
	}
	// A new file with the same name; its drop reaches the hub, its ingest does not.
	writeFile(t, drop, []byte("---\ntitle: Newer one\n---\nSecond\n"))
	if state, out := mac.sendDrops([]string{rel}, 1); state != pushOK {
		t.Fatalf("sending the new drop: %+v", out)
	}
	settings := filepath.Join(w.Hub, "hooks", "vault-limits.json")
	original, _ := os.ReadFile(settings)
	tight := strings.Replace(string(original), `"daily_bytes_per_place": 52428800`, `"daily_bytes_per_place": 1`, 1)
	if tight == string(original) {
		t.Fatalf("could not tighten the allowance")
	}
	if err := os.WriteFile(settings, []byte(tight), 0644); err != nil {
		t.Fatal(err)
	}
	mac.Hooks.PushResult = func(_ int, res gitResult) gitResult {
		return gitResult{Stderr: "unreadable answer", Err: errors.New("exit status 128")}
	}
	if _, out := mac.Save(IngestOp(mac.Engine, drop, "agent-olivier")); out.Line != "REFUSED no-connection" {
		t.Fatalf("unsettled ingest: %+v", out)
	}
	mac.Hooks = Hooks{}
	if err := os.WriteFile(settings, original, 0644); err != nil {
		t.Fatal(err)
	}
	msg, out := mac.Save(IngestOp(mac.Engine, drop, "agent-olivier"))
	if out.Line != "SAVED" || out.Exit != 0 || strings.Contains(msg, "Already saved") {
		t.Fatalf("retry = %+v (%q): the new drop must really be ingested", out, msg)
	}
	if n := mustGit(t, w.Hub, "log", "--format=%s", "--grep=vault: ingest", "refs/heads/main"); strings.Count(n, "\n") != 1 {
		t.Errorf("hub should hold two ingest commits:\n%s", n)
	}
	if m, _ := filepath.Glob(filepath.Join(w.Mac, "01_Ideas", "IDEA-*--newer-one.md")); len(m) != 1 {
		t.Errorf("the second note is missing: %v", m)
	}
	cleanExceptIgnored(t, w.Mac)
}

// P3 (coverage of existing behaviour): an inbox file that git cannot see is refused, not lost.
func TestSave_IngestOfAnInboxFileGitCannotSeeIsRefusedAndStays(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	exclude := filepath.Join(w.Mac, ".git", "info", "exclude")
	old, _ := os.ReadFile(exclude)
	if err := os.WriteFile(exclude, append(old, []byte("\n_inbox/human/hidden.md\n")...), 0644); err != nil {
		t.Fatal(err)
	}
	drop := filepath.Join(w.Mac, "_inbox", "human", "hidden.md")
	writeFile(t, drop, []byte("---\ntitle: Hidden\n---\nBody\n"))
	_, out := mac.Save(IngestOp(mac.Engine, drop, "agent-olivier"))
	if out.Line != "REFUSED engine-error" || out.Exit != ExitEngineError || !strings.Contains(out.Detail, "inbox") {
		t.Fatalf("outcome = %+v", out)
	}
	if _, err := os.Stat(drop); err != nil || mac.Repo.hasMarker() {
		t.Fatalf("the file must stay and no marker may remain: %v", err)
	}
}

// P3 (coverage of existing behaviour): ingest through a link to a real inbox drop.
func TestSave_IngestThroughALinkToARealInboxDropRemovesTheLinkOnly(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	real := filepath.Join(w.Mac, "_inbox", "human", "linked.md")
	writeFile(t, real, []byte("---\ntitle: Linked one\n---\nBody\n"))
	link := filepath.Join(t.TempDir(), "via.md")
	if err := os.Symlink(real, link); err != nil {
		t.Fatal(err)
	}
	if _, out := mac.Save(IngestOp(mac.Engine, link, "agent-olivier")); out.Line != "SAVED" || out.Exit != 0 {
		t.Fatalf("outcome = %+v", out)
	}
	if _, err := os.Lstat(link); !os.IsNotExist(err) {
		t.Errorf("the link is what the engine removes")
	}
	if _, err := os.Stat(real); err != nil {
		t.Errorf("the real drop must stay: %v", err)
	}
	if m, _ := filepath.Glob(filepath.Join(w.Mac, "01_Ideas", "IDEA-*--linked-one.md")); len(m) != 1 {
		t.Errorf("expected one note, got %v", m)
	}
	cleanExceptIgnored(t, w.Mac)
}

// I3: a failing log is not "not saved yet".
func TestAlreadySaved_AGitFailureIsAnErrorNotAnAnswer(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	if _, err := mac.alreadySaved("some-key"); err != nil {
		t.Fatalf("a healthy folder must answer: %v", err)
	}
	mac.Repo.Remote = "no-such-remote"
	if done, err := mac.alreadySaved("some-key"); err == nil || done {
		t.Fatalf("a git failure must be an error, got (%v, %v)", done, err)
	}
}

// Without a sync config main.go calls op.Run() directly: it must work for any
// source and behave as IngestFile always has.
func TestIngestOp_RunWorksOnAnOutsideSourceWithoutASyncer(t *testing.T) {
	w := newWorld(t)
	e := vault.NewVaultEngine(w.Mac)
	src := filepath.Join(t.TempDir(), "plain.md")
	writeFile(t, src, []byte("---\ntitle: Plain outside\n---\nBody\n"))
	op := IngestOp(e, src, "agent-olivier")
	if op.Run == nil {
		t.Fatal("Run must always be set")
	}
	msg, err := op.Run()
	if err != nil || !strings.HasPrefix(msg, "Ingested note as IDEA-") {
		t.Fatalf("Run = (%q, %v)", msg, err)
	}
	if _, err := os.Stat(src); !os.IsNotExist(err) {
		t.Errorf("ingest has always removed its source")
	}
	if m, _ := filepath.Glob(filepath.Join(w.Mac, "01_Ideas", "IDEA-*--plain-outside.md")); len(m) != 1 {
		t.Errorf("expected the note, got %v", m)
	}
}

func TestIngestOp_RunGivesTheCallersOwnPathToTheEngine(t *testing.T) {
	w := newWorld(t)
	e := vault.NewVaultEngine(w.Mac)
	dir := t.TempDir()
	target := filepath.Join(dir, "target.md")
	writeFile(t, target, []byte("---\ntitle: Via link\n---\nBody\n"))
	link := filepath.Join(dir, "link.md")
	if err := os.Symlink(target, link); err != nil {
		t.Fatal(err)
	}
	if _, err := IngestOp(e, link, "a").Run(); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if _, err := os.Lstat(link); !os.IsNotExist(err) {
		t.Errorf("the path the caller gave is the one removed")
	}
	if _, err := os.Stat(target); err != nil {
		t.Errorf("the link's target is not what the engine removes: %v", err)
	}
}

func TestIngestOp_RunOnAMissingSourceGivesTheEnginesOwnError(t *testing.T) {
	w := newWorld(t)
	e := vault.NewVaultEngine(w.Mac)
	missing := filepath.Join(t.TempDir(), "nope.md")
	_, want := e.IngestFile(missing)
	if want == nil {
		t.Fatal("the engine should fail on a missing file")
	}
	for _, p := range []string{missing, filepath.Join(w.Mac, "_inbox", "human", "nope.md")} {
		_, want := e.IngestFile(p)
		if _, got := IngestOp(e, p, "a").Run(); got == nil || got.Error() != want.Error() {
			t.Errorf("%s: error = %v, want the engine's own: %v", p, got, want)
		}
	}
}

// A drop whose name holds glob characters must be looked up literally: the
// name "n[a].md" must not find the deleting commit of the unrelated "na.md".
func TestIngestKey_DropNameWithGlobCharactersIsLookedUpLiterally(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	plain := filepath.Join(w.Mac, "_inbox", "human", "na.md")
	writeFile(t, plain, []byte("---\ntitle: Plain name\n---\nBody\n"))
	if _, out := mac.Save(IngestOp(mac.Engine, plain, "agent-olivier")); out.Line != "SAVED" {
		t.Fatalf("ingest of na.md: %+v", out)
	}
	rel := "_inbox/human/n[a].md"
	key, err := ingestKey(mac.Repo, filepath.Join(w.Mac, filepath.FromSlash(rel)), rel)
	if err != nil || key != "" {
		t.Fatalf("ingestKey = (%q, %v): a file never seen must give no key, not the key of na.md", key, err)
	}
}

// Both sides together: a hub that cannot read its own settings refuses the
// send, and the place reports it as an engine error (exit 1), never as a size
// or type limit, which would tell an agent "do not retry". Once the hub is
// repaired the very same save goes through.
func TestSave_HubFaultIsAnEngineErrorAndTheSameSaveWorksAfterRepair(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	settings := filepath.Join(w.Hub, "hooks", "vault-limits.json")
	original, err := os.ReadFile(settings)
	if err != nil {
		t.Fatalf("read settings: %v", err)
	}
	if err := os.WriteFile(settings, []byte("{not json"), 0644); err != nil {
		t.Fatalf("break settings: %v", err)
	}
	sha := readSHA(t, w.Mac, note1)
	_, out := mac.Save(commitOp(mac, note1, sha, 5))
	if out.Line != "REFUSED engine-error" || out.Exit != ExitEngineError || !strings.Contains(out.Detail, "hub settings unreadable") {
		t.Fatalf("outcome = %+v, want REFUSED engine-error naming the hub settings", out)
	}
	if mac.Repo.hasMarker() {
		t.Fatalf("marker left behind")
	}
	cleanExceptIgnored(t, w.Mac)
	if hub := mustGit(t, w.Hub, "rev-list", "--count", "refs/heads/main"); hub != "1" {
		t.Fatalf("the hub must not have taken the send, has %s commits", hub)
	}
	if err := os.WriteFile(settings, original, 0644); err != nil {
		t.Fatalf("restore settings: %v", err)
	}
	if _, out := mac.Save(commitOp(mac, note1, sha, 5)); out.Line != "SAVED" {
		t.Fatalf("after the repair = %+v, want SAVED", out)
	}
}

// hubUpdateHook makes the shared copy run body once, while the first send is
// being taken in. Later sends pass.
func hubUpdateHook(t *testing.T, hub, body string) {
	t.Helper()
	once := filepath.Join(hub, "update-hook-ran")
	script := "#!/bin/sh\nif [ ! -e '" + once + "' ]; then\n: > '" + once + "'\nunset GIT_QUARANTINE_PATH\n" + body + "\nfi\nexit 0\n"
	if err := os.MkdirAll(filepath.Join(hub, "hooks"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(hub, "hooks", "update"), []byte(script), 0755); err != nil {
		t.Fatal(err)
	}
}

// Two sends reach the shared copy at the same instant. Git then answers
// "[remote rejected]" instead of "[rejected]". The answers here are git's own.
// The shared copy is put back before the engine looks, so it has not moved.
func TestSave_RemoteRejectedFromALostRaceIsTriedAgain(t *testing.T) {
	for _, c := range []struct {
		name       string
		locked     bool
		stdoutOnly bool
		says       string
	}{
		{"the shared copy moved under the send", false, false, "cannot lock ref"},
		{"the shared copy moved under the send, reason line only", false, true, "incorrect old value provided"},
		{"another send holds the lock", true, false, "cannot lock ref"},
	} {
		t.Run(c.name, func(t *testing.T) {
			w := newWorld(t)
			mac := newSyncer(t, w.Mac)
			base := mustGit(t, w.Hub, "rev-parse", "refs/heads/main")
			lock := filepath.Join(w.Hub, "refs", "heads", "main.lock")
			if c.locked {
				hubUpdateHook(t, w.Hub, ": > '"+lock+"'")
			} else {
				other := mustGit(t, w.Hub, "commit-tree", "-p", base, "-m", "other place", base+"^{tree}")
				hubUpdateHook(t, w.Hub, "git update-ref refs/heads/main "+other)
			}
			pushes, first := 0, ""
			mac.Hooks.PushResult = func(attempt int, res gitResult) gitResult {
				pushes++
				if attempt == 1 {
					_ = os.Remove(lock)
					mustGit(t, w.Hub, "update-ref", "refs/heads/main", base)
					if c.stdoutOnly {
						res.Stderr = ""
					}
					first = res.Stdout + res.Stderr
				}
				return res
			}
			_, out := mac.Save(commitOp(mac, note1, readSHA(t, w.Mac, note1), 5))
			t.Logf("git answered the first send with:\n%s", first)
			if c.stdoutOnly && !strings.Contains(first, c.says) {
				t.Skipf("this git does not word the reason as %q", c.says)
			}
			if !strings.Contains(first, "\t[remote rejected]") || !strings.Contains(first, c.says) {
				t.Fatalf("the first send should be answered [remote rejected] with %q", c.says)
			}
			if out.Line != "SAVED" || out.Exit != 0 || pushes != 2 {
				t.Fatalf("outcome = %+v after %d sends, want SAVED on the second", out, pushes)
			}
			if mac.Repo.hasMarker() {
				t.Errorf("marker left behind")
			}
			cleanExceptIgnored(t, w.Mac)
			if n := mustGit(t, w.Hub, "rev-list", "--count", base+"..refs/heads/main"); n != "1" {
				t.Errorf("hub should hold exactly one save, has %s", n)
			}
		})
	}
}

// A hook on the shared copy that declines is not a lost race: the answer stays
// unclear and the send is not repeated.
func TestSave_RemoteRejectedByAHookIsNotTriedAgain(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	hubUpdateHook(t, w.Hub, "exit 1")
	pushes, first := 0, ""
	mac.Hooks.PushResult = func(attempt int, res gitResult) gitResult {
		pushes++
		if attempt == 1 {
			first = res.Stdout + res.Stderr
		}
		return res
	}
	_, out := mac.Save(commitOp(mac, note1, readSHA(t, w.Mac, note1), 5))
	if !strings.Contains(first, "\t[remote rejected] (hook declined)") {
		t.Fatalf("the send should be answered [remote rejected] (hook declined), got:\n%s", first)
	}
	if out.Line != "REFUSED no-connection" || out.Exit != ExitNoConnection || pushes != 1 {
		t.Fatalf("outcome = %+v after %d sends, want no-connection after one", out, pushes)
	}
	if !mac.Repo.hasMarker() {
		t.Errorf("marker must stay")
	}
	if n := mustGit(t, w.Mac, "rev-list", "--count", mac.Repo.remoteRef()+"..HEAD"); n != "1" {
		t.Errorf("the local commit must stay, ahead by %s", n)
	}
}
