"""Shared helpers for the engine test-suite. Not a test module."""
import subprocess
from pathlib import Path


def git(cwd: Path, *args: str) -> str:
    """Run `git <args>` in cwd; return stripped stdout; fail loudly with git's stderr."""
    cp = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert cp.returncode == 0, f"git {' '.join(args)} failed: {cp.stderr}"
    return cp.stdout.strip()
