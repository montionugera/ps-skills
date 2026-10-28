#!/usr/bin/env python3
"""Tests for the closing banner of skills/handoff/scripts/herdr-handoff.sh.

A fake `herdr` on PATH answers the few calls the script makes; its pane status comes from
FAKE_STATUS. Nothing here starts an agent or a real Herdr tab."""
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "handoff" / "scripts" / "herdr-handoff.sh"

FAKE_HERDR = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
case "$1 $2" in
  "status server") echo "status: running" ;;
  "tab create") echo '{"result":{"tab":{"tab_id":"t9"},"root_pane":{"pane_id":"p9"}}}' ;;
  "pane list") echo '{"result":{"panes":[{"pane_id":"p9"}]}}' ;;
  "pane get") echo '{"result":{"pane":{"agent":"claude","agent_status":"'"$FAKE_STATUS"'"}}}' ;;
esac
exit 0
"""


class HerdrHandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        (d / "bin").mkdir()
        herdr = d / "bin" / "herdr"
        herdr.write_text(FAKE_HERDR)
        herdr.chmod(herdr.stat().st_mode | stat.S_IXUSR)
        self.log = d / "herdr.log"
        self.doc = d / "handoff-2026-10-19-test.md"
        self.doc.write_text("# Handoff\n## 1. Main Context\n")

    def run_script(self, *args, status="working", timeout=2, extra_env=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("HERDR", "T3", "CLAUDE"))}
        env.update({
            "PATH": f"{Path(self.tmp.name) / 'bin'}:{env['PATH']}", "FAKE_LOG": str(self.log),
            "FAKE_STATUS": status, "HERDR_TAB_ID": "t1", "T3CODE_HOME": self.tmp.name,
            "HERDR_HANDOFF_CONFIRM_TIMEOUT": str(timeout),
        })
        env.update(extra_env or {})
        r = subprocess.run(
            ["bash", str(SCRIPT), str(self.doc), "--kind", "claude", "--mode", "plan", "--multiplexer", "herdr",
             "--cwd", self.tmp.name, *args],
            capture_output=True, text=True, env=env, timeout=60,
        )
        return r

    def tab_create_line(self):
        return next(l for l in self.log.read_text().splitlines() if l.startswith("tab create"))

    def test_new_tab_is_pinned_to_the_callers_workspace(self):
        r = self.run_script("--running", "1", extra_env={"HERDR_WORKSPACE_ID": "w7"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--workspace w7", self.tab_create_line())

    def test_new_tab_omits_workspace_when_not_inside_herdr(self):
        r = self.run_script("--running", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("--workspace", self.tab_create_line())

    def test_running_agents_keep_the_tab_open_and_never_say_safe(self):
        r = self.run_script("--running", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("KEEP THIS TAB OPEN", r.stdout)
        self.assertIn("2 agents still running", r.stdout)
        self.assertNotIn("SAFE", r.stdout)
        self.assertNotIn("Closing THIS tab", r.stdout)

    def test_running_agents_win_over_close_source(self):
        r = self.run_script("--running", "1", "--close-source")
        self.assertIn("KEEP THIS TAB OPEN", r.stdout)
        self.assertNotIn("Closing THIS tab", r.stdout)

    def test_running_zero_closes_the_source_tab(self):
        r = self.run_script("--running", "0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Closing THIS tab (t1)", r.stdout)
        self.assertNotIn("KEEP", r.stdout)

    def test_leading_zero_is_decimal_not_octal(self):
        r = self.run_script("--running", "08")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("KEEP THIS TAB OPEN — 8 agents still running", r.stdout)
        self.assertNotIn("Closing THIS tab", r.stdout)

    def test_non_numeric_confirm_timeout_falls_back(self):
        r = self.run_script("--running", "1", timeout="abc")
        self.assertIn("HANDOFF CONFIRMED", r.stdout)
        self.assertNotIn("syntax error", r.stderr)

    def test_running_must_be_a_number(self):
        r = self.run_script("--running", "two")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--running", r.stderr)

    def test_no_flag_states_the_count_is_unknown_and_never_says_safe(self):
        r = self.run_script()
        self.assertIn("count unknown", r.stdout)
        self.assertNotIn("SAFE", r.stdout)

    def test_status_unknown_keeps_polling_and_only_warns_at_timeout(self):
        r = self.run_script("--running", "0", status="unknown", timeout=3)
        self.assertEqual(r.returncode, 1)
        self.assertIn("status unknown", r.stdout)
        self.assertNotIn("HANDOFF CONFIRMED", r.stdout)
        self.assertNotIn("Closing THIS tab", r.stdout)
        polls = [line for line in self.log.read_text().splitlines() if line.startswith("pane get")]
        self.assertGreaterEqual(len(polls), 3)

    def test_idle_blocked_and_working_count_as_confirmed(self):
        for status in ("idle", "blocked", "working"):
            with self.subTest(status=status):
                r = self.run_script("--running", "1", status=status)
                self.assertIn("HANDOFF CONFIRMED", r.stdout)


if __name__ == "__main__":
    unittest.main()
