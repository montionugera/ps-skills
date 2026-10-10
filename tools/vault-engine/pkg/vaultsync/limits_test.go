package vaultsync

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCheckFile(t *testing.T) {
	l := DefaultLimits()
	cases := []struct {
		path     string
		size     int64
		wantCode string
		wantText string
	}{
		{"01_Ideas/IDEA-2026-000001--a.md", 1048576, "", ""},
		{"01_Ideas/IDEA-2026-000001--a.md", 1048577, "too-large", "limit max_file_bytes=1048576"},
		{"_meta/ledger/captures.jsonl", 10, "", ""},
		{"04_Knowledge/pic.PNG", 307200, "", ""},
		{"04_Knowledge/pic.png", 307201, "too-large", "limit max_image_bytes=307200"},
		{"01_Ideas/data.zip", 10, "type-not-allowed", "file type that is not accepted"},
		{".gitignore", 10, "", ""},
		{"_inbox/human/.gitkeep", 0, "", ""},
		{"_meta/scripts/test_e2e.sh", 10, "", ""},
		{"01_Ideas/run.sh", 10, "type-not-allowed", "file type that is not accepted"},
		{"_meta/ledger/raw/RUN-1.raw", 10, "", ""},
		{"01_Ideas/x.raw", 10, "type-not-allowed", "file type that is not accepted"},
		{".obsidian/app.json", 10, "type-not-allowed", "denied_prefixes: .obsidian/"},
		{"_meta/bin/sync.json", 10, "type-not-allowed", "denied_prefixes: _meta/bin/"},
		{"_meta/indexes/ideas.jsonl", 10, "type-not-allowed", "denied_prefixes: _meta/indexes/"},
		{"graft/cache.json", 10, "type-not-allowed", "denied_prefixes: graft/"},
		{".Obsidian/app.json", 10, "type-not-allowed", "denied_prefixes: .obsidian/"},
		{"_META/Bin/sync.json", 10, "type-not-allowed", "denied_prefixes: _meta/bin/"},
		{"_Meta/guards/save-in-progress.json", 10, "type-not-allowed", "denied_prefixes: _meta/guards/"},
	}
	for _, c := range cases {
		v := l.CheckFile(c.path, c.size)
		if c.wantCode == "" {
			if v != nil {
				t.Errorf("%s (%d bytes): expected accepted, got %v", c.path, c.size, v)
			}
			continue
		}
		if v == nil || v.Code != c.wantCode || !strings.Contains(v.Message, c.wantText) {
			t.Errorf("%s (%d bytes): expected %s containing %q, got %v", c.path, c.size, c.wantCode, c.wantText, v)
		}
	}
}

func TestDefaultLimitsCarryTheSpecValues(t *testing.T) {
	l := DefaultLimits()
	if l.Ref != "refs/heads/main" || l.MaxInputBytes != 20971520 || l.MaxFileBytes != 1048576 ||
		l.MaxImageBytes != 307200 || l.MaxFilesPerPush != 500 || l.DailyBytesPerPlace != 52428800 {
		t.Fatalf("limit values differ from the spec: %+v", l)
	}
	if len(l.DeniedPrefixes) != 9 || len(l.AllowedExt) != 7 || len(l.ImageExt) != 3 {
		t.Fatalf("limit lists differ from the spec: %+v", l)
	}
}

func TestLoadLimits(t *testing.T) {
	good, err := json.Marshal(DefaultLimits())
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	dir := t.TempDir()
	write := func(body []byte) string {
		f := filepath.Join(dir, "limits.json")
		if err := os.WriteFile(f, body, 0644); err != nil {
			t.Fatalf("write: %v", err)
		}
		return f
	}
	l, err := LoadLimits(write(good))
	if err != nil || l.MaxInputBytes != 20971520 || len(l.DeniedPrefixes) != 9 {
		t.Fatalf("good file should load, got (%+v, %v)", l, err)
	}
	for _, key := range []string{"ref", "max_input_bytes", "max_file_bytes", "max_image_bytes",
		"max_files_per_push", "daily_bytes_per_place", "allowed_ext", "denied_prefixes"} {
		var m map[string]any
		if err := json.Unmarshal(good, &m); err != nil {
			t.Fatalf("unmarshal: %v", err)
		}
		delete(m, key)
		body, _ := json.Marshal(m)
		if _, err := LoadLimits(write(body)); err == nil {
			t.Errorf("file missing %q should be refused", key)
		}
	}
	if _, err := LoadLimits(filepath.Join(dir, "absent.json")); err == nil {
		t.Errorf("absent file should be refused")
	}
}
