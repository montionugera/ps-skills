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
			code := PreReceive(in, &stderr, limits, "mac-test", time.Now())
			if code == 0 || !strings.Contains(stderr.String(), "vault-hub: REFUSED type-not-allowed: ") {
				t.Fatalf("expected refusal, got code=%d stderr=%q", code, stderr.String())
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
