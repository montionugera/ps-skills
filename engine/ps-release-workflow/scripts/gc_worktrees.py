"""ps-release-workflow:gc — Garbage collect and prune merged feature worktrees."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import argparse
import json
import subprocess
import sys
from pathlib import Path

from lib.git_ops import _run as git_run, GitError
from lib.release_freeze import is_release_frozen
from lib.repo import find_repo_root, is_ps_release_workflow_repo
from lib.state import file_lock, mutate_state
from lib.worktree_gc import (
    get_working_feature_marker,
    get_worktree_gitdir,
    removable,
)


def _worktree_size_kb(wt: Path) -> int:
    try:
        cp = subprocess.run(["du", "-sk", str(wt)], capture_output=True, text=True, check=False)
        if cp.returncode == 0 and cp.stdout.strip():
            return int(cp.stdout.split()[0])
    except Exception:
        pass
    return 0


def collect_worktree_status(repo: Path, force: bool = False, idle_window_hours: float = 24.0) -> list[dict]:
    wt_root = repo / ".claude" / "worktrees"
    if not wt_root.is_dir():
        return []

    results = []
    for wt in sorted(wt_root.iterdir()):
        if not wt.is_dir() or wt.name == "_release":
            continue

        gitdir = get_worktree_gitdir(wt)
        marker = get_working_feature_marker(wt, gitdir)
        feature_id = marker.get("feature") if marker else None

        ok, reason = removable(
            repo,
            wt,
            idle_window_hours=idle_window_hours,
            skip_liveness=False,
        )

        verdict = "keep"
        forced = False

        if ok:
            verdict = "remove"
        else:
            # Check if --force overrides S4, S5, or L3
            overridable = any(reason.startswith(prefix) for prefix in ("S4:", "S5:", "L3:"))
            if force and overridable:
                verdict = "remove"
                forced = True
            elif not marker:
                verdict = "unknown"

        size_kb = _worktree_size_kb(wt)

        results.append({
            "path": str(wt),
            "name": wt.name,
            "feature": feature_id,
            "verdict": verdict,
            "reason": reason if not ok else "all safety checks passed",
            "forced": forced,
            "size_kb": size_kb,
        })
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="psrw gc",
        description="Garbage collect and prune merged feature worktrees (report by default).",
    )
    parser.add_argument("--apply", action="store_true", help="Execute removal of eligible worktrees.")
    parser.add_argument("--dry-run", action="store_true", help="Report only (default).")
    parser.add_argument("--force", action="store_true", help="Override S4 (uncommitted), S5 (ignored), L3 (idle) checks.")
    parser.add_argument("--idle-hours", type=float, default=24.0, help="Idle cutoff window in hours (default: 24.0).")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument("--repo", type=Path, default=None, help="Target repository root.")

    args = parser.parse_args()

    repo = find_repo_root(args.repo or Path.cwd())
    if not is_ps_release_workflow_repo(repo):
        print(f"ERROR: {repo} not opted into ps-release-workflow", file=sys.stderr)
        return 1

    if is_release_frozen(repo):
        print("ERROR: release is frozen; worktree gc refused.", file=sys.stderr)
        return 1

    items = collect_worktree_status(repo, force=args.force, idle_window_hours=args.idle_hours)

    if args.json:
        print(json.dumps(items, indent=2))
    else:
        print(f"\nps-release-workflow gc — {repo}")
        if not items:
            print("  No feature worktrees found.")
        else:
            print(f"  {'Worktree':<40} {'Feature':<10} {'Size':<10} {'Verdict':<10} Reason")
            print("  " + "-" * 85)
            for item in items:
                size_str = f"{item['size_kb']/1024:.1f} MB"
                verdict_str = item["verdict"].upper()
                if item["forced"]:
                    verdict_str += " (FORCED)"
                print(f"  {item['name'][:38]:<40} {str(item['feature']):<10} {size_str:<10} {verdict_str:<10} {item['reason']}")

    if not args.apply:
        removable_count = sum(1 for i in items if i["verdict"] == "remove")
        if not args.json and removable_count > 0:
            print(f"\nℹ️  {removable_count} worktree(s) eligible for removal. Run with --apply to execute.")
        return 0

    # Execute removal
    removed_count = 0
    failed_count = 0
    claims_file = repo / ".claude" / "state" / "claims.json"

    for item in items:
        if item["verdict"] != "remove":
            continue

        wt_path = Path(item["path"])
        lock_path = repo / ".claude" / "state" / f"gc-{wt_path.name}.lock"

        with file_lock(lock_path):
            if not wt_path.exists():
                continue

            # Final check inside lock
            ok, reason = removable(repo, wt_path, skip_liveness=True)
            if not ok and not (args.force and any(reason.startswith(p) for p in ("S4:", "S5:", "L3:"))):
                print(f"⚠️  Skipping {item['name']}: condition changed inside lock ({reason})", file=sys.stderr)
                failed_count += 1
                continue

            try:
                git_run(repo, "worktree", "remove", "--force", str(wt_path))
                removed_count += 1
                if not args.json:
                    print(f"✅ Removed worktree: {item['name']}")

                # Drop claims entry if feature is known
                if item["feature"]:
                    def drop(claims: dict) -> dict:
                        claims.pop(item["feature"], None)
                        return claims
                    try:
                        mutate_state(claims_file, drop, default={})
                    except Exception:
                        pass
            except GitError as e:
                print(f"❌ Failed to remove {item['name']}: {e}", file=sys.stderr)
                failed_count += 1

    try:
        git_run(repo, "worktree", "prune")
    except Exception:
        pass

    if not args.json:
        print(f"\nSummary: {removed_count} removed, {failed_count} failed.")

    return 1 if failed_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
