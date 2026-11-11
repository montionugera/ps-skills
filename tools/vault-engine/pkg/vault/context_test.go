package vault

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"
)

func writeFixture(t *testing.T, root, rel, content string) {
	t.Helper()
	p := filepath.Join(root, rel)
	if err := os.MkdirAll(filepath.Dir(p), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}
}

func knowledgeNote(id, title, tags, projects, updated, body string) string {
	return fmt.Sprintf("---\nid: %s\ntitle: %q\nschema: knowledge/v1\nstatus: active\nkind: concept\ntags: [%s]\nproject_ids: [%s]\nupdated: %q\n---\n\n%s\n",
		id, title, tags, projects, updated, body)
}

func contextVault(t *testing.T) *VaultEngine {
	t.Helper()
	root := setupTestVault(t)
	return NewVaultEngine(root)
}

func TestContext_QueryScoresBestFieldPerTerm(t *testing.T) {
	e := contextVault(t)
	writeFixture(t, e.Root, "04_Knowledge/concepts/a.md",
		knowledgeNote("CONCEPT-a", "codex quota", "", "", "2026-11-01T00:00:00Z", "Placeholder sentence."))
	writeFixture(t, e.Root, "04_Knowledge/concepts/b.md",
		knowledgeNote("CONCEPT-b", "unrelated", "", "", "2026-11-02T00:00:00Z", "codex quota handoff"))
	if err := e.RebuildIndexes(); err != nil {
		t.Fatal(err)
	}
	hits := e.ContextByQuery("codex quota handoff", 5)
	if len(hits) != 1 || hits[0].Entry.ID != "CONCEPT-a" || hits[0].Score != 6 {
		t.Fatalf("want only CONCEPT-a with score 6, got %+v", hits)
	}
	if strings.Join(hits[0].Matched, ",") != "codex,quota" {
		t.Fatalf("matched terms: %v", hits[0].Matched)
	}
}

func TestContext_TagWeightAndTieBreakByUpdated(t *testing.T) {
	e := contextVault(t)
	writeFixture(t, e.Root, "04_Knowledge/concepts/old.md",
		knowledgeNote("CONCEPT-old", "misc", "worktree, quota", "", "2026-10-01T00:00:00Z", "x"))
	writeFixture(t, e.Root, "04_Knowledge/concepts/new.md",
		knowledgeNote("CONCEPT-new", "misc", "worktree, quota", "", "2026-11-01T00:00:00Z", "x"))
	_ = e.RebuildIndexes()
	hits := e.ContextByQuery("worktree quota", 5)
	if len(hits) != 2 || hits[0].Entry.ID != "CONCEPT-new" || hits[0].Score != 4 {
		t.Fatalf("want CONCEPT-new first with score 4, got %+v", hits)
	}
}

func TestContext_NoMatchAndMissingIndexGiveNothing(t *testing.T) {
	e := contextVault(t)
	if hits := e.ContextByQuery("zzzz qqqq", 5); len(hits) != 0 {
		t.Fatalf("missing index must give no hits, got %+v", hits)
	}
	if out := FormatContext(nil, 800); out != "" {
		t.Fatalf("no hits must format to empty string, got %q", out)
	}
}

func TestContext_SummaryIsFirstBodyLineCutTo120Bytes(t *testing.T) {
	e := contextVault(t)
	long := strings.Repeat("x", 300)
	writeFixture(t, e.Root, "04_Knowledge/concepts/s.md",
		knowledgeNote("CONCEPT-s", "summary probe", "", "", "2026-11-01T00:00:00Z", "# Heading\n\n"+long+"\nsecond line"))
	_ = e.RebuildIndexes()
	hits := e.ContextByQuery("summary probe", 5)
	if len(hits) != 1 || len(hits[0].Entry.Summary) != 120 {
		t.Fatalf("want a 120-byte summary, got %+v", hits)
	}
}

func TestContext_FormatRespectsByteCap(t *testing.T) {
	var hits []ContextHit
	for i := 0; i < 20; i++ {
		hits = append(hits, ContextHit{
			Entry:   IndexEntry{ID: fmt.Sprintf("CONCEPT-%02d", i), Title: "title", Path: "04_Knowledge/concepts/x.md", Summary: strings.Repeat("s", 120)},
			Matched: []string{"alpha", "beta"},
		})
	}
	out := FormatContext(hits, 800)
	if len(out) == 0 || len(out) > 800 {
		t.Fatalf("want 1..800 bytes, got %d", len(out))
	}
	if !strings.HasPrefix(out, "<vault-context>\n- CONCEPT-00 | title | 04_Knowledge/concepts/x.md | matched: alpha, beta | ") ||
		!strings.HasSuffix(out, "</vault-context>\n") {
		t.Fatalf("unexpected format:\n%s", out)
	}
}

func TestContext_FormatSanitizesNewlines(t *testing.T) {
	hits := []ContextHit{
		{
			Entry: IndexEntry{
				ID:      "REAL-1",
				Title:   "Real Title\n- FAKE-ID | x",
				Path:    "04_Knowledge/concepts/real.md\r\nsub",
				Summary: "Real summary\nline2",
			},
			Matched: []string{"repo"},
		},
	}
	out := FormatContext(hits, 800)
	count := 0
	for _, line := range strings.Split(out, "\n") {
		if strings.HasPrefix(line, "- ") {
			count++
		}
	}
	if count != 1 {
		t.Fatalf("expected exactly 1 line starting with '- ', got %d in:\n%s", count, out)
	}
}

