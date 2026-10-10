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
	Name          string                        // "commit", "ingest", "capture", "publish-knowledge"
	Actor         string                        // recorded as <actor>@<place>
	FailPrefix    string                        // today's stderr prefix, e.g. "Commit FAILED"
	Key           string                        // fixed one-time key; "" = no duplicate check
	KeyFn         func(r *Repo) (string, error) // if set, replaces Key: asked by the save step after recovery and update, so it sees the folder as it is then
	Drop          string                        // vault-relative inbox file that must be sent first, or ""
	Refuse        string                        // non-empty: the save step refuses this op before anything is touched
	Run           func() (string, error)        // returns exactly what main.go prints on success
	NoFingerprint bool                          // commit sent without the note's fingerprint: the save step refuses it
}

func shortHash(parts ...string) string {
	sum := sha256.Sum256([]byte(strings.Join(parts, "\x00")))
	return hex.EncodeToString(sum[:])[:32]
}

func CommitOp(e *vault.VaultEngine, req vault.CommitRequest) Op {
	return Op{Name: "commit", Actor: req.Actor, FailPrefix: "Commit FAILED", NoFingerprint: req.ExpectedSHA256 == "", Run: func() (string, error) {
		if err := e.CommitRecord(req); err != nil {
			return "", err
		}
		return fmt.Sprintf("Commit SUCCESS for %s by %s (OCC validated)\n", req.RecordID, req.Actor), nil
	}}
}

// resolvePath makes p absolute and follows symlinks. A file that is already
// gone is resolved through its folder, so a retry sees the same path.
func resolvePath(p string) (string, error) {
	abs, err := filepath.Abs(p)
	if err != nil {
		return "", err
	}
	if r, err := filepath.EvalSymlinks(abs); err == nil {
		return r, nil
	}
	dir, err := filepath.EvalSymlinks(filepath.Dir(abs))
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, filepath.Base(abs)), nil
}

const ingestOutsideInbox = "ingest deletes its source file, and only a file in the inbox (_inbox/) is kept in the shared history first: put the file in the inbox, then ingest it from there"

// IngestOp: IngestFile deletes its source, so with sync configured the source
// must be a file under _inbox/ (checked again against git in the save step).
// Anything else is refused before any marker opens (Op.Refuse).
func IngestOp(e *vault.VaultEngine, filePath, actor string) Op {
	// Run is always set and always gets the caller's own path, exactly as the
	// plain (no sync config) path has always done. Refuse, Drop and Key are
	// worked out from the symlink-resolved path.
	op := Op{Name: "ingest", Actor: actor, FailPrefix: "Ingest failed", Refuse: ingestOutsideInbox,
		Run: func() (string, error) {
			assignedID, err := e.IngestFile(filePath)
			if err != nil {
				return "", err
			}
			return fmt.Sprintf("Ingested note as %s\n", assignedID), nil
		}}
	abs, err := resolvePath(filePath)
	if err != nil {
		return op
	}
	root, err := resolvePath(e.Root)
	if err != nil {
		return op
	}
	rel, err := filepath.Rel(root, abs)
	if err != nil || rel == ".." || strings.HasPrefix(rel, "../") {
		return op // a file outside the vault
	}
	rel = filepath.ToSlash(rel)
	if !strings.HasPrefix(rel, "_inbox/") {
		return op
	}
	op.Refuse, op.Drop = "", rel
	op.KeyFn = func(r *Repo) (string, error) { return ingestKey(r, abs, rel) }
	return op
}

// ingestKey is the path plus the content of the drop, never the path alone (a
// bare path would match an older ingest of a reused name). While the file is
// there its content is read; once it is gone (the first try arrived and
// deleted it) the content comes from the commit that deleted it, so the retry
// finds its own earlier save. If no such commit is known the key is empty: no
// duplicate check, and the engine reports the missing file itself.
func ingestKey(r *Repo, abs, rel string) (string, error) {
	data, err := os.ReadFile(abs)
	if err == nil {
		return "ingest:" + rel + ":" + shortHash(string(data)), nil
	}
	if !os.IsNotExist(err) {
		return "", err
	}
	rev, err := r.local("log", "-1", "--format=%H", "--since=24.hours.ago", "--diff-filter=D", r.remoteRef(), "--", rel)
	if err != nil || rev == "" {
		return "", err
	}
	res := r.run(localTimeout, "show", rev+"^:"+rel)
	if res.Err != nil {
		return "", fmt.Errorf("git show: %w: %s", res.Err, strings.TrimSpace(res.Stderr))
	}
	return "ingest:" + rel + ":" + shortHash(res.Stdout), nil
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
