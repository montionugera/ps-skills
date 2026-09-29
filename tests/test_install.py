"""Focused checks for top-level command installation."""

import os
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def run_install(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        HOME=str(home),
        CLAUDE_HOME=str(home / ".claude"),
        AGENTS_HOME=str(home / ".agents"),
        GEMINI_HOME=str(home / ".gemini"),
        CURSOR_HOME=str(home / ".cursor"),
        BIN_HOME=str(home / ".local" / "bin"),
        PATH="/usr/bin:/bin",
        CI="true",
    )
    return subprocess.run(
        ["bash", str(REPO / "install.sh"), *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_installer_links_ps_work(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    result = run_install(home)

    assert result.returncode == 0, result.stderr
    installed = home / ".local" / "bin" / "ps-work"
    assert installed.is_symlink()
    assert installed.resolve() == (REPO / "bin" / "ps-work").resolve()
    assert os.access(installed, os.X_OK)
    command = subprocess.run([str(installed), "--help"], capture_output=True, text=True)
    assert command.returncode == 0, command.stderr


def test_installer_replaces_foreign_ps_work_only_with_force(tmp_path: Path) -> None:
    home = tmp_path / "home"
    installed = home / ".local" / "bin" / "ps-work"
    installed.parent.mkdir(parents=True)
    foreign = tmp_path / "foreign-command"
    foreign.write_text("foreign\n")
    installed.symlink_to(foreign)

    preserved = run_install(home)
    assert preserved.returncode == 0, preserved.stderr
    assert installed.resolve() == foreign

    replaced = run_install(home, "--force")
    assert replaced.returncode == 0, replaced.stderr
    assert installed.is_symlink()
    assert installed.resolve() == (REPO / "bin" / "ps-work").resolve()
    assert os.access(installed, os.X_OK)
