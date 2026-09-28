package vault

import (
	"strings"
)

type BucketType string

const (
	BucketInbox        BucketType = "inbox"
	BucketWorking      BucketType = "working"
	BucketReviewNeeded BucketType = "review_needed"
	BucketConflicts    BucketType = "conflicts"
	BucketCompleted    BucketType = "completed"
)

type BucketManager struct{}

func NewBucketManager() *BucketManager {
	return &BucketManager{}
}

func (bm *BucketManager) ClassifyRecord(rec *RecordEnvelope) BucketType {
	if strings.HasPrefix(rec.Path, "_inbox/") {
		return BucketInbox
	}

	status, ok := rec.Frontmatter["status"].(string)
	if !ok {
		return BucketInbox
	}

	switch strings.ToLower(status) {
	case "conflict", "conflicted":
		return BucketConflicts
	case "review_needed", "needs_review", "pending_review":
		return BucketReviewNeeded
	case "working", "triaged", "in_progress", "researching":
		return BucketWorking
	case "committed", "completed", "candidate", "shipped", "done":
		return BucketCompleted
	default:
		return BucketInbox
	}
}
