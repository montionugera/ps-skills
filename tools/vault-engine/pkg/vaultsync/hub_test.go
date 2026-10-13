package vaultsync

import (
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestHubSettingsFileMatchesDefaultLimits(t *testing.T) {
	l, err := LoadLimits(filepath.Join("..", "..", "hub", "vault-limits.json"))
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if !reflect.DeepEqual(l, DefaultLimits()) {
		t.Fatalf("hub/vault-limits.json and DefaultLimits() differ:\nfile: %+v\ncode: %+v", l, DefaultLimits())
	}
}

func TestHub_AcceptsNotesAndRefusesEachLimit(t *testing.T) {
	many := map[string]int{}
	for i := 0; i < 600; i++ {
		many[fmt.Sprintf("01_Ideas/n%03d.md", i)] = 10
	}
	cases := []struct {
		name  string
		files map[string]int
		want  string // "" = accepted; otherwise text the refusal must contain
	}{
		{"note", map[string]int{"01_Ideas/a.md": 2048}, ""},
		{"image at 300 KB", map[string]int{"04_Knowledge/p.png": 307200}, ""},
		{"script exception", map[string]int{"_meta/scripts/x.sh": 100}, ""},
		{"gitkeep exception", map[string]int{"_inbox/human/.gitkeep": 0}, ""},
		{"5 MB note", map[string]int{"01_Ideas/big.md": 5 << 20}, "vault-hub: REFUSED too-large: 01_Ideas/big.md is 5242880 bytes; limit max_file_bytes=1048576"},
		{"image over 300 KB", map[string]int{"04_Knowledge/p.png": 307201}, "limit max_image_bytes=307200"},
		{"archive", map[string]int{"01_Ideas/a.zip": 10}, "vault-hub: REFUSED type-not-allowed: 01_Ideas/a.zip"},
		{"script elsewhere", map[string]int{"01_Ideas/x.sh": 10}, "vault-hub: REFUSED type-not-allowed"},
		{"obsidian folder", map[string]int{".obsidian/app.json": 10}, "denied_prefixes: .obsidian/"},
		{"engine folder", map[string]int{"_meta/bin/sync.json": 10}, "denied_prefixes: _meta/bin/"},
		{"600 files", many, "limit max_files_per_push=500"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			hub := newHub(t)
			dir := seededClone(t, hub)
			before := mustGit(t, hub, "rev-parse", "refs/heads/main")
			commitFiles(t, dir, c.files)
			out, err := pushAs(t, dir, "mac-test", "HEAD:refs/heads/main")
			if c.want == "" {
				if err != nil {
					t.Fatalf("expected accepted, got: %v\n%s", err, out)
				}
				return
			}
			if err == nil || !strings.Contains(out, c.want) {
				t.Fatalf("expected refusal containing %q, got err=%v\n%s", c.want, err, out)
			}
			if after := mustGit(t, hub, "rev-parse", "refs/heads/main"); after != before {
				t.Fatalf("hub moved although the push was refused")
			}
		})
	}
}

func TestHub_RefusesBigFileAddedThenDeletedInOnePush(t *testing.T) {
	hub := newHub(t)
	dir := seededClone(t, hub)
	sizeBefore := dirSize(t, hub)
	commitFiles(t, dir, map[string]int{"01_Ideas/big.md": 5 << 20})
	mustGit(t, dir, "rm", "--quiet", "01_Ideas/big.md")
	mustGit(t, dir, "commit", "--quiet", "-m", "remove it again")
	out, err := pushAs(t, dir, "mac-test", "HEAD:refs/heads/main")
	if err == nil || !strings.Contains(out, "limit max_file_bytes=1048576") {
		t.Fatalf("expected refusal, got err=%v\n%s", err, out)
	}
	if grown := dirSize(t, hub) - sizeBefore; grown > 64*1024 {
		t.Fatalf("hub grew by %d bytes after a refused push", grown)
	}
}

