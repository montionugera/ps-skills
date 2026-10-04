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
from unittest import mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = REPO_ROOT / "bin"
SCRIPT_PATH = BIN_DIR / "dispatch-agy-worker"
CODEX_SCRIPT_PATH = BIN_DIR / "dispatch-codex-worker"

# Keep every in-process and CLI test run out of the user's real ~/.local/state/dispatch/events.jsonl.
_EVENTS_TMP = tempfile.TemporaryDirectory()
os.environ["DISPATCH_EVENTS_FILE"] = str(Path(_EVENTS_TMP.name) / "events.jsonl")

import importlib.machinery
import importlib.util
loader = importlib.machinery.SourceFileLoader("dispatch_agy_worker", str(SCRIPT_PATH))
spec = importlib.util.spec_from_loader("dispatch_agy_worker", loader)
dispatch_mod = importlib.util.module_from_spec(spec)
loader.exec_module(dispatch_mod)


def codex_enabled():
    """Codex is in DISABLED_AGENTS. Tests of the dormant codex code paths switch it back on in-process."""
    return mock.patch.object(dispatch_mod, "DISABLED_AGENTS", frozenset())


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

    def _write_healthy_state(self, age_minutes, now):
        content = {"snapshot": {"windows": [
            {"kind": "five_hour", "remaining_percent": 90.0, "resets_at": now + 5000},
            {"kind": "weekly", "remaining_percent": 90.0, "resets_at": now + 50000},
        ]}}
        self.state_file.write_text(json.dumps(content), encoding="utf-8")
        mtime = now - age_minutes * 60
        os.utime(self.state_file, (mtime, mtime))

    def test_stale_observation_is_not_eligible(self):
        now = time.time()
        self._write_healthy_state(dispatch_mod.STALE_OBSERVATION_MINUTES + 30, now)
        eligible, rem_5h, _rem_weekly, msg = dispatch_mod.check_quota(
            "agy", str(self.state_file), min_5h=30.0, min_weekly=10.0, current_time=now
        )
        self.assertFalse(eligible)
        self.assertEqual(rem_5h, 90.0)
        self.assertIn("stale", msg)
        self.assertIn("not eligible", msg)

    def test_fresh_observation_within_threshold_stays_eligible(self):
        now = time.time()
        self._write_healthy_state(dispatch_mod.STALE_OBSERVATION_MINUTES - 5, now)
        eligible, _r5, _rw, msg = dispatch_mod.check_quota(
            "agy", str(self.state_file), min_5h=30.0, min_weekly=10.0, current_time=now
        )
        self.assertTrue(eligible)
        self.assertNotIn("stale", msg)

    def _write_state(self, now, fetched_age_minutes=None, mtime_age_minutes=0, reset_5h=5000, reset_weekly=50000):
        snapshot = {"windows": [
            {"kind": "five_hour", "remaining_percent": 90.0, "resets_at": now + reset_5h},
            {"kind": "weekly", "remaining_percent": 90.0, "resets_at": now + reset_weekly},
        ]}
        if fetched_age_minutes is not None:
            snapshot["fetched_at_unix"] = int(now - fetched_age_minutes * 60)
        self.state_file.write_text(json.dumps({"snapshot": snapshot}), encoding="utf-8")
        mtime = now - mtime_age_minutes * 60
        os.utime(self.state_file, (mtime, mtime))

    def _check(self, now):
        return dispatch_mod.check_quota("agy", str(self.state_file), min_5h=30.0, min_weekly=10.0, current_time=now)

    def test_age_is_judged_from_fetched_at_not_mtime(self):
        now = time.time()
        self._write_state(now, fetched_age_minutes=5, mtime_age_minutes=dispatch_mod.STALE_OBSERVATION_MINUTES + 30)
        eligible, _r5, _rw, msg = self._check(now)
        self.assertTrue(eligible, msg)
        self.assertNotIn("stale", msg)

        self._write_state(now, fetched_age_minutes=dispatch_mod.STALE_OBSERVATION_MINUTES + 30, mtime_age_minutes=0)
        eligible, _r5, _rw, msg = self._check(now)
        self.assertFalse(eligible)
        self.assertIn("stale", msg)

    def test_old_observation_is_not_stale_once_both_windows_have_reset(self):
        now = time.time()
        self._write_state(now, fetched_age_minutes=600, mtime_age_minutes=600, reset_5h=-60, reset_weekly=-60)
        eligible, rem_5h, rem_weekly, msg = self._check(now)
        self.assertTrue(eligible, msg)
        self.assertEqual((rem_5h, rem_weekly), (100.0, 100.0))
        self.assertNotIn("stale", msg)

    def test_old_observation_stays_stale_while_one_window_has_not_reset(self):
        now = time.time()
        self._write_state(now, fetched_age_minutes=600, mtime_age_minutes=600, reset_5h=-60)
        eligible, rem_5h, _rw, msg = self._check(now)
        self.assertFalse(eligible)
        self.assertEqual(rem_5h, 100.0)
        self.assertIn("stale", msg)

    def test_allow_stale_keeps_a_stale_observation_eligible(self):
        now = time.time()
        self._write_state(now, fetched_age_minutes=600, mtime_age_minutes=600)
        with mock.patch.object(dispatch_mod, "ALLOW_STALE", True, create=True):
            eligible, _r5, _rw, msg = self._check(now)
        self.assertTrue(eligible, msg)
        self.assertIn("stale", msg)
        self.assertIn("--allow-stale", msg)


@codex_enabled()
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

    def _age(self, file_path, now):
        mtime = now - (dispatch_mod.STALE_OBSERVATION_MINUTES + 30) * 60
        os.utime(file_path, (mtime, mtime))

    def test_auto_skips_stale_agent_even_with_higher_runway(self):
        now = time.time()
        self._write_quota(self.agy_file, 95.0, 95.0)  # best runway, but the observation is stale
        self._write_quota(self.codex_file, 50.0, 90.0)
        self._age(self.agy_file, now)

        agent, eligible, r5, _rw, _msg = dispatch_mod.route_best_agent(
            min_5h=30.0, min_weekly=10.0, agy_state_file=str(self.agy_file),
            codex_state_file=str(self.codex_file), current_time=now
        )
        self.assertEqual(agent, "codex")
        self.assertTrue(eligible)
        self.assertEqual(r5, 50.0)

    def test_auto_fails_when_both_observations_are_stale(self):
        now = time.time()
        self._write_quota(self.agy_file, 95.0, 95.0)
        self._write_quota(self.codex_file, 90.0, 90.0)
        self._age(self.agy_file, now)
        self._age(self.codex_file, now)

        _agent, eligible, _r5, _rw, msg = dispatch_mod.route_best_agent(
            min_5h=30.0, min_weekly=10.0, agy_state_file=str(self.agy_file),
            codex_state_file=str(self.codex_file), current_time=now
        )
        self.assertFalse(eligible)
        self.assertIn("Auto routing failed", msg)
        self.assertIn("stale", msg)


