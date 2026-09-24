"""A release is frozen from the moment promote starts: a feature shipped into it
afterwards is not in the PR that merges, so it would be stranded (joy-companion
2026-09-24: F-022 shipped into release/1.5 at 18:58, the 1.5 PR merged at 18:59
without it, and the catalog still claimed it shipped on 1.5)."""
import json
import subprocess
from pathlib import Path

import pytest

from tests._helpers import git
from scripts.init_work_new_release import new_release
from scripts.new_idea import new_idea
from scripts.promote_idea_to_refined import promote_idea_to_refined
from scripts.init_work_refined_backlog import claim_feature
from scripts.ship_current_work_to_release import ship_current_work
from scripts.promote_release import Gate2FailedError, cleanup, promote_release
from lib.release_freeze import ReleaseFrozenError

PR_URL = "https://github.com/o/r/pull/1"


class Gh:
    """gh stub; `on` maps an op (create/view/checks/merge/edit) to a callback
    run when that op is invoked, returning (rc, stdout, stderr)."""

    def __init__(self, on: dict | None = None):
        self.calls: list[str] = []
        self.on = on or {}

    def __call__(self, cmd, **kw):
        op = cmd[2]
        self.calls.append(op)
        rc, out, err = self.on[op]() if op in self.on else (0, PR_URL, "")
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)


def _commit(wt: Path, name: str) -> None:
    (wt / name).write_text(name + "\n")
    git(wt, "add", ".")
    git(wt, "commit", "-q", "-m", f"add {name}")


def _release_with_two_claims(repo: Path, owner: str, integration: str = "exit 0") -> tuple:
    """release/1.1 with F-001 shipped and F-002 claimed + committed, not shipped."""
    s = repo / "scripts"
    s.mkdir(exist_ok=True)
    for name, body in (("precheck.sh", "exit 0"), ("integration.sh", integration)):
        (s / name).write_text(f"#!/bin/sh\n{body}\n")
        (s / name).chmod(0o755)
    # Like a real `psrw init`: state/ is gitignored, so claims churn never
    # dirties the main checkout that cleanup resets to origin/main.
    (repo / ".gitignore").write_text(".claude/state/\n.claude/worktrees/\n")
    git(repo, "rm", "-q", "-r", "--cached", ".claude/state")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "gates")
    git(repo, "push", "-q", "origin", "main")
    new_release(repo, version="1.1")
    wts = []
    for title in ("First", "Second"):
        idea = new_idea(repo, title=title)
        feat = promote_idea_to_refined(repo, idea["id"], allow_empty_spec=True)
        wt = Path(claim_feature(repo, feat["id"], owner=owner)["worktree"])
        _commit(wt, f"{title.lower()}.txt")
        wts.append((feat["id"], wt))
    ship_current_work(wts[0][1])
    return wts


def _rel(repo: Path) -> Path:
    return repo / ".claude" / "worktrees" / "_release"


def _main_catalog(repo: Path) -> list:
    return json.loads((repo / ".claude" / "refined_backlog" / "_catalog.json").read_text())


# ── (a) ship refuses a frozen release ──────────────────────────────────────────


def test_ship_during_a_babysit_promote_is_refused(tmp_repo_with_release: Path, fixed_owner: str):
    """The F-022 window: the PR is open and CI is being watched; a ship landing
    now would merge locally but never reach the PR."""
    repo = tmp_repo_with_release
    (_f1, _), (f2, wt2) = _release_with_two_claims(repo, fixed_owner)
    seen = {}

    def ship_while_ci_runs():
        with pytest.raises(ReleaseFrozenError) as ei:
            ship_current_work(wt2)
        seen["msg"] = str(ei.value)
        return (0, "", "")

    promote_release(repo, run_gate2=False, run_deploy=False, babysit=True,
                    gh_runner=Gh({"checks": ship_while_ci_runs}))
    assert "next release" in seen["msg"]
    # Never merged, never marked shipped: cleanup kept its branch.
    assert git(repo, "rev-parse", "--verify", f"feat/{f2}")


def test_ship_into_a_finalized_release_names_the_freeze(tmp_repo_with_release: Path, fixed_owner: str):
    repo = tmp_repo_with_release
    (_f1, _), (f2, wt2) = _release_with_two_claims(repo, fixed_owner)
    promote_release(repo, run_gate2=False, run_deploy=False, gh_runner=Gh())
    with pytest.raises(ReleaseFrozenError, match="next release"):
        ship_current_work(wt2)


