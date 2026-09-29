package vault

import (
	"testing"
)

func TestChangeProposal_EvidenceValidation(t *testing.T) {
	// 1. Valid proposal with evidence
	p1 := &ChangeProposal{
		ProposalID:      "PROP-01",
		RunID:           "RUN-01",
		Actor:           "claude",
		ContractVersion: "v1",
		Operation:       ProposalPatch,
		TargetPath:      "01_Ideas/dark-mode.md",
		BaseSHA256:      "abc12345",
		ProposedContent: "# Dark Mode Spec",
		Reason:          "Feasibility verified",
		Confidence:      0.9,
		EvidenceRefs:    []string{"SRC-2026-0012"},
	}
	if err := p1.Validate(); err != nil {
		t.Errorf("expected valid proposal to pass, got error: %v", err)
	}

	// 2. High confidence (>0.8) without evidence is rejected
	p2 := &ChangeProposal{
		ProposalID:      "PROP-02",
		RunID:           "RUN-02",
		Actor:           "claude",
		ContractVersion: "v1",
		Operation:       ProposalPatch,
		TargetPath:      "01_Ideas/dark-mode.md",
		BaseSHA256:      "abc12345",
		ProposedContent: "# Unverified Spec",
		Reason:          "Guessed score",
		Confidence:      0.9,
		EvidenceRefs:    []string{},
	}
	if err := p2.Validate(); err == nil {
		t.Errorf("expected validation error for confidence > 0.8 without evidence, got nil")
	}

	// 3. Lower confidence (<=0.8) without evidence is allowed (e.g. preliminary spark)
	p3 := &ChangeProposal{
		ProposalID:      "PROP-03",
		RunID:           "RUN-03",
		Actor:           "gemini",
		ContractVersion: "v1",
		Operation:       ProposalCreate,
		TargetPath:      "01_Ideas/preliminary.md",
		ProposedContent: "# Spark",
		Reason:          "Raw hypothesis",
		Confidence:      0.6,
		EvidenceRefs:    []string{},
	}
	if err := p3.Validate(); err != nil {
		t.Errorf("expected preliminary spark to pass without evidence, got: %v", err)
	}

	// 4. Missing proposal_id
	p4 := &ChangeProposal{TargetPath: "01_Ideas/a.md"}
	if err := p4.Validate(); err == nil {
		t.Errorf("expected error for missing proposal_id")
	}

	// 5. Missing target_path
	p5 := &ChangeProposal{ProposalID: "P-5"}
	if err := p5.Validate(); err == nil {
		t.Errorf("expected error for missing target_path")
	}

	// 6. Patch without base_sha256
	p6 := &ChangeProposal{
		ProposalID: "P-6",
		TargetPath: "01_Ideas/a.md",
		Operation:  ProposalPatch,
	}
	if err := p6.Validate(); err == nil {
		t.Errorf("expected error for patch without base_sha256")
	}
}