func TestHub_RefusesRewriteDeleteSideBranchAndTag(t *testing.T) {
	hub := newHub(t)
	dir := seededClone(t, hub)
	commitFiles(t, dir, map[string]int{"01_Ideas/a.md": 10})
	if out, err := pushAs(t, dir, "mac-test", "HEAD:refs/heads/main"); err != nil {
		t.Fatalf("setup push: %v\n%s", err, out)
	}
	tip := mustGit(t, hub, "rev-parse", "refs/heads/main")

	// Deleting main is refused by git itself (receive.denyDeletes) before the
	// hook runs, so only "the push failed" can be asserted. A side branch and a
	// tag reach the hook, which must print its contract line.
	if out, err := pushAs(t, dir, "mac-test", ":refs/heads/main"); err == nil {
		t.Fatalf("deleting main should be refused\n%s", out)
	}
	for _, refspec := range []string{"HEAD:refs/heads/side", "HEAD:refs/tags/v1"} {
		out, err := pushAs(t, dir, "mac-test", refspec)
		if err == nil || !strings.Contains(out, "vault-hub: REFUSED type-not-allowed: ") {
			t.Fatalf("push %s should be refused by the hook, got err=%v\n%s", refspec, err, out)
		}
	}
	// History rewrite: refused by git itself (receive.denyNonFastForwards) before the hook runs.
	// Drop the last commit, add a different one, force it.
	mustGit(t, dir, "reset", "--quiet", "--hard", "HEAD~1")
	commitFiles(t, dir, map[string]int{"01_Ideas/b.md": 10})
	if out, err := pushAs(t, dir, "mac-test", "HEAD:refs/heads/main", "--force"); err == nil {
		t.Fatalf("forced rewrite should be refused\n%s", out)
	}
	if now := mustGit(t, hub, "rev-parse", "refs/heads/main"); now != tip {
		t.Fatalf("hub tip changed from %s to %s", tip, now)
	}
	if refs := mustGit(t, hub, "for-each-ref", "--format=%(refname)"); refs != "refs/heads/main" {
		t.Fatalf("unexpected refs on hub: %s", refs)
	}
}

func TestHub_CutsOffHugeUpload(t *testing.T) {
	if testing.Short() {
		t.Skip("writes 100 MB")
	}
	hub := newHub(t)
	dir := seededClone(t, hub)
	sizeBefore := dirSize(t, hub)
	blob := make([]byte, 100<<20)
	if _, err := rand.Read(blob); err != nil { // random bytes do not compress
		t.Fatalf("rand: %v", err)
	}
	writeFile(t, filepath.Join(dir, "01_Ideas", "huge.md"), blob)
	mustGit(t, dir, "add", "-A")
	mustGit(t, dir, "commit", "--quiet", "-m", "huge")
	out, err := pushAs(t, dir, "mac-test", "HEAD:refs/heads/main")
	if err == nil || !strings.Contains(out, "pack exceeds maximum allowed size") {
		t.Fatalf("expected the upload to be cut off, got err=%v\n%s", err, out)
	}
	if grown := dirSize(t, hub) - sizeBefore; grown > 64*1024 {
		t.Fatalf("hub grew by %d bytes after a cut-off upload", grown)
	}
}

// Data must not be able to hide outside files: a commit message is stored too.
func TestHub_CommitMessagesCountAgainstTheLimits(t *testing.T) {
	hub := newHub(t)
	dir := seededClone(t, hub)
	writeFile(t, filepath.Join(dir, "01_Ideas", "a.md"), []byte("a\n"))
	mustGit(t, dir, "add", "-A")
	mustGit(t, dir, "commit", "--quiet", "-m", strings.Repeat("x", 100000))
	if out, err := pushAs(t, dir, "mac-test", "HEAD:refs/heads/main"); err != nil {
		t.Fatalf("a 100 KB commit message is within the limits: %v\n%s", err, out)
	}
	usage, _ := filepath.Glob(filepath.Join(hub, "vault-usage", "*.json"))
	if len(usage) != 1 {
		t.Fatalf("expected one usage file, found %v", usage)
	}
	var used map[string]int64
	data, _ := os.ReadFile(usage[0])
	if err := json.Unmarshal(data, &used); err != nil || used["mac-test"] < 100000 {
		t.Fatalf("the commit message was not counted against the daily allowance: %s (%v)", data, err)
	}

	big := filepath.Join(t.TempDir(), "message.txt")
	writeFile(t, big, []byte(strings.Repeat("x", 2<<20)))
	writeFile(t, filepath.Join(dir, "01_Ideas", "b.md"), []byte("b\n"))
	mustGit(t, dir, "add", "-A")
	mustGit(t, dir, "commit", "--quiet", "-F", big)
	out, err := pushAs(t, dir, "mac-test", "HEAD:refs/heads/main")
	if err == nil || !strings.Contains(out, "vault-hub: REFUSED too-large: a commit record") || !strings.Contains(out, "limit max_file_bytes=1048576") {
		t.Fatalf("a 2 MB commit message must be refused, got err=%v\n%s", err, out)
	}
}

