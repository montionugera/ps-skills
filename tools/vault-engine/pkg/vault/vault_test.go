package vault

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

func setupTestVault(t *testing.T) string {
	tmp := t.TempDir()
	dirs := []string{
		"_inbox/human",
		"_inbox/agent/claude",
		"_inbox/agent/antigravity",
		"_archive/ideas",
		"_archive/projects",
		"_meta/schemas",
		"_meta/indexes",
		"_meta/locks",
		"_meta/events",
		"01_Ideas/boards",
		"02_Projects",
		"03_Areas/finance",
		"03_Areas/engineering",
		"04_Knowledge/sops",
	}
	for _, d := range dirs {
		if err := os.MkdirAll(filepath.Join(tmp, d), 0755); err != nil {
			t.Fatalf("failed to create fixture dir %s: %v", d, err)
		}
	}
	return tmp
}

func TestBC01_IngestAndIDAllocation(t *testing.T) {
	root := setupTestVault(t)
	engine := NewVaultEngine(root)

	inboxFile := filepath.Join(root, "_inbox/human/quick-idea.md")
	content := `---
title: AI Invoice Matcher
impact: 4
effort: 2
area_ids: [area-finance]
---
Manual invoice matching takes 30 mins per batch.
`
	if err := os.WriteFile(inboxFile, []byte(content), 0644); err != nil {
		t.Fatalf("failed to write inbox file: %v", err)
	}

	assignedID, err := engine.IngestFile(inboxFile)
	if err != nil {
		t.Fatalf("ingest failed: %v", err)
	}

	if !strings.HasPrefix(assignedID, "IDEA-") {
		t.Errorf("expected ID starting with IDEA-, got %s", assignedID)
	}

	// Verify file moved to 01_Ideas
	matches, _ := filepath.Glob(filepath.Join(root, "01_Ideas", assignedID+"*.md"))
	if len(matches) != 1 {
		t.Fatalf("expected exactly 1 idea file, found %d", len(matches))
	}

	// Verify index updated
	indexPath := filepath.Join(root, "_meta/indexes/ideas.jsonl")
	indexBytes, err := os.ReadFile(indexPath)
	if err != nil {
		t.Fatalf("failed to read ideas index: %v", err)
	}
	if !strings.Contains(string(indexBytes), assignedID) {
		t.Errorf("ideas index does not contain %s", assignedID)
	}
}

func TestBC02_FrontmatterSchemaValidation(t *testing.T) {
	root := setupTestVault(t)
	engine := NewVaultEngine(root)

	// Valid idea
	validFM := map[string]interface{}{
		"schema":  "idea/v1",
		"id":      "IDEA-2026-000001",
		"kind":    "idea",
		"title":   "Valid Idea",
		"status":  "triage",
		"impact":  4,
		"effort":  2,
		"created": "2026-09-27",
		"updated": "2026-09-27",
	}
	errs := engine.ValidateFrontmatter(validFM)
	if len(errs) != 0 {
		t.Errorf("expected 0 errors for valid frontmatter, got: %v", errs)
	}

	// Invalid: impact out of bounds (6) and invalid status
	invalidFM := map[string]interface{}{
		"schema": "idea/v1",
		"id":     "IDEA-2026-000002",
		"kind":   "idea",
		"title":  "Invalid Idea",
		"status": "flying",
		"impact": 6,
	}
	errs = engine.ValidateFrontmatter(invalidFM)
	if len(errs) < 2 {
		t.Errorf("expected at least 2 errors for invalid frontmatter, got %d: %v", len(errs), errs)
	}
}

func TestBC03_AtomicLockContention(t *testing.T) {
	root := setupTestVault(t)
	engine := NewVaultEngine(root)

	recordID := "IDEA-2026-000001"
	concurrency := 50

	var successCount int32
	var failCount int32
	var wg sync.WaitGroup

	for i := 0; i < concurrency; i++ {
		wg.Add(1)
		go func(agentNum int) {
			defer wg.Done()
			agentName := fmt.Sprintf("agent-%d", agentNum)
			ctx, err := engine.AcquireLock(recordID, agentName, "triage")
			if err == nil {
				atomic.AddInt32(&successCount, 1)
				// Do not release immediately to ensure contention
				_ = ctx
			} else {
				atomic.AddInt32(&failCount, 1)
			}
		}(i)
	}

	wg.Wait()

	if successCount != 1 {
		t.Fatalf("expected EXACTLY 1 lock acquisition, got %d", successCount)
	}
	if failCount != int32(concurrency-1) {
		t.Fatalf("expected %d failed lock attempts due to contention, got %d", concurrency-1, failCount)
	}
}

