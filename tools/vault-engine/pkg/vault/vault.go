package vault

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"gopkg.in/yaml.v3"
)

var (
	ErrLockContention = errors.New("lock contention: record already locked")
	ErrConflict       = errors.New("conflict: expected sha does not match current record sha")
	ErrValidation     = errors.New("validation error")
	ErrNotFound       = errors.New("record not found")
	ErrInvalidLock    = errors.New("invalid or unacquired lock")

	ideaIDRegex      = regexp.MustCompile(`^IDEA-\d{4}-\d{6}$`)
	areaIDRegex      = regexp.MustCompile(`^area-[a-z0-9-]+$`)
	projectIDRegex   = regexp.MustCompile(`^PROJ-[a-z0-9-]+$`)
	knowledgeIDRegex = regexp.MustCompile(`^(KNOW|THESIS|CONCEPT|SOP|REF)-[a-z0-9-]+$`)
)

type RecordEnvelope struct {
	RecordID    string                 `json:"record_id"`
	SHA256      string                 `json:"sha256"`
	Path        string                 `json:"path"`
	Frontmatter map[string]interface{} `json:"frontmatter"`
	Body        string                 `json:"body"`
}

type CommitRequest struct {
	RecordID       string                 `json:"record_id"`
	ExpectedSHA256 string                 `json:"expected_sha256"`
	Updates        map[string]interface{} `json:"updates"`
	Actor          string                 `json:"actor"`
	IdempotencyKey string                 `json:"idempotency_key"`
	Reason         string                 `json:"reason"`
}

type IdeaFrontmatter struct {
	Schema       string                 `yaml:"schema" json:"schema"`
	ID           string                 `yaml:"id" json:"id"`
	Kind         string                 `yaml:"kind" json:"kind"`
	Title        string                 `yaml:"title" json:"title"`
	Status       string                 `yaml:"status" json:"status"`
	Owner        string                 `yaml:"owner,omitempty" json:"owner,omitempty"`
	AreaIDs      []string               `yaml:"area_ids,omitempty" json:"area_ids,omitempty"`
	ProjectIDs   []string               `yaml:"project_ids,omitempty" json:"project_ids,omitempty"`
	DomainIDs    []string               `yaml:"domain_ids,omitempty" json:"domain_ids,omitempty"`
	Horizon      string                 `yaml:"horizon,omitempty" json:"horizon,omitempty"`
	Impact       int                    `yaml:"impact,omitempty" json:"impact,omitempty"`
	Effort       int                    `yaml:"effort,omitempty" json:"effort,omitempty"`
	Confidence   int                    `yaml:"confidence,omitempty" json:"confidence,omitempty"`
	StrategicFit int                    `yaml:"strategic_fit,omitempty" json:"strategic_fit,omitempty"`
	Risk         int                    `yaml:"risk,omitempty" json:"risk,omitempty"`
	Evidence     string                 `yaml:"evidence_level,omitempty" json:"evidence_level,omitempty"`
	Decision     string                 `yaml:"decision,omitempty" json:"decision,omitempty"`
	Created      string                 `yaml:"created" json:"created"`
	Updated      string                 `yaml:"updated" json:"updated"`
	ArchivedAt   string                 `yaml:"archived_at,omitempty" json:"archived_at,omitempty"`
	Tags         []string               `yaml:"tags,omitempty" json:"tags,omitempty"`
	Extra        map[string]interface{} `yaml:",inline" json:"extra,omitempty"`
}

type IndexEntry struct {
	ID      string   `json:"id"`
	Path    string   `json:"path"`
	Title   string   `json:"title"`
	Status  string   `json:"status"`
	AreaIDs []string `json:"area_ids"`
	Impact  int      `json:"impact,omitempty"`
	Effort  int      `json:"effort,omitempty"`
	Updated string   `json:"updated"`
	SHA256  string   `json:"sha256"`
}

type AuditEvent struct {
	RecordID  string                 `json:"record_id"`
	AgentID   string                 `json:"agent_id"`
	Timestamp string                 `json:"timestamp"`
	Diff      map[string]interface{} `json:"diff"`
}

type LockContext struct {
	LockPath string
	RecordID string
	AgentID  string
	acquired bool
	mu       sync.Mutex
}

func (l *LockContext) Release() error {
	l.mu.Lock()
	defer l.mu.Unlock()
	if !l.acquired {
		return nil
	}
	ownerFile := filepath.Join(l.LockPath, "owner")
	_ = os.Remove(ownerFile)
	err := os.Remove(l.LockPath)
	l.acquired = false
	return err
}

func (l *LockContext) IsAcquired() bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.acquired
}

type VaultEngine struct {
	Root string
}

