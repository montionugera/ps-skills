"""Tests for scripts/gc_worktrees.py and psrw gc command."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.gc_worktrees import collect_worktree_status, main as gc_main
from scripts.init_work_new_release import new_release
from scripts.new_idea import new_idea
from scripts.promote_idea_to_refined import promote_idea_to_refined
from scripts.init_work_refined_backlog import claim_feature


def _setup_shipped_worktree(repo: Path, owner: str) -> tuple[dict, Path]:
    new_release(repo, version="1.1")
    idea = new_idea(repo, title="Shipped feature")
    feat = promote_idea_to_refined(repo, idea["id"], allow_empty_spec=True)
    claim = claim_feature(repo, feat["id"], owner=owner)
    wt = Path(claim["worktree"])

    (wt / "code.py").write_text("# done\n")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "feat: done"], cwd=wt, check=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=wt).decode().strip()

    cat_path = repo / ".claude" / "worktrees" / "_release" / ".claude" / "refined_backlog" / "_catalog.json"
    entries = json.loads(cat_path.read_text())
    for e in entries:
        if e["id"] == feat["id"]:
            e["status"] = "shipped"
            e["shipped_sha"] = head_sha
            e["release_version"] = "1.1"
    cat_path.write_text(json.dumps(entries, indent=2))
    return feat, wt


def test_gc_dry_run_reports_without_deleting(tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys):
    feat, wt = _setup_shipped_worktree(tmp_repo_with_release, fixed_owner)
    monkeypatch.chdir(tmp_repo_with_release)
    monkeypatch.setattr(sys, "argv", ["psrw-gc", "--idle-hours", "0"])

    exit_code = gc_main()
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "REMOVE" in captured.out
    assert "1 worktree(s) eligible for removal" in captured.out
    # Worktree must still exist
    assert wt.is_dir()


def test_gc_apply_removes_eligible_worktree(tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys):
    feat, wt = _setup_shipped_worktree(tmp_repo_with_release, fixed_owner)
    claims_file = tmp_repo_with_release / ".claude" / "state" / "claims.json"
    assert feat["id"] in json.loads(claims_file.read_text())

    monkeypatch.chdir(tmp_repo_with_release)
    monkeypatch.setattr(sys, "argv", ["psrw-gc", "--apply", "--idle-hours", "0"])

    exit_code = gc_main()
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Removed worktree:" in captured.out
    assert not wt.exists()

    # Claims ledger entry should be cleaned up
    assert feat["id"] not in json.loads(claims_file.read_text())


def test_gc_keeps_active_claimed_worktree(tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys):
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="In progress")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea["id"], allow_empty_spec=True)
    claim = claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)
    wt = Path(claim["worktree"])

    monkeypatch.chdir(tmp_repo_with_release)
    monkeypatch.setattr(sys, "argv", ["psrw-gc", "--apply", "--idle-hours", "0"])

    exit_code = gc_main()
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "KEEP" in captured.out
    assert wt.is_dir()


def test_gc_force_overrides_idle_window(tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys):
    feat, wt = _setup_shipped_worktree(tmp_repo_with_release, fixed_owner)
    monkeypatch.chdir(tmp_repo_with_release)
    # Default 24h idle window, but --force provided
    monkeypatch.setattr(sys, "argv", ["psrw-gc", "--apply", "--force"])

    exit_code = gc_main()
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Removed worktree:" in captured.out
    assert not wt.exists()


def test_gc_refuses_when_release_is_frozen(tmp_repo_with_release: Path, monkeypatch, capsys):
    from lib.release_freeze import freeze_release
    freeze_release(tmp_repo_with_release, "1.1")

    monkeypatch.chdir(tmp_repo_with_release)
    monkeypatch.setattr(sys, "argv", ["psrw-gc"])

    exit_code = gc_main()
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "release is frozen" in captured.err


def test_gc_json_output(tmp_repo_with_release: Path, fixed_owner: str, monkeypatch, capsys):
    feat, wt = _setup_shipped_worktree(tmp_repo_with_release, fixed_owner)
    monkeypatch.chdir(tmp_repo_with_release)
    monkeypatch.setattr(sys, "argv", ["psrw-gc", "--json", "--idle-hours", "0"])

    exit_code = gc_main()
    assert exit_code == 0
    captured = capsys.readouterr()
    items = json.loads(captured.out)
    assert isinstance(items, list)
    assert len(items) == 1
    assert items[0]["feature"] == feat["id"]
    assert items[0]["verdict"] == "remove"
