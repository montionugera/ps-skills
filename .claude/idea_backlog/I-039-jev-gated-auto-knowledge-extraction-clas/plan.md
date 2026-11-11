# I-039 Slice 1: Automatic Knowledge Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Claude Code session gets the relevant agentic-vault notes injected automatically, at session start and per prompt, with no LLM calls and hard byte limits.

**Architecture:** `vault-engine` gains a `context` command that scores notes from one index file (`_meta/indexes/knowledge.jsonl`, extended with tags, project ids, summary and body terms). A UserPromptSubmit hook, `vault-recall.py`, calls it per prompt, keeps per-session state so a note is injected once, and enforces the byte budget. The existing SessionStart hook (`agent-harness/scripts/vault-bootstrap.py`) already calls `vault-engine context --cwd` and starts working once the command exists.

**Tech Stack:** Go 1.22 (`tools/vault-engine`, `gopkg.in/yaml.v3`), Python 3.11+ stdlib (`skills/agentic-vault/hooks/`, `bin/ps-skills-doctor`), `unittest`, bash.

**Spec:** `.claude/idea_backlog/I-039-jev-gated-auto-knowledge-extraction-clas/spec.md` (requirements R0–R5, R14; the retrieval rows of the token budget table).

**Scope of this plan:** slice 1 only. Slices 2 (save in shadow mode) and 3 (auto integrate and publish, result loop) get their own plans after slice 1 is live, because their inputs do not exist yet (labelled calibration sets, the extractor call shape). Facts already verified for those plans: `ArchiveRecord` exists at `tools/vault-engine/pkg/vault/vault.go:673`; `bin/dispatch-agy-worker:1485` sets `CLAUDE_VAULT_SUMMARY=0` for workers. Still open: whether the extractor can be a single model call.

## Global Constraints

- SessionStart `<vault-context>` block: at most 800 bytes.
- Per-prompt injection: at most 3 notes and 1,200 bytes, and nothing below score 4.
- Per-session total including the SessionStart block: at most 6 distinct notes and 2,400 bytes; a note is injected once per session.
- Injected form per note: id, title, path, matched terms, summary of at most 120 bytes. Never more of the body.
- Scoring: for each distinct query term (lower-case, 4 or more characters, stop words removed), add the highest weight among the fields containing it: title 3, any tag 2, body terms 1. Threshold 4. Ties broken by newest `updated`.
- Fail open everywhere: a missing engine, vault, index or state file produces no output and exit 0. The hook's hard timeout on the engine is 2 seconds.
- Speed: `ContextByQuery` over a 2,000-note index completes in at most 50 ms at p95.
- The hook does nothing when the prompt is shorter than 12 characters, starts with `/`, or any of `VAULT_RECALL=0`, `VAULT_CONTEXT_BOOTSTRAP=0`, `CLAUDE_VAULT_SUMMARY=0` is set.
- The repo is public: no real vault note ids, titles or prompts in committed fixtures. The 20-prompt recall set lives at `~/.claude/state/vault-recall/recall_set.jsonl`, outside the repo. (The spec named `tests/fixtures/vault_recall_set.jsonl`; this plan moves it for that reason.)
- Before Task 1: run `psrw sync-main`, then `psrw refine I-039` and `psrw claim F-NNN`. All edits happen in the claimed feature worktree, never in the main checkout.
- Commits: new commits only, never `--amend`.

Batch: 2,3

---

### Task 1: `vault-engine context` command and index fields

**Files:**
- Create: `tools/vault-engine/pkg/vault/context.go`
- Create: `tools/vault-engine/pkg/vault/context_test.go`
- Create: `tools/vault-engine/cmd/vault-engine/context_cmd.go`
- Create: `tools/vault-engine/recall_eval.sh`
- Modify: `tools/vault-engine/pkg/vault/vault.go` (`IndexEntry` at line 78; projects loop and knowledge walk inside `RebuildIndexes`, line 389)
- Modify: `tools/vault-engine/cmd/vault-engine/main.go` (after `engine := vault.NewVaultEngine(vaultRoot)`; `printUsage` at line 467)
- Modify: `tools/vault-engine/README.md`

**Interfaces:**
- Consumes: `VaultEngine.ParseMarkdown`, `VaultEngine.RebuildIndexes`, `IndexEntry` (existing).
- Produces:
  - `IndexEntry` fields `Tags []string`, `ProjectIDs []string`, `Summary string`, `Terms []string`, `ReleaseRepo string` (all `omitempty`).
  - `func Terms(s string) []string`, `func SummaryLine(body string) string`, `func RepoRoot(dir string) string`.
  - `type ContextHit struct { Entry IndexEntry; Score int; Matched []string }`.
  - `func (v *VaultEngine) ContextByQuery(query string, limit int) []ContextHit`
  - `func (v *VaultEngine) ContextByCwd(dir string) []ContextHit`
  - `func FormatContext(hits []ContextHit, maxBytes int) string`
  - CLI: `vault-engine context [--cwd <dir>] [--query <text>] [--limit N] [--max-bytes B]`. Output format, one line per note between the tags, which Task 2 parses:

    ```
    <vault-context>
    - <id> | <title> | <path> | matched: <t1>, <t2> | <summary>
    </vault-context>
    ```

    In `--cwd` mode the `matched:` field is `matched: repo`. Empty result prints nothing. Exit code is always 0.

- [ ] **Step 1: Write the failing tests**

