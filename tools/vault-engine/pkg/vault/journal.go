package vault

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
)

type Journal struct {
	SnapshotDir string
}

func NewJournal(snapshotDir string) *Journal {
	_ = os.MkdirAll(snapshotDir, 0755)
	return &Journal{
		SnapshotDir: snapshotDir,
	}
}

type Transaction struct {
	TxID        string
	TxDir       string
	Snapshots   map[string]string // originalPath -> snapshotPath
	isCommitted bool
}

func (j *Journal) BeginTx(txID string) (*Transaction, error) {
	txDir := filepath.Join(j.SnapshotDir, txID)
	if err := os.MkdirAll(txDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create tx snapshot dir: %w", err)
	}

	return &Transaction{
		TxID:      txID,
		TxDir:     txDir,
		Snapshots: make(map[string]string),
	}, nil
}

func (tx *Transaction) Snapshot(originalPath string) error {
	if _, err := os.Stat(originalPath); os.IsNotExist(err) {
		return nil // nothing to snapshot for newly created files
	}

	snapFileName := fmt.Sprintf("%d.snap", len(tx.Snapshots)+1)
	snapFilePath := filepath.Join(tx.TxDir, snapFileName)

	src, err := os.Open(originalPath)
	if err != nil {
		return fmt.Errorf("failed to open source for snapshot: %w", err)
	}
	defer src.Close()

	dst, err := os.OpenFile(snapFilePath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0644)
	if err != nil {
		return fmt.Errorf("failed to open dest for snapshot: %w", err)
	}
	defer dst.Close()

	if _, err := io.Copy(dst, src); err != nil {
		return fmt.Errorf("failed to copy file for snapshot: %w", err)
	}

	tx.Snapshots[originalPath] = snapFilePath
	return nil
}

func (tx *Transaction) Commit() error {
	tx.isCommitted = true
	// On commit, cleanup snapshot directory
	return os.RemoveAll(tx.TxDir)
}

func (tx *Transaction) Rollback() error {
	for originalPath, snapFilePath := range tx.Snapshots {
		src, err := os.Open(snapFilePath)
		if err != nil {
			return fmt.Errorf("failed to open snapshot for restore: %w", err)
		}

		dst, err := os.OpenFile(originalPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0644)
		if err != nil {
			src.Close()
			return fmt.Errorf("failed to open original file for restore: %w", err)
		}

		_, copyErr := io.Copy(dst, src)
		src.Close()
		dst.Close()

		if copyErr != nil {
			return fmt.Errorf("failed to restore file from snapshot: %w", copyErr)
		}
	}

	_ = os.RemoveAll(tx.TxDir)
	return nil
}