func NewVaultEngine(root string) *VaultEngine {
	abs, err := filepath.Abs(root)
	if err != nil {
		abs = root
	}
	return &VaultEngine{Root: abs}
}

func (v *VaultEngine) ParseMarkdown(raw string) (map[string]interface{}, string, error) {
	if !strings.HasPrefix(raw, "---\n") {
		return map[string]interface{}{}, raw, nil
	}
	parts := strings.SplitN(raw[4:], "\n---\n", 2)
	if len(parts) < 2 {
		return map[string]interface{}{}, raw, nil
	}
	var fm map[string]interface{}
	if err := yaml.Unmarshal([]byte(parts[0]), &fm); err != nil {
		return nil, "", fmt.Errorf("failed to parse yaml frontmatter: %w", err)
	}
	if fm == nil {
		fm = make(map[string]interface{})
	}
	return fm, parts[1], nil
}

func (v *VaultEngine) SerializeMarkdown(fm map[string]interface{}, body string) (string, error) {
	data, err := yaml.Marshal(fm)
	if err != nil {
		return "", fmt.Errorf("failed to marshal yaml: %w", err)
	}
	cleanBody := strings.TrimLeft(body, "\r\n")
	return fmt.Sprintf("---\n%s---\n%s", string(data), cleanBody), nil
}

