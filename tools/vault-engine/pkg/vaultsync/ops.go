package vaultsync

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"obsidian-vault-engine/pkg/vault"
)

// Op is one existing engine operation, wrapped so that the same closure serves
// the plain path (no sync config) and the save step.
type Op struct {
	Name       string                 // "commit", "ingest", "capture", "publish-knowledge"
	Actor      string                 // recorded as <actor>@<place>
	FailPrefix string                 // today's stderr prefix, e.g. "Commit FAILED"
	Key        string                 // one-time key; "" = no duplicate check
	Drop       string                 // vault-relative inbox file that must be sent first, or ""
	Run        func() (string, error) // returns exactly what main.go prints on success
}

func shortHash(parts ...string) string {
	sum := sha256.Sum256([]byte(strings.Join(parts, "\x00")))
	return hex.EncodeToString(sum[:])[:32]
}

func CommitOp(e *vault.VaultEngine, req vault.CommitRequest) Op {
	return Op{Name: "commit", Actor: req.Actor, FailPrefix: "Commit FAILED", Run: func() (string, error) {
		if err := e.CommitRecord(req); err != nil {
			return "", err
		}
		return fmt.Sprintf("Commit SUCCESS for %s by %s (OCC validated)\n", req.RecordID, req.Actor), nil
	}}
}

func IngestOp(e *vault.VaultEngine, filePath, actor string) Op {
	op := Op{Name: "ingest", Actor: actor, FailPrefix: "Ingest failed", Run: func() (string, error) {
		assignedID, err := e.IngestFile(filePath)
		if err != nil {
			return "", err
		}
		return fmt.Sprintf("Ingested note as %s\n", assignedID), nil
	}}
	abs, err := filepath.Abs(filePath)
	if err != nil {
		return op
	}
	rel, err := filepath.Rel(e.Root, abs)
	if err != nil || strings.HasPrefix(rel, "..") {
		return op // a file outside the vault: no drop to send, no key
	}
	rel = filepath.ToSlash(rel)
	if strings.HasPrefix(rel, "_inbox/") {
		op.Drop = rel
	}
	// Path plus content while the file exists; path only once it is gone (a
	// retry after the first try arrived), which matches the earlier key as a prefix.
	op.Key = "ingest:" + rel + ":"
	if data, err := os.ReadFile(abs); err == nil {
		op.Key += shortHash(string(data))
	}
	return op
}

func PublishOp(e *vault.VaultEngine, filePath, category, author string) Op {
	op := Op{Name: "publish-knowledge", Actor: author, FailPrefix: "Publish knowledge failed", Run: func() (string, error) {
		assignedID, err := e.PublishKnowledge(filePath, category, author)
		if err != nil {
			return "", err
		}
		return fmt.Sprintf("Published knowledge note as %s\n", assignedID), nil
	}}
	if data, err := os.ReadFile(filePath); err == nil {
		op.Key = "publish:" + shortHash(filepath.Base(filePath), string(data), category, author)
	}
	return op
}

func CaptureOp(e *vault.VaultEngine, key, category, origin, payload string) Op {
	return Op{Name: "capture", Actor: origin, FailPrefix: "Capture failed", Run: func() (string, error) {
		ledger := vault.NewCaptureLedger(filepath.Join(e.Root, "_meta", "ledger"))
		entry, err := ledger.RecordCapture(key, vault.CategoryTrack(category), origin, payload)
		if err != nil {
			return "", err
		}
		data, _ := json.Marshal(entry)
		return string(data) + "\n", nil
	}}
}
