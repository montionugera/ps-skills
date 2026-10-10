package main

import (
	"fmt"
	"os"
	"time"

	"obsidian-vault-engine/pkg/vault"
	"obsidian-vault-engine/pkg/vaultsync"
)

// runMutating runs one changing operation. Without a sync config it prints
// exactly what the engine printed before; with one it runs the save step and
// ends with one fixed line.
func runMutating(engine *vault.VaultEngine, cfg *vaultsync.Config, op vaultsync.Op) {
	if cfg == nil {
		msg, err := op.Run()
		if err != nil {
			fmt.Fprintf(os.Stderr, "%s: %v\n", op.FailPrefix, err)
			os.Exit(1)
		}
		fmt.Print(msg)
		return
	}
	msg, out := vaultsync.NewSyncer(engine, cfg).Save(op)
	finish(op.FailPrefix, msg, out)
}

// finish prints the reason (stderr, possibly several lines), the engine's own
// message, and the fixed last line, which is always the very last stdout line.
func finish(failPrefix, msg string, out vaultsync.Outcome) {
	if out.Exit != 0 && out.Detail != "" {
		fmt.Fprintf(os.Stderr, "%s: %s\n", failPrefix, out.Detail)
	}
	fmt.Print(msg)
	fmt.Println(out.Line)
	os.Exit(out.Exit)
}

// refuseIfSynced stops commands that would change notes outside the save step.
func refuseIfSynced(cfg *vaultsync.Config, command string) {
	if cfg == nil {
		return
	}
	finish(command, "", vaultsync.Outcome{Line: "REFUSED engine-error", Exit: vaultsync.ExitEngineError,
		Detail: "not available in a shared folder; use commit, ingest, capture or publish-knowledge"})
}

// lockIfSynced takes the folder lock for a local-only command and returns the release function.
func lockIfSynced(engine *vault.VaultEngine, cfg *vaultsync.Config) func() {
	if cfg == nil {
		return func() {}
	}
	lock, err := vaultsync.AcquireFolderLock(engine.Root, time.Duration(cfg.LockTimeoutMS)*time.Millisecond)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(vaultsync.ExitBusy)
	}
	return lock.Release
}

func actorFromEnv() string {
	if a := os.Getenv("VAULT_ACTOR"); a != "" {
		return a
	}
	return "agent"
}
