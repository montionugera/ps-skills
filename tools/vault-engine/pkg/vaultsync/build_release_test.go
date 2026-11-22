package vaultsync

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"syscall"
	"testing"
	"time"
)

// buildFixture is a tiny git repository shaped like the engine folder: the
// real build script, a module, and a main package with the stamped variable.
// The script is run there, never in the source tree.
func buildFixture(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	script, err := os.ReadFile(filepath.Join("..", "..", "scripts", "build-release.sh"))
	if err != nil {
		t.Fatalf("read the build script: %v", err)
	}
	writeFile(t, filepath.Join(dir, "scripts", "build-release.sh"), script)
	writeFile(t, filepath.Join(dir, "go.mod"), []byte("module fixture\n\ngo 1.22\n"))
	writeFile(t, filepath.Join(dir, ".gitignore"), []byte("bin/\n"))
	writeFile(t, filepath.Join(dir, "cmd", "vault-engine", "main.go"),
		[]byte("package main\n\nimport \"fmt\"\n\nvar version = \"dev\"\n\nfunc main() { fmt.Printf(\"vault-engine %s\\n\", version) }\n"))
	mustGit(t, dir, "init", "--quiet", "--initial-branch=main")
	commitAll(t, dir, "fixture")
	return dir
}

// buildTimeout bounds one run of the build script (three cross-builds; about
// ten seconds warm, a few minutes on a cold build cache).
const buildTimeout = 15 * time.Minute

func commitAll(t *testing.T, dir, msg string) {
	t.Helper()
	mustGit(t, dir, "add", "-A")
	mustGit(t, dir, "commit", "--quiet", "-m", msg)
}

// runBuild runs the build script in dir with VERSION, GOOS, GOARCH and GOFLAGS
// emptied; extra ("NAME=value") is set after that. git's location variables
// are not passed on (placeEnv). A build that hangs is killed, with every
// process it started, after buildTimeout.
func runBuild(t *testing.T, dir string, extra ...string) (string, error) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), buildTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, "bash", filepath.Join(dir, "scripts", "build-release.sh"))
	cmd.Env = placeEnv(dir)
	for _, drop := range []string{"VERSION", "GOOS", "GOARCH", "GOFLAGS"} {
		cmd.Env = append(cmd.Env, drop+"=")
	}
	cmd.Env = append(cmd.Env, extra...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error { return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) }
	cmd.WaitDelay = 10 * time.Second
	out, err := cmd.CombinedOutput()
	if ctx.Err() != nil {
		t.Fatalf("the build script did not finish within %v:\n%s", buildTimeout, out)
	}
	return string(out), err
}

// releaseSet fails the test unless bin/release holds exactly the three
// binaries and a checksum file that matches them. It returns the checksum file.
func releaseSet(t *testing.T, dir string) string {
	t.Helper()
	rel := filepath.Join(dir, "bin", "release")
	entries, err := os.ReadDir(rel)
	if err != nil {
		t.Fatalf("no release folder: %v", err)
	}
	var names []string
	for _, e := range entries {
		names = append(names, e.Name())
	}
	want := "SHA256SUMS vault-engine-darwin-amd64 vault-engine-darwin-arm64 vault-engine-linux-amd64"
	if got := strings.Join(names, " "); got != want {
		t.Fatalf("release folder holds %q, want %q", got, want)
	}
	check := exec.Command("shasum", "-a", "256", "-c", "SHA256SUMS")
	check.Dir = rel
	if out, err := check.CombinedOutput(); err != nil {
		t.Fatalf("the checksum file does not match the binaries: %v\n%s", err, out)
	}
	sums, err := os.ReadFile(filepath.Join(rel, "SHA256SUMS"))
	if err != nil {
		t.Fatalf("read the checksum file: %v", err)
	}
	return string(sums)
}

var versionLine = regexp.MustCompile(`(?m)^version (\S+)$`)

func builtVersion(t *testing.T, out string) string {
	t.Helper()
	m := versionLine.FindStringSubmatch(out)
	if m == nil {
		t.Fatalf("no version line in the build output:\n%s", out)
	}
	return m[1]
}