func TestHub_DailyAllowanceIsPerPlace(t *testing.T) {
	hub := newHub(t)
	l := DefaultLimits()
	l.DailyBytesPerPlace = 4096
	settings := fmt.Sprintf(`{"ref":"refs/heads/main","max_input_bytes":20971520,"max_file_bytes":1048576,"max_image_bytes":307200,
"max_files_per_push":500,"daily_bytes_per_place":%d,"allowed_ext":[".md"],"image_ext":[".png"],"allowed_names":[".gitignore"],
"ext_under_prefix":{},"denied_prefixes":[".obsidian/"]}`, l.DailyBytesPerPlace)
	if err := os.WriteFile(filepath.Join(hub, "hooks", "vault-limits.json"), []byte(settings), 0644); err != nil {
		t.Fatalf("write settings: %v", err)
	}
	mac := seededClone(t, hub)
	commitFiles(t, mac, map[string]int{"01_Ideas/a.md": 3000})
	if out, err := pushAs(t, mac, "mac-test", "HEAD:refs/heads/main"); err != nil {
		t.Fatalf("first 3000 bytes should fit: %v\n%s", err, out)
	}
	commitFiles(t, mac, map[string]int{"01_Ideas/b.md": 3001})
	out, err := pushAs(t, mac, "mac-test", "HEAD:refs/heads/main")
	if err == nil || !strings.Contains(out, "limit daily_bytes_per_place=4096") || !strings.Contains(out, "mac-test") {
		t.Fatalf("expected daily allowance refusal for mac-test, got err=%v\n%s", err, out)
	}
	// The other place carries on.
	srv := filepath.Join(t.TempDir(), "srv")
	mustGit(t, filepath.Dir(srv), "clone", "--quiet", hub, srv)
	commitFiles(t, srv, map[string]int{"01_Ideas/c.md": 3002})
	if out, err := pushAs(t, srv, "srv-test", "HEAD:refs/heads/main"); err != nil {
		t.Fatalf("srv-test should still be accepted: %v\n%s", err, out)
	}
	// A push without an identity is refused.
	commitFiles(t, srv, map[string]int{"01_Ideas/d.md": 10})
	if out, err := gitIn(t, srv, []string{"VAULT_HUB_PLACE="}, "push", "--porcelain", "origin", "HEAD:refs/heads/main"); err == nil {
		t.Fatalf("push without VAULT_HUB_PLACE should be refused\n%s", out)
	}
}

type failingReader struct{}

func (failingReader) Read([]byte) (int, error) { return 0, errors.New("read failed") }

