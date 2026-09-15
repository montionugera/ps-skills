"""session_start_reminder: prints a brief status at session start if in opted-in repo.

The hook is a thin bash wrapper: fast walk-up for .release.json (no python spawn
when absent), then a single `status.py --brief` invocation.
"""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "session_start_reminder.sh"


def _run(cwd: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PWD": str(cwd)}
    return subprocess.run([str(SCRIPT)], cwd=cwd, capture_output=True, text=True, env=env)


def test_no_output_outside_workflow_repo(tmp_path: Path):
    cp = _run(tmp_path)
    assert cp.returncode == 0
    assert cp.stdout == ""


def test_prints_active_claim_inside_workflow_repo(tmp_repo_with_release: Path, fixed_owner: str):
    # Trigger active release + claim.
    from scripts.init_work_new_release import new_release
    from scripts.new_idea import new_idea
    from scripts.promote_idea_to_refined import promote_idea_to_refined
    from scripts.init_work_refined_backlog import claim_feature
    new_release(tmp_repo_with_release, version="1.1")
    idea = new_idea(tmp_repo_with_release, title="X")
    feat = promote_idea_to_refined(tmp_repo_with_release, idea["id"])
    claim_feature(tmp_repo_with_release, feat["id"], owner=fixed_owner)

    cp = _run(tmp_repo_with_release)
    assert cp.returncode == 0
    assert "ps-release-workflow" in cp.stdout.lower()
    assert "1.1" in cp.stdout
    assert feat["id"] in cp.stdout


def test_brief_output_inside_workflow_repo_stays_short(tmp_repo_with_release: Path, fixed_owner: str):
    from scripts.init_work_new_release import new_release
    new_release(tmp_repo_with_release, version="1.1")
    cp = _run(tmp_repo_with_release)
    assert cp.returncode == 0
    lines = [ln for ln in cp.stdout.splitlines() if ln.strip()]
    assert 1 <= len(lines) <= 6


def test_never_fails_even_on_corrupt_state(tmp_repo_with_release: Path):
    (tmp_repo_with_release / ".release.json").write_text("{not json")
    cp = _run(tmp_repo_with_release)
    assert cp.returncode == 0
