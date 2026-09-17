#!/usr/bin/env python3
"""
Unit tests for bin/dispatch-agy-worker and bin/dispatch-codex-worker
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = REPO_ROOT / "bin"
SCRIPT_PATH = BIN_DIR / "dispatch-agy-worker"
CODEX_SCRIPT_PATH = BIN_DIR / "dispatch-codex-worker"

import importlib.machinery
import importlib.util
loader = importlib.machinery.SourceFileLoader("dispatch_agy_worker", str(SCRIPT_PATH))
spec = importlib.util.spec_from_loader("dispatch_agy_worker", loader)
dispatch_mod = importlib.util.module_from_spec(spec)
loader.exec_module(dispatch_mod)


class TestQuotaLogic(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.agy_file = Path(self.temp_dir.name) / "agy-status.json"
        self.codex_file = Path(self.temp_dir.name) / "codex-status.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_state(self, path, content):
        path.write_text(json.dumps(content), encoding="utf-8")

    def test_agy_quota_healthy(self):
        self._write_state(self.agy_file, {
            "snapshot": {
                "windows": [
                    {"kind": "five_hour", "remaining_percent": 85.0},
                    {"kind": "weekly", "remaining_percent": 95.0}
                ]
            }
        })
        eligible, rem_5h, rem_weekly, msg = dispatch_mod.check_quota("agy", str(self.agy_file), min_5h=30.0, min_weekly=10.0)
        self.assertTrue(eligible)
        self.assertEqual(rem_5h, 85.0)
        self.assertEqual(rem_weekly, 95.0)
        self.assertIn("[AGY]", msg)

    def test_codex_quota_healthy(self):
        self._write_state(self.codex_file, {
            "windows": [
                {"kind": "five_hour", "remaining_percent": 100.0},
                {"kind": "weekly", "remaining_percent": 98.0}
            ]
        })
        eligible, rem_5h, rem_weekly, msg = dispatch_mod.check_quota("codex", str(self.codex_file), min_5h=30.0, min_weekly=10.0)
        self.assertTrue(eligible)
        self.assertEqual(rem_5h, 100.0)
        self.assertEqual(rem_weekly, 98.0)
        self.assertIn("[CODEX]", msg)

    def test_codex_quota_5h_too_low(self):
        self._write_state(self.codex_file, {
            "windows": [
                {"kind": "five_hour", "remaining_percent": 20.0},
                {"kind": "weekly", "remaining_percent": 95.0}
            ]
        })
        eligible, rem_5h, rem_weekly, msg = dispatch_mod.check_quota("codex", str(self.codex_file), min_5h=30.0, min_weekly=10.0)
        self.assertFalse(eligible)
        self.assertEqual(rem_5h, 20.0)
        self.assertIn("20.0%", msg)

    def test_quota_payload_fallback(self):
        self._write_state(self.agy_file, {
            "payload": {
                "quota": {
                    "gemini-5h": {"remaining_fraction": 0.55},
                    "gemini-weekly": {"remaining_fraction": 0.80}
                }
            }
        })
        eligible, rem_5h, rem_weekly, msg = dispatch_mod.check_quota("agy", str(self.agy_file), min_5h=30.0, min_weekly=10.0)
        self.assertTrue(eligible)
        self.assertAlmostEqual(rem_5h, 55.0)
        self.assertAlmostEqual(rem_weekly, 80.0)

    def test_missing_state_file(self):
        non_existent = Path(self.temp_dir.name) / "does-not-exist.json"
        eligible, rem_5h, rem_weekly, msg = dispatch_mod.check_quota("agy", str(non_existent))
        self.assertFalse(eligible)
        self.assertIn("not found", msg)

    def test_corrupt_json(self):
        self.agy_file.write_text("NOT_JSON_DATA", encoding="utf-8")
        eligible, rem_5h, rem_weekly, msg = dispatch_mod.check_quota("agy", str(self.agy_file))
        self.assertFalse(eligible)
        self.assertIn("Failed to parse", msg)


class TestWindowRollover(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "rollover-state.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_5h_window_rollover_when_resets_at_in_past(self):
        now = 1789658000
        past_reset = 1789657000  # resets_at < now -> replenished to 100%
        content = {
            "snapshot": {
                "windows": [
                    {"kind": "five_hour", "remaining_percent": 15.0, "resets_at": past_reset},
                    {"kind": "weekly", "remaining_percent": 90.0, "resets_at": now + 50000}
                ]
            }
        }
        self.state_file.write_text(json.dumps(content), encoding="utf-8")
        eligible, rem_5h, rem_weekly, msg = dispatch_mod.check_quota(
            "agy", str(self.state_file), min_5h=30.0, min_weekly=10.0, current_time=now
        )
        self.assertTrue(eligible)
        self.assertEqual(rem_5h, 100.0)
        self.assertEqual(rem_weekly, 90.0)

    def test_5h_window_no_rollover_when_resets_at_in_future(self):
        now = 1789658000
        future_reset = 1789660000  # resets_at > now -> not replenished
        content = {
            "snapshot": {
                "windows": [
                    {"kind": "five_hour", "remaining_percent": 15.0, "resets_at": future_reset},
                    {"kind": "weekly", "remaining_percent": 90.0, "resets_at": now + 50000}
                ]
            }
        }
        self.state_file.write_text(json.dumps(content), encoding="utf-8")
        eligible, rem_5h, rem_weekly, msg = dispatch_mod.check_quota(
            "agy", str(self.state_file), min_5h=30.0, min_weekly=10.0, current_time=now
        )
        self.assertFalse(eligible)
        self.assertEqual(rem_5h, 15.0)

    def test_rollover_iso8601_format(self):
        now = 1789658000  # 2026-09-17 approx
        # ISO string in past
        content = {
            "payload": {
                "quota": {
                    "gemini-5h": {"remaining_fraction": 0.10, "reset_time": "2026-09-17T00:00:00Z"},
                    "gemini-weekly": {"remaining_fraction": 0.80, "reset_time": "2026-09-24T00:00:00Z"}
                }
            }
        }
        self.state_file.write_text(json.dumps(content), encoding="utf-8")
        eligible, rem_5h, rem_weekly, msg = dispatch_mod.check_quota(
            "agy", str(self.state_file), min_5h=30.0, min_weekly=10.0, current_time=now
        )
        self.assertTrue(eligible)
        self.assertEqual(rem_5h, 100.0)


class TestBestRunwayAutoRouting(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.agy_file = Path(self.temp_dir.name) / "agy-state.json"
        self.codex_file = Path(self.temp_dir.name) / "codex-state.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_quota(self, file_path, rem_5h, rem_weekly):
        file_path.write_text(json.dumps({
            "windows": [
                {"kind": "five_hour", "remaining_percent": rem_5h},
                {"kind": "weekly", "remaining_percent": rem_weekly}
            ]
        }), encoding="utf-8")

    def test_runway_calculation(self):
        # min_5h=30, min_weekly=10
        # 5h=60 (surplus 30), weekly=90 (surplus 80) -> runway = min(30, 80) = 30
        runway = dispatch_mod.calculate_runway(60.0, 90.0, min_5h=30.0, min_weekly=10.0)
        self.assertEqual(runway, 30.0)

        # 5h=90 (surplus 60), weekly=25 (surplus 15) -> runway = min(60, 15) = 15
        runway2 = dispatch_mod.calculate_runway(90.0, 25.0, min_5h=30.0, min_weekly=10.0)
        self.assertEqual(runway2, 15.0)

    def test_auto_picks_agent_with_higher_runway(self):
        # agy: 5h=40 (surplus 10), weekly=80 (surplus 70) -> runway = 10
        self._write_quota(self.agy_file, 40.0, 80.0)
        # codex: 5h=70 (surplus 40), weekly=90 (surplus 80) -> runway = 40
        self._write_quota(self.codex_file, 70.0, 90.0)

        agent, eligible, r5, rw, msg = dispatch_mod.route_best_agent(
            min_5h=30.0, min_weekly=10.0,
            agy_state_file=str(self.agy_file),
            codex_state_file=str(self.codex_file)
        )
        self.assertEqual(agent, "codex")
        self.assertTrue(eligible)
        self.assertEqual(r5, 70.0)
        self.assertIn("runway: 40.0", msg)

    def test_auto_picks_agy_when_agy_has_higher_runway(self):
        # agy: 5h=90 (surplus 60), weekly=95 (surplus 85) -> runway = 60
        self._write_quota(self.agy_file, 90.0, 95.0)
        # codex: 5h=50 (surplus 20), weekly=90 (surplus 80) -> runway = 20
        self._write_quota(self.codex_file, 50.0, 90.0)

        agent, eligible, r5, rw, msg = dispatch_mod.route_best_agent(
            min_5h=30.0, min_weekly=10.0,
            agy_state_file=str(self.agy_file),
            codex_state_file=str(self.codex_file)
        )
        self.assertEqual(agent, "agy")
        self.assertTrue(eligible)
        self.assertEqual(r5, 90.0)
        self.assertIn("runway: 60.0", msg)

    def test_auto_fails_when_both_have_negative_runway(self):
        # agy: 5h=20 (surplus -10), weekly=50 -> runway = -10
        self._write_quota(self.agy_file, 20.0, 50.0)
        # codex: 5h=50, weekly=5 (surplus -5) -> runway = -5
        self._write_quota(self.codex_file, 50.0, 5.0)

        agent, eligible, r5, rw, msg = dispatch_mod.route_best_agent(
            min_5h=30.0, min_weekly=10.0,
            agy_state_file=str(self.agy_file),
            codex_state_file=str(self.codex_file)
        )
        self.assertFalse(eligible)
        self.assertIn("Auto routing failed", msg)


class TestPromptContract(unittest.TestCase):
    def test_wrap_prompt_contract_includes_rules(self):
        raw_prompt = "Implement feature X and fix bug Y."
        wrapped = dispatch_mod.wrap_prompt_contract(raw_prompt)

        # Check required rules
        self.assertIn("Test-Driven Development (TDD)", wrapped)
        self.assertIn("never git commit --amend", wrapped.lower())
        self.assertIn("preserve protected config files", wrapped.lower())
        self.assertIn(".release.json", wrapped)
        self.assertIn("Task Brief:\nImplement feature X and fix bug Y.", wrapped)


class TestReportFormatting(unittest.TestCase):
    def test_report_line_count_and_content(self):
        long_output = "\n".join([f"log line {i}" for i in range(50)])
        report = dispatch_mod.format_report(
            agent="agy",
            status="SUCCESS",
            exit_code=0,
            cwd="/test/dir",
            files_changed=2,
            diff_summary="2 files changed, 10 insertions(+)",
            tail_output=long_output
        )
        lines = report.splitlines()
        self.assertLessEqual(len(lines), 15)
        self.assertEqual(lines[0], "=== AGY SUBAGENT REPORT ===")
        self.assertIn("Status: SUCCESS (exit 0)", lines[1])
        self.assertIn("Directory: /test/dir", lines[2])
        self.assertIn("Files Modified: 2 (2 files changed, 10 insertions(+))", lines[3])
        self.assertEqual(lines[-1], "===========================")

    def test_codex_report_header(self):
        report = dispatch_mod.format_report(
            agent="codex",
            status="SUCCESS",
            exit_code=0,
            cwd="/test/dir",
            files_changed=1,
            diff_summary="1 file changed",
            tail_output="done"
        )
        self.assertIn("=== CODEX SUBAGENT REPORT ===", report)


class TestCLIExecution(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "test-quota.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_state(self, rem_5h, rem_weekly):
        content = {
            "snapshot": {
                "windows": [
                    {"kind": "five_hour", "remaining_percent": rem_5h},
                    {"kind": "weekly", "remaining_percent": rem_weekly}
                ]
            }
        }
        self.state_file.write_text(json.dumps(content), encoding="utf-8")

    def test_cli_check_quota_healthy(self):
        self._write_state(80.0, 90.0)
        res = subprocess.run(
            [str(SCRIPT_PATH), "--check-quota", "--state-file", str(self.state_file)],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("80.0%", res.stdout)

    def test_cli_check_quota_low(self):
        self._write_state(20.0, 90.0)
        res = subprocess.run(
            [str(SCRIPT_PATH), "--check-quota", "--state-file", str(self.state_file)],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("20.0%", res.stdout)

    def test_cli_codex_binary_invocation(self):
        self._write_state(85.0, 95.0)
        res = subprocess.run(
            [str(CODEX_SCRIPT_PATH), "--check-quota", "--state-file", str(self.state_file)],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("[CODEX]", res.stdout)

    def test_cli_codex_dry_run_with_terra(self):
        self._write_state(85.0, 95.0)
        res = subprocess.run(
            [str(CODEX_SCRIPT_PATH), "--task", "test", "--dry-run", "--state-file", str(self.state_file)],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("gpt-5.6-terra", res.stdout)

    def test_cli_fallback_exit_code_10_when_quota_insufficient(self):
        self._write_state(15.0, 80.0)
        res = subprocess.run(
            [str(SCRIPT_PATH), "--task", "test task", "--state-file", str(self.state_file)],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 10)
        self.assertIn("FALLBACK_INTERNAL", res.stdout)

    def test_cli_missing_task_arg(self):
        res = subprocess.run(
            [str(SCRIPT_PATH)],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 2)

    def test_cli_dry_run_isolated_flag(self):
        self._write_state(85.0, 95.0)
        res = subprocess.run(
            [str(SCRIPT_PATH), "--task", "test task", "--dry-run", "--isolated", "--state-file", str(self.state_file)],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("[isolated worktree]", res.stdout)

    def test_cli_priority_mode_subscription_skips_cursor(self):
        self._write_state(85.0, 95.0)
        res = subprocess.run(
            [str(SCRIPT_PATH), "--priority", "cursor:gemini-3.8-flash > agy", "--mode", "subscription_quota_remaining", "--task", "test", "--dry-run", "--state-file", str(self.state_file)],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Would dispatch to agy", res.stdout)

    def test_cli_priority_mode_on_demand_allows_cursor(self):
        fake_bin_dir = Path(self.temp_dir.name) / "bin"
        fake_bin_dir.mkdir(exist_ok=True)
        fake_cursor = fake_bin_dir / "cursor-agent"
        fake_cursor.write_text("#!/bin/sh\necho 'Logged in as test@example.com'\nexit 0\n")
        fake_cursor.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{fake_bin_dir}:{env.get('PATH', '')}"

        res = subprocess.run(
            [str(SCRIPT_PATH), "--priority", "cursor:gemini-3.8-flash > agy", "--mode", "on_demand", "--task", "test", "--dry-run"],
            capture_output=True,
            text=True,
            env=env
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Would dispatch to cursor with gemini-3.8-flash", res.stdout)

    def test_execute_in_isolated_worktree_applies_changes_and_cleans_up(self):
        # Create a git repo in temp dir to test execute_in_isolated_worktree
        repo_dir = Path(self.temp_dir.name) / "test-repo"
        repo_dir.mkdir()
        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True, capture_output=True)
        (repo_dir / "initial.txt").write_text("initial content\n", encoding="utf-8")
        subprocess.run(["git", "add", "initial.txt"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo_dir, check=True, capture_output=True)

        captured_worktree = []

        def worker_callback(wt_dir):
            captured_worktree.append(wt_dir)
            # Create a new file and edit existing file in the worktree
            (Path(wt_dir) / "new_file.txt").write_text("created in worktree\n", encoding="utf-8")
            (Path(wt_dir) / "initial.txt").write_text("modified in worktree\n", encoding="utf-8")
            return 0, "mock stdout", "", 2, "2 files modified"

        exit_code, stdout, stderr, files_changed, diff_summary = dispatch_mod.execute_in_isolated_worktree(
            str(repo_dir), worker_callback
        )

        self.assertEqual(exit_code, 0)
        # Verify changes were applied back to repo_dir
        self.assertEqual((repo_dir / "initial.txt").read_text(encoding="utf-8"), "modified in worktree\n")
        self.assertTrue((repo_dir / "new_file.txt").exists())
        self.assertEqual((repo_dir / "new_file.txt").read_text(encoding="utf-8"), "created in worktree\n")

        # Verify worktree directory was cleaned up
        self.assertEqual(len(captured_worktree), 1)
        self.assertFalse(os.path.exists(captured_worktree[0]))


class TestPriorityChainRouting(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.agy_file = Path(self.temp_dir.name) / "agy.json"
        self.codex_file = Path(self.temp_dir.name) / "codex.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_priority_chain(self):
        chain_str = "cursor:gemini-3.8-flash > gemini > codex:terra:5.6"
        chain = dispatch_mod.parse_priority_chain(chain_str)
        self.assertEqual(len(chain), 3)
        self.assertEqual(chain[0], ("cursor", "gemini-3.8-flash"))
        self.assertEqual(chain[1], ("agy", None))
        self.assertEqual(chain[2], ("codex", "gpt-5.6-terra"))

    def test_waterfall_skips_cursor_when_on_demand_disallowed(self):
        # agy is healthy
        self.agy_file.write_text(json.dumps({
            "windows": [
                {"kind": "five_hour", "remaining_percent": 80.0},
                {"kind": "weekly", "remaining_percent": 90.0}
            ]
        }))
        chain = dispatch_mod.parse_priority_chain("cursor:gemini-3.8-flash > agy > codex")
        agent, model, eligible, r5, rw, msg = dispatch_mod.route_priority_chain(
            chain,
            allow_on_demand=False,
            agy_state_file=str(self.agy_file),
            codex_state_file=str(self.codex_file)
        )
        self.assertTrue(eligible)
        self.assertEqual(agent, "agy")

    def test_waterfall_routes_to_codex_when_agy_low(self):
        self.agy_file.write_text(json.dumps({
            "windows": [
                {"kind": "five_hour", "remaining_percent": 10.0},
                {"kind": "weekly", "remaining_percent": 90.0}
            ]
        }))
        self.codex_file.write_text(json.dumps({
            "windows": [
                {"kind": "five_hour", "remaining_percent": 85.0},
                {"kind": "weekly", "remaining_percent": 95.0}
            ]
        }))
        chain = dispatch_mod.parse_priority_chain("cursor:gemini-3.8-flash > agy > codex:terra:5.6")
        agent, model, eligible, r5, rw, msg = dispatch_mod.route_priority_chain(
            chain,
            allow_on_demand=False,
            agy_state_file=str(self.agy_file),
            codex_state_file=str(self.codex_file)
        )
        self.assertTrue(eligible)
        self.assertEqual(agent, "codex")
        self.assertEqual(model, "gpt-5.6-terra")

    def test_waterfall_all_exhausted_returns_not_eligible(self):
        self.agy_file.write_text(json.dumps({
            "windows": [
                {"kind": "five_hour", "remaining_percent": 10.0},
                {"kind": "weekly", "remaining_percent": 90.0}
            ]
        }))
        self.codex_file.write_text(json.dumps({
            "windows": [
                {"kind": "five_hour", "remaining_percent": 15.0},
                {"kind": "weekly", "remaining_percent": 95.0}
            ]
        }))
        chain = dispatch_mod.parse_priority_chain("cursor > agy > codex")
        agent, model, eligible, r5, rw, msg = dispatch_mod.route_priority_chain(
            chain,
            allow_on_demand=False,
            agy_state_file=str(self.agy_file),
            codex_state_file=str(self.codex_file)
        )
        self.assertFalse(eligible)
        self.assertIn("Chain exhausted", msg)


class TestConfigLoading(unittest.TestCase):
    def test_load_dispatch_config(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("# comment\n")
            f.write("DISPATCH_ROUTING_PREFERENCE=\"cursor:gemini-3.8-flash > codex\"\n")
            f.write("DISPATCH_ALLOW_ON_DEMAND=1\n")
            temp_config = f.name

        try:
            cfg = dispatch_mod.load_dispatch_config(temp_config)
            self.assertEqual(cfg.get("DISPATCH_ROUTING_PREFERENCE"), "cursor:gemini-3.8-flash > codex")
            self.assertEqual(cfg.get("DISPATCH_ALLOW_ON_DEMAND"), "1")
        finally:
            if os.path.exists(temp_config):
                os.unlink(temp_config)

    def test_load_explicit_ai_agent_config(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("# explicit modern config\n")
            f.write("AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_MODE=\"subscription_quota_remaining\"\n")
            f.write("AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_ROUTING_PREFERENCE=\"cursor:gemini-3.8-flash > agy > codex\"\n")
            temp_config = f.name

        try:
            cfg = dispatch_mod.load_dispatch_config(temp_config)
            mode_str, is_on_demand = dispatch_mod.get_config_mode(cfg)
            pref = dispatch_mod.get_config_preference(cfg)
            self.assertEqual(mode_str, "subscription_quota_remaining")
            self.assertFalse(is_on_demand)
            self.assertEqual(pref, "cursor:gemini-3.8-flash > agy > codex")
        finally:
            if os.path.exists(temp_config):
                os.unlink(temp_config)

    def test_get_config_mode_on_demand(self):
        cfg = {"AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_MODE": "on_demand"}
        mode_str, is_on_demand = dispatch_mod.get_config_mode(cfg)
        self.assertEqual(mode_str, "on_demand")
        self.assertTrue(is_on_demand)

    def test_get_config_mode_fallback_allow_on_demand(self):
        cfg = {"DISPATCH_ALLOW_ON_DEMAND": "1"}
        mode_str, is_on_demand = dispatch_mod.get_config_mode(cfg)
        self.assertEqual(mode_str, "on_demand")
        self.assertTrue(is_on_demand)

    def test_get_config_preference_precedence(self):
        cfg = {
            "AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_ROUTING_PREFERENCE": "explicit > chain",
            "DISPATCH_ROUTING_PREFERENCE": "old > chain"
        }
        self.assertEqual(dispatch_mod.get_config_preference(cfg), "explicit > chain")


if __name__ == "__main__":
    unittest.main()

