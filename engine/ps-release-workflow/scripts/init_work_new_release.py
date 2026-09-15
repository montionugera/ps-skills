"""ps-release-workflow:new-release — mint release/<v> + _release worktree."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib.backlog_paths import read_release_state
from lib.git_ops import add_worktree_new_branch, commit_all, fetch_and_ff_main
from lib.owner import resolve_owner_id
from lib.repo import find_repo_root, is_ps_release_workflow_repo


class ReleaseAlreadyInProgressError(Exception): pass
class BadVersionError(Exception): pass


def _parse_semver(v: str) -> tuple[int, int]:
    parts = v.split(".")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise BadVersionError(f"version {v} must be MAJOR.MINOR (e.g. 1.1)")
    return int(parts[0]), int(parts[1])


def _bump_minor(v: str) -> str:
    maj, min = _parse_semver(v)
    return f"{maj}.{min + 1}"


def new_release(repo: Path, version: Optional[str] = None, owner: Optional[str] = None) -> dict:
    repo = Path(repo)
    if not is_ps_release_workflow_repo(repo):
        raise RuntimeError(f"{repo} not opted into ps-release-workflow")

    # In-progress detection: the _release worktree's .release.json is the source
    # of truth (fix #2), NOT main's flag — new_release no longer writes to main.
    if read_release_state(repo) is not None:
        raise ReleaseAlreadyInProgressError("a release is already in progress")

    # main's .release.json carries the LAST-PROMOTED state — use it to pick the
    # next version, but never write to it here.
    rj = json.loads((repo / ".release.json").read_text())
    current = rj.get("version", "1.0")
    new_v = version or _bump_minor(current)
    if _parse_semver(new_v) <= _parse_semver(current):
        raise BadVersionError(f"new version {new_v} must be > current {current}")

    branch = f"release/{new_v}"
    worktree = repo / ".claude" / "worktrees" / "_release"
    worktree.parent.mkdir(parents=True, exist_ok=True)

    # Sync local main to origin/main first: PR-based promote advances only the
    # remote, so a stale local main would branch the release from a base missing
    # the just-promoted release (the F-189/release-1.14 incident). Raises on a
    # diverged local main rather than silently cutting from the wrong base.
    fetch_and_ff_main(repo)

    # Create release branch + worktree pinned to it (now from an up-to-date main).
    add_worktree_new_branch(repo, worktree, branch, "main")

    # Write the start-state on the RELEASE BRANCH (in the _release worktree), NOT
    # main (fix #2). This keeps the PR squash the sole writer of main, so local
    # main never carries an unpushed start commit that diverges from origin.
    rel_rj_path = worktree / ".release.json"
    rel_rj = json.loads(rel_rj_path.read_text())
    rel_rj["version"] = new_v
    rel_rj["in_progress"] = True
    rel_rj["started_at"] = datetime.now(timezone.utc).isoformat()
    rel_rj["started_by"] = owner or resolve_owner_id()
    rel_rj_path.write_text(json.dumps(rel_rj, indent=2) + "\n")
    commit_all(worktree, f"chore(release): start {new_v}")

    return {"version": new_v, "branch": branch, "worktree": str(worktree)}


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="psrw new-release",
        description="Open release/<v> and its long-lived _release worktree.",
    )
    p.add_argument("--version", default=None)
    args = p.parse_args()
    repo = find_repo_root(Path.cwd())
    try:
        result = new_release(repo, version=args.version)
    except (ReleaseAlreadyInProgressError, BadVersionError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}))
    print(f"\n✅ Started release {result['version']} (branch: {result['branch']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
