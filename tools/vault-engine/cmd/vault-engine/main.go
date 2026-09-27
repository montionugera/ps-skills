package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"obsidian-vault-engine/pkg/agent"
	"obsidian-vault-engine/pkg/vault"
	"obsidian-vault-engine/pkg/workflow"
)

func main() {
	if len(os.Args) < 2 {
		printUsage()
		os.Exit(1)
	}

	command := os.Args[1]

	// Determine vault root: if VAULT_ROOT env is set, use it; otherwise search up
	vaultRoot := os.Getenv("VAULT_ROOT")
	if vaultRoot == "" {
		// default to two levels up from _meta/engine or cwd
		cwd, _ := os.Getwd()
		if _, err := os.Stat(filepath.Join(cwd, "_meta")); err == nil {
			vaultRoot = cwd
		} else if _, err := os.Stat(filepath.Join(cwd, "..", "..", "_meta")); err == nil {
			vaultRoot = filepath.Clean(filepath.Join(cwd, "..", ".."))
		} else {
			vaultRoot = cwd
		}
	}

	engine := vault.NewVaultEngine(vaultRoot)

	switch command {
	case "rebuild-index":
		if err := engine.RebuildIndexes(); err != nil {
			fmt.Fprintf(os.Stderr, "Error rebuilding indexes: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("Successfully rebuilt indexes in %s\n", filepath.Join(engine.Root, "_meta", "indexes"))

	case "ingest":
		if len(os.Args) < 3 {
			fmt.Fprintln(os.Stderr, "Usage: vault-engine ingest <file_path>")
			os.Exit(1)
		}
		assignedID, err := engine.IngestFile(os.Args[2])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Ingest failed: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("Ingested note as %s\n", assignedID)

	case "validate":
		if len(os.Args) < 3 {
			fmt.Fprintln(os.Stderr, "Usage: vault-engine validate <file_path>")
			os.Exit(1)
		}
		data, err := os.ReadFile(os.Args[2])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Read file error: %v\n", err)
			os.Exit(1)
		}
		fm, _, err := engine.ParseMarkdown(string(data))
		if err != nil {
			fmt.Fprintf(os.Stderr, "Markdown parsing error: %v\n", err)
			os.Exit(1)
		}
		errs := engine.ValidateFrontmatter(fm)
		if len(errs) > 0 {
			fmt.Printf("Validation FAILED for %s:\n", os.Args[2])
			for _, e := range errs {
				fmt.Printf(" - %s\n", e)
			}
			os.Exit(1)
		}
		fmt.Printf("Validation PASSED for %s\n", os.Args[2])

	case "lock":
		if len(os.Args) < 5 {
			fmt.Fprintln(os.Stderr, "Usage: vault-engine lock <record_id> <agent_id> <operation>")
			os.Exit(1)
		}
		ctx, err := engine.AcquireLock(os.Args[2], os.Args[3], os.Args[4])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Lock acquisition failed: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("Lock acquired for %s by %s\n", ctx.RecordID, ctx.AgentID)

	case "unlock":
		if len(os.Args) < 3 {
			fmt.Fprintln(os.Stderr, "Usage: vault-engine unlock <record_id>")
			os.Exit(1)
		}
		lockDir := filepath.Join(engine.Root, "_meta", "locks", fmt.Sprintf("%s.lock", os.Args[2]))
		ctx := &vault.LockContext{
			LockPath: lockDir,
			RecordID: os.Args[2],
		}
		// Force release
		_ = os.Remove(filepath.Join(lockDir, "owner"))
		_ = os.Remove(lockDir)
		fmt.Printf("Lock released for %s\n", ctx.RecordID)

	case "validate-dag":
		if len(os.Args) < 3 {
			fmt.Fprintln(os.Stderr, "Usage: vault-engine validate-dag <workflow_file>")
			os.Exit(1)
		}
		wf, err := workflow.LoadWorkflow(os.Args[2])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Failed to load workflow: %v\n", err)
			os.Exit(1)
		}
		if err := wf.Validate(); err != nil {
			fmt.Fprintf(os.Stderr, "Workflow DAG validation FAILED: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("Workflow DAG validation PASSED for %s (version %s, states: %d)\n", wf.WorkflowID, wf.Version, len(wf.States))

	case "validate-agent":
		if len(os.Args) < 3 {
			fmt.Fprintln(os.Stderr, "Usage: vault-engine validate-agent <manifest_file>")
			os.Exit(1)
		}
		data, err := os.ReadFile(os.Args[2])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Read manifest error: %v\n", err)
			os.Exit(1)
		}
		var m agent.AgentManifest
		if err := json.Unmarshal(data, &m); err != nil {
			fmt.Fprintf(os.Stderr, "JSON parse error: %v\n", err)
			os.Exit(1)
		}
		reg := agent.NewAgentRegistry(filepath.Join(engine.Root, "_meta", "agents"))
		if err := reg.ValidateManifest(&m); err != nil {
			fmt.Fprintf(os.Stderr, "Agent validation FAILED: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("Agent validation PASSED for %s (role: %s)\n", m.AgentID, m.Role)

	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n", command)
		printUsage()
		os.Exit(1)
	}
}

func printUsage() {
	fmt.Println("Usage: vault-engine <command> [arguments]")
	fmt.Println("Commands:")
	fmt.Println("  rebuild-index                       Rebuild _meta/indexes/*.jsonl")
	fmt.Println("  ingest <file_path>                  Ingest raw note from inbox")
	fmt.Println("  validate <file_path>                Validate note schema")
	fmt.Println("  lock <record_id> <agent> <op>       Acquire atomic lock")
	fmt.Println("  unlock <record_id>                  Release lock")
	fmt.Println("  validate-dag <workflow_file>        Validate workflow DAG acyclicity")
	fmt.Println("  validate-agent <manifest_file>      Validate agent recruitment manifest")
}
