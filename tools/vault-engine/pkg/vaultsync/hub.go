package vaultsync

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const zeroSHA = "0000000000000000000000000000000000000000"

// hubFault labels a refusal that is the hub's own fault: it could not read or
// compute something (settings, git's own input, a git command, the usage
// ledger). The send is still refused, but the place reports it as an engine
// error (exit 1), not as a size or type limit, which would tell an agent not
// to retry. Rules the sender broke keep "too-large" / "type-not-allowed".
const hubFault = "engine-error"

// hubGit runs git inside the hook: cwd is the bare repository and the
// environment (including git's quarantine variables) is inherited untouched.
func hubGit(stdin string, args ...string) (string, error) {
	cmd := exec.Command("git", args...)
	cmd.Stdin = strings.NewReader(stdin)
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("git %s: %w: %s", args[0], err, strings.TrimSpace(errb.String()))
	}
	return out.String(), nil
}

// batchCheck feeds input to `git cat-file --batch-check=<format>` (format is
// "<word> <size>") and calls visit for each output line. A git failure or an
// unparseable line is the hub's own fault and is refused as hubFault; a
// non-empty code returned by visit stops the scan and is returned as the refusal.
func batchCheck(input, format, gitFail string, visit func(word string, size int64) (code, msg string)) (string, string) {
	out, err := hubGit(input, "cat-file", "--batch-check="+format)
	if err != nil {
		return hubFault, fmt.Sprintf("%s: %v", gitFail, err)
	}
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		f := strings.Fields(line)
		if len(f) != 2 {
			return hubFault, "incoming object cannot be measured: " + line
		}
		n, err := strconv.ParseInt(f[1], 10, 64)
		if err != nil { // git prints "<name> missing" for an object it does not have
			return hubFault, "incoming object cannot be measured: " + line
		}
		if code, msg := visit(f[0], n); code != "" {
			return code, msg
		}
	}
	return "", ""
}

