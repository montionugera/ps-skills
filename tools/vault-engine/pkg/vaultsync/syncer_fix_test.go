package vaultsync

import "testing"

// I3: a failing log is not "not saved yet".
func TestAlreadySaved_AGitFailureIsAnErrorNotAnAnswer(t *testing.T) {
	w := newWorld(t)
	mac := newSyncer(t, w.Mac)
	if _, err := mac.alreadySaved("some-key"); err != nil {
		t.Fatalf("a healthy folder must answer: %v", err)
	}
	mac.Repo.Remote = "no-such-remote"
	if done, err := mac.alreadySaved("some-key"); err == nil || done {
		t.Fatalf("a git failure must be an error, got (%v, %v)", done, err)
	}
}