func TestPreReceive_RefusesInputItCannotRead(t *testing.T) {
	// Copy the settings into a temp "hooks" folder: the ledger goes to <hooks>/../vault-usage.
	data, err := os.ReadFile(filepath.Join("..", "..", "hub", "vault-limits.json"))
	if err != nil {
		t.Fatalf("read settings: %v", err)
	}
	limits := filepath.Join(t.TempDir(), "hooks", "vault-limits.json")
	writeFile(t, limits, data)
	zero := strings.Repeat("0", 40)
	dir := hubRepo(t)
	cases := map[string]io.Reader{
		"two fields":      strings.NewReader(zero + " " + zero + "\n"),
		"four fields":     strings.NewReader(zero + " " + zero + " refs/heads/main extra\n"),
		"blank line":      strings.NewReader("\n"),
		"read error":      failingReader{},
		"oversized token": strings.NewReader(strings.Repeat("x", 128*1024) + "\n"),
	}
	for name, in := range cases {
		t.Run(name, func(t *testing.T) {
			var stderr strings.Builder
			code := PreReceive(dir, in, &stderr, limits, "mac-test", time.Now())
			// git itself writes these lines; one the hub cannot read is the hub's
			// own fault, not a rule the sender broke.
			if code == 0 || !strings.Contains(stderr.String(), "vault-hub: REFUSED engine-error: ") {
				t.Fatalf("expected an engine-error refusal, got code=%d stderr=%q", code, stderr.String())
			}
		})
	}
}

func TestChargeDaily_RefusesAnUnreadableOrCorruptLedger(t *testing.T) {
	now := time.Date(2026, 10, 10, 12, 0, 0, 0, time.UTC)
	t.Run("ledger path cannot be read", func(t *testing.T) {
		dir := t.TempDir()
		if err := os.Mkdir(filepath.Join(dir, "2026-10-10.json"), 0755); err != nil {
			t.Fatal(err)
		}
		if _, ok, err := chargeDaily(dir, "mac-test", now, 10, 1000); err == nil || ok {
			t.Fatalf("expected an error, got ok=%v err=%v", ok, err)
		}
	})
	t.Run("corrupt ledger is kept", func(t *testing.T) {
		dir := t.TempDir()
		file := filepath.Join(dir, "2026-10-10.json")
		writeFile(t, file, []byte("{not json"))
		if _, ok, err := chargeDaily(dir, "mac-test", now, 10, 1000); err == nil || ok {
			t.Fatalf("expected an error, got ok=%v err=%v", ok, err)
		}
		if data, _ := os.ReadFile(file); string(data) != "{not json" {
			t.Fatalf("corrupt ledger was overwritten: %q", data)
		}
	})
	t.Run("other places survive a charge", func(t *testing.T) {
		dir := t.TempDir()
		file := filepath.Join(dir, "2026-10-10.json")
		writeFile(t, file, []byte(`{"srv-test":500}`))
		if _, ok, err := chargeDaily(dir, "mac-test", now, 10, 1000); err != nil || !ok {
			t.Fatalf("charge: ok=%v err=%v", ok, err)
		}
		data, _ := os.ReadFile(file)
		var got map[string]int64
		if err := json.Unmarshal(data, &got); err != nil || got["srv-test"] != 500 || got["mac-test"] != 10 {
			t.Fatalf("ledger = %s (%v)", data, err)
		}
	})
}

func TestChargeDaily_AFolderSyncFailureAfterTheRenameStillCountsAsCharged(t *testing.T) {
	prev := syncDir
	t.Cleanup(func() { syncDir = prev })
	syncDir = func(string) error { return errors.New("simulated folder sync failure") }

	dir := t.TempDir()
	now := time.Date(2026, 10, 10, 12, 0, 0, 0, time.UTC)
	file := filepath.Join(dir, "2026-10-10.json")

	used1, ok, err := chargeDaily(dir, "mac-test", now, 100, 1000)
	if err != nil || !ok {
		t.Fatalf("first chargeDaily: ok=%v err=%v, want ok=true err=nil", ok, err)
	}
	if used1 != 100 {
		t.Fatalf("first chargeDaily returned used=%d, want 100", used1)
	}

	data, err := os.ReadFile(file)
	if err != nil {
		t.Fatalf("reading usage file: %v", err)
	}
	var usage map[string]int64
	if err := json.Unmarshal(data, &usage); err != nil {
		t.Fatalf("unmarshaling usage file: %v", err)
	}
	if usage["mac-test"] != used1 {
		t.Fatalf("usage file on disk has %d, chargeDaily returned %d", usage["mac-test"], used1)
	}

	used2, ok, err := chargeDaily(dir, "mac-test", now, 50, 1000)
	if err != nil || !ok {
		t.Fatalf("second chargeDaily: ok=%v err=%v, want ok=true err=nil", ok, err)
	}
	if used2 != used1+50 {
		t.Fatalf("expected total to grow by exactly added amount once to %d, got %d", used1+50, used2)
	}

	data, err = os.ReadFile(file)
	if err != nil {
		t.Fatalf("reading usage file after second charge: %v", err)
	}
	if err := json.Unmarshal(data, &usage); err != nil {
		t.Fatalf("unmarshaling usage file after second charge: %v", err)
	}
	if usage["mac-test"] != used2 {
		t.Fatalf("usage file on disk has %d, chargeDaily returned %d", usage["mac-test"], used2)
	}
}

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

