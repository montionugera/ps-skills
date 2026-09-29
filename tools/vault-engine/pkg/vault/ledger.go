package vault

import (
	"bufio"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

var (
	ErrConflictPayload = errors.New("conflict: idempotency key reused with changed payload")
)

type CaptureEntry struct {
	RunID          string        `json:"run_id"`
	IdempotencyKey string        `json:"idempotency_key"`
	Category       CategoryTrack `json:"category"`
	SourceOrigin   string        `json:"source_origin"`
	PayloadSHA256  string        `json:"payload_sha256"`
	RawPayloadPath string        `json:"raw_payload_path"`
	Timestamp      string        `json:"timestamp"`
}

type CaptureLedger struct {
	mu         sync.Mutex
	LedgerDir  string
	LedgerFile string
	RawDir     string
}

func NewCaptureLedger(ledgerDir string) *CaptureLedger {
	ledgerFile := filepath.Join(ledgerDir, "captures.jsonl")
	rawDir := filepath.Join(ledgerDir, "raw")
	_ = os.MkdirAll(rawDir, 0755)

	return &CaptureLedger{
		LedgerDir:  ledgerDir,
		LedgerFile: ledgerFile,
		RawDir:     rawDir,
	}
}

func (l *CaptureLedger) hashPayload(payload string) string {
	sum := sha256.Sum256([]byte(payload))
	return hex.EncodeToString(sum[:])
}

func (l *CaptureLedger) generateRunID() string {
	b := make([]byte, 3)
	_, _ = rand.Read(b)
	return fmt.Sprintf("RUN-%s-%s", time.Now().UTC().Format("20060102"), hex.EncodeToString(b))
}

func (l *CaptureLedger) RecordCapture(idempotencyKey string, category CategoryTrack, sourceOrigin string, rawPayload string) (*CaptureEntry, error) {
	l.mu.Lock()
	defer l.mu.Unlock()

	payloadHash := l.hashPayload(rawPayload)

	// Check existing ledger
	if file, err := os.Open(l.LedgerFile); err == nil {
		scanner := bufio.NewScanner(file)
		for scanner.Scan() {
			line := scanner.Bytes()
			if len(line) == 0 {
				continue
			}
			var existing CaptureEntry
			if err := json.Unmarshal(line, &existing); err == nil {
				if existing.IdempotencyKey == idempotencyKey {
					_ = file.Close()
					if existing.PayloadSHA256 != payloadHash {
						return nil, ErrConflictPayload
					}
					return &existing, nil
				}
			}
		}
		_ = file.Close()
	}

	runID := l.generateRunID()
	rawFileName := fmt.Sprintf("%s.raw", runID)
	rawFilePath := filepath.Join(l.RawDir, rawFileName)

	if err := os.WriteFile(rawFilePath, []byte(rawPayload), 0644); err != nil {
		return nil, fmt.Errorf("failed to write raw payload: %w", err)
	}

	entry := &CaptureEntry{
		RunID:          runID,
		IdempotencyKey: idempotencyKey,
		Category:       category,
		SourceOrigin:   sourceOrigin,
		PayloadSHA256:  payloadHash,
		RawPayloadPath: rawFilePath,
		Timestamp:      time.Now().UTC().Format(time.RFC3339),
	}

	data, err := json.Marshal(entry)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal entry: %w", err)
	}

	f, err := os.OpenFile(l.LedgerFile, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return nil, fmt.Errorf("failed to append to ledger file: %w", err)
	}
	defer f.Close()

	if _, err := f.Write(append(data, '\n')); err != nil {
		return nil, fmt.Errorf("failed to write to ledger file: %w", err)
	}

	return entry, nil
}