func (v *VaultEngine) ComputeSHA256(filePath string) (string, error) {
	f, err := os.Open(filePath)
	if err != nil {
		return "", err
	}
	defer f.Close()

	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func (v *VaultEngine) ValidateFrontmatter(fm map[string]interface{}) []string {
	var errs []string

	schema, _ := fm["schema"].(string)
	if schema == "" {
		errs = append(errs, "missing required field 'schema'")
	}
	kind, _ := fm["kind"].(string)
	if kind == "" {
		errs = append(errs, "missing required field 'kind'")
	}
	id, _ := fm["id"].(string)
	if id == "" {
		errs = append(errs, "missing required field 'id'")
	}

	switch kind {
	case "idea":
		if id != "" && !ideaIDRegex.MatchString(id) {
			errs = append(errs, fmt.Sprintf("invalid idea id format: '%s', expected IDEA-YYYY-NNNNNN", id))
		}
		status, _ := fm["status"].(string)
		validIdeaStatuses := map[string]bool{
			"inbox": true, "triage": true, "incubating": true,
			"candidate": true, "committed": true, "rejected": true, "archived": true,
		}
		if !validIdeaStatuses[status] {
			errs = append(errs, fmt.Sprintf("invalid idea status '%s'", status))
		}
		for _, ratingField := range []string{"impact", "effort", "confidence", "strategic_fit", "risk"} {
			if val, exists := fm[ratingField]; exists && val != nil {
				intVal, ok := toInt(val)
				if !ok || intVal < 1 || intVal > 5 {
					errs = append(errs, fmt.Sprintf("field '%s' must be an integer between 1 and 5 (got %v)", ratingField, val))
				}
			}
		}

	case "area":
		if id != "" && !areaIDRegex.MatchString(id) {
			errs = append(errs, fmt.Sprintf("invalid area id format: '%s', expected area-<slug>", id))
		}
		status, _ := fm["status"].(string)
		validAreaStatuses := map[string]bool{
			"active": true, "watch": true, "delegated": true, "retired": true,
		}
		if !validAreaStatuses[status] {
			errs = append(errs, fmt.Sprintf("invalid area status '%s'", status))
		}

	case "project":
		if id != "" && !projectIDRegex.MatchString(id) {
			errs = append(errs, fmt.Sprintf("invalid project id format: '%s', expected PROJ-<slug>", id))
		}
		status, _ := fm["status"].(string)
		validProjectStatuses := map[string]bool{
			"proposed": true, "active": true, "blocked": true, "done": true, "cancelled": true,
		}
		if !validProjectStatuses[status] {
			errs = append(errs, fmt.Sprintf("invalid project status '%s'", status))
		}

	case "knowledge", "thesis", "concept", "sop", "reference":
		if id != "" && !knowledgeIDRegex.MatchString(id) {
			errs = append(errs, fmt.Sprintf("invalid knowledge id format: '%s', expected (KNOW|THESIS|CONCEPT|SOP|REF)-<slug>", id))
		}
		status, _ := fm["status"].(string)
		validKnowledgeStatuses := map[string]bool{
			"draft": true, "active": true, "deprecated": true, "archived": true,
		}
		if !validKnowledgeStatuses[status] {
			errs = append(errs, fmt.Sprintf("invalid knowledge status '%s'", status))
		}
	}


	return errs
}

func toInt(v interface{}) (int, bool) {
	switch n := v.(type) {
	case int:
		return n, true
	case int64:
		return int(n), true
	case float64:
		if n == float64(int(n)) {
			return int(n), true
		}
		return 0, false
	default:
		return 0, false
	}
}

func (v *VaultEngine) NextIdeaID() string {
	ideaDirs := []string{
		filepath.Join(v.Root, "01_Ideas"),
		filepath.Join(v.Root, "_archive", "ideas"),
	}

	maxID := 0
	pattern := regexp.MustCompile(`IDEA-\d{4}-(\d+)`)

	for _, d := range ideaDirs {
		entries, err := os.ReadDir(d)
		if err != nil {
			continue
		}
		for _, e := range entries {
			m := pattern.FindStringSubmatch(e.Name())
			if len(m) > 1 {
				num, _ := strconv.Atoi(m[1])
				if num > maxID {
					maxID = num
				}
			}
		}
	}

	year := time.Now().Format("2006")
	return fmt.Sprintf("IDEA-%s-%06d", year, maxID+1)
}

func (v *VaultEngine) IngestFile(inboxFilePath string) (string, error) {
	contentBytes, err := os.ReadFile(inboxFilePath)
	if err != nil {
		return "", fmt.Errorf("reading inbox file: %w", err)
	}

	fm, body, err := v.ParseMarkdown(string(contentBytes))
	if err != nil {
		return "", err
	}

	assignedID := v.NextIdeaID()
	title, _ := fm["title"].(string)
	if title == "" {
		base := filepath.Base(inboxFilePath)
		title = strings.TrimSuffix(base, filepath.Ext(base))
	}

	slugReg := regexp.MustCompile(`[^a-zA-Z0-9]+`)
	slug := strings.Trim(slugReg.ReplaceAllString(strings.ToLower(title), "-"), "-")
	if slug == "" {
		slug = "untitled"
	}

	impact, _ := toInt(fm["impact"])
	if impact == 0 {
		impact = 3
	}
	effort, _ := toInt(fm["effort"])
	if effort == 0 {
		effort = 3
	}
	status, _ := fm["status"].(string)
	if status == "" {
		status = "triage"
	}

	normFM := map[string]interface{}{
		"schema":         "idea/v1",
		"id":             assignedID,
		"kind":           "idea",
		"title":          title,
		"status":         status,
		"owner":          "pasit",
		"area_ids":       fm["area_ids"],
		"project_ids":    fm["project_ids"],
		"domain_ids":     fm["domain_ids"],
		"horizon":        "next",
		"impact":         impact,
		"effort":         effort,
		"confidence":     3,
		"strategic_fit":  3,
		"risk":           2,
		"evidence_level": "anecdotal",
		"decision":       "undecided",
		"created":        time.Now().Format("2006-01-02"),
		"updated":        time.Now().UTC().Format(time.RFC3339),
		"tags":           []string{"idea"},
	}

	// Copy custom extra fields
	for k, val := range fm {
		if _, exists := normFM[k]; !exists {
			normFM[k] = val
		}
	}

	destFilename := fmt.Sprintf("%s--%s.md", assignedID, slug)
	destDir := filepath.Join(v.Root, "01_Ideas")
	if err := os.MkdirAll(destDir, 0755); err != nil {
		return "", err
	}

	destPath := filepath.Join(destDir, destFilename)
	serialized, err := v.SerializeMarkdown(normFM, body)
	if err != nil {
		return "", err
	}

	if err := os.WriteFile(destPath, []byte(serialized), 0644); err != nil {
		return "", err
	}

	_ = os.Remove(inboxFilePath)
	_ = v.RebuildIndexes()

	return assignedID, nil
}

func (v *VaultEngine) RebuildIndexes() error {
	ideasDir := filepath.Join(v.Root, "01_Ideas")
	indexesDir := filepath.Join(v.Root, "_meta", "indexes")
	if err := os.MkdirAll(indexesDir, 0755); err != nil {
		return err
	}

	// 1. Ideas
	ideaEntries, _ := os.ReadDir(ideasDir)
	var ideaList []IndexEntry

	for _, e := range ideaEntries {
		if !strings.HasPrefix(e.Name(), "IDEA-") || !strings.HasSuffix(e.Name(), ".md") {
			continue
		}
		path := filepath.Join(ideasDir, e.Name())
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		fm, _, err := v.ParseMarkdown(string(data))
		if err != nil {
			continue
		}
		id, _ := fm["id"].(string)
		if id == "" {
			continue
		}
		title, _ := fm["title"].(string)
		status, _ := fm["status"].(string)
		var areaIDs []string
		if rawAreas, ok := fm["area_ids"].([]interface{}); ok {
			for _, a := range rawAreas {
				if s, sok := a.(string); sok {
					areaIDs = append(areaIDs, s)
				}
			}
		}
		impact, _ := toInt(fm["impact"])
		effort, _ := toInt(fm["effort"])
		updated, _ := fm["updated"].(string)
		sha, _ := v.ComputeSHA256(path)

		relPath, _ := filepath.Rel(v.Root, path)
		ideaList = append(ideaList, IndexEntry{
			ID:      id,
			Path:    relPath,
			Title:   title,
			Status:  status,
			AreaIDs: areaIDs,
			Impact:  impact,
			Effort:  effort,
			Updated: updated,
			SHA256:  sha,
		})
	}

	sort.Slice(ideaList, func(i, j int) bool {
		return ideaList[i].ID < ideaList[j].ID
	})

	ideasIndexPath := filepath.Join(indexesDir, "ideas.jsonl")
	var ideaLines []string
	for _, entry := range ideaList {
		b, _ := json.Marshal(entry)
		ideaLines = append(ideaLines, string(b))
	}
	_ = os.WriteFile(ideasIndexPath, []byte(strings.Join(ideaLines, "\n")+"\n"), 0644)

	// 2. Projects
	projectsDir := filepath.Join(v.Root, "02_Projects")
	var projList []IndexEntry
	projFolders, _ := os.ReadDir(projectsDir)
	for _, pf := range projFolders {
		if !pf.IsDir() {
			continue
		}
		hubPath := filepath.Join(projectsDir, pf.Name(), "Project Hub.md")
		data, err := os.ReadFile(hubPath)
		if err != nil {
			continue
		}
		fm, _, err := v.ParseMarkdown(string(data))
		if err != nil {
			continue
		}
		id, _ := fm["id"].(string)
		title, _ := fm["title"].(string)
		status, _ := fm["status"].(string)
		var areaIDs []string
		if rawAreas, ok := fm["area_ids"].([]interface{}); ok {
			for _, a := range rawAreas {
				if s, sok := a.(string); sok {
					areaIDs = append(areaIDs, s)
				}
			}
		}
		updated, _ := fm["updated"].(string)
		sha, _ := v.ComputeSHA256(hubPath)
		relPath, _ := filepath.Rel(v.Root, hubPath)
		projList = append(projList, IndexEntry{
			ID:      id,
			Path:    relPath,
			Title:   title,
			Status:  status,
			AreaIDs: areaIDs,
			Updated: updated,
			SHA256:  sha,
		})
	}

	sort.Slice(projList, func(i, j int) bool {
		return projList[i].ID < projList[j].ID
	})

	projIndexPath := filepath.Join(indexesDir, "projects.jsonl")
	var projLines []string
	for _, entry := range projList {
		b, _ := json.Marshal(entry)
		projLines = append(projLines, string(b))
	}
	_ = os.WriteFile(projIndexPath, []byte(strings.Join(projLines, "\n")+"\n"), 0644)

	// 3. Knowledge
	knowledgeDir := filepath.Join(v.Root, "04_Knowledge")
	var knowList []IndexEntry
	_ = filepath.Walk(knowledgeDir, func(path string, info os.FileInfo, err error) error {
		if err != nil || info == nil || info.IsDir() || !strings.HasSuffix(path, ".md") {
			return nil
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return nil
		}
		fm, _, err := v.ParseMarkdown(string(data))
		if err != nil {
			return nil
		}
		id, _ := fm["id"].(string)
		if id == "" {
			return nil
		}
		title, _ := fm["title"].(string)
		status, _ := fm["status"].(string)
		sha, _ := v.ComputeSHA256(path)
		relPath, _ := filepath.Rel(v.Root, path)
		knowList = append(knowList, IndexEntry{
			ID:      id,
			Path:    relPath,
			Title:   title,
			Status:  status,
			Updated: fmt.Sprintf("%v", fm["updated"]),
			SHA256:  sha,
		})
		return nil
	})

	sort.Slice(knowList, func(i, j int) bool {
		return knowList[i].ID < knowList[j].ID
	})

	knowIndexPath := filepath.Join(indexesDir, "knowledge.jsonl")
	var knowLines []string
	for _, entry := range knowList {
		b, _ := json.Marshal(entry)
		knowLines = append(knowLines, string(b))
	}
	_ = os.WriteFile(knowIndexPath, []byte(strings.Join(knowLines, "\n")+"\n"), 0644)

	return nil
}


func (v *VaultEngine) AcquireLock(recordID, agentID, operation string) (*LockContext, error) {
	lockDir := filepath.Join(v.Root, "_meta", "locks", fmt.Sprintf("%s.lock", recordID))
	if err := os.MkdirAll(filepath.Dir(lockDir), 0755); err != nil {
		return nil, err
	}

	// Atomic lock claim via os.Mkdir (POSIX mkdir is atomic)
	if err := os.Mkdir(lockDir, 0755); err != nil {
		if os.IsExist(err) {
			ownerInfo, _ := os.ReadFile(filepath.Join(lockDir, "owner"))
			return nil, fmt.Errorf("%w: record %s is locked by %s", ErrLockContention, recordID, strings.TrimSpace(string(ownerInfo)))
		}
		return nil, err
	}

	ownerFile := filepath.Join(lockDir, "owner")
	content := fmt.Sprintf("%s %s %s\n", agentID, time.Now().UTC().Format(time.RFC3339), operation)
	_ = os.WriteFile(ownerFile, []byte(content), 0644)

	return &LockContext{
		LockPath: lockDir,
		RecordID: recordID,
		AgentID:  agentID,
		acquired: true,
	}, nil
}

func (v *VaultEngine) MutateNote(recordID string, lockCtx *LockContext, updates map[string]interface{}, agentID string) error {
	if lockCtx == nil || !lockCtx.IsAcquired() || lockCtx.RecordID != recordID {
		return ErrInvalidLock
	}

	// Locate note
	ideasDir := filepath.Join(v.Root, "01_Ideas")
	files, err := os.ReadDir(ideasDir)
	if err != nil {
		return err
	}

	var targetPath string
	for _, f := range files {
		if strings.HasPrefix(f.Name(), recordID) && strings.HasSuffix(f.Name(), ".md") {
			targetPath = filepath.Join(ideasDir, f.Name())
			break
		}
	}

	if targetPath == "" {
		return fmt.Errorf("%w: %s", ErrNotFound, recordID)
	}

	raw, err := os.ReadFile(targetPath)
	if err != nil {
		return err
	}

	fm, body, err := v.ParseMarkdown(string(raw))
	if err != nil {
		return err
	}

	diff := make(map[string]interface{})
	for k, newVal := range updates {
		if fm[k] != newVal {
			diff[k] = newVal
			fm[k] = newVal
		}
	}

	fm["updated"] = time.Now().UTC().Format(time.RFC3339)

	// Validate before writing
	valErrs := v.ValidateFrontmatter(fm)
	if len(valErrs) > 0 {
		return fmt.Errorf("%w: %s", ErrValidation, strings.Join(valErrs, "; "))
	}

	serialized, err := v.SerializeMarkdown(fm, body)
	if err != nil {
		return err
	}

	// Atomic write via temporary sibling
	tmpPath := targetPath + ".tmp"
	if err := os.WriteFile(tmpPath, []byte(serialized), 0644); err != nil {
		return err
	}
	if err := os.Rename(tmpPath, targetPath); err != nil {
		_ = os.Remove(tmpPath)
		return err
	}

	// Emit audit event
	eventDir := filepath.Join(v.Root, "_meta", "events", time.Now().UTC().Format("2006/01"))
	_ = os.MkdirAll(eventDir, 0755)
	eventPath := filepath.Join(eventDir, fmt.Sprintf("%d-%s.json", time.Now().UnixNano(), agentID))
	audit := AuditEvent{
		RecordID:  recordID,
		AgentID:   agentID,
		Timestamp: time.Now().UTC().Format(time.RFC3339),
		Diff:      diff,
	}
	auditData, _ := json.MarshalIndent(audit, "", "  ")
	_ = os.WriteFile(eventPath, auditData, 0644)

	// Release lock and sync index
	_ = lockCtx.Release()
	_ = v.RebuildIndexes()

	return nil
}

func (v *VaultEngine) ArchiveRecord(recordID, kind string) (string, error) {
	srcDir := filepath.Join(v.Root, "01_Ideas")
	if kind == "project" {
		srcDir = filepath.Join(v.Root, "02_Projects")
	}

	files, err := os.ReadDir(srcDir)
	if err != nil {
		return "", err
	}

	var targetPath string
	var filename string
	for _, f := range files {
		if strings.HasPrefix(f.Name(), recordID) {
			targetPath = filepath.Join(srcDir, f.Name())
			filename = f.Name()
			break
		}
	}

	if targetPath == "" {
		return "", fmt.Errorf("%w: %s", ErrNotFound, recordID)
	}

	raw, err := os.ReadFile(targetPath)
	if err != nil {
		return "", err
	}

	fm, body, err := v.ParseMarkdown(string(raw))
	if err != nil {
		return "", err
	}

	fm["status"] = "archived"
	fm["archived_at"] = time.Now().Format("2006-01-02")
	fm["updated"] = time.Now().UTC().Format(time.RFC3339)

	destDir := filepath.Join(v.Root, "_archive", kind+"s")
	if err := os.MkdirAll(destDir, 0755); err != nil {
		return "", err
	}
	destPath := filepath.Join(destDir, filename)

	serialized, err := v.SerializeMarkdown(fm, body)
	if err != nil {
		return "", err
	}

	if err := os.WriteFile(destPath, []byte(serialized), 0644); err != nil {
		return "", err
	}
	_ = os.Remove(targetPath)
	_ = v.RebuildIndexes()

	return destPath, nil
}

func (v *VaultEngine) GetProjectsForArea(areaID string) ([]map[string]interface{}, error) {
	var projects []map[string]interface{}
	projectsDir := filepath.Join(v.Root, "02_Projects")
	entries, err := os.ReadDir(projectsDir)
	if err != nil {
		return nil, err
	}

	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		hubPath := filepath.Join(projectsDir, e.Name(), "Project Hub.md")
		data, err := os.ReadFile(hubPath)
		if err != nil {
			continue
		}
		fm, _, err := v.ParseMarkdown(string(data))
		if err != nil {
			continue
		}
		if rawAreas, ok := fm["area_ids"].([]interface{}); ok {
			for _, a := range rawAreas {
				if str, sok := a.(string); sok && str == areaID {
					projects = append(projects, fm)
					break
				}
			}
		}
	}
	return projects, nil
}

