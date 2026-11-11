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
	limit := fs.Int("limit", 0, "maximum notes (default 5 for --query, 3 for --cwd)")
	maxBytes := fs.Int("max-bytes", 0, "output cap in bytes (default 800 for --cwd, 2000 for --query)")
	if err := fs.Parse(args); err != nil {
		return 0
	}
	var hits []vault.ContextHit
	budget := *maxBytes
	n := *limit
	if *query != "" {
		if n == 0 {
			n = 5
		}
		hits = engine.ContextByQuery(*query, n)
		if budget == 0 {
			budget = 2000
		}
	} else {
		hits = engine.ContextByCwd(*cwd)
		if n == 0 {
			n = 3
		}
		if len(hits) > n {
			hits = hits[:n]
		}
		if budget == 0 {
			budget = 800
		}
	}
	fmt.Print(vault.FormatContext(hits, budget))
	return 0
}
