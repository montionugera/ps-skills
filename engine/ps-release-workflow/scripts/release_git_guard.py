#!/usr/bin/env python3
"""PreToolUse (Bash) guard: no hand-run git writes on a release/<v> branch.

Only psrw puts code on release/<v>: `psrw ship` and `psrw sync-main` run Gate 1,
update the catalog and run the local deploy (which, in joy-companion, installs the
Mac app). A hand-run `git merge` skips all three. psrw runs its own git as a child
process, which this hook never sees, so psrw keeps working.

Blocks (exit 2) a Bash command that runs `git merge|commit|cherry-pick|rebase|revert|
reset|pull|am` in a checkout whose branch is release/* and whose top level has
.release.json. The directory is taken from `git -C <dir>`, else the last `cd <dir>`
before it, else the hook's cwd. `--abort`/`--quit` are allowed (cleaning up a
conflict psrw left). Escape hatch, for the exact command psrw itself prints after a
conflict: put PSRW_ALLOW_RELEASE_GIT=1 in the command.

Anything unparseable is allowed: a Bash guard that fails closed would block every
command on this machine.
"""
import json
import os
import re
import shlex
import subprocess
import sys

WRITES = {"merge", "commit", "cherry-pick", "rebase", "revert", "reset", "pull", "am"}
CLEANUP = {"--abort", "--quit"}
ESCAPE = "PSRW_ALLOW_RELEASE_GIT=1"
# git global options that take a value as the next word.
VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


def segments(command: str):
    """Split a shell command on && || ; | and newlines; each part as shlex words."""
    for part in re.split(r"&&|\|\||[;|\n]", command):
        try:
            words = shlex.split(part)
        except ValueError:
            continue
        if words:
            yield words


def git_writes(command: str, cwd: str):
    """Yield (subcommand, directory) for every git write in the command."""
    here = cwd
    for words in segments(command):
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]  # leading VAR=value assignments
        if not words:
            continue
        if words[0] == "cd" and len(words) > 1:
            here = os.path.join(here, os.path.expanduser(words[1]))
            continue
        if os.path.basename(words[0]) != "git":
            continue
        target, i = here, 1
        while i < len(words) and words[i].startswith("-"):
            opt = words[i]
            if opt in VALUE_OPTS and i + 1 < len(words):
                if opt == "-C":
                    target = os.path.join(target, os.path.expanduser(words[i + 1]))
                i += 2
            else:
                i += 1
        if i < len(words) and words[i] in WRITES and not CLEANUP & set(words[i + 1:]):
            yield words[i], target


def release_branch(directory: str):
    """The release/* branch checked out in an opted-in repo at directory, else None."""
    def git(*args):
        r = subprocess.run(["git", "-C", directory, *args], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if not branch.startswith("release/"):
        return None
    top = git("rev-parse", "--show-toplevel")
    return branch if top and os.path.isfile(os.path.join(top, ".release.json")) else None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    command = (data.get("tool_input") or {}).get("command") or ""
    if "git" not in command or ESCAPE in command:
        return 0
    cwd = data.get("cwd") or os.getcwd()
    for sub, directory in git_writes(command, cwd):
        try:
            branch = release_branch(directory)
        except (OSError, subprocess.SubprocessError):
            continue
        if branch:
            print(
                f"BLOCKED: hand-run `git {sub}` on {branch} ({directory}).\n"
                "Only psrw puts code on a release branch, because it also runs Gate 1, the catalog "
                "and the local deploy (the Mac app install in joy-companion).\n"
                "- A claimed feature: `psrw ship` from its worktree.\n"
                "- Unplanned work: idea, refine, claim, then `psrw ship`; or a hotfix PR to main, "
                "then `psrw sync-main`.\n"
                f"- Only for the exact command psrw printed after a conflict: add {ESCAPE} to it.",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