class TestPromptContract(unittest.TestCase):
    def test_wrap_prompt_contract_includes_rules(self):
        raw_prompt = "Implement feature X and fix bug Y."
        wrapped = dispatch_mod.wrap_prompt_contract(raw_prompt)

        # Check required rules
        self.assertIn("Test-Driven Development (TDD)", wrapped)
        self.assertIn("never git commit --amend", wrapped.lower())
        self.assertIn("preserve protected config files", wrapped.lower())
        self.assertIn("Scoped Verification", wrapped)
        self.assertIn("TARGETED unit tests", wrapped)
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

    def test_execute_in_isolated_worktree_salvages_on_failure(self):
        repo_dir = Path(self.temp_dir.name) / "test-salvage-repo"
        repo_dir.mkdir()
        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True, capture_output=True)
        (repo_dir / "initial.txt").write_text("initial content\n", encoding="utf-8")
        subprocess.run(["git", "add", "initial.txt"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo_dir, check=True, capture_output=True)

        def failing_worker(wt_dir):
            (Path(wt_dir) / "partial_fix.txt").write_text("critical partial fix\n", encoding="utf-8")
            return 1, "", "FAILED: timed out", 1, "1 file modified"

        exit_code, stdout, stderr, files_changed, diff_summary = dispatch_mod.execute_in_isolated_worktree(
            str(repo_dir), failing_worker
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("[Salvage] Partial work preserved at", stderr)
        patch_path = stderr.split("[Salvage] Partial work preserved at")[-1].strip()
        self.assertTrue(os.path.isfile(patch_path))
        patch_content = Path(patch_path).read_text(encoding="utf-8")
        self.assertIn("critical partial fix", patch_content)
        if os.path.exists(patch_path):
            os.unlink(patch_path)


class TestTimeoutAndGitInspection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name) / "test-repo"
        self.repo_dir.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.repo_dir, check=True, capture_output=True)
        (self.repo_dir / "base.txt").write_text("base content\n", encoding="utf-8")
        subprocess.run(["git", "add", "base.txt"], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "base commit"], cwd=self.repo_dir, check=True, capture_output=True)
        self.initial_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo_dir, capture_output=True, text=True
        ).stdout.strip()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_execute_worker_process_timeout_handling(self):
        cmd = ["python3", "-c", "import time, sys; sys.stdout.write('partial output\\n'); sys.stdout.flush(); time.sleep(5)"]
        exit_code, stdout, stderr, is_timeout = dispatch_mod.execute_worker_process(
            cmd, str(self.repo_dir), timeout_seconds=1, agent_name="test-worker"
        )
        self.assertEqual(exit_code, 124)
        self.assertTrue(is_timeout)
        self.assertIn("FAILED: test-worker timed out after 1s.", stderr)
        self.assertIn("partial output", stdout)

    def test_execute_worker_process_timeout_kills_grandchildren_holding_pipes(self):
        # A backgrounded grandchild inherits stdout/stderr. Killing only the direct child either hangs
        # communicate() (older Pythons) or leaves the grandchild running; the whole group must die.
        pid_file = Path(self.temp_dir.name) / "grandchild.pid"
        cmd = ["sh", "-c", f"sleep 30 & echo $! > {pid_file}; sleep 30"]
        start = time.monotonic()
        exit_code, _stdout, stderr, is_timeout = dispatch_mod.execute_worker_process(
            cmd, str(self.repo_dir), timeout_seconds=1, agent_name="test-worker"
        )
        self.assertLess(time.monotonic() - start, 10)
        self.assertTrue(is_timeout)
        self.assertEqual(exit_code, 124)
        self.assertIn("FAILED: test-worker timed out after 1s.", stderr)
        grandchild = int(pid_file.read_text().strip())
        deadline = time.monotonic() + 5
        alive = True
        while alive and time.monotonic() < deadline:
            try:
                os.kill(grandchild, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                alive = False
        if alive:
            os.kill(grandchild, 9)
        self.assertFalse(alive, "grandchild survived the worker timeout")

    def test_execute_worker_process_returns_promptly_when_descendant_holds_pipes(self):
        # The worker exits 0 at once, but a backgrounded descendant keeps stdout/stderr open.
        cmd = ["sh", "-c", "echo hi; sleep 8 & exit 0"]
        start = time.monotonic()
        exit_code, stdout, _stderr, is_timeout = dispatch_mod.execute_worker_process(
            cmd, str(self.repo_dir), timeout_seconds=3, agent_name="test-worker"
        )
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(exit_code, 0)
        self.assertFalse(is_timeout)
        self.assertIn("hi", stdout)

    def test_execute_worker_process_gives_worker_eof_on_stdin(self):
        # A worker waiting on an interactive prompt must see EOF, not block on the dispatcher's stdin.
        read_end, write_end = os.pipe()  # never written to: inheriting it would block `read` until timeout
        saved_stdin = os.dup(0)
        try:
            os.dup2(read_end, 0)
            exit_code, stdout, _stderr, is_timeout = dispatch_mod.execute_worker_process(
                ["sh", "-c", "read x; echo got:$x"], str(self.repo_dir), timeout_seconds=3, agent_name="test-worker"
            )
        finally:
            os.dup2(saved_stdin, 0)
            os.close(saved_stdin)
            os.close(read_end)
            os.close(write_end)
        self.assertFalse(is_timeout)
        self.assertEqual(stdout, "got:")
        self.assertNotEqual(exit_code, 124)

    def test_execute_worker_process_streams_to_log_before_exit(self):
        log = Path(self.temp_dir.name) / "stream.log"
        cmd = ["python3", "-c", "import sys, time; print('early line', flush=True); "
                                "sys.stderr.write('err line\\n'); sys.stderr.flush(); time.sleep(3); print('late')"]
        result = {}
        t = __import__("threading").Thread(target=lambda: result.update(r=dispatch_mod.execute_worker_process(
            cmd, str(self.repo_dir), timeout_seconds=20, agent_name="test-worker", log_path=str(log))))
        t.start()
        deadline = time.monotonic() + 2.5
        seen = ""
        while time.monotonic() < deadline and "err line" not in seen:
            seen = log.read_text(encoding="utf-8") if log.exists() else ""
            time.sleep(0.05)
        self.assertTrue(t.is_alive(), "worker already exited; streaming not demonstrated")
        self.assertIn("early line", seen)
        self.assertIn("err line", seen)
        t.join(30)
        exit_code, stdout, stderr, is_timeout = result["r"]
        self.assertEqual((exit_code, is_timeout), (0, False))
        self.assertEqual(stdout, "early line\nlate")
        self.assertEqual(stderr, "err line")
        self.assertIn("late", log.read_text(encoding="utf-8"))

    def test_execute_worker_process_timeout_with_log_path_still_kills_group(self):
        log = Path(self.temp_dir.name) / "stream.log"
        start = time.monotonic()
        exit_code, stdout, stderr, is_timeout = dispatch_mod.execute_worker_process(
            ["sh", "-c", "echo partial; sleep 30 & sleep 30"], str(self.repo_dir), timeout_seconds=1,
            agent_name="test-worker", log_path=str(log))
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual((exit_code, is_timeout), (124, True))
        self.assertIn("partial", stdout)
        self.assertIn("timed out after 1s", stderr)
        self.assertIn("partial", log.read_text(encoding="utf-8"))

    def test_inspect_git_changes_with_commits_and_working_tree(self):
        # 1. Create a commit
        (self.repo_dir / "committed_file.txt").write_text("committed content\n", encoding="utf-8")
        subprocess.run(["git", "add", "committed_file.txt"], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "worker commit 1"], cwd=self.repo_dir, check=True, capture_output=True)

        # 2. Modify base.txt (uncommitted modification)
        (self.repo_dir / "base.txt").write_text("modified uncommitted\n", encoding="utf-8")

        # 3. Create an untracked file
        (self.repo_dir / "untracked.txt").write_text("untracked content\n", encoding="utf-8")

        files_changed, diff_summary, commit_count = dispatch_mod.inspect_git_changes(
            str(self.repo_dir), self.initial_head
        )
        self.assertEqual(commit_count, 1)
        self.assertEqual(files_changed, 3)
        self.assertIn("1 commit(s)", diff_summary)

    def test_execute_in_isolated_worktree_creates_salvage_branch_on_failure(self):
        def worker_that_commits_then_fails(wt_dir):
            (Path(wt_dir) / "committed_before_timeout.txt").write_text("critical saved work\n", encoding="utf-8")
            subprocess.run(["git", "add", "committed_before_timeout.txt"], cwd=wt_dir, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "partial commit before timeout"], cwd=wt_dir, check=True, capture_output=True)
            return 124, "finished tests", "FAILED: worker timed out after 900s", 1, "1 commit(s), 1 file changed"

        exit_code, stdout, stderr, files_changed, diff_summary = dispatch_mod.execute_in_isolated_worktree(
            str(self.repo_dir), worker_that_commits_then_fails
        )

        self.assertEqual(exit_code, 124)
        self.assertIn("[Salvage] Commits preserved on git branch 'worker-salvage-", stderr)

        # Verify that the salvage branch actually exists in self.repo_dir and contains the commit
        branches_res = subprocess.run(["git", "branch"], cwd=self.repo_dir, capture_output=True, text=True)
        salvage_branches = [b.strip() for b in branches_res.stdout.splitlines() if "worker-salvage-" in b]
        self.assertTrue(len(salvage_branches) >= 1)
        target_branch = salvage_branches[0].replace("*", "").strip()

        log_res = subprocess.run(["git", "log", "-n", "1", "--oneline", target_branch], cwd=self.repo_dir, capture_output=True, text=True)
        self.assertIn("partial commit before timeout", log_res.stdout)

    def test_format_report_status_derivation(self):
        rep_partial = dispatch_mod.format_report(
            "agy", "TIMEOUT_PARTIAL_WORK", 124, "/path/to/repo", 2, "1 commit(s), 2 files changed", "tail log"
        )
        self.assertIn("Status: TIMEOUT_PARTIAL_WORK (exit 124)", rep_partial)
        self.assertIn("Files Modified: 2 (1 commit(s), 2 files changed)", rep_partial)

        rep_none = dispatch_mod.format_report(
            "agy", "TIMEOUT_NO_PROGRESS", 124, "/path/to/repo", 0, "no git diff", "tail log"
        )
        self.assertIn("Status: TIMEOUT_NO_PROGRESS (exit 124)", rep_none)
        self.assertIn("Files Modified: 0 (no git diff)", rep_none)


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

    @codex_enabled()
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

    def test_get_config_timeout_precedence_and_default(self):
        self.assertEqual(dispatch_mod.get_config_timeout({}), 2400)
        self.assertEqual(dispatch_mod.get_config_timeout({"DISPATCH_TIMEOUT": "600"}), 600)
        self.assertEqual(dispatch_mod.get_config_timeout({"AI_AGENT_AUTO_DISPATCH_TIMEOUT": "1200", "DISPATCH_TIMEOUT": "600"}), 1200)