```go test:tools/vault-engine/pkg/vault/context_test.go
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
	if hits := e.ContextByCwd(t.TempDir()); len(hits) != 0 {
		t.Fatalf("unrelated dir must give no hits, got %+v", hits)
	}
}

func TestContext_QueryP95Under50msAt2000Notes(t *testing.T) {
	e := contextVault(t)
	var lines []string
	for i := 0; i < 2000; i++ {
		var terms []string
		for j := 0; j < 80; j++ {
			terms = append(terms, fmt.Sprintf("term%04dx%02d", i, j))
		}
		lines = append(lines, fmt.Sprintf(`{"id":"CONCEPT-%04d","path":"04_Knowledge/concepts/n%04d.md","title":"note number %04d","status":"active","area_ids":null,"updated":"2026-11-01T00:00:00Z","sha256":"x","terms":["%s"]}`,
			i, i, i, strings.Join(terms, `","`)))
	}
	writeFixture(t, e.Root, "_meta/indexes/knowledge.jsonl", strings.Join(lines, "\n")+"\n")
	var runs []time.Duration
	for i := 0; i < 20; i++ {
		start := time.Now()
		e.ContextByQuery("note number 0042 term0042x07", 5)
		runs = append(runs, time.Since(start))
	}
	sort.Slice(runs, func(a, b int) bool { return runs[a] < runs[b] })
	if p95 := runs[18]; p95 > 50*time.Millisecond {
		t.Fatalf("p95 %v exceeds 50ms", p95)
	}
}
```

Verify-Cmd: cd tools/vault-engine && go test ./pkg/vault/ -run TestContext -count=1

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd tools/vault-engine && go test ./pkg/vault/ -run TestContext -count=1`
Expected: build failure, `undefined: ContextHit`, `undefined: FormatContext`, `e.ContextByQuery undefined`.

- [ ] **Step 3: Extend `IndexEntry` and `RebuildIndexes`**

In `tools/vault-engine/pkg/vault/vault.go`, add five fields to `IndexEntry` after `SHA256`:

```go
	SHA256  string   `json:"sha256"`
	// Retrieval fields, filled for knowledge notes (ReleaseRepo for projects).
	Tags        []string `json:"tags,omitempty"`
	ProjectIDs  []string `json:"project_ids,omitempty"`
	Summary     string   `json:"summary,omitempty"`
	Terms       []string `json:"terms,omitempty"`
	ReleaseRepo string   `json:"release_repo,omitempty"`
