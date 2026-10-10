package vaultsync

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"
)

var ErrNoConnection = errors.New("no connection to the shared copy")

// ErrNothingToCommit is returned by Commit when it is given no paths.
var ErrNothingToCommit = errors.New("nothing to commit: no paths given")

// ErrTimedOut marks a git command that was stopped by its own time limit.
var ErrTimedOut = errors.New("timed out")

// ErrStopped marks a git command that was not started because the program is
// shutting down (see Repo.gate).
var ErrStopped = errors.New("stopped")

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
	// lock must be set by the caller (NewRepo leaves it nil) right after taking
	// the folder lock; while set, every git child inherits its descriptor, so a
	// git still running after the engine is killed keeps the folder locked.
	// That protection holds only when the engine dies WITHOUT calling
	// FolderLock.Release (Release unlocks for inheritors too).
	lock *FolderLock
	// gate, when set, is asked before every git command (the one place they all
	// pass through); a non-nil answer is returned as the command's error and
	// nothing is started. The daemon uses it to stop at once after a stop signal;
	// tests use it to count commands or to fail one.
	gate func(args []string) error
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

// exitOnSignal ends the engine after a termination signal has stopped the git
// child. A variable so tests can observe it; production value is os.Exit.
var exitOnSignal = os.Exit

// gitSafetyFlags keep git from starting long-lived descendants (file-system
// monitor, background gc or maintenance, hooks) that would inherit the folder
// lock descriptor and outlive the engine. credential.helper is left alone.
var gitSafetyFlags = []string{"--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "gc.auto=0",
	"-c", "maintenance.auto=false", "-c", "core.hooksPath=/dev/null"}

// gitLocationVars are the variables with which a caller (a git hook of another
// repository, `git rebase --exec`, a tool that exports GIT_DIR) tells git which
// repository, index or object store to use. A place never passes them on: its
// git commands must find the notes folder's own repository from the folder.
// Only the place drops them; the hub's hook (hubGit) keeps git's environment.
var gitLocationVars = map[string]bool{
	"GIT_DIR": true, "GIT_WORK_TREE": true, "GIT_INDEX_FILE": true, "GIT_COMMON_DIR": true,
	"GIT_OBJECT_DIRECTORY": true, "GIT_ALTERNATE_OBJECT_DIRECTORIES": true, "GIT_QUARANTINE_PATH": true,
	"GIT_NAMESPACE": true, "GIT_PREFIX": true, "GIT_IMPLICIT_WORK_TREE": true, "GIT_SHALLOW_FILE": true,
	"GIT_GRAFT_FILE": true, "GIT_REPLACE_REF_BASE": true, "GIT_CEILING_DIRECTORIES": true,
}

// placeEnv is this process's environment without gitLocationVars, and with
// git forbidden to look for a repository above the notes folder.
func placeEnv(root string) []string {
	var env []string
	for _, kv := range os.Environ() {
		if name, _, _ := strings.Cut(kv, "="); !gitLocationVars[name] {
			env = append(env, kv)
		}
	}
	if abs, err := filepath.Abs(root); err == nil {
		env = append(env, "GIT_CEILING_DIRECTORIES="+filepath.Dir(abs))
	}
	return env
}

// ownRepository checks that the notes folder is the top level of its own git
// repository. Without that, reset, checkout and the moving of stray files
// would act on whatever repository git found instead.
func (r *Repo) ownRepository() error {
	top, err := r.local("rev-parse", "--show-toplevel")
	if err == nil {
		rootInfo, rootErr := os.Stat(r.Root)
		topInfo, topErr := os.Stat(top)
		if rootErr == nil && topErr == nil && os.SameFile(rootInfo, topInfo) {
			return nil
		}
		err = fmt.Errorf("git uses %s", top)
	}
	if errors.Is(err, ErrStopped) {
		return err
	}
	return fmt.Errorf("the notes folder %s is not the top level of its own git repository: %w", r.Root, err)
}

// run executes git with a time limit. While the folder lock is held, the child
// inherits the lock's descriptor: if this process is killed, a still-running
// git keeps the folder locked until it has finished. git runs in its own
// process group; a time-out, SIGINT, SIGTERM or SIGHUP kills the whole group,
// and a signal then ends the engine with status 128+signal.
func (r *Repo) run(timeout time.Duration, args ...string) gitResult {
	if r.gate != nil {
		if err := r.gate(args); err != nil {
			return gitResult{Err: err}
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, "git", append(append([]string{}, gitSafetyFlags...), args...)...)
	cmd.Dir = r.Root
	cmd.Env = append(placeEnv(r.Root), "GIT_TERMINAL_PROMPT=0", "GIT_LITERAL_PATHSPECS=1", "LC_ALL=C", "VAULT_HUB_PLACE="+r.Place)
	cmd.WaitDelay = 2 * time.Second
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error { return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) }
	if r.lock != nil && r.lock.f != nil {
		cmd.ExtraFiles = []*os.File{r.lock.f}
	}
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM, syscall.SIGHUP)
	defer signal.Stop(sigs)
	err := cmd.Start()
	if err == nil {
		done := make(chan error, 1)
		go func() { done <- cmd.Wait() }()
		select {
		case err = <-done:
		case sig := <-sigs:
			_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
			<-done
			code := 128
			if s, ok := sig.(syscall.Signal); ok {
				code += int(s)
			}
			exitOnSignal(code)
			err = fmt.Errorf("interrupted by %v", sig)
		}
	}
	if ctx.Err() == context.DeadlineExceeded {
		err = fmt.Errorf("%w after %v", ErrTimedOut, timeout)
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

// isAncestor tells "a is not an ancestor of b" (false, nil) from a git failure
// such as a time-out or an unknown ref (false, error): only the first means
// the answer is no.
func (r *Repo) isAncestor(a, b string) (bool, error) {
	res := r.run(localTimeout, "merge-base", "--is-ancestor", a, b)
	if res.Err == nil {
		return true, nil
	}
	var ee *exec.ExitError
	if errors.As(res.Err, &ee) && ee.ExitCode() == 1 {
		return false, nil
	}
	return false, fmt.Errorf("git merge-base: %w: %s", res.Err, strings.TrimSpace(res.Stderr))
}

// Commit records exactly the given paths (additions, changes and deletions)
// as <actor>@<place>; anything else staged stays staged, and paths are literal
// names, not patterns. No paths gives ErrNothingToCommit and touches nothing.
// A non-empty key is stored as a Vault-Op-Key trailer.
func (r *Repo) Commit(paths []string, actor, subject, key string) error {
	if len(paths) == 0 {
		return ErrNothingToCommit
	}
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
	_, err := r.local(append([]string{"-c", "user.name=" + who, "-c", "user.email=" + who + ".vault.invalid", "-c", "commit.gpgsign=false",
		"commit", "--quiet", "--no-verify", "-m", msg, "--"}, paths...)...)
	return err
}
