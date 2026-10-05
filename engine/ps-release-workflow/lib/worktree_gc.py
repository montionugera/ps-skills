"""worktree_gc — Shared safety core for worktree garbage collection and teardown.

Implements safety checks S1–S8 and liveness checks L1–L3 per Thinker architectural ruling.
"""
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

from lib.catalog import find_entry, list_entries
from lib.git_ops import _run as git_run, GitError

DEFAULT_ALLOWLIST = {
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".svelte-kit",
    "target",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "coverage",
    ".turbo",
    ".DS_Store",
    ".dart_tool",
}


def get_worktree_gitdir(wt: Path) -> Optional[Path]:
    """Resolve the gitdir for a linked worktree from its .git file."""
    git_file = wt / ".git"
    if not git_file.is_file():
        return None
    try:
        content = git_file.read_text().strip()
        if content.startswith("gitdir:"):
            target = content.split("gitdir:", 1)[1].strip()
            p = Path(target)
            if not p.is_absolute():
                p = (wt / p).resolve()
            return p
    except OSError:
        pass
    return None


def get_working_feature_marker(wt: Path, gitdir: Optional[Path] = None) -> Optional[dict]:
    """Find and parse working-feature.json in gitdir or wt root."""
    search_dirs = []
    if gitdir and gitdir.exists():
        search_dirs.append(gitdir)
    search_dirs.append(wt)

    for d in search_dirs:
        marker = d / "working-feature.json"
        if marker.is_file():
            try:
                return json.loads(marker.read_text())
            except (json.JSONDecodeError, OSError):
                pass
    return None


def is_worktree_locked(repo: Path, wt: Path) -> bool:
    """Check if git worktree list --porcelain marks this worktree as locked."""
    try:
        cp = git_run(repo, "worktree", "list", "--porcelain", check=False)
        blocks = cp.stdout.strip().split("\n\n")
        wt_resolved = str(wt.resolve())
        for block in blocks:
            lines = [line.strip() for line in block.split("\n")]
            is_target = any(line.startswith("worktree ") and Path(line.split(" ", 1)[1]).resolve() == wt.resolve() for line in lines)
            if is_target:
                return any(line == "locked" or line.startswith("locked ") for line in lines)
    except Exception:
        pass
    return False


