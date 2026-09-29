package vault

import (
	"testing"
)

func TestBucketManager_ExclusiveClassification(t *testing.T) {
	bm := NewBucketManager()

	// 1. Inbox
	recInbox := &RecordEnvelope{
		Path: "_inbox/human/clip.md",
		Frontmatter: map[string]interface{}{
			"status": "raw",
		},
	}
	if b := bm.ClassifyRecord(recInbox); b != BucketInbox {
		t.Errorf("expected BucketInbox, got %s", b)
	}

	// 2. Working
	recWorking := &RecordEnvelope{
		Path: "01_Ideas/dark-mode.md",
		Frontmatter: map[string]interface{}{
			"status": "working",
		},
	}
	if b := bm.ClassifyRecord(recWorking); b != BucketWorking {
		t.Errorf("expected BucketWorking, got %s", b)
	}

	// 3. Review Needed
	recReview := &RecordEnvelope{
		Path: "01_Ideas/dark-mode.md",
		Frontmatter: map[string]interface{}{
			"status": "review_needed",
		},
	}
	if b := bm.ClassifyRecord(recReview); b != BucketReviewNeeded {
		t.Errorf("expected BucketReviewNeeded, got %s", b)
	}

	// 4. Conflicts
	recConflict := &RecordEnvelope{
		Path: "01_Ideas/dark-mode.md",
		Frontmatter: map[string]interface{}{
			"status": "conflict",
		},
	}
	if b := bm.ClassifyRecord(recConflict); b != BucketConflicts {
		t.Errorf("expected BucketConflicts, got %s", b)
	}

	// 5. Completed
	recDone := &RecordEnvelope{
		Path: "01_Ideas/dark-mode.md",
		Frontmatter: map[string]interface{}{
			"status": "committed",
		},
	}
	if b := bm.ClassifyRecord(recDone); b != BucketCompleted {
		t.Errorf("expected BucketCompleted, got %s", b)
	}

	// 6. Missing status
	recNoStatus := &RecordEnvelope{
		Path:        "01_Ideas/no-status.md",
		Frontmatter: map[string]interface{}{},
	}
	if b := bm.ClassifyRecord(recNoStatus); b != BucketInbox {
		t.Errorf("expected BucketInbox for missing status, got %s", b)
	}

	// 7. Unknown status fallback
	recUnknown := &RecordEnvelope{
		Path: "01_Ideas/unknown.md",
		Frontmatter: map[string]interface{}{
			"status": "some_arbitrary_value",
		},
	}
	if b := bm.ClassifyRecord(recUnknown); b != BucketInbox {
		t.Errorf("expected BucketInbox for unknown status, got %s", b)
	}
}
