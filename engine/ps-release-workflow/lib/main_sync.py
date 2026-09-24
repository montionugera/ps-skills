"""Main sync primitive: absorbs main (including squash-merged hotfixes) into release/<v>."""
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from lib.git_ops import (
    GitError,
    _run as git_run,
    diff_names,
    has_origin,
    is_ancestor,
    is_dirty,
    rev_count,
    rev_parse,
    unmerged_files,
)


PROTECTED_PREFIXES = (
    ".release.json",
    ".claude/idea_backlog",
    ".claude/refined_backlog",
    ".claude/epic_backlog",
    ".claude/state",
)


def _is_protected(path: str) -> bool:
    norm = path.replace("\\", "/")
    if norm.startswith("./"):
        norm = norm[2:]
    return any(norm == p or norm.startswith(f"{p}/") for p in PROTECTED_PREFIXES)


@dataclass
class MainSyncResult:
    synced: bool
    main_sha: Optional[str]
    source: str
    behind: int
    files: list[str]


class MainSyncError(RuntimeError):
    """Base error for main sync failures."""


class MainSyncConflictError(MainSyncError):
    def __init__(self, conflicted_files: list[str], main_sha: str, base_sha: str):
        self.conflicted_files = conflicted_files
        self.main_sha = main_sha
        self.base_sha = base_sha
        files_str = ", ".join(conflicted_files) if conflicted_files else "unknown"
        super().__init__(
            f"Merge conflict while syncing main@{main_sha[:12]} (base {base_sha[:12]}): {files_str}"
        )


class ProtectedPathSyncError(MainSyncError):
    def __init__(self, protected_files: list[str], main_sha: str):
        self.protected_files = protected_files
        self.main_sha = main_sha
        files_str = ", ".join(protected_files)
        super().__init__(
            f"main@{main_sha[:12]} modified protected D11 release paths: {files_str}"
        )


class MainUnreachableError(MainSyncError):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"Cannot reach origin/main: {detail}")


def resolve_main_sha(repo: Path, *, strict: bool = False) -> tuple[str, str]:
    """Fetch origin main (if origin exists) and return (pinned_sha, source label).

    Never touches the main checkout's working tree or index.
    """
    repo = Path(repo).resolve()
    if not has_origin(repo):
        return rev_parse(repo, "main"), "main (no origin)"

    cp = git_run(repo, "fetch", "origin", "main", check=False)
    if cp.returncode != 0:
        if strict:
            err = (cp.stderr or cp.stdout or "").strip()
            raise MainUnreachableError(err or "git fetch origin main exited non-zero")
        print("⚠️ fetch origin main failed — syncing from last-known origin/main", file=sys.stderr)
        try:
            return rev_parse(repo, "origin/main"), "origin/main (stale: fetch failed)"
        except Exception as e:
            if strict:
                raise MainUnreachableError(f"origin/main ref not found: {e}") from e
            return rev_parse(repo, "main"), "main (fetch failed, fell back to local)"

    return rev_parse(repo, "origin/main"), "origin/main"


def sync_main_into_release(
    repo: Path,
    rel_wt: Path,
    release_branch: str,
    main_sha: str,
    source: str,
) -> MainSyncResult:
    """CALLER MUST HOLD file_lock(rel_wt).

    Merges main_sha into rel_wt if not already contained.
    On failure or conflict, the tree is cleanly restored with git merge --abort.
    """
    rel_wt = Path(rel_wt).resolve()
    if is_dirty(rel_wt):
        raise RuntimeError(f"_release worktree {rel_wt} has uncommitted changes")

    # If main_sha is already reachable from release HEAD, nothing to do
    if is_ancestor(rel_wt, main_sha, "HEAD"):
        return MainSyncResult(
            synced=False,
            main_sha=main_sha,
            source=source,
            behind=0,
            files=[],
        )

    base_sha = git_run(rel_wt, "merge-base", "HEAD", main_sha).stdout.strip()
    changed_files = diff_names(rel_wt, base_sha, main_sha)

    # Protect D11 state files
    protected_hits = [f for f in changed_files if _is_protected(f)]
    if protected_hits:
        raise ProtectedPathSyncError(protected_hits, main_sha)

    behind_count = rev_count(rel_wt, f"HEAD..{main_sha}")

    # Perform the merge with --no-ff
    cp = git_run(
        rel_wt,
        "merge",
        "--no-ff",
        "--no-edit",
        "-m",
        f"chore(release): sync main@{main_sha[:12]} into {release_branch}",
        main_sha,
        check=False,
    )

    if cp.returncode != 0:
        conflicted = unmerged_files(rel_wt)
        git_run(rel_wt, "merge", "--abort", check=False)
        raise MainSyncConflictError(conflicted, main_sha, base_sha)

    return MainSyncResult(
        synced=True,
        main_sha=main_sha,
        source=source,
        behind=behind_count,
        files=changed_files,
    )


def render_sync_failure(err: Exception, release_branch: str, feature_id: str) -> str:
    rel_name = release_branch.split("/")[-1]
    if isinstance(err, MainSyncConflictError):
        conflicted = ", ".join(err.conflicted_files) if err.conflicted_files else "unknown"
        return (
            f"release/{rel_name} cannot absorb main@{err.main_sha[:12]} automatically.\n"
            f"   Conflicting files: {conflicted}\n"
            f"   Nothing was merged; {feature_id} remains claimed and unshipped.\n"
            f"   Resolve once, by hand, in the _release worktree:\n"
            f"     cd .claude/worktrees/_release\n"
            f"     git merge --no-ff {err.main_sha}\n"
            f"     ./scripts/precheck.sh\n"
            f"   Then re-run: psrw ship"
        )
    if isinstance(err, ProtectedPathSyncError):
        hits = ", ".join(err.protected_files)
        return (
            f"main@{err.main_sha[:12]} modified protected release backlog paths: {hits}\n"
            f"   Automatic sync refused to prevent corrupting release state.\n"
            f"   Inspect main's commits and reconcile manually."
        )
    return f"Main sync failed: {err}"