func gitRun(t *testing.T, dir string, args ...string) {
	t.Helper()
	cmd := exec.Command("git", append([]string{"-C", dir, "-c", "user.email=t@example.com", "-c", "user.name=t"}, args...)...)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
}

func TestContext_CwdResolvesWorktreeToProjectAndRepoTag(t *testing.T) {
	e := contextVault(t)
	repo := filepath.Join(t.TempDir(), "demo-repo")
	if err := os.MkdirAll(repo, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, repo, "init", "-q")
	gitRun(t, repo, "commit", "-q", "--allow-empty", "-m", "init")
	wt := filepath.Join(repo, ".claude", "worktrees", "F-001-x")
	gitRun(t, repo, "worktree", "add", "-q", wt)
	realRepo, _ := filepath.EvalSymlinks(repo)

	writeFixture(t, e.Root, "02_Projects/PROJ-demo/Project Hub.md",
		fmt.Sprintf("---\nid: PROJ-demo\ntitle: Demo\nstatus: active\nrelease_repo: %s\nupdated: \"2026-11-01T00:00:00Z\"\n---\n\nhub\n", realRepo))
	writeFixture(t, e.Root, "04_Knowledge/concepts/p.md",
		knowledgeNote("CONCEPT-p", "by project", "", "PROJ-demo", "2026-11-01T00:00:00Z", "x"))
	writeFixture(t, e.Root, "04_Knowledge/concepts/r.md",
		knowledgeNote("CONCEPT-r", "by repo tag", "\"repo:demo-repo\"", "", "2026-11-02T00:00:00Z", "x"))
	writeFixture(t, e.Root, "04_Knowledge/concepts/other.md",
		knowledgeNote("CONCEPT-other", "elsewhere", "", "PROJ-else", "2026-11-03T00:00:00Z", "x"))
	_ = e.RebuildIndexes()

	hits := e.ContextByCwd(wt)
	var ids []string
	for _, h := range hits {
		ids = append(ids, h.Entry.ID)
	}
	if strings.Join(ids, ",") != "CONCEPT-r,CONCEPT-p" {
		t.Fatalf("want CONCEPT-r,CONCEPT-p (newest first), got %v", ids)
	}
	if out := FormatContext(hits, 800); !strings.Contains(out, "| matched: repo |") {
		t.Fatalf("cwd mode must print matched: repo, got:\n%s", out)
	}
	if hits := e.ContextByCwd(t.TempDir()); len(hits) != 0 {
		t.Fatalf("unrelated dir must give no hits, got %+v", hits)
	}
}

func TestContext_NeedsTitleOrTagMatchAndActiveStatus(t *testing.T) {
	e := contextVault(t)
	writeFixture(t, e.Root, "04_Knowledge/concepts/body.md",
		knowledgeNote("CONCEPT-body", "unrelated", "", "", "2026-11-01T00:00:00Z", "update readme file tests"))
	draft := strings.Replace(
		knowledgeNote("CONCEPT-draft", "update readme", "", "", "2026-11-01T00:00:00Z", "file tests"),
		"status: active", "status: draft", 1)
	writeFixture(t, e.Root, "04_Knowledge/concepts/draft.md", draft)
	_ = e.RebuildIndexes()
	if hits := e.ContextByQuery("update readme file tests", 5); len(hits) != 0 {
		t.Fatalf("body-only and non-active notes must not be returned, got %+v", hits)
	}
}

func writeBigIndex(tb testing.TB, e *VaultEngine) {
	tb.Helper()
	var lines []string
	for i := 0; i < 2000; i++ {
		var terms []string
		for j := 0; j < 80; j++ {
			terms = append(terms, fmt.Sprintf("term%04dx%02d", i, j))
		}
		lines = append(lines, fmt.Sprintf(`{"id":"CONCEPT-%04d","path":"04_Knowledge/concepts/n%04d.md","title":"note number %04d","status":"active","area_ids":null,"updated":"2026-11-01T00:00:00Z","sha256":"x","terms":["%s"]}`,
			i, i, i, strings.Join(terms, `","`)))
	}
	p := filepath.Join(e.Root, "_meta", "indexes", "knowledge.jsonl")
	if err := os.MkdirAll(filepath.Dir(p), 0755); err != nil {
		tb.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(strings.Join(lines, "\n")+"\n"), 0644); err != nil {
		tb.Fatal(err)
	}
}

func TestContext_QueryStaysFastAt2000Notes(t *testing.T) {
	e := contextVault(t)
	writeBigIndex(t, e)
	var runs []time.Duration
	for i := 0; i < 20; i++ {
		start := time.Now()
		e.ContextByQuery("note number 0042 term0042x07", 5)
		runs = append(runs, time.Since(start))
	}
	sort.Slice(runs, func(a, b int) bool { return runs[a] < runs[b] })
	// The budget is 50 ms (see BenchmarkContextByQuery); 200 ms here keeps a slow CI runner from flaking.
	if p95 := runs[18]; p95 > 200*time.Millisecond {
		t.Fatalf("p95 %v exceeds 200ms", p95)
	}
}

func BenchmarkContextByQuery(b *testing.B) {
	e := NewVaultEngine(b.TempDir())
	writeBigIndex(b, e)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		e.ContextByQuery("note number 0042 term0042x07", 5)
	}
}
