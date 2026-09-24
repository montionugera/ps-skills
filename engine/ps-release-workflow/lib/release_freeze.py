"""Release freeze: from the moment promote starts, release/<v> takes no more ships.

A feature merged into release/<v> after promote pushed it (or while CI runs on
the PR) is not in the PR that merges: it is stranded, while the catalog on the
release branch says it shipped. promote freezes the release first thing and
lifts the freeze only if it fails before the PR can merge; cleanup lifts it
for good. ship refuses a frozen release under the same _release lock that
serializes its merge, so a ship either lands before the freeze or not at all.

The freeze lives in the gitignored .claude/state/ of the main checkout, so it
is host-local, like every other psrw lock.
"""
from datetime import datetime, timezone
from pathlib import Path

from lib.state import mutate_state, read_state


class ReleaseFrozenError(Exception):
    """A ship or sync-main tried to change a release that is being, or has
    been, promoted."""


def _freeze_file(repo: Path) -> Path:
    return Path(repo) / ".claude" / "state" / "release-freeze.json"


def freeze_release(repo: Path, version: str) -> None:
    def put(d: dict) -> dict:
        d.setdefault(version, {"frozen_at": datetime.now(timezone.utc).isoformat()})
        return d
    mutate_state(_freeze_file(repo), put, default={})


def unfreeze_release(repo: Path, version: str) -> None:
    if not _freeze_file(repo).exists():
        return
    def drop(d: dict) -> dict:
        d.pop(version, None)
        return d
    mutate_state(_freeze_file(repo), drop, default={})


def record_pushed_head(repo: Path, version: str, sha: str) -> None:
    """Remember the exact release head promote handed to main (pushed for the
    PR, or squashed by --direct). cleanup checks shipped features against it,
    which still works when the host auto-deletes the merged head branch."""
    def put(d: dict) -> dict:
        d.setdefault(version, {})["pushed_head"] = sha
        return d
    mutate_state(_freeze_file(repo), put, default={})


def recorded_pushed_head(repo: Path, version: str) -> str | None:
    entry = (read_state(_freeze_file(repo), default={}) or {}).get(version) or {}
    return entry.get("pushed_head")


def frozen_since(repo: Path, version: str) -> str | None:
    """ISO timestamp the release was frozen at, or None if it is not frozen."""
    entry = (read_state(_freeze_file(repo), default={}) or {}).get(version)
    return entry.get("frozen_at") if entry else None


def frozen_error(version: str, feature_id: str, why: str) -> ReleaseFrozenError:
    return ReleaseFrozenError(
        f"release/{version} is frozen ({why}). Shipping {feature_id} into it now "
        f"would strand it: it would not be in the PR that merges to main. Ship it "
        f"into the next release instead: once the {version} PR merges, run "
        f"`psrw promote --cleanup-only {version}` and `psrw new-release`, then "
        f"`psrw ship` again from this worktree."
    )
