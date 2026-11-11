package main

import (
	"flag"
	"fmt"
	"io"

	"obsidian-vault-engine/pkg/vault"
)

// runContext prints knowledge relevant to a session. It always returns 0: retrieval must never block a session.
func runContext(engine *vault.VaultEngine, args []string) int {
	fs := flag.NewFlagSet("context", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	cwd := fs.String("cwd", ".", "session working directory")
	query := fs.String("query", "", "prompt text to match")
	limit := fs.Int("limit", 5, "maximum notes in --query mode")
	maxBytes := fs.Int("max-bytes", 0, "output cap in bytes (default 800 for --cwd, 2000 for --query)")
	if err := fs.Parse(args); err != nil {
		return 0
	}
	var hits []vault.ContextHit
	budget := *maxBytes
	if *query != "" {
		hits = engine.ContextByQuery(*query, *limit)
		if budget == 0 {
			budget = 2000
		}
	} else {
		hits = engine.ContextByCwd(*cwd)
		if budget == 0 {
			budget = 800
		}
	}
	fmt.Print(vault.FormatContext(hits, budget))
	return 0
}