def test_a_failed_promote_unfreezes_the_release(tmp_repo_with_release: Path, fixed_owner: str):
    repo = tmp_repo_with_release
    (_f1, _), (f2, wt2) = _release_with_two_claims(repo, fixed_owner, integration="exit 1")
    with pytest.raises(Gate2FailedError):
        promote_release(repo, run_gate2=True, run_deploy=False, gh_runner=Gh())
    ship_current_work(wt2)  # must not raise ReleaseFrozenError
    assert (_rel(repo) / "second.txt").exists()


def test_babysit_red_checks_unfreeze_so_a_fix_can_ship(tmp_repo_with_release: Path, fixed_owner: str):
    repo = tmp_repo_with_release
    (_f1, _), (f2, wt2) = _release_with_two_claims(repo, fixed_owner)
    with pytest.raises(Gate2FailedError, match="checks FAILED"):
        promote_release(repo, run_gate2=False, run_deploy=False, babysit=True,
                        gh_runner=Gh({"checks": lambda: (1, "", "red")}))
    ship_current_work(wt2)
    assert (_rel(repo) / "second.txt").exists()


# ── (b) promote/cleanup verify what actually landed ───────────────────────────


def test_babysit_refuses_to_merge_when_the_pr_head_is_not_the_local_release(
    tmp_repo_with_release: Path, fixed_owner: str
):
    repo = tmp_repo_with_release
    _release_with_two_claims(repo, fixed_owner)

    def stray_commit_during_ci():
        _commit(_rel(repo), "stray.txt")  # bypasses ship: lands only locally
        return (0, "", "")

    gh = Gh({"checks": stray_commit_during_ci})
    with pytest.raises(Gate2FailedError, match="differs"):
        promote_release(repo, run_gate2=False, run_deploy=False, babysit=True, gh_runner=gh)
    assert "merge" not in gh.calls


def _squash_merge_origin_release_into_origin_main(repo: Path) -> None:
    """What GitHub does when the PR merges: squash the REMOTE release head."""
    clone = repo.parent / "gh-merge"
    subprocess.run(["git", "clone", "-q", "-b", "main", str(repo.parent / "origin.git"), str(clone)],
                   check=True, capture_output=True)
    git(clone, "config", "user.email", "t@t")
    git(clone, "config", "user.name", "T")
    git(clone, "merge", "--squash", "origin/release/1.1")
    git(clone, "commit", "-q", "-m", "release 1.1 (#1)")
    git(clone, "push", "-q", "origin", "HEAD:main")


def test_cleanup_flags_and_resets_a_feature_shipped_after_the_pr_head(
    tmp_repo_with_release: Path, fixed_owner: str, capsys
):
    """Replays F-022: F-002 lands on the LOCAL release after the PR head was
    pushed (bypassing the freeze, e.g. an older psrw), the PR merges without
    it. Cleanup must not silently drop it: flag it loudly, keep its branch,
    and put it back in main's catalog so the next release can ship it."""
    repo = tmp_repo_with_release
    (f1, _), (f2, wt2) = _release_with_two_claims(repo, fixed_owner)
    promote_release(repo, run_gate2=False, run_deploy=False, gh_runner=Gh())

    # Out-of-band late ship into the local release (not pushed).
    rel = _rel(repo)
    git(rel, "merge", "--no-ff", "-q", "-m", "late merge", f"feat/{f2}")
    cat = rel / ".claude" / "refined_backlog" / "_catalog.json"
    entries = json.loads(cat.read_text())
    for e in entries:
        if e["id"] == f2:
            e.update(status="shipped", release_version="1.1",
                     shipped_sha=git(repo, "rev-parse", f"feat/{f2}"))
    cat.write_text(json.dumps(entries, indent=2))
    git(rel, "commit", "-q", "-am", "late ship")

    _squash_merge_origin_release_into_origin_main(repo)
    result = cleanup(repo, version="1.1", gh_runner=Gh({"view": lambda: (0, "MERGED\n", "")}))

    assert result["stranded"] == [f2]
    err = capsys.readouterr().err
    assert f2 in err and "NOT in the merged" in err
    main_entry = next(e for e in _main_catalog(repo) if e["id"] == f2)
    assert main_entry["status"] in ("open", "claimed")
    assert main_entry.get("release_version") is None
    assert main_entry["stranded_from"] == "1.1"
    assert git(repo, "rev-parse", "--verify", f"feat/{f2}"), "stranded branch must be kept"
    # The feature that DID land is promoted as usual.
    assert next(e for e in _main_catalog(repo) if e["id"] == f1)["status"] == "promoted"


def test_ship_records_the_shipped_sha(tmp_repo_with_release: Path, fixed_owner: str):
    repo = tmp_repo_with_release
    (f1, wt1), _ = _release_with_two_claims(repo, fixed_owner)
    cat = json.loads((_rel(repo) / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    entry = next(e for e in cat if e["id"] == f1)
    assert entry["shipped_sha"] == git(wt1, "rev-parse", "HEAD")
