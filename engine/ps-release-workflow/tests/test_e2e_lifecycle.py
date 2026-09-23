"""One full lifecycle driven entirely through the psrw CLI."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PSRW = REPO_ROOT / "bin" / "psrw"


def psrw(repo: Path, *args, home: Path, expect=0):
    proc = subprocess.run(
        [sys.executable, str(PSRW), *args], cwd=repo,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/local/bin",
             "PS_RELEASE_WORKFLOW_SCRIPTED": "1"},
        input="", capture_output=True, text=True,
    )
    assert proc.returncode == expect, (
        f"psrw {' '.join(args)} exited {proc.returncode}\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    return proc


@pytest.mark.slow
def test_full_lifecycle_through_the_cli(tmp_repo, tmp_path):
    home = tmp_path / "_e2e_home"
    (home / ".claude").mkdir(parents=True)

    # init -> new-release -> idea -> refine
    psrw(tmp_repo, "init", home=home)
    assert (tmp_repo / ".release.json").is_file()

    psrw(tmp_repo, "new-release", home=home)
    rel_wt = tmp_repo / ".claude" / "worktrees" / "_release"
    assert rel_wt.is_dir()
    assert json.loads((rel_wt / ".release.json").read_text())["in_progress"] is True

    psrw(tmp_repo, "idea", "add fee cap", home=home)
    idea_catalog = json.loads(
        (rel_wt / ".claude" / "idea_backlog" / "_catalog.json").read_text())
    assert len(idea_catalog) == 1
    idea_id = idea_catalog[0]["id"]

    # The untouched skeleton is refused; a filled spec with acceptance criteria passes.
    psrw(tmp_repo, "refine", idea_id, home=home, expect=1)
    spec = next((rel_wt / ".claude" / "idea_backlog").glob(f"{idea_id}-*")) / "spec.md"
    spec.write_text(
        "# add fee cap\n\n## Problem\n\nFees eat the position.\n\n"
        "## Acceptance criteria\n\n- [ ] an order above the cap is rejected\n")
    psrw(tmp_repo, "refine", idea_id, home=home)
    refined = json.loads(
        (rel_wt / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    assert len(refined) == 1
    feature_id = refined[0]["id"]

    # claim -> commit work in the worktree -> ship
    psrw(tmp_repo, "claim", feature_id, home=home)
    wt = next((tmp_repo / ".claude" / "worktrees").glob(f"{feature_id}-*"))
    assert wt.is_dir()

    (wt / "feature.txt").write_text("the work\n")
    subprocess.run(["git", "add", "feature.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", f"feat: {feature_id}"], cwd=wt,
                   check=True, capture_output=True)

    psrw(wt, "ship", "--no-deploy", home=home)
    shipped = json.loads(
        (rel_wt / ".claude" / "refined_backlog" / "_catalog.json").read_text())
    assert shipped[0]["status"] == "shipped", shipped

    # promote --direct: local squash-merge to main, no gh, no PR
    psrw(tmp_repo, "promote", "--direct", "--no-gate2", home=home)
    main_files = subprocess.run(["git", "ls-tree", "--name-only", "main"],
                                cwd=tmp_repo, capture_output=True, text=True).stdout
    assert "feature.txt" in main_files, "the feature never reached main"


@pytest.mark.slow
def test_status_reports_the_release_after_new_release(tmp_repo, tmp_path):
    home = tmp_path / "_e2e_home2"
    (home / ".claude").mkdir(parents=True)
    psrw(tmp_repo, "init", home=home)
    psrw(tmp_repo, "new-release", home=home)
    out = psrw(tmp_repo, "status", home=home).stdout
    assert "1.1" in out