// hubLimitsCopy puts the shipped settings into a temp "hooks" folder; the
// usage ledger then goes to <hooks>/../vault-usage, also in the temp folder.
func hubLimitsCopy(t *testing.T) string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("..", "..", "hub", "vault-limits.json"))
	if err != nil {
		t.Fatalf("read settings: %v", err)
	}
	limits := filepath.Join(t.TempDir(), "hooks", "vault-limits.json")
	writeFile(t, limits, data)
	return limits
}

// The hub could not read or compute something: that is its own fault. It still
// refuses the send, but with engine-error, never with a label that tells the
// sender its file is too large or of the wrong type.
func TestPreReceive_OwnFaultsAreEngineErrors(t *testing.T) {
	zero, unknown := strings.Repeat("0", 40), strings.Repeat("1", 40)
	dir := hubRepo(t)
	t.Run("settings unreadable", func(t *testing.T) {
		var stderr strings.Builder
		code := PreReceive(dir, strings.NewReader(""), &stderr, filepath.Join(t.TempDir(), "missing.json"), "mac-test", time.Now())
		if code == 0 || !strings.HasPrefix(stderr.String(), "vault-hub: REFUSED engine-error: hub settings unreadable") {
			t.Fatalf("code=%d stderr=%q", code, stderr.String())
		}
	})
	t.Run("settings corrupt", func(t *testing.T) {
		limits := filepath.Join(t.TempDir(), "hooks", "vault-limits.json")
		writeFile(t, limits, []byte("{not json"))
		var stderr strings.Builder
		code := PreReceive(dir, strings.NewReader(""), &stderr, limits, "mac-test", time.Now())
		if code == 0 || !strings.HasPrefix(stderr.String(), "vault-hub: REFUSED engine-error: hub settings unreadable") {
			t.Fatalf("code=%d stderr=%q", code, stderr.String())
		}
	})
	t.Run("git cannot list the incoming commits", func(t *testing.T) {
		var stderr strings.Builder
		code := PreReceive(dir, strings.NewReader(zero+" "+unknown+" refs/heads/main\n"), &stderr, hubLimitsCopy(t), "mac-test", time.Now())
		if code == 0 || !strings.HasPrefix(stderr.String(), "vault-hub: REFUSED engine-error: cannot list incoming commits") {
			t.Fatalf("code=%d stderr=%q", code, stderr.String())
		}
	})
	t.Run("an object cannot be measured", func(t *testing.T) {
		code, msg := batchCheck(dir, unknown+"\n", "%(objectname) %(objectsize)", "cannot measure incoming files",
			func(string, int64) (string, string) { return "", "" })
		if code != "engine-error" || !strings.Contains(msg, "cannot be measured") {
			t.Fatalf("code=%q msg=%q", code, msg)
		}
	})
	t.Run("a rule the sender broke keeps its label", func(t *testing.T) {
		for name, c := range map[string]struct{ place, line, want string }{
			"no sender name": {"", zero + " " + unknown + " refs/heads/main\n", "vault-hub: REFUSED type-not-allowed: sender identity"},
			"other ref":      {"mac-test", zero + " " + unknown + " refs/heads/side\n", "vault-hub: REFUSED type-not-allowed: refs/heads/side is not accepted"},
			"delete":         {"mac-test", unknown + " " + zero + " refs/heads/main\n", "vault-hub: REFUSED type-not-allowed: deleting"},
		} {
			var stderr strings.Builder
			code := PreReceive(dir, strings.NewReader(c.line), &stderr, hubLimitsCopy(t), c.place, time.Now())
			if code == 0 || !strings.HasPrefix(stderr.String(), c.want) {
				t.Errorf("%s: code=%d stderr=%q", name, code, stderr.String())
			}
		}
	})
}

