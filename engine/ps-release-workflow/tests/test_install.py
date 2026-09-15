"""install.sh must be idempotent and never fail a machine that lacks ~/.local/bin."""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL = REPO_ROOT / "install.sh"


def _run(home: Path, path_value: str):
    return subprocess.run(["bash", str(INSTALL)], capture_output=True, text=True,
                          env={"HOME": str(home), "PATH": path_value})


def test_install_creates_the_symlink(tmp_path):
    home = tmp_path / "h"
    (home / ".local" / "bin").mkdir(parents=True)
    proc = _run(home, f"{home}/.local/bin:/usr/bin:/bin")
    assert proc.returncode == 0, proc.stderr
    link = home / ".local" / "bin" / "psrw"
    assert link.is_symlink()
    assert link.resolve() == (REPO_ROOT / "bin" / "psrw").resolve()


def test_install_is_idempotent(tmp_path):
    home = tmp_path / "h"
    (home / ".local" / "bin").mkdir(parents=True)
    first = _run(home, f"{home}/.local/bin:/usr/bin:/bin")
    second = _run(home, f"{home}/.local/bin:/usr/bin:/bin")
    assert first.returncode == 0 and second.returncode == 0
    assert (home / ".local" / "bin" / "psrw").is_symlink()


def test_install_warns_but_succeeds_when_dir_not_on_path(tmp_path):
    home = tmp_path / "h"
    proc = _run(home, "/usr/bin:/bin")
    assert proc.returncode == 0
    assert "PATH" in proc.stdout + proc.stderr
    assert str(REPO_ROOT / "bin" / "psrw") in proc.stdout + proc.stderr
