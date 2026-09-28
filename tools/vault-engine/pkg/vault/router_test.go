package vault

import (
	"testing"
)

func TestPathResolver_CategoryAwareRouting(t *testing.T) {
	resolver := NewPathResolver()

	// 1. Product Idea
	path1 := resolver.Resolve(CategoryProduct, KindIdea, "dark-mode", "")
	if path1 != "01_Ideas/dark-mode.md" {
		t.Errorf("expected 01_Ideas/dark-mode.md, got %s", path1)
	}

	// 2. Process Decision with owner
	path2 := resolver.Resolve(CategoryProcess, KindDecision, "release-gate", "ReleasePipeline")
	if path2 != "02_Projects/ReleasePipeline/decisions/release-gate.md" {
		t.Errorf("expected 02_Projects/ReleasePipeline/decisions/release-gate.md, got %s", path2)
	}

	// 3. Process Decision without owner (global)
	path3 := resolver.Resolve(CategoryProcess, KindDecision, "global-standards", "")
	if path3 != "04_Knowledge/decisions/global-standards.md" {
		t.Errorf("expected 04_Knowledge/decisions/global-standards.md, got %s", path3)
	}

	// 4. Knowledge Thesis / Research
	path4 := resolver.Resolve(CategoryThesis, KindResearch, "sqlite-wal-scale", "")
	if path4 != "07_Research/sqlite-wal-scale.md" {
		t.Errorf("expected 07_Research/sqlite-wal-scale.md, got %s", path4)
	}

	// 5. Task with owner
	path5 := resolver.Resolve(CategoryProduct, KindTask, "build-login-ui", "AuthProject")
	if path5 != "02_Projects/AuthProject/tasks/build-login-ui.md" {
		t.Errorf("expected 02_Projects/AuthProject/tasks/build-login-ui.md, got %s", path5)
	}

	// 6. Task without owner
	path6 := resolver.Resolve(CategoryProduct, KindTask, "unassigned-task", "")
	if path6 != "_inbox/tasks/unassigned-task.md" {
		t.Errorf("expected _inbox/tasks/unassigned-task.md, got %s", path6)
	}

	// 7. Default fallback
	path7 := resolver.Resolve(CategoryProduct, RecordKind("unknown"), "random", "")
	if path7 != "_inbox/random.md" {
		t.Errorf("expected _inbox/random.md, got %s", path7)
	}
}