func (v *VaultEngine) VerifyWikilink(targetSlug string) bool {
	found := false
	_ = filepath.Walk(v.Root, func(p string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return nil
		}
		if strings.HasSuffix(info.Name(), ".md") && strings.Contains(info.Name(), targetSlug) {
			found = true
			return filepath.SkipAll
		}
		return nil
	})
	return found
}

func (v *VaultEngine) FindRecordPath(recordID string) (string, error) {
	// 1. Direct heuristic search
	if strings.HasPrefix(recordID, "IDEA-") {
		ideasDir := filepath.Join(v.Root, "01_Ideas")
		files, err := os.ReadDir(ideasDir)
		if err == nil {
			for _, f := range files {
				if strings.HasPrefix(f.Name(), recordID) && strings.HasSuffix(f.Name(), ".md") {
					return filepath.Join(ideasDir, f.Name()), nil
				}
			}
		}
	} else if strings.HasPrefix(recordID, "PROJ-") {
		projectsDir := filepath.Join(v.Root, "02_Projects")
		hubPath := filepath.Join(projectsDir, recordID, "Project Hub.md")
		if _, err := os.Stat(hubPath); err == nil {
			return hubPath, nil
		}
		directPath := filepath.Join(projectsDir, recordID+".md")
		if _, err := os.Stat(directPath); err == nil {
			return directPath, nil
		}
	} else if strings.HasPrefix(recordID, "area-") {
		areasDir := filepath.Join(v.Root, "03_Areas")
		slug := strings.TrimPrefix(recordID, "area-")
		hubPath := filepath.Join(areasDir, slug, slug+" Hub.md")
		if _, err := os.Stat(hubPath); err == nil {
			return hubPath, nil
		}
		directPath := filepath.Join(areasDir, recordID+".md")
		if _, err := os.Stat(directPath); err == nil {
			return directPath, nil
		}
	}

	// 2. Search across canonical directories for frontmatter ID or filename match
	searchDirs := []string{
		filepath.Join(v.Root, "01_Ideas"),
		filepath.Join(v.Root, "02_Projects"),
		filepath.Join(v.Root, "03_Areas"),
		filepath.Join(v.Root, "04_Knowledge"),
	}

	for _, sDir := range searchDirs {
		var foundPath string
		_ = filepath.Walk(sDir, func(path string, info os.FileInfo, err error) error {
			if err != nil || info == nil || info.IsDir() || !strings.HasSuffix(path, ".md") {
				return nil
			}
			base := filepath.Base(path)
			if strings.HasPrefix(base, recordID) {
				foundPath = path
				return filepath.SkipAll
			}
			data, err := os.ReadFile(path)
			if err != nil {
				return nil
			}
			fm, _, err := v.ParseMarkdown(string(data))
			if err == nil {
				if id, ok := fm["id"].(string); ok && id == recordID {
					foundPath = path
					return filepath.SkipAll
				}
			}
			return nil
		})
		if foundPath != "" {
			return foundPath, nil
		}
	}

	return "", fmt.Errorf("%w: %s", ErrNotFound, recordID)
}

