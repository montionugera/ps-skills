#!/usr/bin/env python3
"""PreToolUse hook entry point. Blocks code edits outside claimed worktrees.

Hook invocation: receives JSON payload on stdin with tool_name + tool_input.
Exit 0 = allow, exit 2 = block (Claude Code's PreToolUse blocking code; stderr is
fed back to the model). Any other non-zero is a NON-blocking error in Claude Code,
so BLOCK must be 2 — not 1 — or the guard would silently allow the edit.
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import enum
import json
import os
import sys
from pathlib import Path

from lib.owner import self_ids
from lib.repo import find_repo_root, is_ps_release_workflow_repo, RepoNotFoundError


class ExitCode(enum.IntEnum):
    ALLOW = 0
    BLOCK = 2  # Claude Code PreToolUse: exit 2 blocks; 1/other are non-blocking errors


# Tool names that mutate the working tree.
MUTATING_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "write_file", "replace"}  # + Gemini CLI tool names


def _find_target_path(tool_call: dict) -> Path | None:
    tn = tool_call.get("tool_name", "")
    ti = tool_call.get("tool_input", {}) or {}
    if tn in MUTATING_TOOLS:
        # NotebookEdit sends `notebook_path`, everything else `file_path`.
        fp = ti.get("file_path") or ti.get("notebook_path")
        if fp:
            return Path(fp)
    return None


def _containing_worktree(target: Path) -> tuple[Path | None, str | None]:
    """Find the nearest ancestor dir of `target` containing a `.git` entry.

    Walks up from `target` (or `target.parent` if it doesn't exist yet). Returns
    (worktree_dir, kind) where kind is "dir" (a real .git directory → MAIN
    working tree) or "file" (a .git pointer file → linked worktree). Returns
    (None, None) if no `.git` ancestor exists (outside any repo).
    """
    cur = (target if target.exists() else target.parent).resolve()
    while True:
        git = cur / ".git"
        if git.is_dir():
            return (cur, "dir")
        if git.is_file():
            return (cur, "file")
        if cur.parent == cur:
            return (None, None)
        cur = cur.parent


def _read_marker(worktree: Path) -> dict | None:
    """Read .git/worktrees/<id>/working-feature.json for this worktree."""
    git_pointer = worktree / ".git"
    if git_pointer.is_file():
        content = git_pointer.read_text().strip()
        try:
            gitdir = Path(content.split("gitdir:", 1)[1].strip())
            marker = gitdir / "working-feature.json"
            if marker.exists():
                return json.loads(marker.read_text())
        except (IndexError, json.JSONDecodeError):
            pass
    return None


def check_tool_call(tool_call: dict) -> ExitCode:
    # Scripted bypass for the toolkit's own scripts.
    if os.environ.get("PS_RELEASE_WORKFLOW_SCRIPTED") == "1":
        return ExitCode.ALLOW

    target = _find_target_path(tool_call)
    if target is None:
        return ExitCode.ALLOW  # not a mutating call we care about

    # Find the worktree that contains `target` and whether it's the main working
    # tree (.git dir) or a linked worktree (.git pointer file).
    wt_root, kind = _containing_worktree(target)
    if wt_root is None:
        return ExitCode.ALLOW  # outside any git repo

    # Resolve to the *main* repo root (find_repo_root follows worktree pointers).
    try:
        main_root = find_repo_root(target.parent if not target.exists() else target)
    except RepoNotFoundError:
        return ExitCode.ALLOW

    if not is_ps_release_workflow_repo(main_root):
        return ExitCode.ALLOW

    if kind == "dir":
        # Edit in the MAIN working tree of an opted-in repo — block.
        print(f"BLOCKED: {target} is on main of a ps-release-workflow repo. "
              "Claim a feature first: psrw claim --next", file=sys.stderr)
        return ExitCode.BLOCK

    # Linked worktree.
    if wt_root.name == "_release":
        # Toolkit-managed release worktree — allow silently, no warning.
        return ExitCode.ALLOW

    marker = _read_marker(wt_root)
    if marker is None:
        print(f"WARN: {wt_root} is an unmanaged/legacy worktree (no marker). Allowing.", file=sys.stderr)
        return ExitCode.ALLOW

    # A session may be known by several ids: the hook payload's session_id,
    # $CLAUDE_SESSION_ID, and the machine-cached fallback id (historically the
    # id all claims were created with). Owner matching ANY of them → allow.
    # generate=False: the guard is a READ path — with no identity anywhere it
    # judges anonymously (empty set → mismatch → block) rather than persisting
    # a fresh id as a side effect.
    ids = self_ids(payload_session_id=tool_call.get("session_id"), generate=False)
    if marker.get("owner") not in ids:
        print(f"BLOCKED: {wt_root} is claimed by {marker.get('owner')!r}, "
              f"not you ({sorted(ids)!r}). "
              "If this is your feature from a previous session: "
              "psrw claim --resume F-NNN "
              "(F id from the worktree's working-feature.json). "
              "Otherwise pick different work: psrw claim --next",
              file=sys.stderr)
        return ExitCode.BLOCK

    return ExitCode.ALLOW


def _under_workflow_repo(target: Path) -> bool:
    """Crash-fallback check: walk up from `target` (or its nearest existing
    ancestor) looking for a .release.json. Deliberately dumb — no git logic —
    so it cannot itself fail for the reasons the main path might have."""
    try:
        cur = target if target.exists() else target.parent
        cur = cur.resolve()
        while True:
            if (cur / ".release.json").is_file():
                return True
            if cur.parent == cur:
                return False
            cur = cur.parent
    except OSError:
        return False


def main() -> int:
    """Fail-open wrapper: an unexpected exception must never exit 1, which
    Claude Code treats as a NON-blocking error (i.e. the edit would proceed).

    Policy:
    - unparseable stdin JSON → allow (exit 0) with a stderr warning;
    - crash after the target path is known → block (exit 2) if the target sits
      under a workflow repo (.release.json ancestor), else allow with warning;
    - crash before the target path is known → allow with warning.
    """
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"guard: unparseable stdin JSON ({e}); allowing", file=sys.stderr)
        return int(ExitCode.ALLOW)

    target: Path | None = None
    try:
        target = _find_target_path(payload)
        return int(check_tool_call(payload))
    except Exception as e:  # noqa: BLE001 — deliberate catch-all, see docstring
        if target is not None and _under_workflow_repo(target):
            print(f"guard crashed, blocking edit in workflow repo: {e!r}", file=sys.stderr)
            return int(ExitCode.BLOCK)
        print(f"guard: crashed ({e!r}); target not in a workflow repo, allowing", file=sys.stderr)
        return int(ExitCode.ALLOW)


if __name__ == "__main__":
    sys.exit(main())
