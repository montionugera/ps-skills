package agent

import (
	"strings"
	"testing"
)

func TestAgentRegistry_PrivilegeEscalationRejection(t *testing.T) {
	reg := NewAgentRegistry(t.TempDir())

	// Agent requesting forbidden tool "run_command"
	badManifest := &AgentManifest{
		AgentID:       "agent-rogue",
		Role:          "Rogue Agent",
		SystemPrompt:  "Try to run arbitrary commands.",
		ToolAllowlist: []string{"search_web", "run_command"},
	}

	err := reg.ValidateManifest(badManifest)
	if err == nil || !strings.Contains(err.Error(), "privilege escalation rejected") {
		t.Fatalf("expected privilege escalation error, got %v", err)
	}

	// Agent requesting recursive recruitment
	badManifest2 := &AgentManifest{
		AgentID:       "agent-cloner",
		Role:          "Cloner Agent",
		SystemPrompt:  "Try to recruit more agents.",
		ToolAllowlist: []string{"define_subagent"},
	}

	err = reg.ValidateManifest(badManifest2)
	if err == nil || !strings.Contains(err.Error(), "privilege escalation rejected") {
		t.Fatalf("expected privilege escalation error for define_subagent, got %v", err)
	}
}

func TestAgentRegistry_ValidRecruitment(t *testing.T) {
	reg := NewAgentRegistry(t.TempDir())

	validManifest := &AgentManifest{
		AgentID:        "agent-compliance",
		Role:           "Compliance Auditor",
		SystemPrompt:   "Audit ideas for GDPR compliance.",
		ToolAllowlist:  []string{"search_web", "read_url_content"},
		InputContract:  "schemas/idea-v1.json",
		OutputContract: "schemas/compliance-v1.json",
		MaxTurnBudget:  15,
	}

	if err := reg.RegisterAgent(validManifest); err != nil {
		t.Fatalf("expected registration to succeed, got %v", err)
	}

	retrieved, err := reg.GetAgent("agent-compliance")
	if err != nil {
		t.Fatalf("failed to retrieve registered agent: %v", err)
	}
	if retrieved.Role != "Compliance Auditor" {
		t.Errorf("expected role 'Compliance Auditor', got %s", retrieved.Role)
	}
}

func TestAgentRegistry_ValidationEdgeCases(t *testing.T) {
	reg := NewAgentRegistry(t.TempDir())

	// 1. Invalid agent_id regex
	if err := reg.ValidateManifest(&AgentManifest{AgentID: "InvalidID"}); err == nil {
		t.Errorf("expected error for invalid agent ID regex")
	}

	// 2. Empty role
	if err := reg.ValidateManifest(&AgentManifest{AgentID: "agent-test", Role: ""}); err == nil {
		t.Errorf("expected error for empty role")
	}

	// 3. Empty system prompt
	if err := reg.ValidateManifest(&AgentManifest{AgentID: "agent-test", Role: "Tester", SystemPrompt: ""}); err == nil {
		t.Errorf("expected error for empty system prompt")
	}

	// 4. Empty tool allowlist
	if err := reg.ValidateManifest(&AgentManifest{AgentID: "agent-test", Role: "Tester", SystemPrompt: "Prompt", ToolAllowlist: []string{}}); err == nil {
		t.Errorf("expected error for empty tool allowlist")
	}

	// 5. MaxTurnBudget <= 0 defaults to 10
	m1 := &AgentManifest{AgentID: "agent-test", Role: "Tester", SystemPrompt: "Prompt", ToolAllowlist: []string{"search_web"}, MaxTurnBudget: 0}
	if err := reg.ValidateManifest(m1); err != nil {
		t.Errorf("expected valid manifest, got: %v", err)
	}
	if m1.MaxTurnBudget != 10 {
		t.Errorf("expected default budget 10, got %d", m1.MaxTurnBudget)
	}

	// 6. MaxTurnBudget > 30 rejected
	m2 := &AgentManifest{AgentID: "agent-test", Role: "Tester", SystemPrompt: "Prompt", ToolAllowlist: []string{"search_web"}, MaxTurnBudget: 50}
	if err := reg.ValidateManifest(m2); err == nil {
		t.Errorf("expected error for budget > 30")
	}

	// 7. System recruited agent allowed system tools
	mSys := &AgentManifest{
		AgentID:       "agent-system",
		Role:          "System Root",
		SystemPrompt:  "Root supervisor",
		ToolAllowlist: []string{"run_command"},
		RecruitedBy:   "system",
	}
	if err := reg.ValidateManifest(mSys); err != nil {
		t.Errorf("expected system recruited agent to pass, got: %v", err)
	}
}
