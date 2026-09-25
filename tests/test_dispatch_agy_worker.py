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
        self.assertEqual(dispatch_mod.get_config_timeout({}), 900)
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
    """dispatch-thinker (deep-design-v1): Claude Opus 5.5 first, Codex gpt-5.6-sol fallback, exit 12 if neither.

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

    def test_dry_run_falls_back_to_codex_sol_when_claude_missing(self):
        self._codex_quota(100.0, 100.0)
        proc = self._run("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("to codex with gpt-5.6-sol", proc.stdout)

    def test_skip_claude_env_forces_codex(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--dry-run", env_extra={"DISPATCH_THINKER_SKIP_CLAUDE": "1"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("to codex with gpt-5.6-sol", proc.stdout)

    def test_both_unavailable_fails_closed_12(self):
        self._codex_quota(10.0, 5.0)
        proc = self._run("--dry-run")
        self.assertEqual(proc.returncode, 12)
        self.assertIn("Thinker unavailable", proc.stderr)
        self.assertIn("claude", proc.stderr.lower())
        self.assertIn("CODEX", proc.stderr)

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

    def test_explicit_agent_codex_is_respected(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--dry-run", "--agent", "codex")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("to codex with gpt-5.6-sol", proc.stdout)

    def test_explicit_agent_claude_is_respected(self):
        self._fake("claude")
        proc = self._run("--dry-run", "--agent", "claude")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("to claude with claude-opus-5-5", proc.stdout)

    def test_runtime_claude_failure_falls_back_to_codex(self):
        self._fake("claude", exit_code=1, output="claude-boom")
        self._fake("codex", exit_code=0, output="sol-ok")
        self._codex_quota(100.0, 100.0)
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("sol-ok", proc.stdout)
        calls = self.calls_log.read_text(encoding="utf-8").splitlines()
        self.assertTrue(calls[0].startswith("claude -p --model claude-opus-5-5"), calls)
        self.assertTrue(calls[1].startswith("codex exec"), calls)
        self.assertIn('model="gpt-5.6-sol"', calls[1])
        attestation = json.loads((self.repo / ".thinker.json").read_text(encoding="utf-8"))
        self.assertEqual(attestation["agent"], "codex")
        self.assertEqual(attestation["model"], "gpt-5.6-sol")

    def test_runtime_claude_failure_without_eligible_codex_returns_failure(self):
        self._fake("claude", exit_code=1, output="claude-boom")
        self._codex_quota(10.0, 5.0)
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

    def test_runtime_fallback_discards_claude_partial_output_file_then_retries(self):
        out = self.repo / "design.md"
        self._fake("claude", exit_code=1, body=f"echo partial > '{out}'")
        self._fake("codex", output="sol-ok")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--output-file", str(out))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        calls = self.calls_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual([c.split()[0] for c in calls], ["claude", "codex"])
        self.assertFalse(out.exists(), "Claude's partial output must not be attributed to codex")

    def test_runtime_fallback_refused_when_claude_left_other_changes(self):
        (self.repo / "user-wip.txt").write_text("mine", encoding="utf-8")  # user's own uncommitted work
        self._fake("claude", exit_code=1, body=f"echo stray > '{self.repo}/stray.txt'")
        self._fake("codex", output="sol-ok")
        self._codex_quota(100.0, 100.0)
        proc = self._run()
        self.assertEqual(proc.returncode, 12, proc.stdout + proc.stderr)
        self.assertIn("stray.txt", proc.stderr)
        self.assertNotIn("user-wip.txt", proc.stderr)
        calls = self.calls_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(calls), 1, calls)
        self.assertTrue((self.repo / "stray.txt").exists())
        self.assertTrue((self.repo / "user-wip.txt").exists())

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

    def test_thinking_mode_defaults_to_high_effort(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("(effort: high)", proc.stdout)

    def test_thinking_mode_effort_override_cli(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--dry-run", "--effort", "max")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("(effort: max)", proc.stdout)

    def test_thinking_mode_effort_override_env(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--dry-run", env_extra={"THINK_EFFORT": "medium"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("(effort: medium)", proc.stdout)

    def test_claude_run_passes_effort_flag(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        args = self._args("claude")
        self.assertIn("--effort", args)
        self.assertEqual(args[args.index("--effort") + 1], "high")

    def test_claude_run_custom_effort_flag(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--effort", "xhigh")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        args = self._args("claude")
        self.assertIn("--effort", args)
        self.assertEqual(args[args.index("--effort") + 1], "xhigh")

    def test_codex_run_passes_reasoning_effort_config(self):
        self._fake("claude")
        self._fake("codex", output="sol-ok")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--agent", "codex")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        calls = self.calls_log.read_text(encoding="utf-8").splitlines()
        self.assertTrue(calls[0].startswith("codex exec"), calls)
        args = self._args("codex")
        self.assertIn('model_reasoning_effort="high"', args)

    def test_codex_run_normalizes_max_effort_to_high(self):
        self._fake("claude")
        self._fake("codex", output="sol-ok")
        self._codex_quota(100.0, 100.0)
        proc = self._run("--agent", "codex", "--effort", "max")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        args = self._args("codex")
        self.assertIn('model_reasoning_effort="high"', args)

    def test_attestation_records_effort(self):
        self._fake("claude")
        self._codex_quota(100.0, 100.0)
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        attestation = json.loads((self.repo / ".thinker.json").read_text(encoding="utf-8"))
        self.assertEqual(attestation["effort"], "high")


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


if __name__ == "__main__":
    unittest.main()

