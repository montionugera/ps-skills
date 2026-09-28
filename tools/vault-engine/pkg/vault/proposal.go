package vault

import (
	"errors"
	"fmt"
)

var (
	ErrMissingEvidence = errors.New("validation error: evidence citations required when confidence > 0.8")
)

type ProposalOperation string

const (
	ProposalCreate  ProposalOperation = "create"
	ProposalPatch   ProposalOperation = "patch"
	ProposalArchive ProposalOperation = "archive"
)

type ChangeProposal struct {
	ProposalID      string            `json:"proposal_id"`
	RunID           string            `json:"run_id"`
	Actor           string            `json:"actor"`
	ContractVersion string            `json:"contract_version"`
	Operation       ProposalOperation `json:"operation"`
	TargetPath      string            `json:"target_path"`
	BaseSHA256      string            `json:"base_sha256,omitempty"`
	ProposedContent string            `json:"proposed_content"`
	Reason          string            `json:"reason"`
	Confidence      float64           `json:"confidence"`
	EvidenceRefs    []string          `json:"evidence_refs"`
}

func (p *ChangeProposal) Validate() error {
	if p.ProposalID == "" {
		return fmt.Errorf("proposal_id is required")
	}
	if p.TargetPath == "" {
		return fmt.Errorf("target_path is required")
	}
	if p.Operation == ProposalPatch && p.BaseSHA256 == "" {
		return fmt.Errorf("base_sha256 is required for patch operations")
	}
	if p.Confidence > 0.8 && len(p.EvidenceRefs) == 0 {
		return ErrMissingEvidence
	}
	return nil
}
