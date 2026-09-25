#!/usr/bin/env python3
"""
Unit tests for the verify-before-merge step of bin/dispatch-agy-worker.

Every worker and verify command here is a fake (`true`, `false`, tiny temp shell
scripts). No real agy / Codex / Cursor process is ever started.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "bin" / "dispatch-agy-worker"

import importlib.machinery
import importlib.util
loader = importlib.machinery.SourceFileLoader("dispatch_agy_worker_verify", str(SCRIPT_PATH))
spec = importlib.util.spec_from_loader("dispatch_agy_worker_verify", loader)
dispatch_mod = importlib.util.module_from_spec(spec)
loader.exec_module(dispatch_mod)


def _write_executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _init_repo(repo_dir):
    repo_dir.mkdir(parents=True, exist_ok=True)
    for cmd in (
        ["git", "init"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test User"],
    ):
        subprocess.run(cmd, cwd=repo_dir, check=True, capture_output=True)
    (repo_dir / "initial.txt").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True, capture_output=True)


def _head(repo_dir):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True
    ).stdout.strip()


class VerifyTestBase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.repo_dir = self.tmp / "repo"
        _init_repo(self.repo_dir)
        self.worker_calls = self.tmp / "worker-calls.log"
        self.prompts = []

    def tearDown(self):
        self.temp_dir.cleanup()

    def _fake_worker(self, script="true"):
        """Patches build_agent_command with a fake shell worker that logs each invocation."""
        def _build(chosen_agent, chosen_model, wrapped_task, target_dir, output_file=None, **kwargs):
            self.prompts.append(wrapped_task)
            return ["sh", "-c", f"echo call >> '{self.worker_calls}'; {script}"]
        return mock.patch.object(dispatch_mod, "build_agent_command", side_effect=_build)

    def _worker_call_count(self):
        if not self.worker_calls.exists():
            return 0
        return len(self.worker_calls.read_text(encoding="utf-8").splitlines())

    def _run(self, target_dir=None, **verify_opts):
        info = {}
        result = dispatch_mod.run_single_task(
            "do the thing", str(target_dir or self.repo_dir), "agy", None, 30,
            verify_opts=verify_opts, verify_info=info,
        )
        return result, info


class TestResolveVerifyCmd(VerifyTestBase):
    def test_default_resolves_to_precheck_when_present_and_executable(self):
        _write_executable(self.repo_dir / "scripts" / "precheck.sh", "#!/bin/sh\nexit 0\n")
        cmd, source = dispatch_mod.resolve_verify_cmd(str(self.repo_dir))
        self.assertEqual(cmd, "./scripts/precheck.sh")
        self.assertEqual(source, "default")

    def test_default_is_none_when_precheck_missing(self):
        cmd, source = dispatch_mod.resolve_verify_cmd(str(self.repo_dir))
        self.assertIsNone(cmd)
        self.assertEqual(source, "none")

    def test_default_is_none_when_precheck_not_executable(self):
        script = self.repo_dir / "scripts" / "precheck.sh"
        script.parent.mkdir()
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o644)
        cmd, source = dispatch_mod.resolve_verify_cmd(str(self.repo_dir))
        self.assertIsNone(cmd)
        self.assertEqual(source, "none")

    def test_explicit_cmd_wins_over_default(self):
        _write_executable(self.repo_dir / "scripts" / "precheck.sh", "#!/bin/sh\nexit 0\n")
        cmd, source = dispatch_mod.resolve_verify_cmd(str(self.repo_dir), verify_cmd="make test")
        self.assertEqual(cmd, "make test")
        self.assertEqual(source, "explicit")

    def test_no_verify_disables_even_with_precheck(self):
        _write_executable(self.repo_dir / "scripts" / "precheck.sh", "#!/bin/sh\nexit 0\n")
        cmd, source = dispatch_mod.resolve_verify_cmd(str(self.repo_dir), no_verify=True)
        self.assertIsNone(cmd)
        self.assertEqual(source, "disabled")


class TestRunVerifyCmd(VerifyTestBase):
    def test_passing_command(self):
        ok, tail, is_timeout = dispatch_mod.run_verify_cmd("true", str(self.repo_dir), 10)
        self.assertTrue(ok)
        self.assertFalse(is_timeout)

    def test_failing_command_returns_tail_of_at_most_40_lines(self):
        cmd = "i=0; while [ $i -lt 100 ]; do echo line-$i; i=$((i+1)); done; exit 3"
        ok, tail, is_timeout = dispatch_mod.run_verify_cmd(cmd, str(self.repo_dir), 10)
        self.assertFalse(ok)
        self.assertFalse(is_timeout)
        lines = tail.splitlines()
        self.assertLessEqual(len(lines), 41)  # 40 output lines + 1 exit-status line
        self.assertIn("line-99", tail)
        self.assertNotIn("line-10\n", tail)

    def test_timeout_is_failure(self):
        ok, tail, is_timeout = dispatch_mod.run_verify_cmd("sleep 30", str(self.repo_dir), 1)
        self.assertFalse(ok)
        self.assertTrue(is_timeout)
        self.assertIn("timed out", tail)

    def test_runs_inside_target_dir(self):
        ok, tail, _ = dispatch_mod.run_verify_cmd("test -f initial.txt", str(self.repo_dir), 10)
        self.assertTrue(ok)


class TestRunSingleTaskVerify(VerifyTestBase):
    def test_verify_pass_runs_worker_once_and_marks_verified(self):
        with self._fake_worker():
            (exit_code, *_), info = self._run(verify_cmd="true")
        self.assertEqual(exit_code, 0)
        self.assertEqual(self._worker_call_count(), 1)
        self.assertIs(info["verified"], True)
        self.assertEqual(info["verify_cmd"], "true")

    def test_verify_failure_retries_exactly_once_then_fails(self):
        gate = self.tmp / "gate.sh"  # marker lives in the script body, not in the command text
        _write_executable(gate, "#!/bin/sh\necho BOOM-MARKER\nexit 1\n")
        with self._fake_worker():
            (exit_code, _out, stderr, *_), info = self._run(verify_cmd=str(gate))
        self.assertEqual(exit_code, dispatch_mod.VERIFY_FAILED_EXIT_CODE)
        self.assertEqual(self._worker_call_count(), 2)
        self.assertIs(info["verified"], False)
        self.assertEqual(info["verify_attempts"], 2)
        self.assertIn("BOOM-MARKER", info["verify_output"])
        self.assertIn("VERIFY FAILED", stderr)
        # The retry prompt carries the failure output and the fix instruction
        self.assertEqual(len(self.prompts), 2)
        self.assertNotIn("BOOM-MARKER", self.prompts[0])
        self.assertIn("BOOM-MARKER", self.prompts[1])
        self.assertIn("do the thing", self.prompts[1])

    def test_retry_that_fixes_the_failure_ends_verified(self):
        marker = self.tmp / "fixed"
        # Worker creates the marker only on its second invocation
        script = f"[ $(wc -l < '{self.worker_calls}') -ge 2 ] && touch '{marker}'; true"
        with self._fake_worker(script):
            (exit_code, *_), info = self._run(verify_cmd=f"test -f '{marker}'")
        self.assertEqual(exit_code, 0)
        self.assertEqual(self._worker_call_count(), 2)
        self.assertIs(info["verified"], True)
        self.assertEqual(info["verify_attempts"], 2)

    def test_verify_timeout_is_treated_as_failure(self):
        with self._fake_worker():
            (exit_code, *_), info = self._run(verify_cmd="sleep 30", verify_timeout=1)
        self.assertEqual(exit_code, dispatch_mod.VERIFY_FAILED_EXIT_CODE)
        self.assertIs(info["verified"], False)
        self.assertIn("timed out", info["verify_output"])

    def test_no_verify_skips(self):
        _write_executable(self.repo_dir / "scripts" / "precheck.sh", "#!/bin/sh\nexit 1\n")
        with self._fake_worker():
            (exit_code, *_), info = self._run(no_verify=True)
        self.assertEqual(exit_code, 0)
        self.assertEqual(self._worker_call_count(), 1)
        self.assertEqual(info["verified"], "skipped")
        self.assertIsNone(info["verify_cmd"])

    def test_default_precheck_is_used_and_blocks(self):
        _write_executable(self.repo_dir / "scripts" / "precheck.sh", "#!/bin/sh\necho gate-red\nexit 1\n")
        with self._fake_worker():
            (exit_code, *_), info = self._run()
        self.assertEqual(exit_code, dispatch_mod.VERIFY_FAILED_EXIT_CODE)
        self.assertEqual(info["verify_cmd"], "./scripts/precheck.sh")
        self.assertIn("gate-red", info["verify_output"])

    def test_no_gate_available_is_skipped_with_warning(self):
        with self._fake_worker(), mock.patch("sys.stderr") as fake_err:
            (exit_code, *_), info = self._run()
        self.assertEqual(exit_code, 0)
        self.assertEqual(info["verified"], "skipped")
        written = "".join(call.args[0] for call in fake_err.write.call_args_list)
        self.assertIn("UNVERIFIED", written)

    def test_worker_failure_does_not_run_verify(self):
        sentinel = self.tmp / "verify-ran"
        with self._fake_worker("exit 7"):
            (exit_code, *_), info = self._run(verify_cmd=f"touch '{sentinel}'")
        self.assertEqual(exit_code, 7)
        self.assertFalse(sentinel.exists())
        self.assertEqual(self._worker_call_count(), 1)
        self.assertEqual(info["verified"], "skipped")


class TestReviewFindings(VerifyTestBase):
    def test_worker_own_exit_13_is_not_reported_as_verify_failure(self):
        with self._fake_worker(f"exit {dispatch_mod.VERIFY_FAILED_EXIT_CODE}"):
            (exit_code, *_), info = self._run(verify_cmd="true")
        self.assertEqual(exit_code, 1)
        self.assertEqual(info["verified"], "skipped")
        self.assertEqual(info["verify_attempts"], 0)

    def test_batch_does_not_redispatch_without_verify_on_internal_typeerror(self):
        calls = []

        def _boom(*args, **kwargs):
            calls.append(kwargs)
            raise TypeError("bug inside run_single_task")

        with mock.patch.object(dispatch_mod, "run_single_task", side_effect=_boom):
            results = dispatch_mod.execute_batch_parallel(
                [{"task": "t1", "verify_cmd": "true"}], base_repo_dir=str(self.repo_dir),
                chosen_agent="agy", chosen_model=None, timeout_seconds=30, max_parallel=1,
            )
        self.assertEqual(len(calls), 1)
        self.assertIn("verify_opts", calls[0])
        self.assertNotEqual(results[0]["exit_code"], 0)

    def test_batch_overall_exit_code(self):
        vf = dispatch_mod.VERIFY_FAILED_EXIT_CODE
        self.assertEqual(dispatch_mod.batch_overall_exit([{"exit_code": 0}, {"exit_code": 0}]), 0)
        self.assertEqual(dispatch_mod.batch_overall_exit([{"exit_code": 0}, {"exit_code": vf}]), vf)
        self.assertEqual(dispatch_mod.batch_overall_exit([{"exit_code": 1}, {"exit_code": vf}]), 1)


class TestVerifyBlocksMerge(VerifyTestBase):
    COMMIT_WORKER = (
        "echo new > worker_file.txt && git add worker_file.txt && "
        "git commit -q -m 'worker commit'; true"  # `; true`: the retry run has nothing new to commit
    )

    def _dispatch_isolated(self, **verify_opts):
        info = {}

        def _execute(target_dir):
            return dispatch_mod.run_single_task(
                "do the thing", target_dir, "agy", None, 30,
                verify_opts=verify_opts, verify_info=info,
            )

        with self._fake_worker(self.COMMIT_WORKER):
            result = dispatch_mod.execute_in_isolated_worktree(str(self.repo_dir), _execute)
        return result, info

    def _cleanup_salvage(self, stderr):
        for line in stderr.splitlines():
            if "Commits preserved on git branch" in line:
                branch = line.split("'")[1]
                subprocess.run(["git", "branch", "-D", branch], cwd=self.repo_dir, capture_output=True)
            if "Partial work preserved at" in line:
                path = line.split("preserved at")[-1].strip()
                if os.path.isfile(path):
                    os.unlink(path)

    def test_verify_failure_blocks_merge_and_keeps_worktree(self):
        head_before = _head(self.repo_dir)
        (exit_code, _out, stderr, *_), info = self._dispatch_isolated(verify_cmd="false")
        kept = info.get("worktree")
        try:
            self.assertEqual(exit_code, dispatch_mod.VERIFY_FAILED_EXIT_CODE)
            self.assertEqual(_head(self.repo_dir), head_before)
            self.assertFalse((self.repo_dir / "worker_file.txt").exists())
            self.assertIs(info["verified"], False)
            # Worktree left in place for inspection, with the worker's file in it
            self.assertTrue(kept and os.path.isdir(kept))
            self.assertTrue((Path(kept) / "worker_file.txt").exists())
            self.assertIn(kept, stderr)
            # The kept worktree IS the preserved work: no extra salvage branch/patch clutter
            self.assertNotIn("[Salvage]", stderr)
        finally:
            if kept:
                subprocess.run(["git", "worktree", "remove", "--force", kept], cwd=self.repo_dir, capture_output=True)
                shutil.rmtree(kept, ignore_errors=True)
            self._cleanup_salvage(stderr)

    def test_verify_pass_merges_and_removes_worktree(self):
        head_before = _head(self.repo_dir)
        (exit_code, *_), info = self._dispatch_isolated(verify_cmd="test -f worker_file.txt")
        self.assertEqual(exit_code, 0)
        self.assertNotEqual(_head(self.repo_dir), head_before)
        self.assertTrue((self.repo_dir / "worker_file.txt").exists())
        self.assertIs(info["verified"], True)
        self.assertFalse(os.path.exists(info["worktree"]))


class TestPromptContractVerify(unittest.TestCase):
    def test_names_the_verify_command_and_drops_the_e2e_ban(self):
        wrapped = dispatch_mod.wrap_prompt_contract("task", verify_cmd="./scripts/precheck.sh")
        self.assertIn("./scripts/precheck.sh", wrapped)
        self.assertIn("paste its final lines", wrapped)
        self.assertNotIn("Do NOT run the", wrapped)
        self.assertNotIn("end-to-end suite for scoped", wrapped)

    def test_no_verify_command_still_drops_the_e2e_ban(self):
        wrapped = dispatch_mod.wrap_prompt_contract("task")
        self.assertNotIn("Do NOT run the", wrapped)

    def test_acceptance_criteria_section(self):
        wrapped = dispatch_mod.wrap_prompt_contract("task", acceptance="- rows in == rows out\n- button is clickable")
        self.assertIn("Acceptance criteria:", wrapped)
        self.assertIn("rows in == rows out", wrapped)
        self.assertLess(wrapped.index("Acceptance criteria:"), wrapped.index("Task Brief:"))

    def test_no_acceptance_section_when_not_given(self):
        self.assertNotIn("Acceptance criteria:", dispatch_mod.wrap_prompt_contract("task"))

    def test_thinking_mode_contract_unchanged_by_verify(self):
        wrapped = dispatch_mod.wrap_prompt_contract("task", is_thinking=True, acceptance="must cover X")
        self.assertIn("Thinking / Architecture Mode", wrapped)
        self.assertIn("must cover X", wrapped)


class TestResultCarriesVerifiedField(VerifyTestBase):
    def test_format_report_has_verified_line_within_15_lines(self):
        long_output = "\n".join(f"log {i}" for i in range(50))
        report = dispatch_mod.format_report(
            "agy", "VERIFY_FAILED", dispatch_mod.VERIFY_FAILED_EXIT_CODE, "/d", 1, "1 file", long_output,
            verify_info={"verified": False, "verify_cmd": "./scripts/precheck.sh"},
        )
        lines = report.splitlines()
        self.assertLessEqual(len(lines), 15)
        self.assertIn("Verified: false (./scripts/precheck.sh)", lines)

    def test_format_report_defaults_to_skipped(self):
        report = dispatch_mod.format_report("agy", "SUCCESS", 0, "/d", 0, "none", "ok")
        self.assertIn("Verified: skipped (no verify command)", report.splitlines())

    def test_batch_results_carry_verified_field(self):
        with self._fake_worker():
            results = dispatch_mod.execute_batch_parallel(
                [{"task": "t1", "verify_cmd": "true"}, {"task": "t2", "no_verify": True}],
                base_repo_dir=str(self.repo_dir), chosen_agent="agy", chosen_model=None,
                timeout_seconds=30, max_parallel=1,
            )
        self.assertIs(results[0]["verified"], True)
        self.assertEqual(results[0]["verify_cmd"], "true")
        self.assertEqual(results[1]["verified"], "skipped")
        self.assertIsNone(results[1]["verify_cmd"])

    def test_detached_job_state_carries_verified_field(self):
        job_dir = str(self.tmp / "jobs")
        dispatch_mod.save_job_state("job-1", {
            "job_id": "job-1", "agent": "agy", "task": "t", "cwd": str(self.repo_dir),
            "isolated": False, "timeout": 30, "verify_cmd": "false", "verify_timeout": 5,
        }, job_dir=job_dir)
        with self._fake_worker(), self.assertRaises(SystemExit) as ctx:
            dispatch_mod.run_internal_job("job-1", job_dir=job_dir)
        self.assertEqual(ctx.exception.code, dispatch_mod.VERIFY_FAILED_EXIT_CODE)
        state = dispatch_mod.load_job_state("job-1", job_dir=job_dir)
        self.assertEqual(state["status"], "VERIFY_FAILED")
        self.assertIs(state["verified"], False)
        self.assertEqual(state["verify_cmd"], "false")


class TestVerifyCLI(VerifyTestBase):
    """End-to-end through the real CLI, with a fake `agy` binary first on PATH."""

    def setUp(self):
        super().setUp()
        self.state_file = self.tmp / "quota.json"
        self.state_file.write_text(json.dumps({"snapshot": {"windows": [
            {"kind": "five_hour", "remaining_percent": 90.0},
            {"kind": "weekly", "remaining_percent": 90.0},
        ]}}), encoding="utf-8")
        self.fake_bin = self.tmp / "fakebin"
        _write_executable(self.fake_bin / "agy", f"#!/bin/sh\necho call >> '{self.worker_calls}'\necho fake-agy-done\n")
        self.env = os.environ.copy()
        self.env["PATH"] = f"{self.fake_bin}:{self.env.get('PATH', '')}"

    def _cli(self, *extra):
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--agent", "agy", "--state-file", str(self.state_file),
             "--cwd", str(self.repo_dir), "--task", "do the thing", *extra],
            capture_output=True, text=True, env=self.env, timeout=60,
        )

    def test_cli_verify_failure_exit_code_and_report(self):
        res = self._cli("--verify-cmd", "echo GATE-RED-LINE; false", "--acceptance", "it works")
        self.assertEqual(res.returncode, dispatch_mod.VERIFY_FAILED_EXIT_CODE, res.stderr[-500:])
        self.assertIn("Status: VERIFY_FAILED", res.stdout)
        self.assertIn("Verified: false", res.stdout)
        self.assertIn("GATE-RED-LINE", res.stdout + res.stderr)
        self.assertEqual(self._worker_call_count(), 2)

    def test_cli_verify_pass(self):
        res = self._cli("--verify-cmd", "true", "--acceptance", "it works")
        self.assertEqual(res.returncode, 0, res.stderr[-500:])
        self.assertIn("Verified: true (true)", res.stdout)
        self.assertNotIn("no acceptance criteria", res.stderr.lower())

    def test_cli_no_verify_and_missing_acceptance_warn_but_run(self):
        res = self._cli("--no-verify")
        self.assertEqual(res.returncode, 0, res.stderr[-500:])
        self.assertIn("Verified: skipped", res.stdout)
        self.assertIn("no acceptance criteria", res.stderr.lower())

    def test_cli_acceptance_file(self):
        acc = self.tmp / "acceptance.md"
        acc.write_text("- totals match source row count\n", encoding="utf-8")
        _write_executable(
            self.fake_bin / "agy",
            f"#!/bin/sh\nprintf '%s' \"$*\" > '{self.tmp}/prompt.txt'\n",
        )
        res = self._cli("--verify-cmd", "true", "--acceptance-file", str(acc))
        self.assertEqual(res.returncode, 0, res.stderr[-500:])
        self.assertIn("totals match source row count", (self.tmp / "prompt.txt").read_text(encoding="utf-8"))

    def test_cli_verify_and_no_verify_are_mutually_exclusive(self):
        res = self._cli("--verify-cmd", "true", "--no-verify", "--dry-run")
        self.assertEqual(res.returncode, 2)

    def test_cli_dry_run_names_the_verify_plan(self):
        res = self._cli("--verify-cmd", "make gate", "--dry-run")
        self.assertEqual(res.returncode, 0)
        self.assertIn("make gate", res.stdout)


if __name__ == "__main__":
    unittest.main()