func TestBC04_AtomicMutationAndAuditEvents(t *testing.T) {
	root := setupTestVault(t)
	engine := NewVaultEngine(root)

	// Pre-create idea
	ideaPath := filepath.Join(root, "01_Ideas/IDEA-2026-000001--billing.md")
	content := `---
schema: idea/v1
id: IDEA-2026-000001
kind: idea
title: Billing Tool
status: triage
impact: 3
effort: 3
created: 2026-09-27
updated: 2026-09-27
---
Body text.
`
	_ = os.WriteFile(ideaPath, []byte(content), 0644)

	// Acquire lock and mutate
	lockCtx, err := engine.AcquireLock("IDEA-2026-000001", "agent-olivier", "set-candidate")
	if err != nil {
		t.Fatalf("failed to acquire lock: %v", err)
	}

	err = engine.MutateNote("IDEA-2026-000001", lockCtx, map[string]interface{}{
		"status": "candidate",
		"impact": 5,
	}, "agent-olivier")
	if err != nil {
		t.Fatalf("mutation failed: %v", err)
	}

	// Verify file updated
	updatedBytes, _ := os.ReadFile(ideaPath)
	fm, _, _ := engine.ParseMarkdown(string(updatedBytes))
	if fm["status"] != "candidate" {
		t.Errorf("expected status 'candidate', got %v", fm["status"])
	}

	// Verify event logged in _meta/events/
	events, _ := filepath.Glob(filepath.Join(root, "_meta/events/*/*/*.json"))
	if len(events) != 1 {
		t.Fatalf("expected 1 audit event file, got %d", len(events))
	}
}

func TestBC05_AreaRollupAndColdArchive(t *testing.T) {
	root := setupTestVault(t)
	engine := NewVaultEngine(root)

	// Create project under area
	projDir := filepath.Join(root, "02_Projects/PROJ-billing-v2")
	_ = os.MkdirAll(projDir, 0755)
	projFile := filepath.Join(projDir, "Project Hub.md")
	projContent := `---
schema: project/v1
id: PROJ-billing-v2
kind: project
title: Automated Billing v2
status: active
owner: pasit
target_date: 2026-12-31
area_ids: [area-finance]
---
# Project Hub
`
	_ = os.WriteFile(projFile, []byte(projContent), 0644)

	projs, err := engine.GetProjectsForArea("area-finance")
	if err != nil {
		t.Fatalf("get projects for area failed: %v", err)
	}
	if len(projs) != 1 {
		t.Fatalf("expected 1 project for area-finance, got %d", len(projs))
	}

	// Create idea and archive it
	ideaPath := filepath.Join(root, "01_Ideas/IDEA-2026-000099--old-auth.md")
	ideaContent := `---
schema: idea/v1
id: IDEA-2026-000099
kind: idea
title: Old Auth Flow
status: rejected
created: 2026-09-01
updated: 2026-09-01
---
Old auth flow.
`
	_ = os.WriteFile(ideaPath, []byte(ideaContent), 0644)

	archivedPath, err := engine.ArchiveRecord("IDEA-2026-000099", "idea")
	if err != nil {
		t.Fatalf("archive record failed: %v", err)
	}

	if !strings.Contains(archivedPath, "_archive/ideas") {
		t.Errorf("expected path in _archive/ideas, got %s", archivedPath)
	}

	// Verify wikilink integrity
	if !engine.VerifyWikilink("IDEA-2026-000099--old-auth") {
		t.Errorf("expected wikilink to resolve after archiving")
	}
}

func TestBC08_OptimisticConcurrencyCommit(t *testing.T) {
	root := setupTestVault(t)
	engine := NewVaultEngine(root)

	// Ingest raw idea
	inboxFile := filepath.Join(root, "_inbox/human/occ-idea.md")
	_ = os.WriteFile(inboxFile, []byte("---\ntitle: OCC Test\n---\nBody"), 0644)
	id, err := engine.IngestFile(inboxFile)
	if err != nil {
		t.Fatalf("ingest failed: %v", err)
	}

	// Read initial envelope
	env, err := engine.ReadRecord(id)
	if err != nil {
		t.Fatalf("read record failed: %v", err)
	}

	// 1. Commit with matching expected SHA -> should succeed
	err = engine.CommitRecord(CommitRequest{
		RecordID:       id,
		ExpectedSHA256: env.SHA256,
		Updates: map[string]interface{}{
			"status": "candidate",
			"impact": 5,
		},
		Actor:          "agent-olivier",
		IdempotencyKey: "test-attempt-1",
		Reason:         "score-promoted",
	})
	if err != nil {
		t.Fatalf("expected commit to succeed, got %v", err)
	}

	// 2. Commit with old expected SHA -> should reject with conflict
	err = engine.CommitRecord(CommitRequest{
		RecordID:       id,
		ExpectedSHA256: env.SHA256, // Stale hash!
		Updates: map[string]interface{}{
			"status": "committed",
		},
		Actor:  "agent-bestie",
		Reason: "stale-write",
	})
	if err == nil || !strings.Contains(err.Error(), "conflict") {
		t.Fatalf("expected conflict error for stale hash, got %v", err)
	}
}
