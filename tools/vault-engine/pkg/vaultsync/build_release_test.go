package vaultsync

import (
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"testing"
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

func commitAll(t *testing.T, dir, msg string) {
	t.Helper()
	mustGit(t, dir, "add", "-A")
	mustGit(t, dir, "commit", "--quiet", "-m", msg)
}

func runBuild(t *testing.T, dir string) (string, error) {
	t.Helper()
	cmd := exec.Command("bash", filepath.Join(dir, "scripts", "build-release.sh"))
	cmd.Env = os.Environ()
	for _, drop := range []string{"VERSION", "GOOS", "GOARCH", "GOFLAGS"} {
		cmd.Env = append(cmd.Env, drop+"=")
	}
	out, err := cmd.CombinedOutput()
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
	sums, _ := os.ReadFile(filepath.Join(rel, "SHA256SUMS"))
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
	out, err = runBuild(t, dir)
	if err == nil || !strings.Contains(out, "does not carry version") {
		t.Fatalf("a build whose stamp did not take must fail and say so: err=%v\n%s", err, out)
	}
	if got := releaseSet(t, dir); got != dirtySums {
		t.Fatalf("a failed build changed the release set")
	}
}
