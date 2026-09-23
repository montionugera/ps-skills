#!/usr/bin/env python3
"""
Unit tests for bin/sync-agent-rules (generate ~/.gemini/GEMINI.md from ~/.claude/CLAUDE.md).

Every test runs against temp files; the real ~/.claude and ~/.gemini are never touched.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "sync-agent-rules"

SOURCE_TEXT = """# Global Rules

## 1. NO MAGIC

- Tier 3: target tables have non-zero rows.

```bash
@not-an-import.md
```

Use `@Cache` from server-decorator.

@RTK.md
"""
RTK_TEXT = "# RTK\n\nrtk gain\n"


class SyncAgentRulesCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.src_dir = self.tmp / "claude"
        self.dst_dir = self.tmp / "gemini"
        self.src_dir.mkdir()
        self.dst_dir.mkdir()
        self.source = self.src_dir / "CLAUDE.md"
        self.target = self.dst_dir / "GEMINI.md"
        self.local = self.dst_dir / "GEMINI.local.md"
        self.source.write_text(SOURCE_TEXT)
        (self.src_dir / "RTK.md").write_text(RTK_TEXT)

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args,
             "--source", str(self.source), "--target", str(self.target)],
            capture_output=True, text=True, timeout=30,
            env={"HOME": str(self.tmp), "PATH": "/usr/bin:/bin"},
        )

    def backups(self):
        return sorted(self.dst_dir.glob("GEMINI.md.bak-*"))


class TestWrite(SyncAgentRulesCase):
    def test_write_creates_target_with_generated_header(self):
        proc = self.run_tool("--write")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = self.target.read_text()
        first = text.splitlines()[0]
        self.assertIn("GENERATED from", first)
        self.assertIn("CLAUDE.md", first)
        self.assertIn("by sync-agent-rules", first)
        self.assertIn("do not edit by hand", first)

    def test_write_carries_the_source_rules(self):
        self.run_tool("--write")
        self.assertIn("Tier 3: target tables have non-zero rows.", self.target.read_text())

    def test_import_line_is_resolved_inline(self):
        self.run_tool("--write")
        text = self.target.read_text()
        self.assertIn("rtk gain", text)
        self.assertNotIn("\n@RTK.md\n", text)

    def test_at_lines_inside_code_fences_and_mid_line_are_left_alone(self):
        self.run_tool("--write")
        text = self.target.read_text()
        self.assertIn("\n@not-an-import.md\n", text)
        self.assertIn("Use `@Cache` from server-decorator.", text)

    def test_missing_import_is_kept_verbatim_and_warned(self):
        (self.src_dir / "RTK.md").unlink()
        proc = self.run_tool("--write")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("\n@RTK.md\n", self.target.read_text())
        self.assertIn("RTK.md", proc.stderr)

    def test_import_cycle_terminates(self):
        (self.src_dir / "RTK.md").write_text("# RTK\n\n@CLAUDE.md\n")
        proc = self.run_tool("--write")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.target.read_text().count("# Global Rules"), 1)

    def test_nested_import_resolves_relative_to_the_importing_file(self):
        (self.src_dir / "sub").mkdir()
        (self.src_dir / "RTK.md").write_text("# RTK\n\n@sub/deep.md\n")
        (self.src_dir / "sub" / "deep.md").write_text("deep rule\n")
        self.run_tool("--write")
        self.assertIn("deep rule", self.target.read_text())

    def test_write_backs_up_the_existing_target_first(self):
        self.target.write_text("hand copy\n")
        proc = self.run_tool("--write")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "hand copy\n")
        self.assertRegex(backups[0].name, r"^GEMINI\.md\.bak-\d{8}-\d{6}$")
        self.assertIn("Tier 3", self.target.read_text())

    def test_write_is_a_no_op_when_already_in_sync(self):
        self.run_tool("--write")
        proc = self.run_tool("--write")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.backups(), [])

    def test_local_file_is_appended(self):
        self.local.write_text("# ClickUp Zen RFC\n\nagy-only rule\n")
        self.run_tool("--write")
        text = self.target.read_text()
        self.assertIn("agy-only rule", text)
        self.assertGreater(text.index("agy-only rule"), text.index("rtk gain"))

    def test_refuses_to_write_through_a_symlink_onto_the_source(self):
        self.target.symlink_to(self.source)
        proc = self.run_tool("--write")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.source.read_text(), SOURCE_TEXT)

    def test_missing_source_is_an_error_and_writes_nothing(self):
        self.source.unlink()
        proc = self.run_tool("--write")
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(self.target.exists())


class TestWriteSafety(SyncAgentRulesCase):
    """Review fixes: a backup is never clobbered and the file mode is never tightened."""

    def _load(self):
        from importlib.machinery import SourceFileLoader
        from importlib.util import module_from_spec, spec_from_loader
        loader = SourceFileLoader("sync_agent_rules", str(SCRIPT))
        mod = module_from_spec(spec_from_loader("sync_agent_rules", loader))
        loader.exec_module(mod)
        return mod

    def test_two_writes_in_the_same_second_keep_both_backups(self):
        import datetime as real_datetime
        mod = self._load()

        class FrozenClock(real_datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 9, 21, 12, 0, 0)

        mod.datetime = FrozenClock
        self.target.write_text("state one\n")
        mod.write("state two\n", self.source, self.target)
        mod.write("state three\n", self.source, self.target)
        contents = sorted(b.read_text() for b in self.backups())
        self.assertEqual(contents, ["state one\n", "state two\n"])

    def test_write_preserves_the_target_file_mode(self):
        for mode in (0o644, 0o600):
            with self.subTest(mode=oct(mode)):
                self.target.write_text("hand copy\n")
                self.target.chmod(mode)
                self.assertEqual(self.run_tool("--write").returncode, 0)
                self.assertEqual(self.target.stat().st_mode & 0o777, mode)

    def test_a_new_target_is_world_readable_like_any_rules_file(self):
        self.assertEqual(self.run_tool("--write").returncode, 0)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o644)


class TestCheck(SyncAgentRulesCase):
    def test_check_passes_after_write(self):
        self.run_tool("--write")
        proc = self.run_tool("--check")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_check_fails_with_a_diff_when_target_is_stale(self):
        self.run_tool("--write")
        self.source.write_text(SOURCE_TEXT.replace("Tier 3", "Tier 3 and Tier 4"))
        proc = self.run_tool("--check")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("+- Tier 3 and Tier 4", proc.stdout)
        self.assertIn("---", proc.stdout)

    def test_check_fails_when_target_is_missing(self):
        proc = self.run_tool("--check")
        self.assertEqual(proc.returncode, 1)

    def test_check_never_writes(self):
        self.target.write_text("hand copy\n")
        self.run_tool("--check")
        self.assertEqual(self.target.read_text(), "hand copy\n")
        self.assertEqual(self.backups(), [])

    def test_check_diff_is_bounded(self):
        self.target.write_text("".join(f"stale line {i}\n" for i in range(500)))
        proc = self.run_tool("--check", "--max-diff-lines", "20")
        self.assertEqual(proc.returncode, 1)
        self.assertLess(len(proc.stdout.splitlines()), 30)
        self.assertIn("more diff line", proc.stdout)

    def test_check_detects_a_change_in_the_local_file(self):
        self.run_tool("--write")
        self.local.write_text("new agy-only rule\n")
        self.assertEqual(self.run_tool("--check").returncode, 1)


class TestCli(SyncAgentRulesCase):
    def test_a_mode_is_required(self):
        self.assertEqual(self.run_tool().returncode, 2)

    def test_check_and_write_are_mutually_exclusive(self):
        self.assertEqual(self.run_tool("--check", "--write").returncode, 2)


if __name__ == "__main__":
    unittest.main()
