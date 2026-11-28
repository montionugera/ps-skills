"""Focused checks for top-level command installation."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def run_install(home: Path, *args: str, path_prefix: str = "") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        HOME=str(home),
        CLAUDE_HOME=str(home / ".claude"),
        AGENTS_HOME=str(home / ".agents"),
        GEMINI_HOME=str(home / ".gemini"),
        CODEX_HOME=str(home / ".codex"),
        CURSOR_HOME=str(home / ".cursor"),
        BIN_HOME=str(home / ".local" / "bin"),
        PATH=f"{path_prefix}:/usr/bin:/bin" if path_prefix else "/usr/bin:/bin",
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
    for agent_dir in (".claude", ".gemini", ".codex", ".cursor"):
        handoff_link = home / agent_dir / "skills" / "handoff"
        assert handoff_link.is_symlink(), f"missing symlink: {handoff_link}"
        assert handoff_link.resolve() == (REPO / "skills" / "handoff").resolve()


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


def test_installer_keeps_t3_antigravity_sessions_hook_free(tmp_path: Path) -> None:
    # AGY harness bug: with any hook registered, killing a background task can
    # kill the T3 session for good (see install.sh comment).
    fresh = tmp_path / ".t3/userdata/providers/antigravity/fresh/config"
    old = tmp_path / ".t3/userdata/providers/antigravity/old/config"
    fresh.mkdir(parents=True)
    old.mkdir(parents=True)
    (old / "hooks.json").write_text('{"auto-handoff": {}}')

    result = run_install(tmp_path)

    assert result.returncode == 0, result.stderr
    assert not (fresh / "hooks.json").exists()
    assert not (old / "hooks.json").exists()
    assert (old / "hooks.json.disabled-agy-cancel-race").read_text() == '{"auto-handoff": {}}'


FAKE_GO = """#!/bin/sh
while [ "$1" != "-o" ]; do shift; done
printf '#!/bin/sh\\nexit %s\\n' "$FAKE_ENGINE_EXIT" > "$2"
chmod +x "$2"
"""


class TestEngineInstallGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.home = root / "home"
        self.installed = self.home / ".local" / "bin" / "vault-engine"
        self.installed.parent.mkdir(parents=True)
        self.installed.write_text("#!/bin/sh\nexit 0\n# previous\n")
        self.before = self.installed.read_bytes()
        fake = root / "fakebin"
        fake.mkdir()
        (fake / "go").write_text(FAKE_GO)
        (fake / "go").chmod(0o755)
        self.fake = str(fake)

    def install(self, engine_exit: str) -> subprocess.CompletedProcess[str]:
        os.environ["FAKE_ENGINE_EXIT"] = engine_exit
        self.addCleanup(os.environ.pop, "FAKE_ENGINE_EXIT", None)
        return run_install(self.home, path_prefix=self.fake)

    def test_engine_failing_context_keeps_the_installed_binary(self):
        result = self.install("3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.installed.read_bytes(), self.before)
        self.assertIn("vault-engine: the new build fails", result.stdout)

    def test_engine_passing_context_is_installed(self):
        result = self.install("0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.installed.read_bytes(), self.before)
        self.assertNotIn("keeping the installed binary", result.stdout)


if __name__ == "__main__":
    unittest.main()
