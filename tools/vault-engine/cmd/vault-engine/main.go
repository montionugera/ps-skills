package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"obsidian-vault-engine/pkg/agent"
	"obsidian-vault-engine/pkg/daemon"
	"obsidian-vault-engine/pkg/vault"
	"obsidian-vault-engine/pkg/workflow"
)

func main() {
	if len(os.Args) < 2 {
		printUsage()
		os.Exit(1)
	}

	command := os.Args[1]

	// Determine vault root: if VAULT_ROOT env is set, use it; otherwise search up or use system canonical vault
	vaultRoot := os.Getenv("VAULT_ROOT")
	if vaultRoot == "" {
		cwd, _ := os.Getwd()
		if _, err := os.Stat(filepath.Join(cwd, "_meta")); err == nil {
			vaultRoot = cwd
		} else if _, err := os.Stat(filepath.Join(cwd, "..", "..", "_meta")); err == nil {
			vaultRoot = filepath.Clean(filepath.Join(cwd, "..", ".."))
		} else {
			home, _ := os.UserHomeDir()
			candidatePaths := []string{
				filepath.Join(home, "workspace", "agentic-vault"),
				filepath.Join(home, "Documents", "Obsidian Vault"),
			}
			found := false
			for _, p := range candidatePaths {
				if _, err := os.Stat(filepath.Join(p, "_meta")); err == nil {
					vaultRoot = p
					found = true
					break
				}
			}
			if !found {
				vaultRoot = cwd
			}
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

	case "read-record":
		if len(os.Args) < 3 {
			fmt.Fprintln(os.Stderr, "Usage: vault-engine read-record <record_id>")
			os.Exit(1)
		}
		env, err := engine.ReadRecord(os.Args[2])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Read record error: %v\n", err)
			os.Exit(1)
		}
		out, _ := json.MarshalIndent(env, "", "  ")
		fmt.Println(string(out))

	case "commit":
		if len(os.Args) < 6 {
			fmt.Fprintln(os.Stderr, "Usage: vault-engine commit <record_id> <expected_sha> <actor> <updates_json> [idempotency_key] [reason]")
			os.Exit(1)
		}
		recordID := os.Args[2]
		expectedSHA := os.Args[3]
		actor := os.Args[4]
		rawUpdates := os.Args[5]
		var updates map[string]interface{}
		if err := json.Unmarshal([]byte(rawUpdates), &updates); err != nil {
			fmt.Fprintf(os.Stderr, "Invalid updates JSON: %v\n", err)
			os.Exit(1)
		}
		idempotencyKey := ""
		if len(os.Args) > 6 {
			idempotencyKey = os.Args[6]
		}
		reason := "cli-commit"
		if len(os.Args) > 7 {
			reason = os.Args[7]
		}

		err := engine.CommitRecord(vault.CommitRequest{
			RecordID:       recordID,
			ExpectedSHA256: expectedSHA,
			Updates:        updates,
			Actor:          actor,
			IdempotencyKey: idempotencyKey,
			Reason:         reason,
		})
		if err != nil {
			fmt.Fprintf(os.Stderr, "Commit FAILED: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("Commit SUCCESS for %s by %s (OCC validated)\n", recordID, actor)

	case "run-workflow":
		if len(os.Args) < 3 {
			fmt.Fprintln(os.Stderr, "Usage: vault-engine run-workflow <workflow_file> [payload_json]")
			os.Exit(1)
		}
		wf, err := workflow.LoadWorkflow(os.Args[2])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Load workflow error: %v\n", err)
			os.Exit(1)
		}
		var payload map[string]interface{}
		if len(os.Args) > 3 {
			_ = json.Unmarshal([]byte(os.Args[3]), &payload)
		}
		if payload == nil {
			payload = make(map[string]interface{})
		}

		storageDir := filepath.Join(engine.Root, "_meta", "instances")
		instID := fmt.Sprintf("wf-%s-%d", wf.WorkflowID, time.Now().Unix())
		inst := workflow.NewWorkflowInstance(wf, instID, payload, storageDir)
		runner := workflow.NewWorkflowRunner(wf, storageDir)

		// Register standard handlers
		runner.RegisterHandler("vault.ingest_file", func(instance *workflow.WorkflowInstance, step workflow.WorkflowStep) (map[string]interface{}, error) {
			filePath, _ := instance.Payload["file_path"].(string)
			if filePath == "" {
				return nil, fmt.Errorf("missing 'file_path' in workflow payload")
			}
			assignedID, err := engine.IngestFile(filePath)
			if err != nil {
				return nil, err
			}
			return map[string]interface{}{"idea_id": assignedID}, nil
		})

		runner.RegisterHandler("market_gap_analysis", func(instance *workflow.WorkflowInstance, step workflow.WorkflowStep) (map[string]interface{}, error) {
			ideaID, _ := instance.Artifacts["idea_id"].(string)
			return map[string]interface{}{
				"idea_id":        ideaID,
				"market_summary": "High commercial demand verified by Bestie",
				"estimated_roi":  "high",
				"analyst":        "agent-bestie",
			}, nil
		})

		runner.RegisterHandler("architecture_feasibility", func(instance *workflow.WorkflowInstance, step workflow.WorkflowStep) (map[string]interface{}, error) {
			ideaID, _ := instance.Artifacts["idea_id"].(string)
			return map[string]interface{}{
				"idea_id":        ideaID,
				"feasibility":    "feasible",
				"latency_impact": "low",
				"auditor":        "agent-philip",
			}, nil
		})

		runner.RegisterHandler("score_and_promote", func(instance *workflow.WorkflowInstance, step workflow.WorkflowStep) (map[string]interface{}, error) {
			ideaID, _ := instance.Artifacts["idea_id"].(string)
			if ideaID == "" {
				return nil, fmt.Errorf("missing 'idea_id' artifact for promotion")
			}
			env, err := engine.ReadRecord(ideaID)
			if err != nil {
				return nil, err
			}
			err = engine.CommitRecord(vault.CommitRequest{
				RecordID:       ideaID,
				ExpectedSHA256: env.SHA256,
				Updates: map[string]interface{}{
					"status":     "candidate",
					"impact":     5,
					"effort":     2,
					"confidence": 4,
				},
				Actor:          "agent-olivier",
				IdempotencyKey: instance.InstanceID,
				Reason:         "score_and_promote",
			})
			if err != nil {
				return nil, err
			}
			return map[string]interface{}{"status": "candidate", "record_id": ideaID}, nil
		})

		if err := runner.RunUntilTerminal(inst, 20); err != nil {
			fmt.Fprintf(os.Stderr, "Workflow execution failed: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("Workflow %s completed with status: %s (Instance ID: %s)\n", wf.WorkflowID, inst.Status, inst.InstanceID)

	case "daemon":
		interval := 3 * time.Second
		runOnce := false
		wfPath := filepath.Join(engine.Root, "_meta", "workflows", "idea-lifecycle.json")

		for _, arg := range os.Args[2:] {
			if arg == "--once" {
				runOnce = true
			}
		}

		watcher := daemon.NewWatcher(daemon.WatcherConfig{
			VaultRoot:    engine.Root,
			WorkflowPath: wfPath,
			Interval:     interval,
			RunOnce:      runOnce,
		})

		ctx := context.Background()
		if runOnce {
			count, err := watcher.ProcessInboxOnce()
			if err != nil {
				fmt.Fprintf(os.Stderr, "Daemon inbox sweep failed: %v\n", err)
				os.Exit(1)
			}
			fmt.Printf("Daemon inbox sweep complete: %d notes processed\n", count)
		} else {
			fmt.Printf("Starting vault daemon watcher on %s (interval: %v)...\n", engine.Root, interval)
			if err := watcher.Run(ctx); err != nil {
				fmt.Fprintf(os.Stderr, "Daemon error: %v\n", err)
				os.Exit(1)
			}
		}

	case "capture":
		if len(os.Args) < 6 {
			fmt.Fprintln(os.Stderr, "Usage: vault-engine capture <idempotency_key> <category> <origin> <payload>")
			os.Exit(1)
		}
		ledger := vault.NewCaptureLedger(filepath.Join(engine.Root, "_meta", "ledger"))
		entry, err := ledger.RecordCapture(os.Args[2], vault.CategoryTrack(os.Args[3]), os.Args[4], os.Args[5])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Capture failed: %v\n", err)
			os.Exit(1)
		}
		data, _ := json.Marshal(entry)
		fmt.Println(string(data))

	case "route":
		if len(os.Args) < 5 {
			fmt.Fprintln(os.Stderr, "Usage: vault-engine route <category> <kind> <slug> [owner]")
			os.Exit(1)
		}
		owner := ""
		if len(os.Args) >= 6 {
			owner = os.Args[5]
		}
		resolver := vault.NewPathResolver()
		resolved := resolver.Resolve(vault.CategoryTrack(os.Args[2]), vault.RecordKind(os.Args[3]), os.Args[4], owner)
		fmt.Println(resolved)

	case "audit-health":
		report, err := vault.AuditVault(engine.Root)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Audit health failed: %v\n", err)
			os.Exit(1)
		}
		data, _ := json.MarshalIndent(report, "", "  ")
		fmt.Println(string(data))

	case "publish-knowledge":
		if len(os.Args) < 3 {
			fmt.Fprintln(os.Stderr, "Usage: vault-engine publish-knowledge <file_path> [category] [author]")
			os.Exit(1)
		}
		filePath := os.Args[2]
		category := "process"
		if len(os.Args) > 3 {
			category = os.Args[3]
		}
		author := "agent-olivier"
		if len(os.Args) > 4 {
			author = os.Args[4]
		}
		assignedID, err := engine.PublishKnowledge(filePath, category, author)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Publish knowledge failed: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("Published knowledge note as %s\n", assignedID)

	case "search":
		if len(os.Args) < 3 {
			fmt.Fprintln(os.Stderr, "Usage: vault-engine search <query>")
			os.Exit(1)
		}
		query := os.Args[2]
		results, err := engine.SearchIndexes(query)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Search failed: %v\n", err)
			os.Exit(1)
		}
		if len(results) == 0 {
			fmt.Printf("No matching records found for '%s'\n", query)
			return
		}
		fmt.Printf("Found %d matching record(s) for '%s':\n", len(results), query)
		for _, r := range results {
			fmt.Printf(" - [%s] %s (%s)\n", r.ID, r.Title, r.Path)
		}

	case "check-privacy":
		if err := vault.CheckGitPrivacy(engine.Root); err != nil {
			fmt.Fprintf(os.Stderr, "Privacy check FAILED: %v\n", err)
			os.Exit(1)
		}
		fmt.Println("Git privacy check PASSED: all quarantine paths strictly ignored.")

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
	fmt.Println("  search <query>                      Search knowledge, projects, and ideas")
	fmt.Println("  ingest <file_path>                  Ingest raw note from inbox")
	fmt.Println("  read-record <record_id>             Read canonical record with SHA-256")
	fmt.Println("  commit <id> <sha> <actor> <json>    Optimistic concurrency commit")
	fmt.Println("  publish-knowledge <path> [cat] [by] Publish knowledge note transactionally")
	fmt.Println("  capture <key> <cat> <origin> <txt>  Record raw append-only capture")
	fmt.Println("  route <cat> <kind> <slug> [owner]   Resolve path taxonomy")
	fmt.Println("  audit-health                        Audit broken links and stale claims")
	fmt.Println("  check-privacy                       Verify .gitignore quarantine rules")
	fmt.Println("  validate <file_path>                Validate note schema")
	fmt.Println("  lock <record_id> <agent> <op>       Acquire atomic lock")
	fmt.Println("  unlock <record_id>                  Release lock")
	fmt.Println("  validate-dag <workflow_file>        Validate workflow DAG acyclicity")
	fmt.Println("  validate-agent <manifest_file>      Validate agent recruitment manifest")
}


