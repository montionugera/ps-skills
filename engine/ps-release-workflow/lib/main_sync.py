"""Keep the in-progress release/<v> carrying every commit on main.

A hotfix squash-merged to main while a release is open never reaches
release/<v> on its own. Anything that then runs from the release tree (Gate 1,
the local deploy, Gate 2, the promote PR) runs WITHOUT the hotfix — the local
cluster silently loses it. These helpers merge main into release/<v> in the
_release worktree, or refuse loudly with the exact manual command.

Callers MUST hold file_lock(rel_wt) around sync_main_into_release: it mutates
the shared _release worktree exactly like ship's feature merge does.
"""
import sys
from pathlib import Path

from lib.git_ops import GitError, _run as git_run


class MainSyncConflictError(Exception):
    """main could not be merged into release/<v> automatically."""


# Paths main and release/<v> legitimately disagree on (D11: backlog metadata and
# release state live on the release branch). A change to them on main must be
# reconciled by a human, never auto-merged over the release's copy.
_BOOKKEEPING_FILE = ".release.json"
_BOOKKEEPING_DIRS = (".claude/idea_backlog/", ".claude/refined_backlog/",
                     ".claude/epic_backlog/", ".claude/state/")


def resolve_main_ref(repo: Path) -> str:
    """The freshest main available: origin/main after a fetch when an origin
    exists (a PR squash-merge advances only the remote), else local main.
    A failed fetch falls back to the last-fetched origin/main."""
    repo = Path(repo)
    if git_run(repo, "remote", "get-url", "origin", check=False).returncode == 0:
        fetched = git_run(repo, "fetch", "-q", "origin", "main", check=False)
        if fetched.returncode != 0:
            print(f"⚠️  git fetch origin main failed — comparing against the last "
                  f"fetched origin/main, which may miss a just-merged hotfix: "
                  f"{fetched.stderr.strip()}", file=sys.stderr)
        if git_run(repo, "rev-parse", "--verify", "-q", "origin/main", check=False).returncode == 0:
            return "origin/main"
    return "main"


def missing_main_commits(tree: Path, main_ref: str) -> list[str]:
    """Commits on main_ref that the tree's HEAD lacks (empty = up to date)."""
    return git_run(tree, "rev-list", f"HEAD..{main_ref}").stdout.split()


def sync_main_into_release(repo: Path, rel_wt: Path, release_branch: str,
                           main_ref: str | None = None) -> int:
    """Merge main into release/<v> in rel_wt. Returns the number of main
    commits absorbed (0 = already up to date, nothing done).

    Raises MainSyncConflictError — with release/<v> left exactly as it was —
    when main touched release bookkeeping or the merge conflicts.
    """
    rel_wt = Path(rel_wt)
    main_ref = main_ref or resolve_main_ref(repo)
    missing = missing_main_commits(rel_wt, main_ref)
    if not missing:
        return 0

    manual = (f"cd {rel_wt} && git merge {main_ref}   "
              f"# resolve, commit, then re-run the psrw command")
    base = git_run(rel_wt, "merge-base", "HEAD", main_ref).stdout.strip()
    changed = git_run(rel_wt, "diff", "--name-only", base, main_ref).stdout.split()
    touched = [p for p in changed
               if p == _BOOKKEEPING_FILE or p.startswith(_BOOKKEEPING_DIRS)]
    if touched:
        raise MainSyncConflictError(
            f"{release_branch} is {len(missing)} commit(s) behind {main_ref}, but main "
            f"changed release bookkeeping, which must not be auto-merged: "
            f"{', '.join(touched)}.\nMerge by hand keeping the release's copy of those "
            f"paths: cd {rel_wt} && git merge --no-commit {main_ref}; "
            f"git checkout HEAD -- {' '.join(touched)} && git commit --no-edit"
        )

    try:
        git_run(rel_wt, "merge", "--no-ff", "--no-edit", "-m",
                f"chore(release): sync {main_ref} into {release_branch}", main_ref)
    except GitError as e:
        conflicts = git_run(rel_wt, "diff", "--name-only", "--diff-filter=U",
                            check=False).stdout.split()
        git_run(rel_wt, "merge", "--abort", check=False)
        raise MainSyncConflictError(
            f"{release_branch} is {len(missing)} commit(s) behind {main_ref} and the "
            f"merge CONFLICTS in: {', '.join(conflicts) or '(see git output)'}.\n"
            f"Nothing was shipped or deployed. Resolve by hand: {manual}\n({e})"
        ) from e
    return len(missing)