```

In the projects loop of `RebuildIndexes` (the `projList = append(projList, IndexEntry{` literal), add one field:

```go
			ReleaseRepo: stringOrEmpty(fm["release_repo"]),
```

In the knowledge walk of `RebuildIndexes`, change `fm, _, err := v.ParseMarkdown(string(data))` to `fm, body, err := v.ParseMarkdown(string(data))` and add four fields to the `knowList = append(knowList, IndexEntry{` literal:

```go
			Tags:       stringList(fm["tags"]),
			ProjectIDs: stringList(fm["project_ids"]),
			Summary:    SummaryLine(body),
			Terms:      capTerms(Terms(body), 200),
```

- [ ] **Step 4: Write `context.go`**

```go
package vault

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"
)

// ContextHit is one note selected for injection into an agent session.
type ContextHit struct {
	Entry   IndexEntry
	Score   int
	Matched []string
}

const contextThreshold = 4

var termSplit = regexp.MustCompile(`[^a-z0-9]+`)

var stopWords = map[string]bool{
	"about": true, "after": true, "again": true, "also": true, "because": true, "been": true,
	"before": true, "being": true, "check": true, "could": true, "does": true, "doing": true,
	"done": true, "each": true, "from": true, "have": true, "here": true, "into": true,
	"just": true, "like": true, "make": true, "more": true, "most": true, "much": true,
	"need": true, "only": true, "other": true, "over": true, "please": true, "same": true,
	"should": true, "some": true, "such": true, "than": true, "that": true, "their": true,
	"them": true, "then": true, "there": true, "these": true, "they": true, "this": true,
	"those": true, "used": true, "using": true, "very": true, "want": true, "were": true,
	"what": true, "when": true, "where": true, "which": true, "while": true, "will": true,
	"with": true, "would": true, "your": true,
}

// Terms returns the distinct lower-case terms of 4+ characters in s, stop words removed, in first-seen order.
// shortcut: ASCII terms only, so a Thai prompt matches nothing; upgrade when notes are written in Thai.
func Terms(s string) []string {
	seen := map[string]bool{}
	var out []string
	for _, t := range termSplit.Split(strings.ToLower(s), -1) {
		if len(t) < 4 || stopWords[t] || seen[t] {
			continue
		}
		seen[t] = true
		out = append(out, t)
	}
	return out
}

// SummaryLine is the first non-heading, non-empty body line, cut to 120 bytes on a rune boundary.
func SummaryLine(body string) string {
	for _, line := range strings.Split(body, "\n") {
		l := strings.TrimSpace(line)
		if l == "" || strings.HasPrefix(l, "#") {
			continue
		}
		if len(l) > 120 {
			l = l[:120]
			for !utf8.ValidString(l) {
				l = l[:len(l)-1]
			}
		}
		return l
	}
	return ""
}

func capTerms(terms []string, max int) []string {
	if len(terms) > max {
		return terms[:max]
	}
	return terms
}

func stringList(v interface{}) []string {
	raw, ok := v.([]interface{})
	if !ok {
		return nil
	}
	var out []string
	for _, item := range raw {
		if s, ok := item.(string); ok && s != "" {
			out = append(out, s)
		}
	}
	return out
}

func stringOrEmpty(v interface{}) string {
	s, _ := v.(string)
	return s
}

func realPath(p string) string {
	if r, err := filepath.EvalSymlinks(p); err == nil {
		return r
	}
	return filepath.Clean(p)
}

// RepoRoot resolves dir to the main checkout of its git repository, so every worktree maps to one repo.
func RepoRoot(dir string) string {
	out, err := exec.Command("git", "-C", dir, "rev-parse", "--path-format=absolute", "--git-common-dir").Output()
	if err != nil {
		return realPath(dir)
	}
	return realPath(filepath.Dir(strings.TrimSpace(string(out))))
}

func (v *VaultEngine) loadIndex(name string) []IndexEntry {
	f, err := os.Open(filepath.Join(v.Root, "_meta", "indexes", name))
	if err != nil {
		return nil
	}
	defer f.Close()
	var entries []IndexEntry
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	for sc.Scan() {
		var e IndexEntry
		if json.Unmarshal(sc.Bytes(), &e) == nil && e.ID != "" {
			entries = append(entries, e)
		}
	}
	return entries
}

func toSet(terms []string) map[string]bool {
	set := make(map[string]bool, len(terms))
	for _, t := range terms {
		set[t] = true
	}
	return set
}

// ContextByQuery scores every knowledge note against the query and returns up to limit notes at or above the threshold.
func (v *VaultEngine) ContextByQuery(query string, limit int) []ContextHit {
	qTerms := Terms(query)
	if len(qTerms) == 0 {
		return nil
	}
	var hits []ContextHit
	for _, e := range v.loadIndex("knowledge.jsonl") {
		title, tags, body := toSet(Terms(e.Title)), toSet(Terms(strings.Join(e.Tags, " "))), toSet(e.Terms)
		hit := ContextHit{Entry: e}
		for _, q := range qTerms {
			w := 0
			switch {
			case title[q]:
				w = 3
			case tags[q]:
				w = 2
			case body[q]:
				w = 1
			}
			if w > 0 {
				hit.Score += w
				hit.Matched = append(hit.Matched, q)
			}
		}
		if hit.Score >= contextThreshold {
			hits = append(hits, hit)
		}
	}
	sort.SliceStable(hits, func(i, j int) bool {
		if hits[i].Score != hits[j].Score {
			return hits[i].Score > hits[j].Score
		}
		if hits[i].Entry.Updated != hits[j].Entry.Updated {
			return hits[i].Entry.Updated > hits[j].Entry.Updated
		}
		return hits[i].Entry.ID < hits[j].Entry.ID
	})
	if limit > 0 && len(hits) > limit {
		hits = hits[:limit]
	}
	return hits
}

// ContextByCwd returns notes tied to the repository that owns dir: through a project whose
// release_repo is that repo, or through a "repo:<basename>" tag. Newest first.
func (v *VaultEngine) ContextByCwd(dir string) []ContextHit {
	root := RepoRoot(dir)
	projects := map[string]bool{}
	for _, p := range v.loadIndex("projects.jsonl") {
		if p.ReleaseRepo != "" && realPath(p.ReleaseRepo) == root {
			projects[p.ID] = true
		}
	}
	repoTag := "repo:" + filepath.Base(root)
	var hits []ContextHit
	for _, e := range v.loadIndex("knowledge.jsonl") {
		match := false
		for _, id := range e.ProjectIDs {
			match = match || projects[id]
		}
		for _, tag := range e.Tags {
			match = match || tag == repoTag
		}
		if match {
			hits = append(hits, ContextHit{Entry: e, Matched: []string{"repo"}})
		}
	}
	sort.SliceStable(hits, func(i, j int) bool { return hits[i].Entry.Updated > hits[j].Entry.Updated })
	return hits
}

// FormatContext renders hits as a <vault-context> block of at most maxBytes, dropping hits that do not fit.
func FormatContext(hits []ContextHit, maxBytes int) string {
	const open, closeTag = "<vault-context>\n", "</vault-context>\n"
	var b strings.Builder
	b.WriteString(open)
	lines := 0
	for _, h := range hits {
		line := fmt.Sprintf("- %s | %s | %s | matched: %s | %s\n",
			h.Entry.ID, h.Entry.Title, h.Entry.Path, strings.Join(h.Matched, ", "), h.Entry.Summary)
		if b.Len()+len(line)+len(closeTag) > maxBytes {
			break
		}
		b.WriteString(line)
		lines++
	}
	if lines == 0 {
		return ""
	}
	b.WriteString(closeTag)
	return b.String()
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd tools/vault-engine && go test ./pkg/vault/ -count=1`
Expected: `ok  obsidian-vault-engine/pkg/vault` (all existing tests plus the seven `TestContext_*` tests).

- [ ] **Step 6: Add the CLI command**

Create `tools/vault-engine/cmd/vault-engine/context_cmd.go`:

```go
package main

import (
	"flag"
	"fmt"
	"io"

	"obsidian-vault-engine/pkg/vault"
)

// runContext prints knowledge relevant to a session. It always returns 0: retrieval must never block a session.
func runContext(engine *vault.VaultEngine, args []string) int {
	fs := flag.NewFlagSet("context", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	cwd := fs.String("cwd", ".", "session working directory")
	query := fs.String("query", "", "prompt text to match")
	limit := fs.Int("limit", 5, "maximum notes in --query mode")
	maxBytes := fs.Int("max-bytes", 0, "output cap in bytes (default 800 for --cwd, 2000 for --query)")
	if err := fs.Parse(args); err != nil {
		return 0
	}
	var hits []vault.ContextHit
	budget := *maxBytes
	if *query != "" {
		hits = engine.ContextByQuery(*query, *limit)
		if budget == 0 {
			budget = 2000
		}
	} else {
		hits = engine.ContextByCwd(*cwd)
		if budget == 0 {
			budget = 800
		}
	}
	fmt.Print(vault.FormatContext(hits, budget))
	return 0
}
```

In `tools/vault-engine/cmd/vault-engine/main.go`, directly after the line `engine := vault.NewVaultEngine(vaultRoot)` and before `syncCfg, err := vaultsync.LoadConfig(engine.Root)`, add:

```go
	// Read-only and fail-open, so it runs before the sync config can refuse.
	if command == "context" {
		os.Exit(runContext(engine, os.Args[2:]))
	}
```

In `printUsage`, after the `search <query>` line, add:

```go
	fmt.Println("  context [--cwd d] [--query q]       Print knowledge relevant to a session")
```

- [ ] **Step 7: Add an end-to-end case and the recall script**

In `tools/vault-engine/test_e2e.sh`, directly before the line `# Clean up temp test vault`, add:

```bash
# Context retrieval check
mkdir -p "${VAULT_ROOT}/04_Knowledge/concepts"
cat << 'EOF' > "${VAULT_ROOT}/04_Knowledge/concepts/e2e-context.md"
---
id: CONCEPT-e2e-context
title: Flaky gate retries
schema: knowledge/v1
status: active
kind: concept
tags: [gate]
updated: "2026-11-01T00:00:00Z"
---

Retry a flaky gate once before failing the ship.
EOF
"$ENGINE_BIN" rebuild-index > /dev/null
CTX_OUT=$("$ENGINE_BIN" context --query "why does the flaky gate keep failing retries")
if echo "$CTX_OUT" | grep -qF -- "- CONCEPT-e2e-context | Flaky gate retries |"; then
    echo "✅ Context retrieval verified."
else
    echo "❌ ERROR: context output missing the note: $CTX_OUT"
    exit 1
fi
if [ -n "$("$ENGINE_BIN" context --query "zzzz qqqq")" ]; then
    echo "❌ ERROR: context printed output for a non-matching query"
    exit 1
fi
echo "✅ Context stays silent on no match."

```

Create `tools/vault-engine/recall_eval.sh` and `chmod +x` it:

```bash
#!/usr/bin/env bash
# Scores retrieval against a private prompt set. Each line: {"prompt": "...", "expected_id": "..."}
# Usage: recall_eval.sh <set.jsonl> [min_hits]   (VAULT_ENGINE overrides the binary)
set -euo pipefail
SET="${1:?usage: recall_eval.sh <set.jsonl> [min_hits]}"
MIN="${2:-16}"
ENGINE="${VAULT_ENGINE:-vault-engine}"
hits=0
total=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  prompt=$(printf '%s' "$line" | python3 -c 'import json,sys; print(json.load(sys.stdin)["prompt"])')
  want=$(printf '%s' "$line" | python3 -c 'import json,sys; print(json.load(sys.stdin)["expected_id"])')
  total=$((total + 1))
  if "$ENGINE" context --query "$prompt" --limit 3 | grep -qF -- "- $want |"; then
    hits=$((hits + 1))
  else
    echo "MISS: $want <- $prompt"
  fi
done < "$SET"
echo "recall: $hits/$total (min $MIN)"
[ "$hits" -ge "$MIN" ]
```

- [ ] **Step 8: Run everything**

Run: `cd tools/vault-engine && gofmt -l . && go vet ./... && go test -cover ./... && ./test_e2e.sh`
Expected: `gofmt -l` prints nothing, `go vet` prints nothing, every package `ok`, and the e2e ends with `ALL TESTS PASSED` after the two new `✅ Context` lines.

- [ ] **Step 9: Update `tools/vault-engine/README.md`**

Add a section after the `search` documentation:

```markdown
### `context`: knowledge for a session

`vault-engine context --cwd <dir>` prints notes tied to the repository that owns `<dir>` (through a project's `release_repo`, or a `repo:<name>` tag), at most 800 bytes.
`vault-engine context --query "<prompt>"` scores notes by distinct prompt terms: title 3, tag 2, body 1, threshold 4, up to 5 notes.
Both read only `_meta/indexes/`, print nothing when nothing matches, and always exit 0. Run `rebuild-index` once after upgrading so the index carries tags, summaries and terms.
`recall_eval.sh <set.jsonl> [min]` scores retrieval against a private prompt set.
```

- [ ] **Step 10: Commit**

```bash
git add tools/vault-engine
git commit -m "feat(vault-engine): add context command for session knowledge retrieval"
```

- [ ] **Step 11: Phase gate** (rule 7): verify (Step 8 output) → independent review with `code-reviewer` and `golang-reviewer`, RISK: R1 → one fix round → `/simplify` → re-run Step 8.

---

### Task 2: `vault-recall.py` UserPromptSubmit hook

**Files:**
- Create: `skills/agentic-vault/hooks/vault-recall.py` (executable)
- Create: `tests/test_vault_recall.py`

**Interfaces:**
- Consumes: the `vault-engine context` CLI and its line format from Task 1 (`- <id> | <title> | <path> | matched: ... | <summary>`).
- Produces:
  - Hook stdout, only when it injects: `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "<vault-context>\n...lines...\n</vault-context>"}}`.
  - State file `<state>/<session_id>.json` = `{"ids": [str], "bytes": int}`; injection log `<state>/injections.jsonl`, one `{"ts": int, "session_id": str, "note_id": str}` per injected note; optional `<state>/usage.json` with a `"demoted": [str]` list, read if present (slice 3 writes it).
  - Env: `VAULT_ENGINE` (binary path override), `VAULT_RECALL_STATE` (state dir override, default `~/.claude/state/vault-recall`).

- [ ] **Step 1: Write the failing tests**

```python test:tests/test_vault_recall.py
#!/usr/bin/env python3
"""Tests for skills/agentic-vault/hooks/vault-recall.py (UserPromptSubmit knowledge recall)."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "skills" / "agentic-vault" / "hooks" / "vault-recall.py"

STUB = """#!/usr/bin/env python3
import os, sys
key = "STUB_QUERY_FILE" if "--query" in sys.argv else "STUB_CWD_FILE"
path = os.environ.get(key)
if path and os.path.exists(path):
    sys.stdout.write(open(path).read())
"""


def note(note_id, pad=0):
    return f"- {note_id} | Title {note_id} | 04_Knowledge/concepts/{note_id}.md | matched: alpha, beta | {'s' * pad}"


def block(*lines):
    return "<vault-context>\n" + "\n".join(lines) + "\n</vault-context>\n"


class TestVaultRecall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.stub = self.dir / "vault-engine"
        self.stub.write_text(STUB)
        self.stub.chmod(self.stub.stat().st_mode | stat.S_IEXEC)
        self.query_file = self.dir / "query.txt"
        self.cwd_file = self.dir / "cwd.txt"
        self.state = self.dir / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, prompt="how do I fix the codex quota problem", session="s1", env_extra=None, engine=None):
        env = {k: v for k, v in os.environ.items()
               if k not in ("VAULT_RECALL", "VAULT_CONTEXT_BOOTSTRAP", "CLAUDE_VAULT_SUMMARY")}
        env.update({
            "VAULT_ENGINE": str(engine or self.stub),
            "VAULT_RECALL_STATE": str(self.state),
            "STUB_QUERY_FILE": str(self.query_file),
            "STUB_CWD_FILE": str(self.cwd_file),
        })
        env.update(env_extra or {})
        payload = json.dumps({"session_id": session, "prompt": prompt, "cwd": str(self.dir)})
        proc = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def context_of(self, stdout):
        return json.loads(stdout)["hookSpecificOutput"]["additionalContext"]

    def test_injects_matching_note_as_additional_context(self):
        self.query_file.write_text(block(note("CONCEPT-a")))
        out = self.run_hook()
        data = json.loads(out)
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("- CONCEPT-a | Title CONCEPT-a |", self.context_of(out))
        self.assertTrue(self.context_of(out).startswith("<vault-context>\n"))

    def test_same_note_is_injected_once_per_session(self):
        self.query_file.write_text(block(note("CONCEPT-a")))
        self.assertIn("CONCEPT-a", self.run_hook())
        self.assertEqual(self.run_hook(), "")
        self.assertIn("CONCEPT-a", self.run_hook(session="s2"))

    def test_notes_seeded_from_session_start_are_not_repeated(self):
        self.cwd_file.write_text(block(note("CONCEPT-a")))
        self.query_file.write_text(block(note("CONCEPT-a"), note("CONCEPT-b")))
        ctx = self.context_of(self.run_hook())
        self.assertNotIn("CONCEPT-a", ctx)
        self.assertIn("CONCEPT-b", ctx)

    def test_at_most_three_notes_per_prompt(self):
        self.query_file.write_text(block(*[note(f"CONCEPT-{i}") for i in range(5)]))
        ctx = self.context_of(self.run_hook())
        self.assertEqual(ctx.count("\n- "), 3)

    def test_session_cap_of_2400_bytes_and_six_notes(self):
        total = 0
        ids = []
        for i in range(3):
            self.query_file.write_text(block(*[note(f"CONCEPT-{i}{j}", pad=800) for j in range(3)]))
            out = self.run_hook(prompt=f"prompt number {i} about codex quota")
            if out:
                ctx = self.context_of(out)
                lines = [l for l in ctx.splitlines() if l.startswith("- ")]
                total += sum(len(l.encode()) + 1 for l in lines)
                ids += [l[2:].split(" | ")[0] for l in lines]
        self.assertLessEqual(total, 2400)
        self.assertGreater(total, 0)
        self.assertEqual(len(ids), len(set(ids)))
        state = json.loads((self.state / "s1.json").read_text())
        self.assertLessEqual(len(state["ids"]), 6)
        self.assertLessEqual(state["bytes"], 2400)

    def test_missing_engine_is_silent(self):
        self.assertEqual(self.run_hook(engine=self.dir / "nope"), "")

    def test_opt_out_env_vars_are_silent(self):
        self.query_file.write_text(block(note("CONCEPT-a")))
        for key in ("VAULT_RECALL", "VAULT_CONTEXT_BOOTSTRAP", "CLAUDE_VAULT_SUMMARY"):
            self.assertEqual(self.run_hook(env_extra={key: "0"}), "", key)

    def test_short_and_slash_prompts_are_silent(self):
        self.query_file.write_text(block(note("CONCEPT-a")))
        self.assertEqual(self.run_hook(prompt="fix it"), "")
        self.assertEqual(self.run_hook(prompt="/model something long enough"), "")

    def test_demoted_notes_are_dropped(self):
        self.query_file.write_text(block(note("CONCEPT-a"), note("CONCEPT-b")))
        self.state.mkdir(parents=True)
        (self.state / "usage.json").write_text(json.dumps({"demoted": ["CONCEPT-a"]}))
        ctx = self.context_of(self.run_hook())
        self.assertNotIn("CONCEPT-a", ctx)
        self.assertIn("CONCEPT-b", ctx)

    def test_injections_are_logged(self):
        self.query_file.write_text(block(note("CONCEPT-a")))
        self.run_hook()
        rows = [json.loads(l) for l in (self.state / "injections.jsonl").read_text().splitlines()]
        self.assertEqual([(r["session_id"], r["note_id"]) for r in rows], [("s1", "CONCEPT-a")])

    def test_garbage_stdin_is_silent(self):
        proc = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True, timeout=10)
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
```

Verify-Cmd: python3 -m unittest tests.test_vault_recall -v

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_vault_recall -v`
Expected: every test fails or errors because `skills/agentic-vault/hooks/vault-recall.py` does not exist (`can't open file`, return code 2).

- [ ] **Step 3: Write the hook**

Create `skills/agentic-vault/hooks/vault-recall.py`, then `chmod +x` it:

```python
#!/usr/bin/env python3
"""UserPromptSubmit hook: inject up to 3 agentic-vault notes relevant to the prompt.

Calls `vault-engine context --query <prompt>` (no LLM), injects each note at most once per
session, and stops at 6 notes / 2,400 bytes per session. Fails open: any problem means no
output and exit 0, so it can never block a prompt.
"""
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROMPT_NOTES, PROMPT_BYTES = 3, 1200
SESSION_NOTES, SESSION_BYTES = 6, 2400
STATE_MAX_AGE = 7 * 24 * 3600
OPT_OUT = ("VAULT_RECALL", "VAULT_CONTEXT_BOOTSTRAP", "CLAUDE_VAULT_SUMMARY")


def state_dir() -> Path:
    return Path(os.environ.get("VAULT_RECALL_STATE") or Path.home() / ".claude" / "state" / "vault-recall")


def run_engine(args: list[str]) -> str:
    binary = os.environ.get("VAULT_ENGINE") or shutil.which("vault-engine") or str(Path.home() / ".local/bin/vault-engine")
    proc = subprocess.run([binary, "context", *args], capture_output=True, text=True, timeout=2)
    return proc.stdout if proc.returncode == 0 else ""


def note_lines(block: str) -> list[str]:
    return [line for line in block.splitlines() if line.startswith("- ") and " | " in line]


def note_id(line: str) -> str:
    return line[2:].split(" | ", 1)[0]


def size(line: str) -> int:
    return len(line.encode()) + 1


def prune(directory: Path) -> None:
    cutoff = time.time() - STATE_MAX_AGE
    for path in directory.glob("*.json"):
        if path.name != "usage.json" and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


def main() -> int:
    if any(os.environ.get(key) == "0" for key in OPT_OUT):
        return 0
    data = json.load(sys.stdin)
    prompt = (data.get("prompt") or "").strip()
    session = "".join(c for c in str(data.get("session_id") or "") if c.isalnum() or c in "-_")
    if len(prompt) < 12 or prompt.startswith("/") or not session:
        return 0

    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    prune(directory)
    usage = directory / "usage.json"
    demoted = set(json.loads(usage.read_text()).get("demoted", [])) if usage.exists() else set()

    chosen: list[str] = []
    with open(directory / f"{session}.json", "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        raw = handle.read()
        if raw:
            state = json.loads(raw)
        else:
            # First prompt of the session: count what the SessionStart hook already injected.
            seed = note_lines(run_engine(["--cwd", data.get("cwd") or os.getcwd()]))
            state = {"ids": [note_id(line) for line in seed], "bytes": sum(size(line) for line in seed)}
        used = 0
        for line in note_lines(run_engine(["--query", prompt[:2000]])):
            nid = note_id(line)
            if nid in state["ids"] or nid in demoted:
                continue
            if len(chosen) >= PROMPT_NOTES or used + size(line) > PROMPT_BYTES:
                break
            if len(state["ids"]) >= SESSION_NOTES or state["bytes"] + size(line) > SESSION_BYTES:
                break
            chosen.append(line)
            used += size(line)
            state["ids"].append(nid)
            state["bytes"] += size(line)
        handle.seek(0)
        handle.truncate()
        json.dump(state, handle)

    if not chosen:
        return 0
    with open(directory / "injections.jsonl", "a") as log:
        for line in chosen:
            log.write(json.dumps({"ts": int(time.time()), "session_id": session, "note_id": note_id(line)}) + "\n")
    context = "<vault-context>\n" + "\n".join(chosen) + "\n</vault-context>"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_vault_recall -v`
Expected: `Ran 11 tests` … `OK`.

- [ ] **Step 5: Confirm CI picks the test up**

Run: `python3 .github/scripts/check_test_coverage.py`
Expected: exit 0. If it reports `tests/test_vault_recall.py` as not covered, add that file to the test command of the `dispatch-agy-worker (pytest)` job in `.github/workflows/ci.yml` the same way its neighbours in `tests/` are listed, then re-run until it exits 0.

- [ ] **Step 6: Commit**

```bash
git add skills/agentic-vault/hooks/vault-recall.py tests/test_vault_recall.py
git commit -m "feat(agentic-vault): add vault-recall prompt hook with per-session byte budget"
```

---

### Task 3: Doctor check, docs, and go-live

**Files:**
- Modify: `bin/ps-skills-doctor` (new function `check_vault_recall`, called from `main` before the `# Report` block)
- Modify: `tests/test_ps_skills_doctor.py`
- Modify: `README.md`, `skills/agentic-vault/SKILL.md`

**Interfaces:**
- Consumes: the hook path `~/.claude/hooks/vault-recall.py` (linked by `install.sh` from `skills/*/hooks/*`), the `vault-engine context` CLI.
- Produces: `check_vault_recall(home: Path, issues: list, warnings: list) -> None` in `bin/ps-skills-doctor`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ps_skills_doctor.py`, before the `if __name__` block if one exists, otherwise at the end:

```python test:tests/test_ps_skills_doctor.py
import importlib.machinery
import importlib.util
import json as _json


def _load_doctor():
    loader = importlib.machinery.SourceFileLoader("ps_skills_doctor", str(DOCTOR_SCRIPT))
    spec = importlib.util.spec_from_loader("ps_skills_doctor", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestVaultRecallCheck(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.doctor = _load_doctor()
        (self.home / "workspace" / "agentic-vault" / "_meta" / "indexes").mkdir(parents=True)
        (self.home / ".claude" / "hooks").mkdir(parents=True)
        self.index = self.home / "workspace" / "agentic-vault" / "_meta" / "indexes" / "knowledge.jsonl"
        self.hook = self.home / ".claude" / "hooks" / "vault-recall.py"
        self.settings = self.home / ".claude" / "settings.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def healthy(self):
        self.index.write_text('{"id":"CONCEPT-a","title":"A","terms":["alpha"]}\n')
        self.hook.write_text("#!/usr/bin/env python3\n")
        self.settings.write_text(_json.dumps({"hooks": {"UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": f"python3 {self.hook}"}]}]}}))

    def run_check(self):
        issues, warnings = [], []
        self.doctor.check_vault_recall(self.home, issues, warnings)
        return issues, warnings

    def test_healthy_setup_reports_nothing(self):
        self.healthy()
        self.assertEqual(self.run_check(), ([], []))

    def test_no_vault_is_skipped(self):
        import shutil
        shutil.rmtree(self.home / "workspace")
        self.assertEqual(self.run_check(), ([], []))

    def test_unregistered_hook_is_an_issue(self):
        self.healthy()
        self.settings.write_text(_json.dumps({"hooks": {}}))
        issues, _ = self.run_check()
        self.assertTrue(any("not registered" in i for i in issues), issues)

    def test_missing_hook_file_is_an_issue(self):
        self.healthy()
        self.hook.unlink()
        issues, _ = self.run_check()
        self.assertTrue(any("vault-recall.py" in i and "missing" in i for i in issues), issues)

    def test_index_without_terms_is_an_issue(self):
        self.healthy()
        self.index.write_text('{"id":"CONCEPT-a","title":"A"}\n')
        issues, _ = self.run_check()
        self.assertTrue(any("rebuild-index" in i for i in issues), issues)
```

Verify-Cmd: python3 -m unittest tests.test_ps_skills_doctor -v

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_ps_skills_doctor -v`
Expected: the five `TestVaultRecallCheck` tests error with `AttributeError: module 'ps_skills_doctor' has no attribute 'check_vault_recall'`; the existing tests still pass.

- [ ] **Step 3: Add the check to `bin/ps-skills-doctor`**

Add `import json` to the imports at the top. Add this function above `def main():`:

```python
def check_vault_recall(home, issues, warnings):
    """Knowledge retrieval health: hook linked and registered, index carries retrieval fields."""
    vault = Path(os.environ.get("VAULT_ROOT") or home / "workspace" / "agentic-vault")
    if not (vault / "_meta").is_dir():
        return  # no vault on this machine: nothing to check
    hook = home / ".claude" / "hooks" / "vault-recall.py"
    if not hook.exists():
        issues.append(f"Vault recall hook missing: {hook} (run install.sh)")
    try:
        settings = json.loads((home / ".claude" / "settings.json").read_text())
    except (OSError, ValueError):
        settings = {}
    registered = any(
        "vault-recall.py" in h.get("command", "")
        for group in settings.get("hooks", {}).get("UserPromptSubmit", [])
        for h in group.get("hooks", [])
    )
    if not registered:
        issues.append("Vault recall hook not registered under UserPromptSubmit in ~/.claude/settings.json")
    index = vault / "_meta" / "indexes" / "knowledge.jsonl"
    try:
        first = index.read_text().splitlines()[0]
    except (OSError, IndexError):
        first = ""
    if '"terms"' not in first:
        issues.append(f"Vault index has no retrieval fields: run `vault-engine rebuild-index` ({index})")
```

In `main`, directly above the line `# Report`, add:

```python
    check_vault_recall(home, issues, warnings)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_ps_skills_doctor tests.test_vault_recall -v`
Expected: `OK`, all tests pass.

- [ ] **Step 5: Update `README.md` and `skills/agentic-vault/SKILL.md`**

In `README.md`, add under the section that documents `vault-engine` (or the hooks list if there is no such section):

```markdown
### Automatic knowledge retrieval (I-039 slice 1)

- `vault-engine context --cwd <dir>` / `--query "<prompt>"`: print the vault notes relevant to a session, from the index only, no LLM.
- `skills/agentic-vault/hooks/vault-recall.py`: UserPromptSubmit hook. Injects up to 3 notes (1,200 bytes) per prompt, each note once per session, at most 6 notes and 2,400 bytes per session. Register it once in `~/.claude/settings.json` under `hooks.UserPromptSubmit`: `{"type": "command", "command": "python3 ~/.claude/hooks/vault-recall.py", "timeout": 5}`.
- Env: `VAULT_RECALL=0` turns the hook off; `VAULT_ENGINE` and `VAULT_RECALL_STATE` override the binary and the state directory. It is also off when `VAULT_CONTEXT_BOOTSTRAP=0` or `CLAUDE_VAULT_SUMMARY=0` (dispatch workers).
- `ps-skills-doctor` reports when the hook is missing or unregistered, or the index lacks retrieval fields.
```

In `skills/agentic-vault/SKILL.md`, add one row to the CLI Command Reference table after the `search` row:

```markdown
| `context` | `vault-engine context --cwd <dir>` or `--query "<prompt>"` | Notes relevant to a session, from the index only; prints nothing on no match |
```

and replace the body of "### 1. Pre-Flight Knowledge Discovery (Before Coding)" with:

```markdown
Retrieval is automatic in Claude Code: the SessionStart hook injects notes tied to the repo, and the `vault-recall.py` prompt hook injects up to 3 notes per prompt as a `<vault-context>` block. Each line gives the note id, path and the terms that matched. Read the note with `vault-engine read-record "<ID>"` when a line looks relevant. In harnesses without hooks, query by hand:
```bash
vault-engine context --query "<topic>"
vault-engine read-record "<ID>"
```
```

Run: `python3 -m pytest engine/ps-release-workflow/tests/test_docs_single_source.py -q` (from the repo root)
Expected: passes or skips; `agentic-vault` is not a `ps-release-workflow-*` skill, so the 40-line limit does not apply.

- [ ] **Step 6: Commit**

```bash
git add bin/ps-skills-doctor tests/test_ps_skills_doctor.py README.md skills/agentic-vault/SKILL.md
git commit -m "feat(doctor): check vault recall hook and index; document automatic retrieval"
```

- [ ] **Step 7: Phase gate for Tasks 2 and 3** (rule 7): verify (`python3 -m unittest discover -s tests -v` is green) → independent review with `code-reviewer` and `python-reviewer`, RISK: R1 → one fix round → `/simplify` → re-run the suite.

- [ ] **Step 8: Go live on this machine (R1: state it, then do it)**

These steps change the live install, so run them from the feature worktree only after the phase gates pass.

```bash
cp ~/.local/bin/vault-engine ~/.local/bin/vault-engine.bak-pre-context-$(date +%Y%m%d)
(cd tools/vault-engine && go build -o ~/.local/bin/vault-engine ./cmd/vault-engine)
VAULT_ROOT=~/workspace/agentic-vault vault-engine rebuild-index
cp ~/.claude/settings.json ~/.claude/settings.json.bak-vault-recall-$(date +%Y%m%d)
```

Link the hook for this machine (the same link `install.sh` makes once the feature is on `main`): `ln -sfn "$PWD/skills/agentic-vault/hooks/vault-recall.py" ~/.claude/hooks/vault-recall.py`. After the feature ships and the worktree is removed, run `./install.sh` from the main checkout so the link points at `main`.

Add to `~/.claude/settings.json`, inside `hooks.UserPromptSubmit`, a new group after the existing `skill-detect.js` group:

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "python3 /Users/pasitnusso/.claude/hooks/vault-recall.py",
      "timeout": 5
    }
  ]
}
```

- [ ] **Step 9: Live verification on the user's surface (Tier 4)**

Write the private recall set: pick 20 notes from `~/workspace/agentic-vault/_meta/indexes/knowledge.jsonl` and, for each, write one prompt a user would plausibly type about that topic without copying the title word for word. Save as `~/.claude/state/vault-recall/recall_set.jsonl`, one `{"prompt": "...", "expected_id": "..."}` per line.

Run, and paste the output into the task report:

```bash
VAULT_ROOT=~/workspace/agentic-vault vault-engine context --query "codegen drift gate fails in CI"
CLAUDE_PROJECT_DIR=~/workspace/repos/atlas-world-svc ~/workspace/agent-harness/.venv/bin/python ~/workspace/agent-harness/scripts/vault-bootstrap.py | head -c 900
echo '{"session_id":"live-check","prompt":"codegen drift gate fails in CI","cwd":"'$HOME'/ps-skills"}' | python3 ~/.claude/hooks/vault-recall.py
VAULT_ROOT=~/workspace/agentic-vault tools/vault-engine/recall_eval.sh ~/.claude/state/vault-recall/recall_set.jsonl 16
ps-skills-doctor --strict
```

Expected: the first command prints a `<vault-context>` block naming `CONCEPT-codegen-drift-gate`; the second prints a `<vault-context>` block of at most 800 bytes (empty only if no note carries `PROJ-atlas-world`; if empty, check `release_repo` in that project's hub and report it); the third prints JSON whose `additionalContext` names the note; the fourth ends with `recall: N/20 (min 16)` and exit 0; the doctor reports no vault issue. If recall is below 16, report the `MISS` lines; do not lower the threshold or edit the prompts to fit.

Then remove the live-check state: `rm -f ~/.claude/state/vault-recall/live-check.json`.

---

## Self-review notes

- Spec coverage for slice 1: R0 (Task 1 Step 3), R1/R1f (ContextByCwd, tests), R2/R2f/R2p (ContextByQuery, tests), R3/R3f/R4/R5 (Task 2), R14 injection log (Task 2, pulled forward from slice 3 so usage data exists from day one), the retrieval part of R17 (Task 3; the save-side checks arrive with slice 2).
- Not in this plan: R6–R13, R16, R18–R21, R10a/R10b and the `publish-knowledge` collision check (slices 2 and 3).
- Deviation from the spec: the recall set is private (outside the public repo).