// PreReceive is the hub's door check. It returns the hook's exit code. Every
// refusal is one line: "vault-hub: REFUSED <code>: <message>", where <code> is
// "too-large" or "type-not-allowed" for a broken rule (the message names the
// limit) and hubFault for a fault of the hub itself.
func PreReceive(stdin io.Reader, stderr io.Writer, limitsFile, place string, now time.Time) int {
	refuse := func(code, format string, a ...interface{}) int {
		fmt.Fprintf(stderr, "vault-hub: REFUSED %s: %s\n", code, fmt.Sprintf(format, a...))
		return 1
	}
	l, err := LoadLimits(limitsFile)
	if err != nil {
		return refuse(hubFault, "hub settings unreadable: %v", err)
	}
	if !placeRegex.MatchString(place) {
		return refuse("type-not-allowed", "sender identity missing or invalid (VAULT_HUB_PLACE=%q)", place)
	}

	type entry struct{ path, sha string }
	var entries []entry
	var tips []string
	paths := map[string]bool{}
	sizes := map[string]int64{}

	sc := bufio.NewScanner(stdin)
	for sc.Scan() {
		f := strings.Fields(sc.Text())
		if len(f) != 3 {
			return refuse(hubFault, "cannot read the update line %q; expected <old> <new> <ref>", sc.Text())
		}
		oldSHA, newSHA, ref := f[0], f[1], f[2]
		if ref != l.Ref {
			return refuse("type-not-allowed", "%s is not accepted; only ref=%s", ref, l.Ref)
		}
		if newSHA == zeroSHA {
			return refuse("type-not-allowed", "deleting %s is never accepted", ref)
		}
		if oldSHA != zeroSHA {
			// git exits 1 for a clear "not an ancestor"; any other failure is no
			// answer at all, so it is the hub's own fault (still refused).
			if _, err := hubGit("", "merge-base", "--is-ancestor", oldSHA, newSHA); err != nil {
				var ee *exec.ExitError
				if errors.As(err, &ee) && ee.ExitCode() == 1 {
					return refuse("type-not-allowed", "rewriting the history of %s is never accepted", ref)
				}
				return refuse(hubFault, "cannot check that %s only moves forward: %v", ref, err)
			}
		}
		tips = append(tips, newSHA)
		commits, err := hubGit("", "rev-list", newSHA, "--not", "--all")
		if err != nil {
			return refuse(hubFault, "cannot list incoming commits: %v", err)
		}
		for _, c := range strings.Fields(commits) {
			raw, err := hubGit("", "diff-tree", "-r", "--root", "-m", "--no-renames", "--no-commit-id", "--raw", "-z", c)
			if err != nil {
				return refuse(hubFault, "cannot read commit %s: %v", c, err)
			}
			rec := strings.Split(raw, "\x00")
			for i := 0; i+1 < len(rec); i += 2 {
				meta := strings.Fields(rec[i]) // :oldmode newmode oldsha newsha status
				if len(meta) < 5 {
					return refuse(hubFault, "cannot read a file record of commit %s: %q", c, rec[i])
				}
				if meta[4] == "D" {
					continue
				}
				if meta[1] != "100644" && meta[1] != "100755" {
					return refuse("type-not-allowed", "%s is not a regular file (mode %s)", rec[i+1], meta[1])
				}
				entries = append(entries, entry{rec[i+1], meta[3]})
				paths[rec[i+1]] = true
				sizes[meta[3]] = 0
			}
		}
	}

	if err := sc.Err(); err != nil {
		return refuse(hubFault, "cannot read the list of updated refs: %v", err)
	}
	if len(paths) > l.MaxFilesPerPush {
		return refuse("too-large", "the send changes %d files; limit max_files_per_push=%d", len(paths), l.MaxFilesPerPush)
	}
	if len(sizes) > 0 {
		var in strings.Builder
		for sha := range sizes {
			in.WriteString(sha + "\n")
		}
		if code, msg := batchCheck(in.String(), "%(objectname) %(objectsize)", "cannot measure incoming files",
			func(name string, n int64) (string, string) { sizes[name] = n; return "", "" }); code != "" {
			return refuse(code, "%s", msg)
		}
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].path < entries[j].path })
	for _, e := range entries {
		if v := l.CheckFile(e.path, sizes[e.sha]); v != nil {
			return refuse(v.Code, "%s", v.Message)
		}
	}
	// The allowance counts everything the send adds: file contents, commit
	// records (with their messages) and folder records. Counting only file
	// contents would let data hide in a commit message.
	var total int64
	if len(tips) > 0 {
		listed, err := hubGit("", append(append([]string{"rev-list", "--objects"}, tips...), "--not", "--all")...)
		if err != nil {
			return refuse(hubFault, "cannot list incoming objects: %v", err)
		}
		var in strings.Builder
		for _, line := range strings.Split(listed, "\n") {
			if f := strings.Fields(line); len(f) > 0 {
				in.WriteString(f[0] + "\n")
			}
		}
		if code, msg := batchCheck(in.String(), "%(objecttype) %(objectsize)", "cannot measure the send",
			func(typ string, n int64) (string, string) {
				if typ != "blob" && n > l.MaxFileBytes {
					return "too-large", fmt.Sprintf("a %s record in this send is %d bytes (commit message or folder listing); limit max_file_bytes=%d", typ, n, l.MaxFileBytes)
				}
				total += n
				return "", ""
			}); code != "" {
			return refuse(code, "%s", msg)
		}
	}
	usageDir := filepath.Join(filepath.Dir(limitsFile), "..", "vault-usage")
	used, ok, err := chargeDaily(usageDir, place, now, total, l.DailyBytesPerPlace)
	if err != nil {
		return refuse(hubFault, "daily allowance cannot be recorded: %v", err)
	}
	if !ok {
		return refuse("too-large", "place %s has sent %d bytes today and this send adds %d; limit daily_bytes_per_place=%d",
			place, used, total, l.DailyBytesPerPlace)
	}
	return 0
}

// chargeDaily adds bytes to the place's count for the UTC day, unless that
// would pass the limit. One place going over never affects another place.
func chargeDaily(dir, place string, now time.Time, add, limit int64) (int64, bool, error) {
	if err := os.MkdirAll(dir, 0755); err != nil {
		return 0, false, err
	}
	guard, err := os.OpenFile(filepath.Join(dir, "usage.guard"), os.O_CREATE|os.O_RDWR, 0644)
	if err != nil {
		return 0, false, err
	}
	defer guard.Close()
	if err := syscall.Flock(int(guard.Fd()), syscall.LOCK_EX); err != nil {
		return 0, false, err
	}
	file := filepath.Join(dir, now.UTC().Format("2006-01-02")+".json")
	usage := map[string]int64{}
	data, err := os.ReadFile(file)
	switch {
	case err == nil:
		if err := json.Unmarshal(data, &usage); err != nil {
			return 0, false, fmt.Errorf("usage file %s unreadable: %w", file, err)
		}
	case !errors.Is(err, fs.ErrNotExist):
		return 0, false, fmt.Errorf("reading usage file %s: %w", file, err)
	}
	if usage[place]+add > limit {
		return usage[place], false, nil
	}
	usage[place] += add
	data, err = json.Marshal(usage)
	if err != nil {
		return 0, false, err
	}
	tmp := file + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0644)
	if err != nil {
		return 0, false, err
	}
	_, werr := f.Write(data)
	if serr := f.Sync(); werr == nil {
		werr = serr
	}
	if cerr := f.Close(); werr == nil {
		werr = cerr
	}
	if werr != nil {
		return 0, false, fmt.Errorf("writing usage file %s: %w", tmp, werr)
	}
	return usage[place], true, os.Rename(tmp, file)
}
