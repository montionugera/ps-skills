"""session_start_reminder: prints status hint at session start if in opted-in repo."""
import json
import os
import subprocess
from pathlib import Path


def test_no_output_outside_workflow_repo(tmp_path: Path):
    script = Path("scripts/session_start_reminder.sh").resolve()
    env = {**os.environ, "PWD": str(tmp_path)}
    cp = subprocess.run([str(script)], cwd=tmp_path, capture_output=True, text=True, env=env)
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

    script = Path("scripts/session_start_reminder.sh").resolve()
    env = {**os.environ, "PWD": str(tmp_repo_with_release)}
    cp = subprocess.run([str(script)], cwd=tmp_repo_with_release, capture_output=True, text=True, env=env)
    assert "ps-release-workflow" in cp.stdout.lower()
    assert "1.1" in cp.stdout
    assert feat["id"] in cp.stdout
