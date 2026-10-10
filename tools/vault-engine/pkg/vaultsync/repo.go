package vaultsync

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"strings"
	"syscall"
	"time"
)

var ErrNoConnection = errors.New("no connection to the shared copy")

const localTimeout = 30 * time.Second

var unsafeActorChars = regexp.MustCompile(`[^a-zA-Z0-9._-]+`)

// Repo is the git side of one place. The engine itself never runs git; this
// type is the only code that does.
type Repo struct {
	Root       string
	Place      string
	Remote     string
	Branch     string
	NetTimeout time.Duration
	lock       *FolderLock // set while the folder lock is held; inherited by git children
}

func NewRepo(root string, cfg *Config) *Repo {
	return &Repo{Root: root, Place: cfg.Place, Remote: cfg.Remote, Branch: cfg.Branch,
		NetTimeout: time.Duration(cfg.NetTimeoutMS) * time.Millisecond}
}

type gitResult struct {
	Stdout string
	Stderr string
	Err    error
}

// run executes git with a time limit. While the folder lock is held, the child
// inherits the lock's descriptor: if this process is killed, a still-running
// git keeps the folder locked until it has finished.
func (r *Repo) run(timeout time.Duration, args ...string) gitResult {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, "git", append([]string{"--no-optional-locks"}, args...)...)
	cmd.Dir = r.Root
	cmd.Env = append(os.Environ(), "GIT_TERMINAL_PROMPT=0", "LC_ALL=C", "VAULT_HUB_PLACE="+r.Place)
	cmd.WaitDelay = 2 * time.Second
	// Own process group, so a timeout kills git and every helper it started
	// (ssh, remote helpers) instead of leaving them running.
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error { return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) }
	if r.lock != nil && r.lock.f != nil {
		cmd.ExtraFiles = []*os.File{r.lock.f}
	}
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	err := cmd.Run()
	if ctx.Err() == context.DeadlineExceeded {
		err = fmt.Errorf("timed out after %v", timeout)
	}
	return gitResult{Stdout: out.String(), Stderr: errb.String(), Err: err}
}

// local runs a git command that needs no network and returns trimmed stdout.
func (r *Repo) local(args ...string) (string, error) {
	res := r.run(localTimeout, args...)
	if res.Err != nil {
		return "", fmt.Errorf("git %s: %w: %s", args[0], res.Err, strings.TrimSpace(res.Stderr))
	}
	return strings.TrimSpace(res.Stdout), nil
}

func (r *Repo) Head() (string, error) { return r.local("rev-parse", "HEAD") }

func (r *Repo) remoteRef() string { return r.Remote + "/" + r.Branch }

// Status maps each changed or untracked path to its two-letter porcelain code.
// Ignored files never appear. Untracked files are "??".
func (r *Repo) Status() (map[string]string, error) {
	res := r.run(localTimeout, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
	if res.Err != nil {
		return nil, fmt.Errorf("git status: %w: %s", res.Err, strings.TrimSpace(res.Stderr))
	}
	st := map[string]string{}
	for _, rec := range strings.Split(res.Stdout, "\x00") { // not trimmed: a code may start with a space
		if len(rec) > 3 {
			st[rec[3:]] = rec[:2]
		}
	}
	return st, nil
}

func (r *Repo) Fetch() error {
	res := r.run(r.NetTimeout, "fetch", "--quiet", r.Remote, "+refs/heads/"+r.Branch+":refs/remotes/"+r.Remote+"/"+r.Branch)
	if res.Err != nil {
		return fmt.Errorf("%w: fetch: %v: %s", ErrNoConnection, res.Err, strings.TrimSpace(res.Stderr))
	}
	return nil
}

// RemoteHead asks the hub where its main line is, without downloading anything.
func (r *Repo) RemoteHead() (string, error) {
	res := r.run(r.NetTimeout, "ls-remote", r.Remote, "refs/heads/"+r.Branch)
	fields := strings.Fields(res.Stdout)
	if res.Err != nil || len(fields) == 0 {
		return "", fmt.Errorf("%w: ls-remote: %v: %s", ErrNoConnection, res.Err, strings.TrimSpace(res.Stderr))
	}
	return fields[0], nil
}

func (r *Repo) isAncestor(a, b string) bool {
	return r.run(localTimeout, "merge-base", "--is-ancestor", a, b).Err == nil
}

// Commit records exactly the given paths (additions, changes and deletions)
// as <actor>@<place>. A non-empty key is stored as a Vault-Op-Key trailer.
func (r *Repo) Commit(paths []string, actor, subject, key string) error {
	if _, err := r.local(append([]string{"add", "-A", "--"}, paths...)...); err != nil {
		return err
	}
	who := unsafeActorChars.ReplaceAllString(actor, "")
	if who == "" {
		who = "agent"
	}
	who += "@" + r.Place
	msg := subject + " by " + who
	if key != "" {
		msg += "\n\nVault-Op-Key: " + key
	}
	_, err := r.local("-c", "user.name="+who, "-c", "user.email="+who+".vault.invalid", "-c", "commit.gpgsign=false",
		"commit", "--quiet", "--no-verify", "-m", msg)
	return err
}