func (v *VaultEngine) ReadRecord(recordID string) (*RecordEnvelope, error) {
	targetPath, err := v.FindRecordPath(recordID)
	if err != nil {
		return nil, err
	}

	data, err := os.ReadFile(targetPath)
	if err != nil {
		return nil, err
	}
	sha, err := v.ComputeSHA256(targetPath)
	if err != nil {
		return nil, err
	}
	fm, body, err := v.ParseMarkdown(string(data))
	if err != nil {
		return nil, err
	}
	relPath, _ := filepath.Rel(v.Root, targetPath)
	return &RecordEnvelope{
		RecordID:    recordID,
		SHA256:      sha,
		Path:        relPath,
		Frontmatter: fm,
		Body:        body,
	}, nil
}

func (v *VaultEngine) PublishKnowledge(filePath string, category string, author string) (string, error) {
	data, err := os.ReadFile(filePath)
	if err != nil {
		return "", fmt.Errorf("read file: %w", err)
	}
	fm, body, err := v.ParseMarkdown(string(data))
	if err != nil {
		return "", fmt.Errorf("parse markdown: %w", err)
	}

	if fm == nil {
		fm = make(map[string]interface{})
	}
	fm["schema"] = "knowledge/v1"
	if _, ok := fm["status"]; !ok {
		fm["status"] = "active"
	}
	if category != "" {
		fm["category"] = category
	}
	if author != "" {
		fm["author"] = author
	}
	now := time.Now().UTC().Format(time.RFC3339)
	if _, ok := fm["created"]; !ok {
		fm["created"] = time.Now().Format("2006-01-02")
	}
	fm["updated"] = now

	id, _ := fm["id"].(string)
	kind, _ := fm["kind"].(string)
	if kind == "" {
		kind = "knowledge"
		fm["kind"] = kind
	}
	if id == "" {
		base := strings.TrimSuffix(filepath.Base(filePath), ".md")
		slug := strings.ToLower(strings.ReplaceAll(base, " ", "-"))
		prefix := "KNOW"
		switch kind {
		case "thesis":
			prefix = "THESIS"
		case "concept":
			prefix = "CONCEPT"
		case "sop":
			prefix = "SOP"
		case "reference":
			prefix = "REF"
		}
		id = fmt.Sprintf("%s-%s", prefix, slug)
		fm["id"] = id
	}

	errs := v.ValidateFrontmatter(fm)
	if len(errs) > 0 {
		return "", fmt.Errorf("knowledge validation failed: %s", strings.Join(errs, ", "))
	}

	destSubdir := "concepts"
	switch kind {
	case "thesis":
		destSubdir = "theses"
	case "concept":
		destSubdir = "concepts"
	case "sop":
		destSubdir = "sops"
	case "reference":
		destSubdir = "references"
	}

	destDir := filepath.Join(v.Root, "04_Knowledge", destSubdir)
	if err := os.MkdirAll(destDir, 0755); err != nil {
		return "", err
	}

	title, _ := fm["title"].(string)
	if title == "" {
		title = strings.TrimSuffix(filepath.Base(filePath), ".md")
		fm["title"] = title
	}
	filename := filepath.Base(filePath)
	if !strings.HasSuffix(filename, ".md") {
		filename += ".md"
	}
	destPath := filepath.Join(destDir, filename)

	yamlBytes, err := yaml.Marshal(fm)
	if err != nil {
		return "", fmt.Errorf("yaml marshal: %w", err)
	}
	content := fmt.Sprintf("---\n%s---\n\n%s", string(yamlBytes), strings.TrimSpace(body))
	if !strings.HasSuffix(content, "\n") {
		content += "\n"
	}

	if err := os.WriteFile(destPath, []byte(content), 0644); err != nil {
		return "", fmt.Errorf("write knowledge note: %w", err)
	}

	// Emit audit event
	eventDir := filepath.Join(v.Root, "_meta", "events", time.Now().UTC().Format("2006/01"))
	_ = os.MkdirAll(eventDir, 0755)
	eventPath := filepath.Join(eventDir, fmt.Sprintf("%d-%s.json", time.Now().UnixNano(), author))
	audit := AuditEvent{
		RecordID:  id,
		AgentID:   author,
		Timestamp: now,
		Diff: map[string]interface{}{
			"action":   "publish_knowledge",
			"path":     destPath,
			"category": category,
			"kind":     kind,
		},
	}
	auditData, _ := json.MarshalIndent(audit, "", "  ")
	_ = os.WriteFile(eventPath, auditData, 0644)

	_ = v.RebuildIndexes()
	return id, nil
}


