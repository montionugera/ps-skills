package agent

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
)

var (
	agentIDRegex = regexp.MustCompile(`^agent-[a-z0-9-]+$`)
)

type AgentManifest struct {
	AgentID        string   `json:"agent_id"`
	Role           string   `json:"role"`
	SystemPrompt   string   `json:"system_prompt"`
	ToolAllowlist  []string `json:"tool_allowlist"`
	InputContract  string   `json:"input_contract"`
	OutputContract string   `json:"output_contract"`
	MaxTurnBudget  int      `json:"max_turn_budget"`
	RecruitedBy    string   `json:"recruited_by,omitempty"`
	RecruitedAt    string   `json:"recruited_at,omitempty"`
}

type AgentRegistry struct {
	AgentsDir string
}

func NewAgentRegistry(agentsDir string) *AgentRegistry {
	return &AgentRegistry{AgentsDir: agentsDir}
}

func (r *AgentRegistry) ValidateManifest(m *AgentManifest) error {
	if m.AgentID == "" || !agentIDRegex.MatchString(m.AgentID) {
		return fmt.Errorf("invalid agent_id '%s': must match ^agent-[a-z0-9-]+$", m.AgentID)
	}
	if m.Role == "" {
		return errors.New("agent role is required")
	}
	if m.SystemPrompt == "" {
		return errors.New("agent system_prompt is required")
	}
	if len(m.ToolAllowlist) == 0 {
		return errors.New("agent tool_allowlist must contain at least one tool")
	}
	// Thinker Policy Rule: Recruited agents cannot be granted recursive recruitment or raw shell tools
	forbiddenTools := map[string]bool{
		"define_subagent": true,
		"agent_recruit":   true,
		"run_command":     true,
		"shell_exec":      true,
		"system_terminal": true,
	}
	for _, tool := range m.ToolAllowlist {
		if forbiddenTools[tool] {
			return fmt.Errorf("privilege escalation rejected: recruited agent cannot be granted '%s'", tool)
		}
	}
	if m.MaxTurnBudget <= 0 {
		m.MaxTurnBudget = 10
	} else if m.MaxTurnBudget > 30 {
		return fmt.Errorf("max_turn_budget exceeds safety ceiling of 30 (got %d)", m.MaxTurnBudget)
	}
	return nil
}

func (r *AgentRegistry) RegisterAgent(m *AgentManifest) error {
	if err := r.ValidateManifest(m); err != nil {
		return err
	}
	if err := os.MkdirAll(r.AgentsDir, 0755); err != nil {
		return err
	}
	destPath := filepath.Join(r.AgentsDir, fmt.Sprintf("%s.json", m.AgentID))
	data, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(destPath, data, 0644)
}

func (r *AgentRegistry) GetAgent(agentID string) (*AgentManifest, error) {
	path := filepath.Join(r.AgentsDir, fmt.Sprintf("%s.json", agentID))
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("agent '%s' not registered: %w", agentID, err)
	}
	var m AgentManifest
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, fmt.Errorf("invalid agent manifest for '%s': %w", agentID, err)
	}
	return &m, nil
}
