#!/usr/bin/env python3
"""Unit tests for bin/progress-sync.

Covers:
(1) Writes status block atomically and refuses or truncates so file stays <= 2048 bytes.
(2) Updates sdd/latest-progress.md symlink.
(3) With HERDR_PANE_ID set, calls pane report-metadata with --source sdd and state label;
    without it, calls no herdr.
(4) herdr failure or a call over 1 second never fails the command: file is written, exit 0,
    with a stderr warning.
(5) PROGRESS_SYNC=off exits 0 and does nothing.
(6) A --clear option clears the sidebar label.
(7) Source never invokes 'board'.
"""
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "progress-sync"

FAKE_HERDR_SCRIPT = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_HERDR_LOG"
if [ -n "$FAKE_HERDR_SLEEP" ]; then
    sleep "$FAKE_HERDR_SLEEP"
fi
if [ -n "$FAKE_HERDR_EXIT" ]; then
    echo "simulated herdr error" >&2
    exit "$FAKE_HERDR_EXIT"
fi
exit 0
"""


class TestProgressSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)

        # Set up a fake herdr executable
        bin_dir = self.tmp_path / "fake_bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        self.fake_herdr = bin_dir / "fake-herdr"
        self.fake_herdr.write_text(FAKE_HERDR_SCRIPT)
        self.fake_herdr.chmod(self.fake_herdr.stat().st_mode | stat.S_IXUSR)

        self.fake_log = self.tmp_path / "herdr.log"

    def run_sync(self, args, env_overrides=None, input_data=None, timeout=10):
        env = dict(os.environ)
        # Defaults for tests
        env["HERDR_CMD"] = str(self.fake_herdr)
        env["FAKE_HERDR_LOG"] = str(self.fake_log)
        # Clear HERDR_PANE_ID by default unless test explicitly sets it
        env.pop("HERDR_PANE_ID", None)
        env.pop("PROGRESS_SYNC", None)
        env.pop("FAKE_HERDR_SLEEP", None)
        env.pop("FAKE_HERDR_EXIT", None)

        if env_overrides:
            for k, v in env_overrides.items():
                if v is None:
                    env.pop(k, None)
                else:
                    env[k] = v

        cmd = [sys.executable, str(SCRIPT)] + args
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            stdin=subprocess.DEVNULL if input_data is None else None,
            input=input_data,
            timeout=timeout,
        )
        return proc

    def test_script_exists_and_executable(self):
        self.assertTrue(SCRIPT.exists(), f"{SCRIPT} must exist")
        self.assertTrue(os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable")

    def test_atomic_write_and_truncate_oversize(self):
        """(1) Writes atomically and truncates oversized input so file <= 2048 bytes."""
        progress_file = self.tmp_path / ".superpowers" / "sdd" / "test-plan" / "progress.md"
        # Create oversized content (> 2048 bytes)
        large_content = "# Progress\n" + ("A" * 3000) + "\n"

        proc = self.run_sync(["--file", str(progress_file), "--content", large_content])
        self.assertEqual(proc.returncode, 0, f"Sync failed: {proc.stderr}")
        self.assertTrue(progress_file.exists())

        size = progress_file.stat().st_size
        self.assertLessEqual(size, 2048, f"File size {size} exceeds 2048 bytes")
        self.assertEqual(size, 2048)

    def test_atomic_write_refuse_oversize(self):
        """(1) With --refuse, refuses to write if content exceeds 2048 bytes."""
        progress_file = self.tmp_path / ".superpowers" / "sdd" / "test-plan" / "progress.md"
        large_content = "# Progress\n" + ("B" * 3000)

        proc = self.run_sync(["--file", str(progress_file), "--content", large_content, "--refuse"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("exceed", proc.stderr.lower())
        self.assertFalse(progress_file.exists(), "File should not have been written on refusal")

    def test_updates_latest_progress_symlink(self):
        """(2) Updates the sdd/latest-progress.md symlink."""
        sdd_dir = self.tmp_path / ".superpowers" / "sdd"
        plan1_progress = sdd_dir / "plan-alpha" / "progress.md"
        symlink_path = sdd_dir / "latest-progress.md"

        proc = self.run_sync(["--file", str(plan1_progress), "--content", "# Plan Alpha\nBatch 1/2"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(symlink_path.is_symlink(), f"{symlink_path} must be a symlink")
        self.assertEqual(symlink_path.resolve(), plan1_progress.resolve())
        self.assertIn("Plan Alpha", symlink_path.read_text())

        # Now update with plan beta and check symlink points to beta
        plan2_progress = sdd_dir / "plan-beta" / "progress.md"
        proc2 = self.run_sync(["--file", str(plan2_progress), "--content", "# Plan Beta\nBatch 1/3"])
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertEqual(symlink_path.resolve(), plan2_progress.resolve())
        self.assertIn("Plan Beta", symlink_path.read_text())

    def test_herdr_called_when_pane_id_set(self):
        """(3) With HERDR_PANE_ID set, calls pane report-metadata with --source sdd and state label."""
        progress_file = self.tmp_path / "progress.md"
        proc = self.run_sync(
            ["--file", str(progress_file), "--content", "working", "--state-label", "working=Batch 1/2"],
            env_overrides={"HERDR_PANE_ID": "p-101"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.fake_log.exists(), "Fake herdr was not invoked")
        log_content = self.fake_log.read_text()
        self.assertIn("pane report-metadata", log_content)
        self.assertIn("p-101", log_content)
        self.assertIn("--source sdd", log_content)
        self.assertIn("--state-label working=Batch 1/2", log_content)

    def test_herdr_not_called_when_pane_id_unset(self):
        """(3) Without HERDR_PANE_ID, calls no herdr."""
        progress_file = self.tmp_path / "progress.md"
        proc = self.run_sync(
            ["--file", str(progress_file), "--content", "working", "--state-label", "working=Batch 1/2"],
            env_overrides={"HERDR_PANE_ID": None},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(self.fake_log.exists(), "Fake herdr should NOT have been invoked")

    def test_herdr_failure_fails_open(self):
        """(4) herdr failure never fails the command: file is written, exit 0, stderr warning."""
        progress_file = self.tmp_path / "progress.md"
        content = "# Step 1 complete\n"

        proc = self.run_sync(
            ["--file", str(progress_file), "--content", content, "--state-label", "working=Batch 1/2"],
            env_overrides={
                "HERDR_PANE_ID": "p-101",
                "FAKE_HERDR_EXIT": "2",
            },
        )
        self.assertEqual(proc.returncode, 0, "Command should exit 0 even if herdr fails")
        self.assertTrue(progress_file.exists())
        self.assertEqual(progress_file.read_text(), content)
        self.assertIn("warning", proc.stderr.lower())

    def test_herdr_timeout_fails_open(self):
        """(4) herdr call over 1 second never fails: file is written, exit 0, stderr warning."""
        progress_file = self.tmp_path / "progress.md"
        content = "# Step 2 complete\n"

        proc = self.run_sync(
            ["--file", str(progress_file), "--content", content, "--state-label", "working=Batch 2/2"],
            env_overrides={
                "HERDR_PANE_ID": "p-101",
                "FAKE_HERDR_SLEEP": "2",
            },
            timeout=5,
        )
        self.assertEqual(proc.returncode, 0, "Command should exit 0 even if herdr times out")
        self.assertTrue(progress_file.exists())
        self.assertEqual(progress_file.read_text(), content)
        self.assertIn("warning", proc.stderr.lower())
        self.assertIn("timed out", proc.stderr.lower())

    def test_progress_sync_off_does_nothing(self):
        """(5) PROGRESS_SYNC=off exits 0 and does nothing."""
        progress_file = self.tmp_path / "progress.md"
        proc = self.run_sync(
            ["--file", str(progress_file), "--content", "should not write", "--state-label", "working=Batch 1/2"],
            env_overrides={
                "PROGRESS_SYNC": "off",
                "HERDR_PANE_ID": "p-101",
            },
        )
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(progress_file.exists())
        self.assertFalse(self.fake_log.exists(), "herdr should not be called when PROGRESS_SYNC=off")

    def test_clear_option(self):
        """(6) A --clear option clears the sidebar label."""
        proc = self.run_sync(
            ["--clear"],
            env_overrides={"HERDR_PANE_ID": "p-101"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.fake_log.exists(), f"Log missing; stderr: {proc.stderr}")
        log_content = self.fake_log.read_text()
        self.assertIn("pane report-metadata", log_content)
        self.assertIn("p-101", log_content)
        self.assertIn("--source sdd", log_content)
        self.assertIn("--clear-state-labels", log_content)

    def test_clear_without_pane_id_is_noop(self):
        """(6) --clear without HERDR_PANE_ID exits 0 and calls no herdr."""
        proc = self.run_sync(["--clear"], env_overrides={"HERDR_PANE_ID": None})
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(self.fake_log.exists())

    def test_source_never_invokes_board(self):
        """(7) The source never invokes 'board'."""
        self.assertTrue(SCRIPT.exists())
        source = SCRIPT.read_text()
        # Verify no calls to board or boardd
        import re
        self.assertIsNone(
            re.search(r'\b(board|boardd|herdr-board)\b', source),
            "Source code must not mention or invoke 'board'",
        )

    def test_stdin_piped_content(self):
        """Piping content via stdin writes to target file."""
        progress_file = self.tmp_path / "progress.md"
        proc = self.run_sync(["--file", str(progress_file)], input_data="# Stdin content\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(progress_file.exists())
        self.assertEqual(progress_file.read_text(), "# Stdin content\n")

    def test_state_label_normalization(self):
        """State label without STATUS= is automatically normalized with working= prefix."""
        progress_file = self.tmp_path / "progress.md"
        proc = self.run_sync(
            ["--file", str(progress_file), "--content", "data", "--state-label", "Batch 1/2: working"],
            env_overrides={"HERDR_PANE_ID": "p-101"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        log_content = self.fake_log.read_text()
        self.assertIn("--state-label working=Batch 1/2: working", log_content)

    def test_state_label_inferred_from_markdown_content(self):
        """State label is inferred from content if not explicitly passed."""
        progress_file = self.tmp_path / "progress.md"
        content = "# Title\n\n**State:** Batch 3/5: working\n"
        proc = self.run_sync(
            ["--file", str(progress_file), "--content", content],
            env_overrides={"HERDR_PANE_ID": "p-101"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        log_content = self.fake_log.read_text()
        self.assertIn("--state-label working=Batch 3/5: working", log_content)

    def test_piped_input_late_arriving_read_in_full(self):
        """(1) Piped input arriving late (upstream sleeps 0.3s) is read in full."""
        progress_file = self.tmp_path / "progress.md"
        env = dict(os.environ)
        env["HERDR_CMD"] = str(self.fake_herdr)
        env["FAKE_HERDR_LOG"] = str(self.fake_log)
        env.pop("HERDR_PANE_ID", None)

        pipeline = f"(sleep 0.3 && printf '# Late arriving progress\\n') | '{sys.executable}' '{SCRIPT}' --file '{progress_file}'"
        proc = subprocess.run(
            ["bash", "-c", pipeline],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0, f"Sync failed: {proc.stderr}")
        self.assertTrue(progress_file.exists(), "Progress file was not created")
        self.assertEqual(progress_file.read_text(), "# Late arriving progress\n")

    def test_real_terminal_stdin_never_blocks(self):
        """(1) Real terminal stdin never blocks progress-sync."""
        import pty
        progress_file = self.tmp_path / "progress.md"
        env = dict(os.environ)
        env["HERDR_CMD"] = str(self.fake_herdr)
        env["FAKE_HERDR_LOG"] = str(self.fake_log)
        env.pop("HERDR_PANE_ID", None)

        master, slave = pty.openpty()
        try:
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--file", str(progress_file), "--state-label", "done"],
                stdin=slave,
                capture_output=True,
                text=True,
                env=env,
                timeout=2,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
        finally:
            os.close(master)
            os.close(slave)

    def test_bare_status_done_keeps_real_status(self):
        """(2) A bare status like 'done' keeps its real status, not 'working'."""
        progress_file = self.tmp_path / "progress.md"
        proc = self.run_sync(
            ["--file", str(progress_file), "--content", "finished", "--state-label", "done"],
            env_overrides={"HERDR_PANE_ID": "p-101"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        log_content = self.fake_log.read_text()
        self.assertIn("--state-label done=done", log_content)
        self.assertNotIn("--state-label working=done", log_content)

    def test_state_prefix_done_keeps_real_status(self):
        """(2) A status like 'State: done' keeps its real status, not 'working'."""
        progress_file = self.tmp_path / "progress.md"
        proc = self.run_sync(
            ["--file", str(progress_file), "--content", "finished", "--state-label", "State: done"],
            env_overrides={"HERDR_PANE_ID": "p-101"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        log_content = self.fake_log.read_text()
        self.assertIn("--state-label done=done", log_content)
        self.assertNotIn("--state-label working=", log_content)

    def test_markdown_bare_status_done_keeps_real_status(self):
        """(2) Inferred status from 'State: done' keeps real status 'done'."""
        progress_file = self.tmp_path / "progress.md"
        content = "# Title\n\n**State:** done\n"
        proc = self.run_sync(
            ["--file", str(progress_file), "--content", content],
            env_overrides={"HERDR_PANE_ID": "p-101"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        log_content = self.fake_log.read_text()
        self.assertIn("--state-label done=done", log_content)
        self.assertNotIn("--state-label working=done", log_content)

    def test_state_label_without_content_updates_existing_file(self):
        """(3) --state-label with no content updates the label in the existing file."""
        progress_file = self.tmp_path / "progress.md"
        initial_content = "# Progress\n\n**State:** working=Batch 1/2\n\nInitial notes.\n"
        progress_file.write_text(initial_content)

        proc = self.run_sync(
            ["--file", str(progress_file), "--state-label", "done"],
            env_overrides={"HERDR_PANE_ID": "p-101"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        updated_content = progress_file.read_text()
        self.assertIn("**State:** done", updated_content)
        self.assertNotIn("working=Batch 1/2", updated_content)
        self.assertIn("Initial notes.", updated_content)

    def test_state_label_without_content_creates_file_if_absent(self):
        """--state-label with no content and absent target file creates minimal progress.md."""
        progress_file = self.tmp_path / "progress_new.md"
        proc = self.run_sync(
            ["--file", str(progress_file), "--state-label", "State: done"],
            env_overrides={"HERDR_PANE_ID": "p-101"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(progress_file.exists())
        content = progress_file.read_text()
        self.assertIn("**State:** done", content)



if __name__ == "__main__":

    unittest.main()
