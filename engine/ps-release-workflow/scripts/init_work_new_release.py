"""ps-release-workflow:new-release — mint release/<v> + _release worktree."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib.git_ops import add_worktree_new_branch
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

    rj_path = repo / ".release.json"
    rj = json.loads(rj_path.read_text())

    if rj.get("in_progress"):
        raise ReleaseAlreadyInProgressError(f"release/{rj['version']} still in progress")

    current = rj.get("version", "1.0")
    new_v = version or _bump_minor(current)
    if _parse_semver(new_v) <= _parse_semver(current):
        raise BadVersionError(f"new version {new_v} must be > current {current}")

    branch = f"release/{new_v}"
    worktree = repo / ".claude" / "worktrees" / "_release"
    worktree.parent.mkdir(parents=True, exist_ok=True)

    # Create release branch + worktree pinned to it.
    add_worktree_new_branch(repo, worktree, branch, "main")

    # Update .release.json on main and commit.
    rj["version"] = new_v
    rj["in_progress"] = True
    rj["started_at"] = datetime.now(timezone.utc).isoformat()
    rj["started_by"] = owner or resolve_owner_id()
    rj_path.write_text(json.dumps(rj, indent=2) + "\n")

    from lib.git_ops import commit_all
    commit_all(repo, f"chore(release): start {new_v}")

    return {"version": new_v, "branch": branch, "worktree": str(worktree)}


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
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
