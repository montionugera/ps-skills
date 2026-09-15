"""ps-release-workflow:status — one-screen "what's in flight" report.

Joins the release state (_release worktree .release.json), the refined/idea
catalogs, the claims ledger, and actual `git worktree list` reality into a
single report with a state-chosen "Next:" hint. Read-only; never writes.

Usage:
    python3 status.py [--repo PATH] [--brief]

Always exits 0 (it backs the SessionStart hook — a status failure must never
break a session). Not-opted-in repos get a single quiet line.
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import argparse
import json
import subprocess
import sys
from pathlib import Path

from lib.backlog_paths import read_release_state, release_worktree_path
from lib.owner import self_ids
from lib.repo import RepoNotFoundError, find_repo_root, is_ps_release_workflow_repo
from lib.state import read_state

STATUS_ORDER = ("open", "claimed", "shipped", "promoted")


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _registered_worktrees(repo: Path) -> set[str] | None:
    """Resolved paths of git-registered worktrees, or None if git is unavailable."""
    cp = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo, capture_output=True, text=True,
    )
    if cp.returncode != 0:
        return None
    paths: set[str] = set()
    for line in cp.stdout.splitlines():
        if line.startswith("worktree "):
            raw = Path(line[len("worktree "):].strip())
            try:
                paths.add(str(raw.resolve()))
            except OSError:
                paths.add(str(raw))
    return paths


def _catalog_root(repo: Path) -> Path:
    """Catalogs live on the release branch (_release worktree) while it exists;
    after cleanup they live on main (the main checkout)."""
    wt = release_worktree_path(repo)
    if (wt / ".claude" / "refined_backlog" / "_catalog.json").exists():
        return wt
    return repo


def _feature_worktree(repo: Path, feature_id: str, claims: dict) -> Path | None:
    claim = claims.get(feature_id) or {}
    if claim.get("worktree"):
        return Path(claim["worktree"])
    matches = sorted((repo / ".claude" / "worktrees").glob(f"{feature_id}-*"))
    return matches[0] if matches else None


def _next_hint(in_progress: bool, pending_cleanup: bool, cleanup_version: str | None,
               counts: dict) -> str:
    if pending_cleanup:
        # B3: cleanup deletes the remote release branch, which auto-closes an
        # unmerged PR — never hint it unconditionally.
        v = cleanup_version if cleanup_version is not None else "<version>"
        return f"after the release PR merges: psrw promote --cleanup-only {v}"
    if not in_progress:
        return "psrw new-release"
    if counts["open"]:
        return "psrw claim --next"
    if counts["claimed"]:
        return "implement the claimed feature(s), then psrw ship"
    if counts["shipped"]:
        return "psrw promote"
    return "refined backlog is empty — psrw idea then psrw refine"


def collect_status(repo: Path) -> dict:
    repo = Path(repo).resolve()
    main_rj = _read_json(repo / ".release.json")
    if not main_rj:
        raise ValueError(f"unreadable .release.json in {repo}")

    state = read_release_state(repo)  # None unless a release is in progress
    in_progress = state is not None
    rel_wt_rj = _read_json(release_worktree_path(repo) / ".release.json")

    version = (state or {}).get("version") or main_rj.get("version")
    last_promoted_version = (
        main_rj.get("last_promoted_version") or rel_wt_rj.get("last_promoted_version")
    )
    last_promoted_at = main_rj.get("last_promoted_at") or rel_wt_rj.get("last_promoted_at")

    cat_root = _catalog_root(repo)
    features = read_state(
        cat_root / ".claude" / "refined_backlog" / "_catalog.json", default=[]
    ) or []
    ideas = read_state(
        cat_root / ".claude" / "idea_backlog" / "_catalog.json", default=[]
    ) or []
    claims = read_state(repo / ".claude" / "state" / "claims.json", default={}) or {}
    registered = _registered_worktrees(repo)

    counts = {s: 0 for s in STATUS_ORDER}
    counts["total"] = len(features)
    enriched: list[dict] = []
    for e in features:
        status = e.get("status", "open")
        counts[status] = counts.get(status, 0) + 1
        wt = _feature_worktree(repo, e["id"], claims) if status == "claimed" else None
        drift = None
        if status == "claimed":
            if wt is None or not wt.is_dir():
                drift = "claimed but worktree missing"
            elif registered is not None and str(wt.resolve()) not in registered:
                drift = "worktree dir present but not registered with git"
        enriched.append({
            "id": e["id"],
            "title": e.get("title", ""),
            "status": status,
            "release_version": e.get("release_version"),
            "owner": (claims.get(e["id"]) or {}).get("owner") or e.get("claimed_by"),
            "worktree": str(wt) if wt else None,
            "drift": drift,
        })

    # Leftover worktree dirs (feature worktrees and/or _release) after a promote.
    wt_root = repo / ".claude" / "worktrees"
    leftover_worktrees = (
        sorted(d.name for d in wt_root.iterdir() if d.is_dir()) if wt_root.is_dir() else []
    )
    pending_cleanup = not in_progress and bool(
        leftover_worktrees
        or counts["shipped"]
        or counts["claimed"]
        or claims
    )
    cleanup_version = last_promoted_version or version

    # Own ACTIVE claims: ledger entries owned by this session whose catalog
    # status is still "claimed" (stale ledger entries for shipped/promoted
    # features would otherwise bloat the line).
    # generate=False: status is a READ path — with no identity anywhere it
    # reports no own claims rather than persisting a fresh id as a side effect.
    me = self_ids(generate=False)
    still_claimed = {f["id"] for f in enriched if f["status"] == "claimed"}
    own_claims = sorted(
        fid for fid, c in claims.items()
        if c.get("owner") in me and (fid in still_claimed or fid not in {f["id"] for f in enriched})
    )

    return {
        "opted_in": True,
        "repo": str(repo),
        "release": {
            "version": version,
            "in_progress": in_progress,
            "started_at": (state or {}).get("started_at"),
            "started_by": (state or {}).get("started_by"),
            "last_promoted_version": last_promoted_version,
            "last_promoted_at": last_promoted_at,
        },
        "features": enriched,
        "counts": counts,
        "ideas": {
            "total": len(ideas),
            "unpromoted": sum(1 for i in ideas if not i.get("promoted_to")),
        },
        "own_claims": own_claims,
        "leftover_worktrees": leftover_worktrees,
        "pending_cleanup": pending_cleanup,
        "next": _next_hint(in_progress, pending_cleanup, cleanup_version, counts),
    }


def _date(ts: str | None) -> str:
    return (ts or "?")[:10]


def _release_line(st: dict) -> str:
    rel = st["release"]
    if rel["in_progress"]:
        line = f"release {rel['version']} in progress (started {_date(rel['started_at'])}"
        if rel.get("started_by"):
            line += f" by {rel['started_by']}"
        line += ")"
    else:
        line = "no release in progress"
    if rel.get("last_promoted_version"):
        line += f"; last promoted: {rel['last_promoted_version']} ({_date(rel['last_promoted_at'])})"
    return line


def _counts_line(st: dict) -> str:
    c = st["counts"]
    parts = [f"{c[s]} {s}" for s in STATUS_ORDER if c.get(s)]
    feats = " / ".join(parts) if parts else "none"
    i = st["ideas"]
    return f"features: {feats} ({c['total']} total); ideas: {i['total']} ({i['unpromoted']} unpromoted)"


def render_brief(st: dict) -> str:
    lines = [
        f"ps-release-workflow: {_release_line(st)}",
        _counts_line(st),
    ]
    if st["own_claims"]:
        shown = st["own_claims"][:8]
        more = len(st["own_claims"]) - len(shown)
        lines.append(
            f"your claims: {', '.join(shown)}" + (f" (+{more} more)" if more else "")
        )
    elif st["release"]["in_progress"]:
        lines.append("your claims: none")
    drifted = [f for f in st["features"] if f["drift"]]
    if drifted:
        lines.append(f"drift: {len(drifted)} claimed feature(s) with worktree problems "
                     f"({', '.join(f['id'] for f in drifted[:3])})")
    lines.append(f"Next: {st['next']}")
    return "\n".join(lines)


def render_full(st: dict) -> str:
    lines = [
        f"ps-release-workflow status — {st['repo']}",
        f"Release: {_release_line(st)}",
        "",
    ]
    # Keep the table one-screen: always show open/claimed rows; shipped rows
    # only for the current release cycle (older shipped/promoted are summarized).
    version = st["release"]["version"]
    active = [
        f for f in st["features"]
        if f["status"] in ("open", "claimed")
        or (f["status"] == "shipped" and f.get("release_version") == version)
    ]
    lines.append(f"Features ({_counts_line(st)}):")
    if active:
        for f in active:
            title = f["title"][:44] + ("…" if len(f["title"]) > 44 else "")
            row = f"  {f['id']:<7} {title:<45} {f['status']:<8}"
            if f["status"] == "claimed" and f["owner"]:
                row += f" {f['owner']}"
            if f["status"] == "claimed" and f["worktree"]:
                try:
                    row += f"  {Path(f['worktree']).relative_to(st['repo'])}"
                except ValueError:
                    row += f"  {f['worktree']}"
            if f["drift"]:
                row += f"  [!! {f['drift']}]"
            lines.append(row)
        omitted = st["counts"]["total"] - len(active)
        if omitted:
            lines.append(f"  (+{omitted} shipped/promoted feature(s) from earlier releases omitted)")
    else:
        lines.append("  (no open/claimed features, none shipped this release)")

    if st["pending_cleanup"]:
        lines.append("")
        lines.append(
            f"Pending cleanup: release not in progress but "
            f"{len(st['leftover_worktrees'])} worktree(s) / "
            f"unarchived features remain: {', '.join(st['leftover_worktrees'][:5]) or '-'}"
        )
    lines.append("")
    lines.append(f"Next: {st['next']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="psrw status",
                                description="ps-release-workflow status report")
    p.add_argument("--repo", default=None, help="repo root (default: resolve from cwd)")
    p.add_argument("--brief", action="store_true", help="compact <=6-line summary")
    args = p.parse_args(argv)

    try:
        if args.repo:
            repo = Path(args.repo).resolve()
        else:
            repo = find_repo_root(Path.cwd())
    except RepoNotFoundError:
        print("not a ps-release-workflow repo")
        return 0
    if not is_ps_release_workflow_repo(repo):
        print("not a ps-release-workflow repo")
        return 0

    try:
        st = collect_status(repo)
        print(render_brief(st) if args.brief else render_full(st))
    except Exception as e:  # noqa: BLE001 — status must never break a session
        print(f"ps-release-workflow: status unavailable ({type(e).__name__}: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
