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
		if e.Status != "active" {
			continue
		}
		title, tags, body := toSet(Terms(e.Title)), toSet(Terms(strings.Join(e.Tags, " "))), toSet(e.Terms)
		hit := ContextHit{Entry: e}
		strong := false // a title or tag match; body-only overlap on common words is noise
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
				strong = strong || w >= 2
			}
		}
		if hit.Score >= contextThreshold && strong {
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
		if e.Status != "active" {
			continue
		}
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
