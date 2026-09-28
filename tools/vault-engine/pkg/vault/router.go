package vault

import (
	"fmt"
)

type PathResolver struct{}

func NewPathResolver() *PathResolver {
	return &PathResolver{}
}

func (r *PathResolver) Resolve(category CategoryTrack, kind RecordKind, slug string, owner string) string {
	switch kind {
	case KindIdea:
		return fmt.Sprintf("01_Ideas/%s.md", slug)
	case KindResearch:
		return fmt.Sprintf("07_Research/%s.md", slug)
	case KindDecision:
		if owner != "" {
			return fmt.Sprintf("02_Projects/%s/decisions/%s.md", owner, slug)
		}
		return fmt.Sprintf("04_Knowledge/decisions/%s.md", slug)
	case KindTask:
		if owner != "" {
			return fmt.Sprintf("02_Projects/%s/tasks/%s.md", owner, slug)
		}
		return fmt.Sprintf("_inbox/tasks/%s.md", slug)
	default:
		return fmt.Sprintf("_inbox/%s.md", slug)
	}
}