def has_running_process_in(wt: Path) -> bool:
    """L1: Return True if any active process has cwd under wt (excluding self/ancestors)."""
    try:
        cp = subprocess.run(
            ["lsof", "-a", "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        wt_str = str(wt.resolve())
        for line in cp.stdout.splitlines():
            if line.startswith("n/"):
                cwd_path = line[1:].strip()
                if cwd_path == wt_str or cwd_path.startswith(wt_str + "/"):
                    return True
    except Exception:
        pass
    return False


def is_container_mounting(wt: Path) -> bool:
    """L2: Return True if any running docker container mounts wt."""
    try:
        cp = subprocess.run(
            ["docker", "ps", "-q"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        cids = cp.stdout.strip().split()
        if not cids:
            return False
        inspect_cp = subprocess.run(
            ["docker", "inspect", "--format", "{{range .Mounts}}{{.Source}} {{end}}"] + cids,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        wt_str = str(wt.resolve())
        for mount in inspect_cp.stdout.split():
            if mount == wt_str or mount.startswith(wt_str + "/"):
                return True
    except Exception:
        pass
    return False


def is_modified_recently(wt: Path, gitdir: Optional[Path], idle_seconds: float) -> bool:
    """L3: Return True if any file in gitdir or tracked tree was modified recently."""
    now = time.time()
    cutoff = now - idle_seconds

    # Check gitdir
    if gitdir and gitdir.exists():
        try:
            for root, _, files in os.walk(gitdir):
                for f in files:
                    fp = os.path.join(root, f)
                    if os.path.getmtime(fp) > cutoff:
                        return True
        except OSError:
            pass

    # Check wt mtime
    try:
        if os.path.getmtime(wt) > cutoff:
            return True
    except OSError:
        pass

    return False


def removable(
    repo: Path,
    wt: Path,
    *,
    catalog_entries: Optional[list] = None,
    idle_window_hours: float = 24.0,
    skip_liveness: bool = False,
    allowlist: Optional[set] = None,
) -> Tuple[bool, str]:
    """Evaluate all S1–S8 and L1–L3 safety checks.

    Returns (True, "removable") or (False, "<named refusal reason>").
    """
    repo = Path(repo).resolve()
    wt = Path(wt).resolve()
    effective_allowlist = allowlist or DEFAULT_ALLOWLIST

    # S1: Identity
    if wt.name == "_release":
        return False, "S1: identity is _release worktree"
    if wt == repo:
        return False, "S1: path is main repository checkout"
    expected_parent = (repo / ".claude" / "worktrees").resolve()
    if wt.parent.resolve() != expected_parent:
        return False, f"S1: path is not directly under {expected_parent}"

    # Gitdir & Marker check
    gitdir = get_worktree_gitdir(wt)
    if not gitdir or not gitdir.exists():
        return False, "S1: cannot resolve linked worktree gitdir"

    marker = get_working_feature_marker(wt, gitdir)
    if not marker or not marker.get("feature"):
        return False, "S2: missing or invalid working-feature.json marker"

    feature_id = marker["feature"]

    # S2: Catalog Status
    # Look up catalog in _release worktree first, then repo root
    release_cat = repo / ".claude" / "worktrees" / "_release" / ".claude" / "refined_backlog" / "_catalog.json"
    root_cat = repo / ".claude" / "refined_backlog" / "_catalog.json"

    entry = None
    if catalog_entries:
        for e in catalog_entries:
            if e.get("id") == feature_id:
                entry = e
                break
    if not entry and release_cat.is_file():
        entry = find_entry(release_cat, feature_id)
    if not entry and root_cat.is_file():
        entry = find_entry(root_cat, feature_id)

    if not entry:
        return False, f"S2: feature {feature_id} not found in catalog"

    status = entry.get("status")
    if status not in ("shipped", "promoted"):
        return False, f"S2: feature {feature_id} status is '{status}' (must be shipped or promoted)"

    # S3: Nothing beyond what shipped
    shipped_sha = entry.get("shipped_sha")
    if not shipped_sha:
        return False, f"S3: feature {feature_id} missing shipped_sha in catalog"

    try:
        cp_ahead = git_run(wt, "rev-list", "--count", f"{shipped_sha}..HEAD", check=False)
        if cp_ahead.returncode != 0:
            return False, f"S3: cannot verify commit ancestry against shipped_sha {shipped_sha[:8]}"
        ahead_count = int(cp_ahead.stdout.strip())
        if ahead_count > 0:
            return False, f"S3: worktree HEAD has {ahead_count} unpushed/unshipped commit(s) beyond shipped_sha"
    except Exception as e:
        return False, f"S3: git error checking ancestry: {e}"

    # S4: Tracked and untracked clean
    try:
        cp_status = git_run(wt, "status", "--porcelain", "--untracked-files=all", check=False)
        if cp_status.stdout.strip():
            return False, "S4: worktree has uncommitted tracked or untracked changes"
    except Exception as e:
        return False, f"S4: error checking git status: {e}"

    # S5: Ignored files regenerable
    try:
        cp_ignored = git_run(wt, "status", "--porcelain", "--ignored", check=False)
        for line in cp_ignored.stdout.splitlines():
            line = line.strip()
            if line.startswith("!! "):
                rel_path = line[3:].strip()
                top_part = rel_path.split("/", 1)[0]
                if top_part not in effective_allowlist and rel_path not in effective_allowlist:
                    return False, f"S5: non-allowlisted ignored file present: {rel_path}"
    except Exception as e:
        return False, f"S5: error checking ignored files: {e}"

    # S6: No operation in progress
    op_indicators = ["MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "BISECT_LOG", "AUTO_MERGE"]
    for op in op_indicators:
        if (gitdir / op).exists():
            return False, f"S6: git operation in progress ({op} exists)"

    # S7: Not pinned / locked
    if is_worktree_locked(repo, wt):
        return False, "S7: worktree is locked (pinned by user/system)"

    # S8: Attached HEAD
    try:
        cp_head = git_run(wt, "symbolic-ref", "-q", "HEAD", check=False)
        if cp_head.returncode != 0:
            return False, "S8: worktree has detached HEAD"
    except Exception as e:
        return False, f"S8: error checking symbolic-ref: {e}"

    # Liveness checks (L1, L2, L3)
    if not skip_liveness:
        # L1: Process cwd
        if has_running_process_in(wt):
            return False, "L1: an active process has its current working directory inside worktree"

        # L2: Container mount
        if is_container_mounting(wt):
            return False, "L2: an active container mounts this worktree"

        # L3: Idle window
        if idle_window_hours > 0:
            idle_seconds = idle_window_hours * 3600.0
            if is_modified_recently(wt, gitdir, idle_seconds):
                return False, f"L3: worktree modified within idle window ({idle_window_hours}h)"

    return True, "removable"