// A usage ledger the hub cannot write is the hub's fault too: the send is
// refused (fail closed) with engine-error, not with too-large.
func TestHub_UnwritableUsageLedgerIsAnEngineError(t *testing.T) {
	hub := newHub(t)
	writeFile(t, filepath.Join(hub, "vault-usage"), []byte("a file where the ledger folder should be\n"))
	dir := filepath.Join(t.TempDir(), "place")
	writeFile(t, filepath.Join(dir, "README.md"), []byte("seed\n"))
	mustGit(t, dir, "init", "--quiet", "--initial-branch=main")
	mustGit(t, dir, "remote", "add", "origin", hub)
	mustGit(t, dir, "add", "-A")
	mustGit(t, dir, "commit", "--quiet", "-m", "seed")
	out, err := pushAs(t, dir, "mac-test", "HEAD:refs/heads/main")
	if err == nil || !strings.Contains(out, "vault-hub: REFUSED engine-error: daily allowance cannot be recorded") {
		t.Fatalf("expected an engine-error refusal, got err=%v\n%s", err, out)
	}
	if strings.Contains(out, "REFUSED too-large") {
		t.Fatalf("a hub fault must not read as a size limit:\n%s", out)
	}
	if refs := mustGit(t, hub, "for-each-ref"); refs != "" {
		t.Fatalf("the hub must not have taken the send:\n%s", refs)
	}
}

// The forward-only check asks git one yes/no question. Only a clear "no" is a
// history rewrite; a git failure is the hub's own fault. Both are refused.
func TestPreReceive_AncestorCheckThatCannotRunIsAnEngineError(t *testing.T) {
	// Two object names the repository does not have: git cannot answer at all.
	older, newer := strings.Repeat("2", 40), strings.Repeat("1", 40)
	var stderr strings.Builder
	code := PreReceive(hubRepo(t), strings.NewReader(older+" "+newer+" refs/heads/main\n"), &stderr, hubLimitsCopy(t), "mac-test", time.Now())
	if code != 1 || !strings.HasPrefix(stderr.String(), "vault-hub: REFUSED engine-error: cannot check that refs/heads/main only moves forward") {
		t.Fatalf("code=%d stderr=%q", code, stderr.String())
	}
	if strings.Contains(stderr.String(), "rewriting the history") {
		t.Fatalf("a git failure must not read as a history rewrite: %q", stderr.String())
	}
}

// A real rewrite keeps its label. git's own receive.denyNonFastForwards is
// switched off here so that the send reaches the hook's check.
func TestHub_HookItselfRefusesAHistoryRewrite(t *testing.T) {
	hub := newHub(t)
	dir := seededClone(t, hub)
	commitFiles(t, dir, map[string]int{"01_Ideas/a.md": 10})
	if out, err := pushAs(t, dir, "mac-test", "HEAD:refs/heads/main"); err != nil {
		t.Fatalf("setup push: %v\n%s", err, out)
	}
	tip := mustGit(t, hub, "rev-parse", "refs/heads/main")
	mustGit(t, hub, "config", "receive.denyNonFastForwards", "false")
	mustGit(t, dir, "reset", "--quiet", "--hard", "HEAD~1")
	commitFiles(t, dir, map[string]int{"01_Ideas/b.md": 10})
	out, err := pushAs(t, dir, "mac-test", "HEAD:refs/heads/main", "--force")
	if err == nil || !strings.Contains(out, "vault-hub: REFUSED type-not-allowed: rewriting the history of refs/heads/main is never accepted") {
		t.Fatalf("the hook should refuse the rewrite by name, got err=%v\n%s", err, out)
	}
	if now := mustGit(t, hub, "rev-parse", "refs/heads/main"); now != tip {
		t.Fatalf("hub tip changed from %s to %s", tip, now)
	}
}

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