func (v *VaultEngine) CommitRecord(req CommitRequest) error {
	guardsDir := filepath.Join(v.Root, "_meta", "guards")
	if err := os.MkdirAll(guardsDir, 0755); err != nil {
		return err
	}
	guardFile := filepath.Join(guardsDir, fmt.Sprintf("%s.guard", req.RecordID))
	fd, err := syscall.Open(guardFile, syscall.O_CREAT|syscall.O_RDWR, 0644)
	if err != nil {
		return fmt.Errorf("opening commit guard: %w", err)
	}
	defer func() {
		_ = syscall.Close(fd)
	}()

	// Acquire non-blocking exclusive flock
	if err := syscall.Flock(fd, syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return fmt.Errorf("%w: commit in progress by another process", ErrLockContention)
	}
	defer func() {
		_ = syscall.Flock(fd, syscall.LOCK_UN)
	}()

	// 1. Re-read record and verify expected SHA
	env, err := v.ReadRecord(req.RecordID)
	if err != nil {
		return err
	}
	if req.ExpectedSHA256 != "" && env.SHA256 != req.ExpectedSHA256 {
		return fmt.Errorf("%w: expected %s but current is %s", ErrConflict, req.ExpectedSHA256, env.SHA256)
	}

	// 2. Validate patch
	targetPath := filepath.Join(v.Root, env.Path)
	fm := env.Frontmatter
	diff := make(map[string]interface{})
	for k, newVal := range req.Updates {
		if fm[k] != newVal {
			diff[k] = newVal
			fm[k] = newVal
		}
	}
	fm["updated"] = time.Now().UTC().Format(time.RFC3339)
	valErrs := v.ValidateFrontmatter(fm)
	if len(valErrs) > 0 {
		return fmt.Errorf("%w: %s", ErrValidation, strings.Join(valErrs, "; "))
	}

	// 3. Unique temporary sibling write + fsync
	tmpPath := fmt.Sprintf("%s.%d.tmp", targetPath, os.Getpid())
	serialized, err := v.SerializeMarkdown(fm, env.Body)
	if err != nil {
		return err
	}
	tmpF, err := os.OpenFile(tmpPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0644)
	if err != nil {
		return err
	}
	if _, err := tmpF.WriteString(serialized); err != nil {
		_ = tmpF.Close()
		_ = os.Remove(tmpPath)
		return err
	}
	if err := tmpF.Sync(); err != nil {
		_ = tmpF.Close()
		_ = os.Remove(tmpPath)
		return err
	}
	_ = tmpF.Close()

	// Atomic rename
	if err := os.Rename(tmpPath, targetPath); err != nil {
		_ = os.Remove(tmpPath)
		return err
	}

	// 4. Emit Audit Event
	newSHA, _ := v.ComputeSHA256(targetPath)
	eventDir := filepath.Join(v.Root, "_meta", "events", time.Now().UTC().Format("2006/01"))
	_ = os.MkdirAll(eventDir, 0755)
	eventPath := filepath.Join(eventDir, fmt.Sprintf("%d-%s.json", time.Now().UnixNano(), req.Actor))
	audit := map[string]interface{}{
		"record_id":       req.RecordID,
		"actor":           req.Actor,
		"timestamp":       time.Now().UTC().Format(time.RFC3339),
		"old_sha256":      env.SHA256,
		"new_sha256":      newSHA,
		"idempotency_key": req.IdempotencyKey,
		"reason":          req.Reason,
		"diff":            diff,
	}
	auditData, _ := json.MarshalIndent(audit, "", "  ")
	_ = os.WriteFile(eventPath, auditData, 0644)

	// 5. Sync indexes
	return v.RebuildIndexes()
}

func (v *VaultEngine) SearchIndexes(query string) ([]IndexEntry, error) {
	q := strings.ToLower(strings.TrimSpace(query))
	indexesDir := filepath.Join(v.Root, "_meta", "indexes")
	indexFiles := []string{
		filepath.Join(indexesDir, "knowledge.jsonl"),
		filepath.Join(indexesDir, "projects.jsonl"),
		filepath.Join(indexesDir, "ideas.jsonl"),
	}

	var results []IndexEntry
	for _, f := range indexFiles {
		data, err := os.ReadFile(f)
		if err != nil {
			continue
		}
		lines := strings.Split(string(data), "\n")
		for _, line := range lines {
			if strings.TrimSpace(line) == "" {
				continue
			}
			var entry IndexEntry
			if err := json.Unmarshal([]byte(line), &entry); err != nil {
				continue
			}
			if strings.Contains(strings.ToLower(entry.ID), q) ||
				strings.Contains(strings.ToLower(entry.Title), q) ||
				strings.Contains(strings.ToLower(entry.Path), q) {
				results = append(results, entry)
			}
		}
	}
	return results, nil
}