class TestBatchAndAsyncFeatures(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.temp_dir.name) / "jobs"
        self.job_dir.mkdir(parents=True, exist_ok=True)
        self.repo_dir = Path(self.temp_dir.name) / "repo"
        self.repo_dir.mkdir(parents=True, exist_ok=True)

        subprocess.run(["git", "init"], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo_dir, check=True, capture_output=True)

        (self.repo_dir / "base.txt").write_text("initial line\n", encoding="utf-8")
        subprocess.run(["git", "add", "base.txt"], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.repo_dir, check=True, capture_output=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_batch_tasks_args(self):
        tasks = dispatch_mod.parse_batch_tasks(batch_args=["task A", "task B"])
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["task"], "task A")
        self.assertEqual(tasks[1]["task"], "task B")

    def test_parse_batch_tasks_json_list(self):
        json_file = Path(self.temp_dir.name) / "tasks.json"
        json_file.write_text(json.dumps(["task 1", "task 2"]), encoding="utf-8")
        tasks = dispatch_mod.parse_batch_tasks(batch_file=str(json_file))
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["task"], "task 1")
        self.assertEqual(tasks[1]["task"], "task 2")

    def test_parse_batch_tasks_json_dict_list(self):
        json_file = Path(self.temp_dir.name) / "tasks_dict.json"
        json_file.write_text(json.dumps([
            {"task": "task 1", "agent": "cursor", "model": "gemini-3.8-flash"},
            {"task": "task 2", "agent": "codex"}
        ]), encoding="utf-8")
        tasks = dispatch_mod.parse_batch_tasks(batch_file=str(json_file))
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["task"], "task 1")
        self.assertEqual(tasks[0]["agent"], "cursor")
        self.assertEqual(tasks[0]["model"], "gemini-3.8-flash")
        self.assertEqual(tasks[1]["agent"], "codex")

    def test_parse_batch_tasks_txt(self):
        txt_file = Path(self.temp_dir.name) / "tasks.txt"
        txt_file.write_text("# comment\ntask alpha\n\ntask beta\n", encoding="utf-8")
        tasks = dispatch_mod.parse_batch_tasks(batch_file=str(txt_file))
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["task"], "task alpha")
        self.assertEqual(tasks[1]["task"], "task beta")

    def test_job_state_crud(self):
        jid = "dw-test-123"
        state = {"job_id": jid, "status": "RUNNING", "agent": "cursor"}
        dispatch_mod.save_job_state(jid, state, job_dir=str(self.job_dir))

        loaded = dispatch_mod.load_job_state(jid, job_dir=str(self.job_dir))
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["job_id"], jid)
        self.assertEqual(loaded["status"], "RUNNING")

        all_jobs = dispatch_mod.list_all_jobs(job_dir=str(self.job_dir))
        self.assertEqual(len(all_jobs), 1)
        self.assertEqual(all_jobs[0]["job_id"], jid)

    def test_format_status_report(self):
        jobs = [
            {"job_id": "dw-1", "agent": "cursor", "status": "SUCCESS", "files_changed": 2, "diff_summary": "1 commit"},
            {"job_id": "dw-2", "agent": "agy", "status": "RUNNING", "created_at": time.time() - 30}
        ]
        rep = dispatch_mod.format_status_report(jobs)
        self.assertIn("DISPATCH JOBS STATUS", rep)
        self.assertIn("[dw-1] CURSOR | SUCCESS", rep)
        self.assertIn("[dw-2] AGY | RUNNING", rep)
        self.assertLessEqual(len(rep.splitlines()), 15)

    def test_format_batch_report(self):
        results = [
            {"task": "fix auth endpoint", "agent": "cursor", "exit_code": 0, "files_changed": 2, "diff_summary": "1 commit"},
            {"task": "update billing schema", "agent": "agy", "exit_code": 0, "files_changed": 1, "diff_summary": "1 commit"}
        ]
        rep = dispatch_mod.format_batch_report(results)
        self.assertIn("BATCH DISPATCH REPORT (2 tasks: 2 succeeded, 0 failed)", rep)
        self.assertIn("#1 [CURSOR] SUCCESS", rep)
        self.assertIn("#2 [AGY] SUCCESS", rep)
        self.assertLessEqual(len(rep.splitlines()), 15)

    def test_execute_batch_parallel_mocked(self):
        tasks = [
            {"task": "task 1"},
            {"task": "task 2"}
        ]

        def mock_single_task(task_text, target_dir, chosen_agent, chosen_model, timeout_seconds, **_kwargs):
            file_name = "file1.txt" if "task 1" in task_text else "file2.txt"
            (Path(target_dir) / file_name).write_text(f"created by {task_text}\n", encoding="utf-8")
            subprocess.run(["git", "add", file_name], cwd=target_dir, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", f"commit for {task_text}"], cwd=target_dir, check=True, capture_output=True)
            return 0, "output", "", 1, "1 commit"

        orig_run_single_task = dispatch_mod.run_single_task
        try:
            dispatch_mod.run_single_task = mock_single_task
            results = dispatch_mod.execute_batch_parallel(
                tasks,
                base_repo_dir=str(self.repo_dir),
                chosen_agent="cursor",
                chosen_model=None,
                timeout_seconds=30,
                max_parallel=2
            )
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["exit_code"], 0)
            self.assertEqual(results[1]["exit_code"], 0)

            # Check that base_repo_dir has both files merged!
            self.assertTrue((self.repo_dir / "file1.txt").exists())
            self.assertTrue((self.repo_dir / "file2.txt").exists())
        finally:
            dispatch_mod.run_single_task = orig_run_single_task

    def test_dry_run_batch_cli(self):
        state_file = Path(self.temp_dir.name) / "healthy.json"
        state_file.write_text(json.dumps({
            "snapshot": {
                "windows": [
                    {"kind": "five_hour", "remaining_percent": 80.0},
                    {"kind": "weekly", "remaining_percent": 90.0}
                ]
            }
        }), encoding="utf-8")

        res = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--agent", "agy", "--state-file", str(state_file),
             "--dry-run", "--batch", "task 1", "task 2", "--cwd", str(self.repo_dir)],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("DRY_RUN", res.stdout)
        self.assertIn("Would dispatch 2 task(s) in parallel", res.stdout)

    def test_status_and_wait_cli(self):
        jid = "dw-test-cli"
        state = {
            "job_id": jid,
            "agent": "cursor",
            "model": "gemini-3.8-flash",
            "task": "build something",
            "status": "SUCCESS",
            "exit_code": 0,
            "cwd": str(self.repo_dir),
            "files_changed": 1,
            "diff_summary": "1 commit(s)",
            "tail_output": "All done"
        }
        dispatch_mod.save_job_state(jid, state, job_dir=str(self.job_dir))

        # Check status CLI
        status_res = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--status", jid, "--job-dir", str(self.job_dir)],
            capture_output=True,
            text=True
        )
        self.assertEqual(status_res.returncode, 0)
        self.assertIn("[dw-test-cli] CURSOR | SUCCESS", status_res.stdout)

        # Check wait CLI
        wait_res = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--wait", jid, "--job-dir", str(self.job_dir)],
            capture_output=True,
            text=True
        )
        self.assertEqual(wait_res.returncode, 0)
        self.assertIn("Status: SUCCESS (exit 0)", wait_res.stdout)

    def _save_live_job(self, jid, **fields):
        # pid of this test process: alive for the whole test, and no worker is launched.
        state = {"job_id": jid, "agent": "agy", "task": "t", "status": "RUNNING", "pid": os.getpid(),
                 "cwd": str(self.repo_dir), "created_at": time.time(), **fields}
        dispatch_mod.save_job_state(jid, state, job_dir=str(self.job_dir))

    def _wait_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT_PATH), "--job-dir", str(self.job_dir), *args],
                              capture_output=True, text=True)

    def test_wait_budget_is_derived_from_the_job_record(self):
        self.assertEqual(dispatch_mod.wait_budget_seconds([{"timeout": 100, "verify_timeout": 50}], 900), 300)
        self.assertEqual(dispatch_mod.wait_budget_seconds([{}], 900), 2 * 900 + 2 * dispatch_mod.DEFAULT_VERIFY_TIMEOUT)
        self.assertEqual(dispatch_mod.wait_budget_seconds(
            [{"timeout": 100, "verify_timeout": 50}, None, {"timeout": 1000, "verify_timeout": 50}], 10), 2100)

    def test_wait_timeout_on_live_job_reports_still_running(self):
        self._save_live_job("dw-live")
        res = self._wait_cli("--wait", "dw-live", "--wait-timeout", "1")
        self.assertEqual(res.returncode, dispatch_mod.WAIT_STILL_RUNNING_EXIT_CODE, res.stdout + res.stderr)
        self.assertEqual(res.returncode, 14)
        self.assertIn("Status: STILL_RUNNING (exit 14)", res.stdout)
        self.assertEqual(dispatch_mod.load_job_state("dw-live", job_dir=str(self.job_dir))["status"], "RUNNING")

    def test_wait_is_not_bounded_by_the_worker_timeout(self):
        # --timeout 1 used to end the wait after 1s; the wait budget now comes from the job record (2*1 + 2*1 = 4s).
        self._save_live_job("dw-budget", timeout=1, verify_timeout=1)
        started = time.time()
        res = self._wait_cli("--wait", "dw-budget", "--timeout", "1")
        self.assertEqual(res.returncode, 14, res.stdout + res.stderr)
        self.assertGreaterEqual(time.time() - started, 3.5)

    def test_wait_all_timeout_reports_still_running(self):
        self._save_live_job("dw-live-a")
        self._save_live_job("dw-live-b")
        res = self._wait_cli("--wait", "all", "--wait-timeout", "1", "--cwd", str(self.repo_dir))
        self.assertEqual(res.returncode, 14, res.stdout + res.stderr)
        self.assertEqual(res.stdout.count("STILL_RUNNING"), 2)

    def _dead_pid(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return proc.pid

    def _status_of(self, jid):
        return dispatch_mod.load_job_state(jid, job_dir=str(self.job_dir))["status"]

    def test_status_persists_failed_died_for_dead_running_and_pending_jobs(self):
        dead = self._dead_pid()
        self._save_live_job("dw-dead-running", pid=dead)
        self._save_live_job("dw-dead-pending", pid=dead, status="PENDING")
        self._save_live_job("dw-alive")
        res = self._wait_cli("--status")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.count("FAILED_DIED"), 2)
        for jid in ("dw-dead-running", "dw-dead-pending"):
            state = dispatch_mod.load_job_state(jid, job_dir=str(self.job_dir))
            self.assertEqual((state["status"], state["exit_code"]), ("FAILED_DIED", 1))
        self.assertEqual(self._status_of("dw-alive"), "RUNNING")

    def test_status_of_one_dead_pending_job_persists_failed_died(self):
        self._save_live_job("dw-dead-one", pid=self._dead_pid(), status="PENDING")
        res = self._wait_cli("--status", "dw-dead-one")
        self.assertIn("FAILED_DIED", res.stdout)
        self.assertEqual(self._status_of("dw-dead-one"), "FAILED_DIED")

    def test_reap_does_not_overwrite_a_job_that_finished_meanwhile(self):
        self._save_live_job("dw-raced", pid=self._dead_pid(), status="SUCCESS", exit_code=0)
        stale_view = {"job_id": "dw-raced", "status": "RUNNING", "pid": self._dead_pid()}
        result = dispatch_mod.reap_dead_job(stale_view, job_dir=str(self.job_dir))
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(self._status_of("dw-raced"), "SUCCESS")

    def test_wait_all_ignores_jobs_from_another_cwd(self):
        other = Path(self.temp_dir.name) / "other-repo"
        other.mkdir()
        self._save_live_job("dw-elsewhere", cwd=str(other))
        res = self._wait_cli("--wait", "all", "--wait-timeout", "1", "--cwd", str(self.repo_dir))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("No running jobs to wait for", res.stdout)
        res = self._wait_cli("--wait", "all", "--wait-timeout", "1", "--cwd", str(other))
        self.assertEqual(res.returncode, 14, res.stdout + res.stderr)

    def test_extract_tasks_from_plan(self):
        plan_content = """# Plan

## Phase 1: Authentication
- [ ] Task 1.1: Implement login route
- [ ] Task 1.2: Add token validation
### Task 1.3: Refresh token endpoint

## Phase 2: Billing
- [ ] Task 2.1: Add stripe webhook
"""
        plan_file = Path(self.temp_dir.name) / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        # Phase 1 only
        p1_tasks = dispatch_mod.extract_tasks_from_plan(str(plan_file), target_phase="1")
        self.assertEqual(len(p1_tasks), 3)
        self.assertEqual(p1_tasks[0]["task"], "Task 1.1: Implement login route")
        self.assertEqual(p1_tasks[1]["task"], "Task 1.2: Add token validation")
        self.assertEqual(p1_tasks[2]["task"], "Refresh token endpoint")

        # Phase 2 only
        p2_tasks = dispatch_mod.extract_tasks_from_plan(str(plan_file), target_phase="2")
        self.assertEqual(len(p2_tasks), 1)
        self.assertEqual(p2_tasks[0]["task"], "Task 2.1: Add stripe webhook")

    def test_tail_job(self):
        jid = "dw-tail-test"
        log_file = Path(self.temp_dir.name) / "dw-tail.log"
        log_file.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
        state = {
            "job_id": jid,
            "status": "RUNNING",
            "log_file": str(log_file),
            "created_at": time.time()
        }
        dispatch_mod.save_job_state(jid, state, job_dir=str(self.job_dir))

        tail_res = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--tail", jid, "--job-dir", str(self.job_dir), "-n", "2"],
            capture_output=True,
            text=True
        )
        self.assertEqual(tail_res.returncode, 0)
        self.assertIn("TAIL LOG: dw-tail-test", tail_res.stdout)
        self.assertIn("line 2", tail_res.stdout)
        self.assertIn("line 3", tail_res.stdout)
        self.assertNotIn("line 1", tail_res.stdout)

    def test_format_status_report_live_tail(self):
        log_file = Path(self.temp_dir.name) / "live.log"
        log_file.write_text("running pytest unit tests...\n", encoding="utf-8")
        jobs = [{
            "job_id": "dw-live",
            "agent": "cursor",
            "status": "RUNNING",
            "log_file": str(log_file),
            "created_at": time.time() - 10
        }]
        rep = dispatch_mod.format_status_report(jobs)
        self.assertIn("tail: running pytest", rep)

    def test_format_status_report_last_output_and_stalled(self):
        fresh = Path(self.temp_dir.name) / "fresh.log"
        fresh.write_text("working\n", encoding="utf-8")
        stale = Path(self.temp_dir.name) / "stale.log"
        stale.write_text("last words\n", encoding="utf-8")
        old = time.time() - dispatch_mod.STALL_SECONDS - 60
        os.utime(stale, (old, old))
        rep = dispatch_mod.format_status_report([
            {"job_id": "dw-fresh", "agent": "agy", "status": "RUNNING", "log_file": str(fresh), "created_at": time.time() - 5},
            {"job_id": "dw-stale", "agent": "agy", "status": "RUNNING", "log_file": str(stale), "created_at": old},
        ])
        fresh_line = next(l for l in rep.splitlines() if "dw-fresh" in l)
        stale_line = next(l for l in rep.splitlines() if "dw-stale" in l)
        self.assertIn("last output 0s ago", fresh_line)
        self.assertNotIn("STALLED?", fresh_line)
        self.assertIn("STALLED?", stale_line)
        self.assertRegex(stale_line, r"last output 3\d\ds ago")

    def test_format_batch_report_retry_hint(self):
        results = [
            {"task": "task 1", "agent": "cursor", "exit_code": 0, "files_changed": 1, "diff_summary": "ok"},
            {"task": "task 2 failed prompt", "agent": "agy", "exit_code": 1, "files_changed": 0, "diff_summary": "err"}
        ]
        rep = dispatch_mod.format_batch_report(results)
        self.assertIn("Retry: dispatch-worker --task \"task 2 failed prompt\"", rep)

    def test_execute_batch_parallel_merge_conflict_detected(self):
        tasks = [
            {"task": "task 1 edit base"},
            {"task": "task 2 edit base"}
        ]

        def conflicting_single_task(task_text, target_dir, chosen_agent, chosen_model, timeout_seconds, **_kwargs):
            # Both tasks edit base.txt with conflicting lines
            (Path(target_dir) / "base.txt").write_text(f"conflicting edit from {task_text}\n", encoding="utf-8")
            subprocess.run(["git", "add", "base.txt"], cwd=target_dir, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", f"edit from {task_text}"], cwd=target_dir, check=True, capture_output=True)
            return 0, "output", "", 1, "1 commit"

        orig_run_single_task = dispatch_mod.run_single_task
        try:
            dispatch_mod.run_single_task = conflicting_single_task
            results = dispatch_mod.execute_batch_parallel(
                tasks,
                base_repo_dir=str(self.repo_dir),
                chosen_agent="cursor",
                chosen_model=None,
                timeout_seconds=30,
                max_parallel=2
            )
            self.assertEqual(len(results), 2)
            exit_codes = sorted([r["exit_code"] for r in results])
            self.assertEqual(exit_codes, [0, 1])
            failed_task = [r for r in results if r["exit_code"] == 1][0]
            self.assertIn("MERGE_CONFLICT", failed_task["diff_summary"])
        finally:
            dispatch_mod.run_single_task = orig_run_single_task

    def test_think_quota_thresholds_and_model(self):
        # 5h=75%, weekly=30% -> Passes normal (min 30/10), but fails thinking (min 80/20)
        codex_file = Path(self.temp_dir.name) / "codex-status.json"
        codex_file.write_text(json.dumps({
            "windows": [
                {"kind": "five_hour", "remaining_percent": 75.0},
                {"kind": "weekly", "remaining_percent": 30.0}
            ]
        }), encoding="utf-8")
        # Standard check should pass
        el, r5, rw, msg = dispatch_mod.check_quota("codex", str(codex_file), min_5h=30.0, min_weekly=10.0)
        self.assertTrue(el)

        # Thinking check should fail because 5h is 75.0 < 80.0
        el_think, r5_t, rw_t, msg_t = dispatch_mod.check_quota(
            "codex", str(codex_file),
            min_5h=dispatch_mod.DEFAULT_THINK_MIN_5H,
            min_weekly=dispatch_mod.DEFAULT_THINK_MIN_WEEKLY
        )
        self.assertFalse(el_think)
        self.assertIn("75.0%", msg_t)
        self.assertIn("min 80.0%", msg_t)

    def test_normalize_model_name_thinking_aliases(self):
        self.assertEqual(dispatch_mod.normalize_model_name("codex", "sol"), "gpt-5.6-sol")
        self.assertEqual(dispatch_mod.normalize_model_name("codex", "sol:5.6"), "gpt-5.6-sol")
        self.assertEqual(dispatch_mod.normalize_model_name("codex", "thinking"), "gpt-5.6-sol")
        self.assertEqual(dispatch_mod.normalize_model_name("claude", "opus"), "claude-opus-5-5")

    def test_wrap_prompt_contract_with_context_and_output(self):
        cfile = Path(self.temp_dir.name) / "spec.md"
        cfile.write_text("# Feature Spec\nMust implement auth endpoint.", encoding="utf-8")
        out_file = "docs/output.md"

        wrapped = dispatch_mod.wrap_prompt_contract(
            "Implement auth endpoint",
            context_files=[str(cfile)],
            output_file=out_file,
            is_thinking=True
        )
        self.assertIn("Thinking / Architecture Mode", wrapped)
        self.assertIn("Context Document: spec.md", wrapped)
        self.assertIn("Must implement auth endpoint.", wrapped)
        self.assertIn(f"Write your primary output/deliverable directly to the file: '{out_file}'", wrapped)

    def test_extract_tasks_from_plan_attaches_context(self):
        plan_path = Path(self.temp_dir.name) / "plan.md"
        plan_path.write_text(
            "## Phase 1: Setup\n"
            "- [ ] Task 1.1: Create database migration\n",
            encoding="utf-8"
        )
        tasks = dispatch_mod.extract_tasks_from_plan(str(plan_path), target_phase=1)
        self.assertEqual(len(tasks), 1)
        self.assertIn("Create database migration", tasks[0]["task"])
        self.assertEqual(tasks[0]["context_files"], [str(plan_path)])

    def test_format_report_with_artifact_and_context(self):
        rep = dispatch_mod.format_report(
            agent="codex",
            status="SUCCESS",
            exit_code=0,
            cwd="/tmp/repo",
            files_changed=2,
            diff_summary="2 files",
            tail_output="all done",
            artifact="docs/specs/auth.md",
            context_count=3
        )
        self.assertIn("Artifact: docs/specs/auth.md", rep)
        self.assertIn("Context: 3 document(s) referenced", rep)
        self.assertIn("Files Modified: 2 (2 files)", rep)

    def test_deep_design_capability_rejects_forbidden_model(self):
        worker_bin = BIN_DIR / "dispatch-worker"
        proc = subprocess.run(
            [sys.executable, str(worker_bin), "--capability", "deep-design-v1", "--model", "gpt-5.6-terra", "--task", "x"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 12)
        self.assertIn("strictly forbids model 'gpt-5.6-terra'", proc.stderr)


class TestThinkerRouting(unittest.TestCase):
    """dispatch-thinker (deep-design-v1): Claude Opus 5.5 only (codex is disabled), exit 12 if it is unavailable.

    Hermetic: PATH holds only fake binaries plus system dirs, and codex quota comes from a temp --state-file.
    """

    WORKER_BIN = BIN_DIR / "dispatch-worker"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        self.codex_state = self.root / "codex-status.json"
        self.calls_log = self.root / "calls.log"
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"],
                       cwd=self.repo, check=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _codex_quota(self, five_hour, weekly):
        self.codex_state.write_text(json.dumps({"windows": [
            {"kind": "five_hour", "remaining_percent": five_hour},
            {"kind": "weekly", "remaining_percent": weekly},
        ]}), encoding="utf-8")

    def _fake(self, name, exit_code=0, output="ok", body=""):
        path = self.fake_bin / name
        path.write_text(
            f"#!/bin/sh\necho \"{name} $1 $2 $3 $4\" >> '{self.calls_log}'\n"
            f"printf '%s\\0' \"$@\" > '{self.root}/{name}.args'\n"
            f"{body}\necho '{output}'\nexit {exit_code}\n",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _args(self, name):
        return (self.root / f"{name}.args").read_text(encoding="utf-8").split("\0")

    def _run(self, *extra, env_extra=None, capability=True):
        env = {k: v for k, v in os.environ.items()
               if k not in ("DISPATCH_THINKER_SKIP_CLAUDE", "CLAUDE_THINK_MODEL", "CODEX_THINK_MODEL",
                            "THINK_EFFORT", "CLAUDE_THINK_EFFORT", "CODEX_THINK_EFFORT", "DISPATCH_EFFORT")}
        env["PATH"] = f"{self.fake_bin}:/usr/bin:/bin"
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, str(self.WORKER_BIN), *(["--capability", "deep-design-v1"] if capability else ["--think"]),
             "--state-file", str(self.codex_state), "--cwd", str(self.repo), "--task", "x", *extra],
            capture_output=True, text=True, env=env,
        )

    def test_deep_design_capability_dry_run_success(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("DRY_RUN", proc.stdout)

    def test_dry_run_prefers_claude_opus_when_on_path(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("to claude with claude-opus-5-5", proc.stdout)

    def test_claude_model_overridable_via_env(self):
        self._fake("claude")
        proc = self._run("--dry-run", env_extra={"CLAUDE_THINK_MODEL": "claude-opus-9"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("to claude with claude-opus-9", proc.stdout)

    def test_skip_claude_env_fails_closed_instead_of_using_codex(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--dry-run", env_extra={"DISPATCH_THINKER_SKIP_CLAUDE": "1"})
        self.assertEqual(proc.returncode, 12, proc.stdout + proc.stderr)
        self.assertIn("Thinker unavailable", proc.stderr)
        self.assertNotIn("Would dispatch", proc.stdout)

    def test_both_unavailable_fails_closed_12(self):
        self._codex_quota(10.0, 5.0)
        proc = self._run("--dry-run")
        self.assertEqual(proc.returncode, 12)
        self.assertIn("Thinker unavailable", proc.stderr)
        self.assertIn("claude", proc.stderr.lower())
        self.assertNotIn("CODEX", proc.stderr)

    def test_forbidden_model_fails_closed_12(self):
        self._fake("claude")
        proc = self._run("--dry-run", "--model", "gpt-5.6-terra")
        self.assertEqual(proc.returncode, 12)
        self.assertIn("strictly forbids model 'gpt-5.6-terra'", proc.stderr)

    def test_opus_alias_allowed_and_mapped(self):
        self._fake("claude")
        proc = self._run("--dry-run", "--model", "opus")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("to claude with claude-opus-5-5", proc.stdout)

    def test_explicit_agent_codex_is_refused(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--dry-run", "--agent", "codex")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("codex is disabled", proc.stderr)

    def test_explicit_agent_claude_is_respected(self):
        self._fake("claude")
        proc = self._run("--dry-run", "--agent", "claude")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("to claude with claude-opus-5-5", proc.stdout)

    def test_runtime_claude_failure_never_falls_back_to_codex(self):
        self._fake("claude", exit_code=1, output="claude-boom")
        self._fake("codex", exit_code=0, output="sol-ok")
        self._codex_quota(100.0, 100.0)
        proc = self._run()
        self.assertEqual(proc.returncode, 1)
        calls = self.calls_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(calls), 1, calls)


    def test_claude_run_is_least_privilege(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        args = self._args("claude")
        self.assertNotIn("bypassPermissions", args)
        self.assertNotIn("--dangerously-skip-permissions", args)
        self.assertIn("--disallowedTools", args)
        self.assertIn("Bash", args[args.index("--disallowedTools") + 1].split(","))
        self.assertIn("--allowedTools", args)
        self.assertNotIn("Bash", args[args.index("--allowedTools") + 1].split(","))
        self.assertIn("--add-dir", args)

    def test_plain_think_both_unavailable_falls_back_internal_10(self):
        self._codex_quota(10.0, 5.0)
        proc = self._run("--dry-run", capability=False)
        self.assertEqual(proc.returncode, 10, proc.stdout + proc.stderr)
        self.assertIn("FALLBACK_INTERNAL", proc.stdout)

    def test_plain_think_prefers_claude(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--dry-run", capability=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("to claude with claude-opus-5-5", proc.stdout)

    def test_thinking_mode_defaults_to_medium_effort(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("(effort: medium)", proc.stdout)

    def test_thinking_mode_effort_override_cli(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--dry-run", "--effort", "max")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("(effort: max)", proc.stdout)

    def test_thinking_mode_effort_override_env(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--dry-run", env_extra={"THINK_EFFORT": "high"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("(effort: high)", proc.stdout)

    def test_claude_run_passes_effort_flag(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        args = self._args("claude")
        self.assertIn("--effort", args)
        self.assertEqual(args[args.index("--effort") + 1], "medium")

    def test_claude_run_custom_effort_flag(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--effort", "xhigh")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        args = self._args("claude")
        self.assertIn("--effort", args)
        self.assertEqual(args[args.index("--effort") + 1], "xhigh")

    def test_fable_model_is_strictly_forbidden(self):
        self._fake("claude")
        proc = self._run("--dry-run", "--model", "fable")
        self.assertEqual(proc.returncode, 12)
        self.assertIn("strictly forbidden", proc.stderr)

    def test_claude_fable_model_is_strictly_forbidden(self):
        self._fake("claude")
        proc = self._run("--dry-run", "--model", "claude-fable-5-1")
        self.assertEqual(proc.returncode, 12)
        self.assertIn("strictly forbidden", proc.stderr)

    def test_attestation_records_effort(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        attestation = json.loads((self.repo / ".thinker.json").read_text(encoding="utf-8"))
        self.assertEqual(attestation["effort"], "medium")

    def test_think_with_explicit_agy_routes_to_claude(self):
        self._fake("claude")
        for capability in (True, False):
            proc = self._run("--agent", "agy", "--dry-run", capability=capability)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("to claude with claude-opus-5-5", proc.stdout)
            self.assertEqual(proc.stderr.count("NOTICE: thinking mode runs on Claude Opus 5.5 only; ignoring --agent agy"), 1)

    def test_think_with_explicit_agy_fails_closed_without_claude(self):
        self._fake("agy")
        proc = self._run("--agent", "agy", "--dry-run")
        self.assertEqual(proc.returncode, 12, proc.stdout + proc.stderr)
        self.assertNotIn("Would dispatch", proc.stdout)
        proc = self._run("--agent", "agy", "--dry-run", capability=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Would dispatch", proc.stdout)

    def test_think_with_explicit_agy_attests_the_agent_that_ran(self):
        self._fake("claude")
        self._fake("agy")
        proc = self._run("--agent", "agy")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("agy", self.calls_log.read_text(encoding="utf-8"))
        attestation = json.loads((self.repo / ".thinker.json").read_text(encoding="utf-8"))
        self.assertEqual((attestation["agent"], attestation["model"]), ("claude", "claude-opus-5-5"))


class TestEffortHelpers(unittest.TestCase):
    def test_normalize_effort_codex(self):
        self.assertEqual(dispatch_mod.normalize_effort("codex", "low"), "low")
        self.assertEqual(dispatch_mod.normalize_effort("codex", "medium"), "medium")
        self.assertEqual(dispatch_mod.normalize_effort("codex", "high"), "high")
        self.assertEqual(dispatch_mod.normalize_effort("codex", "max"), "high")
        self.assertEqual(dispatch_mod.normalize_effort("codex", "xhigh"), "high")

    def test_normalize_effort_agy(self):
        self.assertEqual(dispatch_mod.normalize_effort("agy", "low"), "low")
        self.assertEqual(dispatch_mod.normalize_effort("agy", "medium"), "medium")
        self.assertEqual(dispatch_mod.normalize_effort("agy", "high"), "high")
        self.assertEqual(dispatch_mod.normalize_effort("agy", "max"), "max")
        self.assertEqual(dispatch_mod.normalize_effort("agy", "xhigh"), "high")

    def test_normalize_effort_cursor(self):
        self.assertIsNone(dispatch_mod.normalize_effort("cursor", "high"))

    def test_normalize_effort_claude(self):
        self.assertEqual(dispatch_mod.normalize_effort("claude", "xhigh"), "xhigh")
        self.assertEqual(dispatch_mod.normalize_effort("claude", "max"), "max")

    def test_resolve_agent_effort_env_overrides(self):
        with mock.patch.dict(os.environ, {"CLAUDE_THINK_EFFORT": "max", "CODEX_THINK_EFFORT": "medium"}):
            self.assertEqual(dispatch_mod.resolve_agent_effort("claude", "high", is_thinking=True), "max")
            self.assertEqual(dispatch_mod.resolve_agent_effort("codex", "high", is_thinking=True), "medium")
            # Not in thinking mode, env overrides do not take effect:
            self.assertEqual(dispatch_mod.resolve_agent_effort("claude", "high", is_thinking=False), "high")

    @codex_enabled()
    def test_build_agent_command_effort_flags(self):
        # Codex
        cmd_c = dispatch_mod.build_agent_command("codex", "gpt-5.6-sol", "task", "/tmp", effort="high")
        self.assertIn('-c', cmd_c)
        self.assertIn('model_reasoning_effort="high"', cmd_c)

        # Claude
        cmd_cl = dispatch_mod.build_agent_command("claude", "claude-opus-5-5", "task", "/tmp", effort="high")
        self.assertIn('--effort', cmd_cl)
        self.assertEqual(cmd_cl[cmd_cl.index('--effort') + 1], "high")

        # AGY
        cmd_a = dispatch_mod.build_agent_command("agy", "gemini-3.8-flash", "task", "/tmp", effort="high")
        self.assertIn('--effort', cmd_a)
        self.assertEqual(cmd_a[cmd_a.index('--effort') + 1], "high")

        # Cursor - no effort flag
        cmd_cur = dispatch_mod.build_agent_command("cursor", "gemini-3.8-flash", "task", "/tmp", effort=None)
        self.assertNotIn('--effort', cmd_cur)


class TestExecutionRuntimeFallback(unittest.TestCase):
    """Non-think single tasks routed by --agent auto / --priority get one retry on the next eligible agent."""

    WORKER_BIN = BIN_DIR / "dispatch-worker"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        self.agy_state = self.root / "agy-status.json"
        self.codex_state = self.root / "codex-status.json"
        self.calls_log = self.root / "calls.log"
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"],
                       cwd=self.repo, check=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _quota(self, path, five_hour, weekly):
        path.write_text(json.dumps({"windows": [
            {"kind": "five_hour", "remaining_percent": five_hour},
            {"kind": "weekly", "remaining_percent": weekly},
        ]}), encoding="utf-8")

    def _fake(self, name, exit_code=0, output="ok", body=""):
        path = self.fake_bin / name
        path.write_text(f"#!/bin/sh\necho \"{name}\" >> '{self.calls_log}'\n{body}\necho '{output}'\nexit {exit_code}\n",
                        encoding="utf-8")
        path.chmod(0o755)

    def _calls(self):
        return self.calls_log.read_text(encoding="utf-8").splitlines() if self.calls_log.exists() else []

    def _run(self, *extra):
        env = {k: v for k, v in os.environ.items()
               if k not in ("AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_ROUTING_PREFERENCE", "DISPATCH_ROUTING_PREFERENCE",
                            "DISPATCH_EFFORT")}
        env.update({
            "PATH": f"{self.fake_bin}:/usr/bin:/bin",
            "DISPATCH_CONFIG_FILE": str(self.root / "no-config.env"),
            "AGY_QUOTA_STATE_FILE": str(self.agy_state),
            "CODEX_QUOTA_STATE_FILE": str(self.codex_state),
            "DISPATCH_EVENTS_FILE": str(self.root / "events.jsonl"),
        })
        return subprocess.run(
            [sys.executable, str(self.WORKER_BIN), "--cwd", str(self.repo), "--task", "x", *extra],
            capture_output=True, text=True, env=env,
        )

    # --- routing helper ---

    @codex_enabled()
    def test_fallback_helper_auto_yields_other_eligible_agent(self):
        self._quota(self.agy_state, 90.0, 90.0)
        self._quota(self.codex_state, 80.0, 80.0)
        fb = dispatch_mod.route_execution_fallback(
            "agy", agy_state_file=str(self.agy_state), codex_state_file=str(self.codex_state))
        self.assertEqual(fb, ("codex", None))

    def test_fallback_helper_none_when_other_agent_ineligible(self):
        self._quota(self.agy_state, 90.0, 90.0)
        self._quota(self.codex_state, 1.0, 1.0)
        fb = dispatch_mod.route_execution_fallback(
            "agy", agy_state_file=str(self.agy_state), codex_state_file=str(self.codex_state))
        self.assertIsNone(fb)

    def test_fallback_helper_priority_chain_skips_chosen_agent_and_keeps_model(self):
        self._quota(self.agy_state, 90.0, 90.0)
        self._quota(self.codex_state, 90.0, 90.0)
        chain = dispatch_mod.parse_priority_chain("codex:gpt-5.6-terra > agy:gemini-x")
        fb = dispatch_mod.route_execution_fallback(
            "codex", chain=chain, agy_state_file=str(self.agy_state), codex_state_file=str(self.codex_state))
        self.assertEqual(fb[0], "agy")
        self.assertEqual(fb, chain[1])

    def test_fallback_helper_priority_chain_respects_on_demand_gate(self):
        self._quota(self.agy_state, 90.0, 90.0)
        chain = dispatch_mod.parse_priority_chain("agy > cursor")
        fb = dispatch_mod.route_execution_fallback("agy", chain=chain, allow_on_demand=False,
                                                   agy_state_file=str(self.agy_state))
        self.assertIsNone(fb)

    # --- retry decision (end to end with fake workers) ---

    def test_chain_agy_failure_falls_back_once_to_claude(self):
        self._quota(self.agy_state, 95.0, 95.0)
        self._fake("agy", exit_code=1, output="agy-boom")
        self._fake("claude", output="claude-ok")
        proc = self._run("--priority", "agy > claude", "--no-verify")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self._calls(), ["agy", "claude"])
        self.assertIn("claude-ok", proc.stdout)
        self.assertIn("falling back once to claude", proc.stderr)
        self.assertNotIn("with None", proc.stderr)
        events = [json.loads(l) for l in (self.root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([e["event"] for e in events], ["route", "start", "fallback", "start", "finish"])
        self.assertEqual(len({e["run_id"] for e in events}), 1)
        fb = events[2]
        self.assertEqual((fb["from_agent"], fb["to_agent"], fb["exit_code"]), ("agy", "claude", 1))
        self.assertEqual((events[-1]["agent"], events[-1]["status"]), ("claude", "SUCCESS"))

    def test_auto_agy_failure_does_not_fall_back_to_codex(self):
        self._quota(self.agy_state, 95.0, 95.0)
        self._quota(self.codex_state, 60.0, 60.0)
        self._fake("agy", exit_code=1, output="agy-boom")
        self._fake("codex", output="codex-ok")
        proc = self._run("--agent", "auto", "--no-verify")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self._calls(), ["agy"])

    def test_pinned_agent_does_not_fall_back(self):
        self._quota(self.agy_state, 95.0, 95.0)
        self._quota(self.codex_state, 60.0, 60.0)
        self._fake("agy", exit_code=1, output="agy-boom")
        self._fake("codex", output="codex-ok")
        proc = self._run("--agent", "agy", "--no-verify")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self._calls(), ["agy"])

    def test_pinned_agent_in_equals_form_does_not_fall_back(self):
        # An explicit --priority routes through the chain; an explicit --agent still pins, however it is spelled.
        self._quota(self.agy_state, 95.0, 95.0)
        self._quota(self.codex_state, 60.0, 60.0)
        self._fake("agy", exit_code=1, output="agy-boom")
        self._fake("codex", output="codex-ok")
        for agent_args in (["--agent", "agy"], ["--agent=agy"]):
            self.calls_log.unlink(missing_ok=True)
            proc = self._run(*agent_args, "--priority", "agy > codex", "--no-verify")
            self.assertNotEqual(proc.returncode, 0, agent_args)
            self.assertEqual(self._calls(), ["agy"], agent_args)

    def test_isolated_execution_error_still_emits_finish(self):
        self._quota(self.agy_state, 95.0, 95.0)
        self._fake("agy")
        import shutil
        shutil.rmtree(self.repo / ".git")  # `git worktree add` now fails inside the isolated runner
        proc = self._run("--agent", "agy", "--no-verify", "--isolated")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("isolated execution error", proc.stderr)
        events = [json.loads(l) for l in (self.root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        fin = [e for e in events if e["event"] == "finish"]
        self.assertEqual([(e["status"], e["exit_code"], e["agent"]) for e in fin], [("ERROR", 1, "agy")])

    def test_verify_failure_does_not_fall_back(self):
        self._quota(self.agy_state, 95.0, 95.0)
        self._quota(self.codex_state, 60.0, 60.0)
        self._fake("agy", output="agy-ok")
        self._fake("codex", output="codex-ok")
        proc = self._run("--agent", "auto", "--verify-cmd", "false")
        self.assertEqual(proc.returncode, dispatch_mod.VERIFY_FAILED_EXIT_CODE, proc.stdout + proc.stderr)
        self.assertNotIn("codex", self._calls())

    def test_failed_agent_leaving_changes_blocks_fallback(self):
        self._quota(self.agy_state, 95.0, 95.0)
        self._quota(self.codex_state, 60.0, 60.0)
        self._fake("agy", exit_code=1, body=f"echo half > '{self.repo}/half.txt'")
        self._fake("claude", output="claude-ok")
        proc = self._run("--priority", "agy > claude", "--no-verify")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self._calls(), ["agy"])
        self.assertIn("left changes behind", proc.stderr)

    def test_fallback_refusal_decision(self):
        refusal = dispatch_mod.fallback_refusal
        self.assertIsNone(refusal("No changes", [], head_moved=False))
        self.assertIsNone(refusal(None, [], head_moved=False))
        self.assertIn("merge conflict", refusal("MERGE_CONFLICT (saved patch: /tmp/x.patch)", [], head_moved=False))
        self.assertIn("could not be compared", refusal("No changes", None, head_moved=False))
        self.assertIn("HEAD moved", refusal("No changes", [], head_moved=True))
        left = refusal("No changes", ["a.txt", "b.txt"], head_moved=False)
        self.assertIn("left changes behind", left)
        self.assertIn("a.txt", left)

    def test_isolated_merge_conflict_after_partial_merge_blocks_fallback(self):
        self._quota(self.agy_state, 95.0, 95.0)
        self._quota(self.codex_state, 60.0, 60.0)
        (self.repo / "a.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.txt"], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "a"],
                       cwd=self.repo, check=True)
        # The base tree's own uncommitted edit makes the worker's patch conflict; its new file is still copied.
        (self.repo / "a.txt").write_text("user edit\n", encoding="utf-8")
        self._fake("agy", body="echo worker > a.txt; echo new > new.txt")
        self._fake("claude", output="claude-ok")
        proc = self._run("--priority", "agy > claude", "--no-verify", "--isolated")
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self._calls(), ["agy"])
        self.assertIn("refusing fallback", proc.stderr)


class TestEventLog(unittest.TestCase):
    """Append-only JSONL event log: one line per routing/run event, never raises."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.events = Path(self.temp_dir.name) / "state" / "events.jsonl"
        self.env = mock.patch.dict(os.environ, {"DISPATCH_EVENTS_FILE": str(self.events)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def _events(self):
        return [json.loads(l) for l in self.events.read_text(encoding="utf-8").splitlines()]

    def test_emit_event_appends_one_json_line_with_ts_and_pid(self):
        dispatch_mod.emit_event("start", run_id="r1", agent="agy")
        dispatch_mod.emit_event("finish", run_id="r1", agent="agy", status="SUCCESS")
        evs = self._events()
        self.assertEqual([e["event"] for e in evs], ["start", "finish"])
        self.assertEqual(evs[0]["run_id"], "r1")
        self.assertEqual(evs[0]["pid"], os.getpid())
        self.assertIsInstance(evs[0]["ts"], float)
        self.assertEqual(evs[1]["status"], "SUCCESS")

    def test_emit_event_never_raises_on_unwritable_path(self):
        self.events.parent.mkdir(parents=True)
        self.events.mkdir()  # a directory where the file should be
        dispatch_mod.emit_event("start", run_id="r1")  # must not raise

    def test_emit_event_never_raises_on_unserializable_field(self):
        dispatch_mod.emit_event("start", run_id="r1", weird=object())

    def test_task_digest_is_hash_only(self):
        d = dispatch_mod.task_digest("short secret prompt")
        self.assertEqual(list(d), ["task_sha"])
        self.assertEqual(len(d["task_sha"]), 12)

    def test_event_log_is_created_owner_only(self):
        old_umask = os.umask(0)
        try:
            dispatch_mod.emit_event("start", run_id="r1")
        finally:
            os.umask(old_umask)
        self.assertEqual(self.events.stat().st_mode & 0o777, 0o600)

    def test_run_internal_job_emits_start_and_finish(self):
        job_dir = str(Path(self.temp_dir.name) / "jobs")
        dispatch_mod.save_job_state("job-ev", {
            "job_id": "job-ev", "agent": "agy", "task": "t", "cwd": self.temp_dir.name,
            "isolated": False, "timeout": 30,
        }, job_dir=job_dir)
        with mock.patch.object(dispatch_mod, "run_single_task", return_value=(0, "ok", "", 2, "2 files")):
            with self.assertRaises(SystemExit):
                dispatch_mod.run_internal_job("job-ev", job_dir=job_dir)
        fin = [e for e in self._events() if e["event"] == "finish"]
        self.assertEqual(len(fin), 1)
        self.assertEqual(fin[0]["run_id"], "job-ev")
        self.assertEqual(fin[0]["status"], "SUCCESS")
        self.assertEqual(fin[0]["files_changed"], 2)
        self.assertIn("duration_s", fin[0])

    def test_run_single_task_emits_start_and_timeout(self):
        repo = Path(self.temp_dir.name) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        with mock.patch.object(dispatch_mod, "build_agent_command", return_value=["sh", "-c", "sleep 5"]):
            dispatch_mod.run_single_task("secret task text", str(repo), "agy", "m1", 1,
                                         verify_opts={"no_verify": True}, run_id="r9")
        evs = self._events()
        start = next(e for e in evs if e["event"] == "start")
        self.assertEqual((start["run_id"], start["agent"], start["model"], start["timeout"]), ("r9", "agy", "m1", 1))
        self.assertTrue(any(e["event"] == "timeout" and e["run_id"] == "r9" for e in evs))
        self.assertNotIn("secret", self.events.read_text(encoding="utf-8"))

    def test_verify_start_is_written_to_job_log(self):
        repo = Path(self.temp_dir.name) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        log = Path(self.temp_dir.name) / "job.log"
        with mock.patch.object(dispatch_mod, "build_agent_command", return_value=["sh", "-c", "echo worked"]):
            dispatch_mod.run_single_task("t", str(repo), "agy", None, 30, verify_opts={"verify_cmd": "true"},
                                         run_id="r1", log_path=str(log))
        self.assertIn("[Verify] running: true", log.read_text(encoding="utf-8"))

    def test_batch_emits_finish_per_task(self):
        def _fake(task_text, target_dir, chosen_agent, chosen_model, timeout_seconds, **_kw):
            return 1, "", "boom", 0, "no diff"
        with mock.patch.object(dispatch_mod, "run_single_task", side_effect=_fake), \
                mock.patch.object(dispatch_mod, "execute_in_isolated_worktree", side_effect=lambda cwd, fn, merge_lock=None: fn(cwd)):
            dispatch_mod.execute_batch_parallel([{"task": "a"}, {"task": "b"}], self.temp_dir.name, "agy", None, 30,
                                                run_id="batch1")
        fin = sorted(e["run_id"] for e in self._events() if e["event"] == "finish")
        self.assertEqual(fin, ["batch1-1", "batch1-2"])


class TestStats(unittest.TestCase):
    """--stats [DAYS] summarizes events.jsonl per agent and tolerates junk lines."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.events = Path(self.temp_dir.name) / "events.jsonl"
        now = time.time()
        old = now - 30 * 86400
        recs = [
            {"ts": now, "event": "start", "run_id": "a", "agent": "agy"},
            {"ts": now, "event": "fallback", "run_id": "a", "from_agent": "agy", "to_agent": "codex"},
            {"ts": now, "event": "start", "run_id": "a", "agent": "codex"},
            {"ts": now, "event": "finish", "run_id": "a", "agent": "codex", "status": "SUCCESS", "duration_s": 10},
            {"ts": now, "event": "start", "run_id": "b", "agent": "agy"},
            {"ts": now, "event": "timeout", "run_id": "b", "agent": "agy"},
            {"ts": now, "event": "finish", "run_id": "b", "agent": "agy", "status": "TIMEOUT_NO_PROGRESS", "duration_s": 900},
            {"ts": now, "event": "start", "run_id": "c", "agent": "agy"},
            {"ts": now, "event": "verify_failed", "run_id": "c", "agent": "agy"},
            {"ts": now, "event": "finish", "run_id": "c", "agent": "agy", "status": "VERIFY_FAILED", "duration_s": 100},
            {"ts": now, "event": "start", "run_id": "d", "agent": "agy"},
            {"ts": now, "event": "finish", "run_id": "d", "agent": "agy", "status": "SUCCESS", "duration_s": 50},
            {"ts": old, "event": "start", "run_id": "z", "agent": "cursor"},
            {"ts": old, "event": "finish", "run_id": "z", "agent": "cursor", "status": "SUCCESS", "duration_s": 1},
        ]
        lines = [json.dumps(r) for r in recs]
        lines.insert(3, "{not json")
        lines.insert(5, "")
        lines.append('["a list"]')
        self.events.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_format_stats_report_counts_per_agent(self):
        rep = dispatch_mod.format_stats_report(dispatch_mod.load_events(str(self.events)), days=7)
        row = {l.split()[0]: l.split() for l in rep.splitlines() if l.split() and l.split()[0] in ("agy", "codex", "cursor")}
        # agent runs ok% timeouts fallbacks verify_failed median
        self.assertEqual(row["agy"][1:], ["4", "25%", "1", "1", "1", "100s"])
        self.assertEqual(row["codex"][1:], ["1", "100%", "0", "0", "0", "10s"])
        self.assertNotIn("cursor", row)  # older than the window

    def test_stats_cli_exits_zero_and_tolerates_malformed_lines(self):
        env = dict(os.environ, DISPATCH_EVENTS_FILE=str(self.events))
        proc = subprocess.run([sys.executable, str(SCRIPT_PATH), "--stats"], capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("agy", proc.stdout)
        proc = subprocess.run([sys.executable, str(SCRIPT_PATH), "--stats", "60"], capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("cursor", proc.stdout)

    def test_stats_missing_file_exits_zero(self):
        env = dict(os.environ, DISPATCH_EVENTS_FILE=str(Path(self.temp_dir.name) / "nope.jsonl"))
        proc = subprocess.run([sys.executable, str(SCRIPT_PATH), "--stats"], capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("No dispatch events", proc.stdout)


class TestCodexDisabled(unittest.TestCase):
    """Codex is switched off in DISABLED_AGENTS: no route, mode or fallback may pick it."""

    WORKER_BIN = BIN_DIR / "dispatch-worker"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.agy_state = self.root / "agy.json"
        self.codex_state = self.root / "codex.json"
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        self._quota(self.agy_state, 40.0, 80.0)
        self._quota(self.codex_state, 100.0, 100.0)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _quota(self, path, five_hour, weekly):
        path.write_text(json.dumps({"windows": [
            {"kind": "five_hour", "remaining_percent": five_hour},
            {"kind": "weekly", "remaining_percent": weekly},
        ]}), encoding="utf-8")

    def _run(self, *args, script=None):
        # Hermetic: no user config, agy and codex quota from temp files, PATH without a real claude/codex.
        env = {k: v for k, v in os.environ.items()
               if "DISPATCH" not in k and k not in ("CLAUDE_THINK_MODEL", "CODEX_THINK_MODEL")}
        env.update({
            "DISPATCH_CONFIG_FILE": str(self.root / "no-config.env"),
            "DISPATCH_EVENTS_FILE": str(self.root / "events.jsonl"),
            "AGY_QUOTA_STATE_FILE": str(self.agy_state),
            "CODEX_QUOTA_STATE_FILE": str(self.codex_state),
            "PATH": f"{self.fake_bin}:/usr/bin:/bin",
        })
        # cwd is passed explicitly: the checkout path is echoed in dry-run output and may itself contain "codex".
        return subprocess.run([sys.executable, str(script or self.WORKER_BIN), "--cwd", str(self.root), *args],
                              capture_output=True, text=True, env=env)

    def _fake_claude(self):
        path = self.fake_bin / "claude"
        path.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
        path.chmod(0o755)

    def test_codex_is_in_disabled_agents(self):
        self.assertIn("codex", dispatch_mod.DISABLED_AGENTS)

    # 1. auto and the default chain never pick codex
    def test_auto_route_ignores_codex_with_higher_runway(self):
        agent, eligible, r5, _rw, msg = dispatch_mod.route_best_agent(
            min_5h=30.0, min_weekly=10.0, agy_state_file=str(self.agy_state), codex_state_file=str(self.codex_state))
        self.assertEqual((agent, eligible, r5), ("agy", True, 40.0))
        self.assertNotIn("codex", msg.lower())

    def test_auto_route_with_agy_low_does_not_pick_codex(self):
        self._quota(self.agy_state, 5.0, 5.0)
        agent, eligible, _r5, _rw, _msg = dispatch_mod.route_best_agent(
            min_5h=30.0, min_weekly=10.0, agy_state_file=str(self.agy_state), codex_state_file=str(self.codex_state))
        self.assertEqual((agent, eligible), ("agy", False))

    def test_default_runtime_fallback_has_no_codex(self):
        self.assertIsNone(dispatch_mod.route_execution_fallback(
            "agy", agy_state_file=str(self.agy_state), codex_state_file=str(self.codex_state)))

    def test_priority_router_skips_codex(self):
        agent, _model, eligible, _r5, _rw, _msg = dispatch_mod.route_priority_chain(
            [("codex", None), ("agy", None)], agy_state_file=str(self.agy_state), codex_state_file=str(self.codex_state))
        self.assertEqual((agent, eligible), ("agy", True))

    def test_cli_auto_dry_run_picks_agy(self):
        proc = self._run("--agent", "auto", "--dry-run", "--task", "x")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Would dispatch to agy", proc.stdout)
        self.assertNotIn("codex", proc.stdout.lower())

    def test_cli_auto_with_agy_low_falls_back_internal_not_codex(self):
        self._quota(self.agy_state, 5.0, 5.0)
        proc = self._run("--agent", "auto", "--dry-run", "--task", "x")
        self.assertEqual(proc.returncode, 10)
        self.assertNotIn("codex", proc.stdout.lower())

    # 2. a priority chain that names codex
    def test_cli_priority_chain_drops_codex_and_uses_agy(self):
        proc = self._run("--priority", "codex > agy", "--dry-run", "--task", "x")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Would dispatch to agy", proc.stdout)
        self.assertEqual(proc.stderr.count("codex is disabled"), 1)

    def test_cli_priority_chain_codex_only_fails(self):
        proc = self._run("--priority", "codex:gpt-5.6-terra", "--dry-run", "--task", "x")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("codex is disabled", proc.stderr)
        self.assertNotIn("Would dispatch", proc.stdout)
        self.assertNotIn("FALLBACK_INTERNAL", proc.stdout)

    # 3. --agent codex is refused
    def test_cli_agent_codex_is_refused(self):
        proc = self._run("--agent", "codex", "--dry-run", "--task", "x")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("codex is disabled", proc.stderr)
        self.assertNotIn("Would dispatch", proc.stdout)

    def test_cli_codex_named_binary_is_refused(self):
        proc = self._run("--dry-run", "--task", "x", script=CODEX_SCRIPT_PATH)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("codex is disabled", proc.stderr)

    def test_codex_named_binary_can_still_inspect_jobs(self):
        proc = self._run("--status", "all", "--job-dir", str(self.root / "jobs"), script=CODEX_SCRIPT_PATH)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_cli_explicit_auto_thinker_uses_claude_not_agy(self):
        self._fake_claude()
        proc = self._run("--think", "--agent", "auto", "--dry-run", "--task", "x")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("to claude with claude-opus-5-5", proc.stdout)

    def test_batch_item_naming_codex_is_refused(self):
        batch_file = self.root / "batch.json"
        batch_file.write_text(json.dumps([{"task": "x", "agent": "codex"}]), encoding="utf-8")
        proc = self._run("--agent", "agy", "--dry-run", "--batch-file", str(batch_file))
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("codex is disabled", proc.stderr)

    def test_build_command_refuses_codex(self):
        with self.assertRaises(ValueError):
            dispatch_mod.build_agent_command("codex", None, "task", "/tmp")

    # 4. the thinker is Claude Opus only
    def test_thinker_route_has_no_codex_fallback(self):
        with mock.patch.object(dispatch_mod, "check_quota", return_value=(True, 100.0, 100.0, "ok")):
            agent, model, eligible, _r5, _rw, _msg, fallback = dispatch_mod.route_thinker(
                codex_state_file=str(self.codex_state))
        self.assertEqual((agent, model, eligible, fallback), ("claude", "claude-opus-5-5", True, None))

    def test_cli_thinker_without_claude_fails_closed(self):
        proc = self._run("--capability", "deep-design-v1", "--dry-run", "--task", "x")
        self.assertEqual(proc.returncode, 12)
        self.assertNotIn("Would dispatch", proc.stdout)

    def test_cli_think_flag_without_claude_does_not_use_codex(self):
        proc = self._run("--think", "--dry-run", "--task", "x")
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Would dispatch", proc.stdout)

    def test_cli_think_with_non_claude_model_fails(self):
        self._fake_claude()
        for flags in (["--think"], ["--capability", "deep-design-v1"], ["--think", "--agent", "auto"]):
            for model in ("gpt-5.6-sol", "sol"):
                proc = self._run(*flags, "--model", model, "--dry-run", "--task", "x")
                self.assertEqual(proc.returncode, 12, (flags, model, proc.stdout, proc.stderr))
                self.assertIn(model, proc.stderr)
                self.assertNotIn("Would dispatch", proc.stdout)

    def test_cli_thinker_uses_claude_opus(self):
        self._fake_claude()
        proc = self._run("--think", "--dry-run", "--task", "x")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("to claude with claude-opus-5-5", proc.stdout)

    # 5. --check-quota neither reports nor depends on codex
    def test_check_quota_auto_ignores_codex(self):
        self.codex_state.unlink()
        proc = self._run("--check-quota")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("codex", proc.stdout.lower())

    def test_check_quota_priority_chain_with_codex_reports_agy(self):
        proc = self._run("--check-quota", "--priority", "codex > agy")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("40.0%", proc.stdout)
        self.assertNotIn("codex", proc.stdout.lower())
        self.assertIn("codex is disabled", proc.stderr)

    # 6. a pinned --agent takes its model from the configured preference chain
    def _configure_preference(self, chain):
        (self.root / "no-config.env").write_text(f'DISPATCH_ROUTING_PREFERENCE="{chain}"\n', encoding="utf-8")

    def test_explicit_agent_uses_model_from_configured_preference(self):
        self._configure_preference("cursor:other-model > agy:gemini-3.8-flash-high")
        proc = self._run("--agent", "agy", "--dry-run", "--task", "x")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Would dispatch to agy with gemini-3.8-flash-high", proc.stdout)

    def test_explicit_model_beats_configured_preference_model(self):
        self._configure_preference("agy:gemini-3.8-flash-high")
        proc = self._run("--agent", "agy", "--model", "gemini-pinned", "--dry-run", "--task", "x")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Would dispatch to agy with gemini-pinned", proc.stdout)
        self.assertNotIn("gemini-3.8-flash-high", proc.stdout)

    def test_explicit_agent_absent_from_preference_keeps_default_model(self):
        self._configure_preference("cursor:other-model")
        proc = self._run("--agent", "agy", "--dry-run", "--task", "x")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Would dispatch to agy in ", proc.stdout)

    # 7. --allow-stale proceeds on a stale quota reading
    def test_cli_allow_stale_proceeds_with_notice(self):
        old = time.time() - (dispatch_mod.STALE_OBSERVATION_MINUTES + 30) * 60
        os.utime(self.agy_state, (old, old))
        proc = self._run("--agent", "agy", "--dry-run", "--task", "x")
        self.assertEqual(proc.returncode, 10, proc.stdout + proc.stderr)
        proc = self._run("--agent", "agy", "--allow-stale", "--dry-run", "--task", "x")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Would dispatch to agy", proc.stdout)
        self.assertEqual(proc.stderr.count("NOTICE: proceeding on a stale quota reading (--allow-stale)"), 1)

    # 8. "was this flag given" is read from the parsed arguments, so `--x=value` counts like `--x value`
    def test_cli_priority_equals_form_is_honoured_with_pinned_agent(self):
        for flag in (["--priority=codex > agy:foo"], ["--priority", "codex > agy:foo"]):
            proc = self._run("--agent", "agy", *flag, "--dry-run", "--task", "x")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("Would dispatch to agy with foo", proc.stdout)
            self.assertEqual(proc.stderr.count("codex is disabled"), 1, flag)

    def _think_thresholds(self, *flags):
        seen = {}

        def fake_route_thinker(**kwargs):
            seen.update(kwargs)
            return "claude", "claude-opus-5-5", True, 100.0, 100.0, "ok", None

        argv = [str(self.WORKER_BIN), "--think", *flags, "--dry-run", "--task", "x", "--cwd", str(self.root)]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.dict(os.environ, {"DISPATCH_CONFIG_FILE": str(self.root / "no-config.env")}), \
                mock.patch.object(dispatch_mod, "route_thinker", fake_route_thinker), \
                mock.patch("builtins.print"), self.assertRaises(SystemExit) as exited:
            dispatch_mod.main()
        self.assertEqual(exited.exception.code, 0)
        return seen["min_5h"], seen["min_weekly"]

    def test_think_thresholds_honour_equals_form(self):
        think_defaults = (dispatch_mod.DEFAULT_THINK_MIN_5H, dispatch_mod.DEFAULT_THINK_MIN_WEEKLY)
        self.assertEqual(self._think_thresholds(), think_defaults)
        self.assertEqual(self._think_thresholds("--min-5h", "55", "--min-weekly", "44"), (55.0, 44.0))
        self.assertEqual(self._think_thresholds("--min-5h=55", "--min-weekly=44"), (55.0, 44.0))

    # 9. built-in worker timeout
    def test_builtin_default_timeout_is_2400s(self):
        proc = self._run("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("(default: 2400s)", " ".join(proc.stdout.split()))
        # and the --wait budget derived from it: worker + verify + one retry + verify
        self.assertEqual(dispatch_mod.wait_budget_seconds([{}], 2400), 2 * 2400 + 2 * dispatch_mod.DEFAULT_VERIFY_TIMEOUT)

    def test_help_does_not_offer_codex(self):
        proc = self._run("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("codex", proc.stdout.lower())


if __name__ == "__main__":
    unittest.main()

