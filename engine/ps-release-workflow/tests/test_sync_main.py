"""psrw sync-main: absorb main (hotfixes) into release/<v> on demand, verified
by Gate 1 on the result. `psrw hotfix --sync-release` delegates to it."""
import subprocess
import sys
from pathlib import Path

import pytest

from tests._helpers import git
from tests.test_main_sync import _land_on_origin_main, _rel_wt
from scripts.init_work_new_release import new_release
from scripts.ship_current_work_to_release import GateFailedError
from scripts.sync_main import sync_main
from lib.main_sync import MainSyncConflictError
from lib.release_freeze import ReleaseFrozenError, freeze_release

PSRW = Path(__file__).resolve().parent.parent / "bin" / "psrw"


def _release_with_precheck(repo: Path, body: str) -> None:
    (repo / "scripts").mkdir(exist_ok=True)
    (repo / "scripts" / "precheck.sh").write_text(f"#!/bin/sh\n{body}\n")
    (repo / "scripts" / "precheck.sh").chmod(0o755)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "precheck")
    git(repo, "push", "-q", "origin", "main")
    new_release(repo, version="1.1")


def test_sync_main_merges_main_and_runs_gate1_on_the_result(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    marker = repo.parent / "gate1.ran"
    _release_with_precheck(repo, f'test -e hotfix.txt && touch "{marker}"')
    _land_on_origin_main(repo, "hotfix.txt", "urgent\n")

    result = sync_main(repo)
    assert result == {"release": "1.1", "synced": 1, "gate1": "passed"}
    assert (_rel_wt(repo) / "hotfix.txt").exists()
    assert marker.exists(), "Gate 1 must verify the synced tree"


def test_sync_main_rolls_back_when_gate1_fails(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    _release_with_precheck(repo, "test ! -e hotfix.txt")
    pre = git(_rel_wt(repo), "rev-parse", "HEAD")
    _land_on_origin_main(repo, "hotfix.txt", "urgent\n")

    with pytest.raises(GateFailedError, match="rolled back"):
        sync_main(repo)
    assert git(_rel_wt(repo), "rev-parse", "HEAD") == pre


def test_sync_main_is_a_no_op_when_release_has_main(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    marker = repo.parent / "gate1.ran"
    _release_with_precheck(repo, f'touch "{marker}"')
    assert sync_main(repo) == {"release": "1.1", "synced": 0, "gate1": None}
    assert not marker.exists()


def test_sync_main_without_a_release_is_a_no_op(tmp_repo_with_release: Path):
    assert sync_main(tmp_repo_with_release) == {"release": None, "synced": 0, "gate1": None}


def test_sync_main_refuses_a_frozen_release(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    _release_with_precheck(repo, "exit 0")
    freeze_release(repo, "1.1")
    _land_on_origin_main(repo, "hotfix.txt", "urgent\n")
    with pytest.raises(ReleaseFrozenError, match="promote"):
        sync_main(repo)
    assert not (_rel_wt(repo) / "hotfix.txt").exists()


def _psrw(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PSRW), *args], cwd=repo,
                          capture_output=True, text=True)


def test_psrw_sync_main_verb_and_hotfix_alias_share_one_path(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    _release_with_precheck(repo, "exit 0")
    _land_on_origin_main(repo, "hotfix.txt", "urgent\n")
    first = _psrw(repo, "sync-main")
    assert first.returncode == 0, first.stderr
    assert '"synced": 1' in first.stdout
    alias = _psrw(repo, "hotfix", "--sync-release")
    assert alias.returncode == 0, alias.stderr
    assert '"synced": 0' in alias.stdout and '"gate1": null' in alias.stdout


def test_psrw_sync_main_conflict_exits_1_with_the_command(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    _release_with_precheck(repo, "exit 0")
    rel = _rel_wt(repo)
    (rel / "README.md").write_text("release side\n")
    git(rel, "commit", "-q", "-am", "release edit")
    _land_on_origin_main(repo, "README.md", "main side\n")
    proc = _psrw(repo, "sync-main")
    assert proc.returncode == 1
    assert "git merge origin/main" in proc.stderr


# ── Review follow-ups ──────────────────────────────────────────────────────────


def test_sync_main_rolls_back_when_precheck_cannot_even_run(tmp_repo_with_release: Path):
    """A non-executable precheck.sh raises PermissionError inside the gate: the
    sync must still be rolled back and the CLI must exit 1, not traceback."""
    repo = tmp_repo_with_release
    _release_with_precheck(repo, "exit 0")
    rel = _rel_wt(repo)
    (rel / "scripts" / "precheck.sh").chmod(0o644)
    git(rel, "commit", "-q", "-am", "precheck loses its exec bit")
    pre = git(rel, "rev-parse", "HEAD")
    _land_on_origin_main(repo, "hotfix.txt", "urgent\n")
    proc = _psrw(repo, "sync-main")
    assert proc.returncode == 1, proc.stderr
    assert "Traceback" not in proc.stderr
    assert git(rel, "rev-parse", "HEAD") == pre


def _with_deploy(repo: Path, body: str) -> Path:
    marker = repo.parent / "deploy.ran"
    (repo / "scripts").mkdir(exist_ok=True)
    (repo / "scripts" / "deploy-local.sh").write_text(f'#!/bin/sh\ntouch "{marker}"\n{body}\n')
    (repo / "scripts" / "deploy-local.sh").chmod(0o755)
    return marker


def test_sync_main_deploy_runs_after_a_verified_sync(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    marker = _with_deploy(repo, "exit 0")
    _release_with_precheck(repo, "exit 0")
    _land_on_origin_main(repo, "hotfix.txt", "urgent\n")
    proc = _psrw(repo, "sync-main", "--deploy")
    assert proc.returncode == 0, proc.stderr
    assert marker.exists()


def test_sync_main_deploy_failure_exits_1(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    _with_deploy(repo, "exit 3")
    _release_with_precheck(repo, "exit 0")
    assert _psrw(repo, "sync-main", "--deploy").returncode == 1


def test_sync_main_deploy_without_a_script_says_so(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    _release_with_precheck(repo, "exit 0")
    proc = _psrw(repo, "sync-main", "--deploy")
    assert proc.returncode == 0
    assert "no local deploy configured" in proc.stdout


def test_sync_main_warns_before_deploying_a_tree_gate1_never_checked(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    marker = _with_deploy(repo, "exit 0")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "deploy only, no precheck")
    git(repo, "push", "-q", "origin", "main")
    new_release(repo, version="1.1")
    _land_on_origin_main(repo, "hotfix.txt", "urgent\n")
    proc = _psrw(repo, "sync-main", "--deploy")
    assert proc.returncode == 0 and marker.exists()
    assert "Gate 1 did not run" in proc.stderr


def test_cli_refusals_exit_1_through_the_verb_and_the_alias(tmp_repo_with_release: Path):
    repo = tmp_repo_with_release
    _release_with_precheck(repo, "test ! -e hotfix.txt")
    _land_on_origin_main(repo, "hotfix.txt", "urgent\n")
    for args in (("sync-main",), ("hotfix", "--sync-release")):
        proc = _psrw(repo, *args)
        assert proc.returncode == 1 and "GateFailedError" in proc.stderr, args
    freeze_release(repo, "1.1")
    for args in (("sync-main",), ("hotfix", "--sync-release")):
        proc = _psrw(repo, *args)
        assert proc.returncode == 1 and "ReleaseFrozenError" in proc.stderr, args


def test_hotfix_alias_calls_sync_main_and_forwards_flags(tmp_repo_with_release, monkeypatch):
    import scripts.sync_main as sm
    from scripts.hotfix import main as hotfix_main
    seen = {}

    def fake_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(sm, "main", fake_main)
    monkeypatch.chdir(tmp_repo_with_release)
    monkeypatch.setattr(sys, "argv", ["hotfix", "--sync-release", "--deploy"])
    assert hotfix_main() == 0
    assert seen["argv"] == ["--deploy"]


def test_hotfix_alias_rejects_a_description(tmp_repo_with_release, monkeypatch):
    from scripts.hotfix import main as hotfix_main
    monkeypatch.chdir(tmp_repo_with_release)
    monkeypatch.setattr(sys, "argv", ["hotfix", "--sync-release", "oops"])
    with pytest.raises(SystemExit) as ei:
        hotfix_main()
    assert ei.value.code == 2