func TestBuildRelease_StampsChecksAndKeepsTheOldSetOnFailure(t *testing.T) {
	dir := buildFixture(t)

	// 1. A clean tree: the plain version, and every binary carries it.
	out, err := runBuild(t, dir)
	if err != nil {
		t.Fatalf("build of a clean tree: %v\n%s", err, out)
	}
	clean := builtVersion(t, out)
	if !regexp.MustCompile(`^0\.2\.0-sync\+[0-9a-f]{7,}$`).MatchString(clean) {
		t.Fatalf("version of a clean tree = %q", clean)
	}
	firstSums := releaseSet(t, dir)
	host := filepath.Join(dir, "bin", "release", "vault-engine-"+runtime.GOOS+"-"+runtime.GOARCH)
	if _, statErr := os.Stat(host); statErr == nil {
		said, runErr := exec.Command(host).Output()
		if runErr != nil || string(said) != "vault-engine "+clean+"\n" {
			t.Fatalf("the built binary says %q (%v), want version %s", said, runErr, clean)
		}
	}

	// 2. An uncommitted change: the version says so. A staging folder left by
	// a run that was killed outright is cleared on the way (releaseSet below
	// accepts nothing but the four files).
	stale := filepath.Join(dir, "bin", "release", ".stage.killed")
	writeFile(t, filepath.Join(stale, "vault-engine-linux-amd64"), []byte("half-built"))
	writeFile(t, filepath.Join(stale, "SHA256SUMS"), []byte("stale"))
	writeFile(t, filepath.Join(dir, "cmd", "vault-engine", "extra.go"), []byte("package main\n\nvar extra = 1\n"))
	if out, err = runBuild(t, dir); err != nil {
		t.Fatalf("build of a changed tree: %v\n%s", err, out)
	}
	if got := builtVersion(t, out); got != clean+".dirty" {
		t.Fatalf("version of a changed tree = %q, want %q", got, clean+".dirty")
	}
	dirtySums := releaseSet(t, dir)
	if dirtySums == firstSums {
		t.Fatalf("a changed tree should have given different binaries")
	}

	// 3. A build that fails part-way (the third target does not compile):
	// the earlier set stays whole, checksum file and binaries still matching.
	writeFile(t, filepath.Join(dir, "cmd", "vault-engine", "broken_linux.go"), []byte("package main\n\nvar broken int = \"only linux fails\"\n"))
	commitAll(t, dir, "break the linux build")
	if out, err = runBuild(t, dir); err == nil {
		t.Fatalf("a build with a failing target must fail:\n%s", out)
	}
	if got := releaseSet(t, dir); got != dirtySums {
		t.Fatalf("a failed build changed the release set")
	}

	// 4. The stamp does not take (the variable was renamed): the build fails
	// and the earlier set stays whole.
	mustGit(t, dir, "rm", "--quiet", "cmd/vault-engine/broken_linux.go")
	writeFile(t, filepath.Join(dir, "cmd", "vault-engine", "main.go"),
		[]byte("package main\n\nimport \"fmt\"\n\nvar buildVersion = \"dev\"\n\nfunc main() { fmt.Printf(\"vault-engine %s\\n\", buildVersion) }\n"))
	commitAll(t, dir, "rename the stamped variable")
	// The check that looks inside the file names the first target and stops the
	// build there. The later check, which runs this machine's binary, adds
	// "(it says: ...)": seeing that would mean the in-file check did not bite.
	out, err = runBuild(t, dir)
	if err == nil || !strings.Contains(out, "build-release: vault-engine-darwin-amd64 does not carry version") ||
		strings.Contains(out, "it says:") {
		t.Fatalf("a build whose stamp did not take must be stopped by the in-file check on the first target: err=%v\n%s", err, out)
	}
	if got := releaseSet(t, dir); got != dirtySums {
		t.Fatalf("a failed build changed the release set")
	}
}

// The fixture has its own main.go, so the test above proves the script, not
// the script together with the real engine. This pins the one name the script
// stamps (-X main.version). The fixture's program also ignores its arguments,
// so the "version" argument the script passes to this machine's binary is not
// checked by any test.
func TestBuildRelease_TheRealEngineStillHasTheStampedVariable(t *testing.T) {
	src, err := os.ReadFile(filepath.Join("..", "..", "cmd", "vault-engine", "main.go"))
	if err != nil {
		t.Fatalf("read the engine's main.go: %v", err)
	}
	if !strings.Contains(string(src), "\nvar version = \"") {
		t.Fatalf("cmd/vault-engine/main.go no longer declares `var version = \"...\"`; scripts/build-release.sh stamps main.version")
	}
}

func TestBuildRelease_AnExplicitVersionIsUsedAsGiven(t *testing.T) {
	dir := buildFixture(t)
	// An uncommitted file: a version the script worked out itself would end in ".dirty".
	writeFile(t, filepath.Join(dir, "cmd", "vault-engine", "extra.go"), []byte("package main\n\nvar extra = 1\n"))
	out, err := runBuild(t, dir, "VERSION=9.9.9-explicit")
	if err != nil {
		t.Fatalf("build with an explicit version: %v\n%s", err, out)
	}
	if got := builtVersion(t, out); got != "9.9.9-explicit" {
		t.Fatalf("version = %q, want the explicit one exactly as given", got)
	}
	releaseSet(t, dir)
	host := filepath.Join(dir, "bin", "release", "vault-engine-"+runtime.GOOS+"-"+runtime.GOARCH)
	if _, statErr := os.Stat(host); statErr == nil {
		said, runErr := exec.Command(host).Output()
		if runErr != nil || string(said) != "vault-engine 9.9.9-explicit\n" {
			t.Fatalf("the built binary says %q (%v), want version 9.9.9-explicit", said, runErr)
		}
	}
}
