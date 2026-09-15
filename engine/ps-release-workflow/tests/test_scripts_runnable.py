"""Regression test: runnable scripts must work via the documented standalone command.

Each script under scripts/ with a `if __name__ == "__main__":` block does module-level
absolute imports (`from lib...`, `from scripts...`). Those only resolve when the toolkit
repo root is on sys.path. The documented invocation
    python3 .../scripts/<name>.py
puts only scripts/ on sys.path[0], so without a path bootstrap every script crashes with
`ModuleNotFoundError: No module named 'lib'`. A sys.path bootstrap at the top of each
script fixes this; this test guards against regression.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

RUNNABLE_SCRIPTS = [
    "init_repo.py",
    "new_idea.py",
    "promote_idea_to_refined.py",
    "init_work_new_release.py",
    "init_work_refined_backlog.py",
    "ship_current_work_to_release.py",
    "unclaim.py",
    "promote_release.py",
    "cleanup_legacy_worktrees.py",
    "guard_check.py",
    "hotfix.py",
]


@pytest.mark.parametrize("script_name", RUNNABLE_SCRIPTS)
def test_script_imports_standalone(script_name, tmp_path):
    """Running the script via the documented command from a non-toolkit cwd must
    NOT fail at import time with ModuleNotFoundError / No module named 'lib'.

    We run with `--help` (argparse scripts exit 0/2 with usage; non-argparse ones
    just ignore it and hit a clean app-level error). cwd and HOME both point at
    tmp_path so the subprocess cannot read or mutate the real repo / global config.
    """
    script = SCRIPTS_DIR / script_name
    assert script.is_file(), f"missing script: {script}"

    proc = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/local/bin"},
        input="",
        capture_output=True,
        text=True,
    )

    combined = proc.stdout + proc.stderr
    assert "ModuleNotFoundError" not in combined, (
        f"{script_name} crashed at import time:\n{combined}"
    )
    assert "No module named 'lib'" not in combined, (
        f"{script_name} could not import lib package:\n{combined}"
    )
    assert "No module named 'scripts'" not in combined, (
        f"{script_name} could not import scripts package:\n{combined}"
    )
