#!/usr/bin/env python3
"""Unit tests for bin/sdd-drive.

Covers all 9 acceptance criteria:
(1) A plan of 4 tasks with all green reviews runs start to finish, exit 0, and
    prints one final summary of at most 15 lines.
(2) The ledger stays <= 2048 bytes after every transition and is written atomically.
(3) Needs-fixes triggers exactly one fix and one re-review; still failing exits with
    a distinct non-zero code naming the task and the report path, and never advances.
(4) The script advances ONLY on an explicit approved verdict: an empty, missing,
    unparsable or unknown review verdict stops and wakes, never advances.
(5) A worker result advances only when status is success, files modified > 0 and
    verified is true; BLOCKED, NEEDS_CONTEXT, verify failure, a timeout, and
    fallback exit 10 each stop with their own reason.
(6) Re-running after a stop resumes from the ledger and skips finished tasks.
(7) Each task has a hard time limit, and hitting it stops with a reason, never hangs.
(8) SDD_DRIVE=off exits non-zero with a clear message, doing nothing.
(9) progress-sync failure never stops the run.
"""

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "sdd-drive"


class TestSddDrive(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)

        # Initialize mock git repository
        self.repo_dir = self.tmp_path / "repo"
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(self.repo_dir)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo_dir), "config", "user.email", "test@test.local"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo_dir), "config", "user.name", "Test User"], check=True, capture_output=True)
        (self.repo_dir / "README.md").write_text("# Test Repo\n")
        subprocess.run(["git", "-C", str(self.repo_dir), "add", "README.md"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo_dir), "commit", "-m", "initial commit"], check=True, capture_output=True)

        # Plan file
        self.plan_file = self.repo_dir / "plan.md"
        self.plan_content = """# Feature Plan

## Task 1: First Task
Verify-Cmd: pytest tests/test_1.py
Implement task 1.

## Task 2: Second Task
Verify-Cmd: pytest tests/test_2.py
Implement task 2.

## Task 3: Third Task
Verify-Cmd: pytest tests/test_3.py
Implement task 3.

## Task 4: Fourth Task
Verify-Cmd: pytest tests/test_4.py
Implement task 4.
"""
        self.plan_file.write_text(self.plan_content)

        # Create bin directory for fake scripts
        self.fake_bin_dir = self.tmp_path / "fake_bin"
        self.fake_bin_dir.mkdir(parents=True, exist_ok=True)

        # Tracking logs
        self.worker_log = self.tmp_path / "worker.log"
        self.review_log = self.tmp_path / "review.log"
        self.sync_log = self.tmp_path / "sync.log"
        self.ledger_history_log = self.tmp_path / "ledger_history.log"

        # Create fake scripts
        self._setup_fake_scripts()

    def _make_executable(self, path: Path, content: str) -> None:
        path.write_text(content)
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _setup_fake_scripts(self) -> None:
        # Fake dispatch-worker
        worker_script = f"""#!/usr/bin/env python3
import sys
import os
import argparse
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--agent")
parser.add_argument("--cwd")
parser.add_argument("--task", default="")
parser.add_argument("--verify-cmd")
parser.add_argument("--acceptance-file")
parser.add_argument("--output-file")
parser.add_argument("--timeout", type=float)
parser.add_argument("--model")
args, _ = parser.parse_known_args()

sleep_sec = float(os.environ.get("FAKE_WORKER_SLEEP", "0"))
if sleep_sec > 0:
    import time
    time.sleep(sleep_sec)

# Check if this invocation is for review
is_review = "review task" in args.task.lower() or (args.output_file and "review" in args.output_file)

if is_review:
    rev_log = Path("{self.review_log}")
    with open(rev_log, "a") as f:
        f.write("REVIEW_INVOKED: " + " ".join(sys.argv[1:]) + "\\n")
    verdict = os.environ.get("FAKE_REVIEW_VERDICT", "Approved")
    review_exit = int(os.environ.get("FAKE_REVIEW_EXIT", "0"))
    content = os.environ.get("FAKE_REVIEW_CONTENT")
    if content is None:
        if verdict == "EMPTY":
            content = ""
        elif verdict == "UNPARSABLE":
            content = "# Review\\nLooks somewhat ok maybe.\\n"
        else:
            content = f"# Review\\n\\n### Assessment\\n**Task quality:** {{verdict}}\\n- **Quality:** {{verdict}}\\nVerdict: {{verdict}}\\nReasoning: Checked thoroughly.\\n"
    if args.output_file:
        Path(args.output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_file).write_text(content)
    print(content)
    sys.exit(review_exit)

# Otherwise it's an implementer worker
log_file = Path("{self.worker_log}")
with open(log_file, "a") as f:
    f.write("WORKER_INVOKED: " + " ".join(sys.argv[1:]) + "\\n")

worker_status = os.environ.get("FAKE_WORKER_STATUS", "SUCCESS")
worker_exit = int(os.environ.get("FAKE_WORKER_EXIT", "0"))
worker_files = int(os.environ.get("FAKE_WORKER_FILES_CHANGED", "2"))
worker_verified = os.environ.get("FAKE_WORKER_VERIFIED", "true")

# Modify repo to simulate actual git changes if files > 0
if worker_files > 0 and args.cwd:
    t_file = Path(args.cwd) / "touched.txt"
    with open(t_file, "a") as f:
        f.write(f"touch by worker: {{args.task}}\\n")
    subprocess.run(["git", "-C", args.cwd, "add", "touched.txt"], check=False, capture_output=True)
    subprocess.run(["git", "-C", args.cwd, "commit", "-m", f"feat: {{args.task}}"], check=False, capture_output=True)

verif_line = "" if worker_verified == "OMIT" else f"Verified: {{worker_verified}} ({{args.verify_cmd or 'none'}})"

report = f\"\"\"=== AGY SUBAGENT REPORT ===
Status: {{worker_status}} (exit {{worker_exit}})
Directory: {{args.cwd}}
Files Modified: {{worker_files}} (1 file changed)
{{verif_line}}
Last Output:
completed work
===========================
\"\"\"

if args.output_file:
    Path(args.output_file).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_file).write_text(report)

print(report)
sys.exit(worker_exit)
"""
        self.fake_dispatch_worker = self.fake_bin_dir / "fake-dispatch-worker"
        self._make_executable(self.fake_dispatch_worker, worker_script)

        # Fake dispatch-thinker (calls dispatch-worker with thinker arguments)
        thinker_script = f"""#!/usr/bin/env bash
exec "{self.fake_dispatch_worker}" "$@"
"""
        self.fake_dispatch_thinker = self.fake_bin_dir / "fake-dispatch-thinker"
        self._make_executable(self.fake_dispatch_thinker, thinker_script)

        # Fake jev-gate
        jev_script = """#!/usr/bin/env python3
import sys
import os

tier = os.environ.get("FAKE_JEV_TIER", "single_flash_reviewer")
if "--hook-line" in sys.argv:
    print(f"jev-gate triage (10ms, $0.00010): tier={tier} (conf=0.95, risk=0.10) | run=code-reviewer | skip=none")
else:
    print(f'{{"review_tier": "{tier}"}}')
sys.exit(0)
"""
        self.fake_jev_gate = self.fake_bin_dir / "fake-jev-gate"
        self._make_executable(self.fake_jev_gate, jev_script)

        # Fake progress-sync
        sync_script = f"""#!/usr/bin/env python3
import sys
import os
from pathlib import Path

log_file = Path("{self.sync_log}")
with open(log_file, "a") as f:
    f.write("SYNC: " + " ".join(sys.argv[1:]) + "\\n")

# Check if simulated failure
if os.environ.get("FAKE_PROGRESS_SYNC_FAIL") == "1":
    sys.stderr.write("fake progress-sync crashed\\n")
    sys.exit(1)

# Check ledger size whenever progress-sync is called with --file
for i, arg in enumerate(sys.argv):
    if arg == "--file" and i + 1 < len(sys.argv):
        p = Path(sys.argv[i + 1])
        if p.exists():
            size = p.stat().st_size
            with open(Path("{self.ledger_history_log}"), "a") as hf:
                hf.write(f"{{p}}: {{size}} bytes\\n")
sys.exit(0)
"""
        self.fake_progress_sync = self.fake_bin_dir / "fake-progress-sync"
        self._make_executable(self.fake_progress_sync, sync_script)

        # Fake task-brief
        brief_script = """#!/usr/bin/env python3
import sys
from pathlib import Path
import re

if len(sys.argv) < 3:
    sys.exit(2)
plan = Path(sys.argv[1])
task_num = sys.argv[2]
out_file = Path(sys.argv[3]) if len(sys.argv) > 3 else plan.parent / f"task-{task_num}-brief.md"

content = plan.read_text()
# Find task section
pattern = rf'(?s)(#+\\s+Task\\s+{task_num}\\b.*?)(?=#+\\s+Task|\\Z)'
m = re.search(pattern, content)
if not m:
    sys.stderr.write(f"Task {task_num} not found\\n")
    sys.exit(3)

out_file.parent.mkdir(parents=True, exist_ok=True)
out_file.write_text(m.group(1))
print(f"wrote {out_file}")
sys.exit(0)
"""
        self.fake_task_brief = self.fake_bin_dir / "fake-task-brief"
        self._make_executable(self.fake_task_brief, brief_script)

        # Fake review-package
        review_package_script = """#!/usr/bin/env python3
import sys
from pathlib import Path
import subprocess

if len(sys.argv) < 4:
    sys.exit(2)
plan = Path(sys.argv[1])
base = sys.argv[2]
head = sys.argv[3]
out = Path(sys.argv[4]) if len(sys.argv) > 4 else plan.parent / f"review-{base}..{head}.diff"

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(f"# Diff {base}..{head}\\nFake diff content\\n")
print(f"wrote {out}: 1 commit(s), 200 bytes")
sys.exit(0)
"""
        self.fake_review_package = self.fake_bin_dir / "fake-review-package"
        self._make_executable(self.fake_review_package, review_package_script)

        # Fake sdd-workspace
        sdd_workspace_script = f"""#!/usr/bin/env bash
slug=$(basename "$1" .md)
dir="{self.repo_dir}/.superpowers/sdd/$slug"
mkdir -p "$dir"
echo "$dir"
"""
        self.fake_sdd_workspace = self.fake_bin_dir / "fake-sdd-workspace"
        self._make_executable(self.fake_sdd_workspace, sdd_workspace_script)

    def get_workspace(self, plan_path: Path) -> Path:
        plan_hash = hashlib.sha256(str(plan_path.resolve()).encode("utf-8")).hexdigest()[:12]
        ws_hash = self.repo_dir / ".superpowers" / "sdd" / plan_hash
        if ws_hash.exists():
            return ws_hash
        return self.repo_dir / ".superpowers" / "sdd" / plan_path.stem

    def _default_env(self) -> Dict[str, str]:
        env = dict(os.environ)
        env["DISPATCH_WORKER_BIN"] = str(self.fake_dispatch_worker)
        env["DISPATCH_THINKER_BIN"] = str(self.fake_dispatch_thinker)
        env["JEV_GATE_BIN"] = str(self.fake_jev_gate)
        env["PROGRESS_SYNC_BIN"] = str(self.fake_progress_sync)
        env["TASK_BRIEF_BIN"] = str(self.fake_task_brief)
        env["REVIEW_PACKAGE_BIN"] = str(self.fake_review_package)
        env["SDD_WORKSPACE_BIN"] = str(self.fake_sdd_workspace)
        return env

    def run_sdd_drive(
        self,
        args: List[str],
        env_overrides: Optional[Dict[str, Optional[str]]] = None,
        timeout: float = 30.0,
    ) -> subprocess.CompletedProcess:
        env = self._default_env()
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
            timeout=timeout,
        )
        return proc

    def test_1_four_tasks_all_green_summary_under_15_lines(self) -> None:
        """(1) A plan of 4 tasks with all green reviews runs start to finish, exit 0,
        and prints one final summary of at most 15 lines.
        """
        proc = self.run_sdd_drive(["--plan", str(self.plan_file), "--cwd", str(self.repo_dir)])
        self.assertEqual(proc.returncode, 0, f"sdd-drive failed: {proc.stderr}\nstdout: {proc.stdout}")

        # Summary line count <= 15
        stdout_lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
        self.assertGreater(len(stdout_lines), 0, "stdout should contain summary")
        self.assertLessEqual(len(stdout_lines), 15, f"Summary exceeded 15 lines ({len(stdout_lines)} lines)")

        # Verify all 4 tasks were executed by implementer
        worker_calls = self.worker_log.read_text().splitlines()
        implement_calls = [c for c in worker_calls if "read brief" in c.lower()]
        self.assertEqual(len(implement_calls), 4, f"Expected 4 implementer calls, got {len(implement_calls)}")

        # Verify ledger file shows all 4 complete
        workspace = self.get_workspace(self.plan_file)
        progress_file = workspace / "progress.md"
        self.assertTrue(progress_file.exists(), "progress.md must exist")
        content = progress_file.read_text()
        self.assertIn("complete", content.lower())

    def test_2_ledger_under_2048_bytes_after_every_transition(self) -> None:
        """(2) The ledger stays <= 2048 bytes after every transition and is written atomically."""
        proc = self.run_sdd_drive(["--plan", str(self.plan_file), "--cwd", str(self.repo_dir)])
        self.assertEqual(proc.returncode, 0)

        # Check ledger history logged during progress-sync calls
        if self.ledger_history_log.exists():
            history = self.ledger_history_log.read_text().splitlines()
            self.assertGreater(len(history), 0, "Ledger size should be tracked across transitions")
            for entry in history:
                match = re.search(r':\s*(\d+)\s*bytes', entry)
                if match:
                    size = int(match.group(1))
                    self.assertLessEqual(size, 2048, f"Ledger size {size} exceeded 2048 bytes during transition: {entry}")

        workspace = self.get_workspace(self.plan_file)
        progress_file = workspace / "progress.md"
        self.assertTrue(progress_file.exists())
        final_size = progress_file.stat().st_size
        self.assertLessEqual(final_size, 2048, f"Final ledger size {final_size} exceeds 2048 bytes")

    def test_3_needs_fixes_triggers_one_fix_and_re_review_exits_on_failure(self) -> None:
        """(3) Needs-fixes triggers exactly one fix and one re-review; still failing
        exits with a distinct non-zero code naming the task and the report path,
        and never advances.
        """
        # Reviewer always returns Needs fixes
        proc = self.run_sdd_drive(
            ["--plan", str(self.plan_file), "--cwd", str(self.repo_dir)],
            env_overrides={"FAKE_REVIEW_VERDICT": "Needs fixes"},
        )
        self.assertNotEqual(proc.returncode, 0, "Should fail when review still needs fixes after round 1")

        # Must name the task and report/review path
        output = proc.stdout + proc.stderr
        self.assertIn("Task 1", output, "Must name Task 1")
        self.assertTrue("review" in output.lower() or "report" in output.lower(), "Must mention review/report path")

        # Verify exactly one fix round (total 2 implementer calls for task 1, 2 review calls)
        worker_calls = self.worker_log.read_text().splitlines()
        implement_calls = [c for c in worker_calls if "read brief" in c.lower() or "fix issues" in c.lower()]
        self.assertEqual(len(implement_calls), 2, f"Expected 1 initial + 1 fix implementer call, got {len(implement_calls)}")

        rev_calls = self.review_log.read_text().splitlines()
        self.assertEqual(len(rev_calls), 2, f"Expected 1 initial + 1 re-review call, got {len(rev_calls)}")

        # Task 2 must never have been dispatched
        task2_calls = [c for c in worker_calls if "task 2" in c.lower()]
        self.assertEqual(len(task2_calls), 0, "Task 2 should never be dispatched when Task 1 fails")

    def test_3b_needs_fixes_advances_if_re_review_approved(self) -> None:
        """Needs-fixes triggers fix round, and if re-review is Approved, advances to next task."""
        # Custom review script that fails first time, approves thereafter
        counter_file = self.tmp_path / "rev_count.txt"
        counter_file.write_text("0")
        custom_review_script = f"""#!/usr/bin/env python3
import sys
from pathlib import Path

cf = Path("{counter_file}")
count = int(cf.read_text().strip())
count += 1
cf.write_text(str(count))

verdict = "Needs fixes" if count == 1 else "Approved"
content = f"# Review\\n\\n### Assessment\\n**Task quality:** {{verdict}}\\n- **Quality:** {{verdict}}\\nVerdict: {{verdict}}\\n"

for i, arg in enumerate(sys.argv):
    if arg == "--output-file" and i + 1 < len(sys.argv):
        Path(sys.argv[i + 1]).write_text(content)
print(content)
sys.exit(0)
"""
        custom_rev_bin = self.fake_bin_dir / "custom-review-worker"
        self._make_executable(custom_rev_bin, custom_review_script)

        # Plan with 2 tasks
        short_plan = self.repo_dir / "short_plan.md"
        short_plan.write_text("""# Short Plan
## Task 1: First
Verify-Cmd: test
Do 1.

## Task 2: Second
Verify-Cmd: test
Do 2.
""")
        proc = self.run_sdd_drive(
            ["--plan", str(short_plan), "--cwd", str(self.repo_dir)],
            env_overrides={
                "DISPATCH_THINKER_BIN": str(custom_rev_bin),
                "DISPATCH_WORKER_BIN": str(self.fake_dispatch_worker),
                "FAKE_JEV_TIER": "argon_or_opus_deep_review",
            },
        )
        self.assertEqual(proc.returncode, 0, f"Should succeed after fix round approved: {proc.stderr}\nstdout: {proc.stdout}")

        # Both task 1 and task 2 should be executed
        worker_calls = self.worker_log.read_text().splitlines()
        task2_calls = [c for c in worker_calls if "task 2" in c.lower()]
        self.assertGreater(len(task2_calls), 0, "Task 2 should have run after Task 1 succeeded")

    def test_4_unparsable_or_missing_verdict_stops_and_never_advances(self) -> None:
        """(4) The script advances ONLY on an explicit approved verdict: an empty,
        missing, unparsable or unknown review verdict stops and wakes, never advances.
        """
        for bad_verdict in ["EMPTY", "UNPARSABLE", "Unknown"]:
            self.setUp()  # Fresh state
            proc = self.run_sdd_drive(
                ["--plan", str(self.plan_file), "--cwd", str(self.repo_dir)],
                env_overrides={"FAKE_REVIEW_VERDICT": bad_verdict},
            )
            self.assertNotEqual(proc.returncode, 0, f"Expected non-zero exit for verdict {bad_verdict}")
            # Ensure Task 2 never ran
            if self.worker_log.exists():
                calls = self.worker_log.read_text().splitlines()
                task2_calls = [c for c in calls if "task 2" in c.lower()]
                self.assertEqual(len(task2_calls), 0, f"Task 2 should not run on bad verdict {bad_verdict}")

    def test_5_worker_failure_modes_stop_with_reasons(self) -> None:
        """(5) A worker result advances only when status is success, files modified > 0
        and verified is true; BLOCKED, NEEDS_CONTEXT, verify failure, a timeout, and
        fallback exit 10 each stop with their own reason.
        """
        cases = [
            ("BLOCKED", {"FAKE_WORKER_STATUS": "BLOCKED", "FAKE_WORKER_EXIT": "1"}, "blocked"),
            ("NEEDS_CONTEXT", {"FAKE_WORKER_STATUS": "NEEDS_CONTEXT", "FAKE_WORKER_EXIT": "1"}, "context"),
            ("VERIFY_FAILURE", {"FAKE_WORKER_VERIFIED": "false", "FAKE_WORKER_EXIT": "13"}, "verif"),
            ("TIMEOUT", {"FAKE_WORKER_STATUS": "TIMEOUT", "FAKE_WORKER_EXIT": "124"}, "time"),
            ("FALLBACK_10", {"FAKE_WORKER_STATUS": "FALLBACK_INTERNAL", "FAKE_WORKER_EXIT": "10"}, "quota"),
            ("ZERO_FILES", {"FAKE_WORKER_STATUS": "SUCCESS", "FAKE_WORKER_FILES_CHANGED": "0"}, "0 files"),
        ]

        for name, overrides, expected_reason_needle in cases:
            self.setUp()
            proc = self.run_sdd_drive(
                ["--plan", str(self.plan_file), "--cwd", str(self.repo_dir)],
                env_overrides=overrides,
            )
            self.assertNotEqual(proc.returncode, 0, f"Case {name} should exit non-zero")
            combined_output = (proc.stdout + proc.stderr).lower()
            self.assertIn(
                expected_reason_needle.lower(),
                combined_output,
                f"Case {name} output should explain reason (needle '{expected_reason_needle}'): {combined_output}",
            )

    def test_6_resume_from_ledger_skips_finished_tasks(self) -> None:
        """(6) Re-running after a stop resumes from the ledger and skips finished tasks."""
        # First run: fail on Task 2
        fail_on_task2_script = f"""#!/usr/bin/env python3
import sys
import os
from pathlib import Path
import subprocess

args = sys.argv[1:]
is_review = "review task" in " ".join(args).lower() or any("review" in a for a in args)

if is_review:
    for i, a in enumerate(args):
        if a == "--output-file" and i + 1 < len(args):
            Path(args[i + 1]).write_text("# Review\\nVerdict: Approved\\n- **Quality:** Approved\\n")
    print("# Review\\nVerdict: Approved\\n- **Quality:** Approved\\n")
    sys.exit(0)

# Implementer
if "Task 2" in " ".join(args):
    print("Status: BLOCKED (exit 1)\\nFiles Modified: 0\\nVerified: false")
    sys.exit(1)

# Task 1 succeeds
subprocess.run(["git", "commit", "--allow-empty", "-m", "task 1"], check=False, capture_output=True)
report = "=== AGY SUBAGENT REPORT ===\\nStatus: SUCCESS (exit 0)\\nFiles Modified: 1\\nVerified: true\\n"
for i, a in enumerate(args):
    if a == "--output-file" and i + 1 < len(args):
        Path(args[i + 1]).write_text(report)
print(report)
sys.exit(0)
"""
        step_worker = self.fake_bin_dir / "step-worker"
        self._make_executable(step_worker, fail_on_task2_script)

        # Run 1: Task 1 passes, Task 2 fails
        proc1 = self.run_sdd_drive(
            ["--plan", str(self.plan_file), "--cwd", str(self.repo_dir)],
            env_overrides={"DISPATCH_WORKER_BIN": str(step_worker), "DISPATCH_THINKER_BIN": str(step_worker)},
        )
        self.assertNotEqual(proc1.returncode, 0, "First run should stop on Task 2 failure")

        # Check that Task 1 is marked complete in ledger
        workspace = self.get_workspace(self.plan_file)
        progress_file = workspace / "progress.md"
        self.assertTrue(progress_file.exists())
        self.assertIn("Task 1", progress_file.read_text())

        # Clear worker log before run 2
        if self.worker_log.exists():
            self.worker_log.unlink()

        # Run 2: Normal all-green worker
        proc2 = self.run_sdd_drive(["--plan", str(self.plan_file), "--cwd", str(self.repo_dir)])
        self.assertEqual(proc2.returncode, 0, f"Second run should succeed: {proc2.stderr}\nstdout: {proc2.stdout}")

        # Worker calls in run 2 should NOT include Task 1
        worker_calls = self.worker_log.read_text().splitlines()
        task1_calls = [c for c in worker_calls if "task 1" in c.lower() and "read brief" in c.lower()]
        self.assertEqual(len(task1_calls), 0, "Task 1 should be skipped on resume")

        # But Task 2, 3, 4 should run
        task2_calls = [c for c in worker_calls if "task 2" in c.lower() and "read brief" in c.lower()]
        self.assertEqual(len(task2_calls), 1, "Task 2 should run on resume")

    def test_7_hard_time_limit_stops_with_reason_never_hangs(self) -> None:
        """(7) Each task has a hard time limit, and hitting it stops with a reason, never hangs."""
        proc = self.run_sdd_drive(
            ["--plan", str(self.plan_file), "--cwd", str(self.repo_dir), "--timeout", "0.5"],
            env_overrides={"FAKE_WORKER_SLEEP": "2.0"},
            timeout=10,
        )
        self.assertNotEqual(proc.returncode, 0, "Timeout should exit non-zero")
        combined = (proc.stdout + proc.stderr).lower()
        self.assertTrue("time" in combined or "timeout" in combined, f"Should report timeout: {combined}")

    def test_8_sdd_drive_off_exits_nonzero(self) -> None:
        """(8) SDD_DRIVE=off exits non-zero with a clear message, doing nothing."""
        proc = self.run_sdd_drive(
            ["--plan", str(self.plan_file), "--cwd", str(self.repo_dir)],
            env_overrides={"SDD_DRIVE": "off"},
        )
        self.assertNotEqual(proc.returncode, 0, "SDD_DRIVE=off must exit non-zero")
        combined = proc.stdout + proc.stderr
        self.assertTrue("off" in combined.lower() or "disabled" in combined.lower(), f"Expected off/disabled message: {combined}")
        # Ensure no worker was called
        self.assertFalse(self.worker_log.exists(), "Worker must not be invoked when SDD_DRIVE=off")

    def test_9_progress_sync_failure_never_stops_run(self) -> None:
        """(9) progress-sync failure never stops the run."""
        proc = self.run_sdd_drive(
            ["--plan", str(self.plan_file), "--cwd", str(self.repo_dir)],
            env_overrides={"FAKE_PROGRESS_SYNC_FAIL": "1"},
        )
        self.assertEqual(proc.returncode, 0, f"Run should succeed even if progress-sync fails: {proc.stderr}\nstdout: {proc.stdout}")
        worker_calls = self.worker_log.read_text().splitlines()
        implement_calls = [c for c in worker_calls if "read brief" in c.lower()]
        self.assertEqual(len(implement_calls), 4, "All 4 tasks should complete despite progress-sync failure")


    def test_finding_1_verdict_parsing_anchored_and_conflicts(self) -> None:
        """Finding 1 / Criterion (1): Verdict counts only from dedicated final line;
        quoted text never counts; conflicting verdict lines stop and wake.
        """
        loader = importlib.machinery.SourceFileLoader("sdd_drive", str(SCRIPT))
        spec = importlib.util.spec_from_loader("sdd_drive", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)

        # 1. Quoted text does not count
        quoted = "> Verdict: Approved\nSome discussion\nVerdict: Needs fixes"
        self.assertEqual(mod.parse_review_verdict(quoted), "Needs fixes")

        # 2. Misleading phrasing does not count
        misleading = "Quality: Needs fixes (was Approved)\nVerdict: Needs fixes"
        self.assertEqual(mod.parse_review_verdict(misleading), "Needs fixes")

        misleading_alone = "Quality: Needs fixes (was Approved)"
        self.assertIsNone(mod.parse_review_verdict(misleading_alone))

        # 3. Conflicting verdicts return None
        conflicting = "Verdict: Approved\nVerdict: Needs fixes"
        self.assertIsNone(mod.parse_review_verdict(conflicting))

        # 4. Valid dedicated final line
        valid_approved = "Some notes\nVerdict: Approved"
        self.assertEqual(mod.parse_review_verdict(valid_approved), "Approved")
        valid_needs_fixes = "Some notes\nVerdict: Needs fixes"
        self.assertEqual(mod.parse_review_verdict(valid_needs_fixes), "Needs fixes")

        # 5. End-to-end: conflicting verdicts in review stop and wake with exit 6
        proc = self.run_sdd_drive(
            ["--plan", str(self.plan_file), "--cwd", str(self.repo_dir)],
            env_overrides={"FAKE_REVIEW_CONTENT": "Verdict: Approved\nVerdict: Needs fixes\n"},
        )
        self.assertEqual(proc.returncode, 6)

    def test_finding_2_reviewer_crash_and_stale_review_file_deleted(self) -> None:
        """Finding 2 / Criterion (2): Review file is deleted before review;
        reviewer non-zero exit stops and wakes immediately (never reads stale Approved file).
        """
        loader = importlib.machinery.SourceFileLoader("sdd_drive", str(SCRIPT))
        spec = importlib.util.spec_from_loader("sdd_drive", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)

        ws = mod.resolve_workspace(self.plan_file, self.repo_dir)
        stale_review_file = ws / "task-1-review.md"
        stale_review_file.parent.mkdir(parents=True, exist_ok=True)
        stale_review_file.write_text("Verdict: Approved\n")

        crash_review_script = """#!/usr/bin/env python3
import sys
sys.stderr.write("Reviewer crashed with OOM\\n")
sys.exit(1)
"""
        crash_reviewer = self.fake_bin_dir / "crash-reviewer"
        self._make_executable(crash_reviewer, crash_review_script)

        proc = self.run_sdd_drive(
            ["--plan", str(self.plan_file), "--cwd", str(self.repo_dir)],
            env_overrides={
                "DISPATCH_WORKER_BIN": str(self.fake_dispatch_worker),
                "DISPATCH_THINKER_BIN": str(crash_reviewer),
                "FAKE_JEV_TIER": "argon_or_opus_deep_review",
            },
        )
        self.assertNotEqual(proc.returncode, 0, "Reviewer crash must stop and wake")
        self.assertFalse(stale_review_file.exists(), "Stale review file should have been deleted prior to review")

    def test_finding_3_workspace_keyed_by_full_plan_path_hash(self) -> None:
        """Finding 3 / Criterion (3): Workspace and ledger are keyed by hash of
        full plan path, not file stem, so two features with plan.md never share a ledger.
        """
        feat_a_dir = self.repo_dir / "features" / "feat_a"
        feat_b_dir = self.repo_dir / "features" / "feat_b"
        feat_a_dir.mkdir(parents=True, exist_ok=True)
        feat_b_dir.mkdir(parents=True, exist_ok=True)

        plan_a = feat_a_dir / "plan.md"
        plan_b = feat_b_dir / "plan.md"
        plan_a.write_text("# Feature A\n## Task 1: A1\nVerify-Cmd: test\nImplement A1\n")
        plan_b.write_text("# Feature B\n## Task 1: B1\nVerify-Cmd: test\nImplement B1\n")

        loader = importlib.machinery.SourceFileLoader("sdd_drive", str(SCRIPT))
        spec = importlib.util.spec_from_loader("sdd_drive", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)

        ws_a = mod.resolve_workspace(plan_a, self.repo_dir)
        ws_b = mod.resolve_workspace(plan_b, self.repo_dir)

        self.assertNotEqual(ws_a, ws_b, "Workspaces for different plan paths must not collide")
        self.assertNotIn("plan", ws_a.name, "Workspace directory name should be a hash, not plan.stem")
        self.assertNotIn("plan", ws_b.name, "Workspace directory name should be a hash, not plan.stem")

    def test_finding_7_only_explicit_verify_cmd_prose_ignored_and_missing_stops(self) -> None:
        """Finding 7 / Criterion (4): Only explicit 'Verify-Cmd:' line at line start is used;
        'Verify:' prose is ignored; task with no Verify-Cmd stops with a reason and is not dispatched.
        """
        prose_plan = self.repo_dir / "prose_plan.md"
        prose_plan.write_text("""# Prose Plan
## Task 1: No Verify Cmd
Verify: please check logs and make sure all looks right
Implement something.
""")
        proc = self.run_sdd_drive(["--plan", str(prose_plan), "--cwd", str(self.repo_dir)])
        self.assertNotEqual(proc.returncode, 0, "Task without explicit Verify-Cmd must stop and wake")
        combined = (proc.stdout + proc.stderr).lower()
        self.assertTrue("verify" in combined, f"Output should explain missing verify cmd: {combined}")

        if self.worker_log.exists():
            calls = self.worker_log.read_text().splitlines()
            self.assertEqual(len(calls), 0, "Worker must not be dispatched when Verify-Cmd is missing")

    def test_finding_8_worker_status_dedicated_line_and_omitted_verified_fails(self) -> None:
        """Finding 8 / Criterion (5): Worker status comes from dedicated final status line;
        omitted verification counts as NOT verified.
        """
        loader = importlib.machinery.SourceFileLoader("sdd_drive", str(SCRIPT))
        spec = importlib.util.spec_from_loader("sdd_drive", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)

        # 1. Output with quoted or earlier Status: FAILED but dedicated final Status: SUCCESS
        stdout_with_quoted = """Some log
> Status: BLOCKED
Some other discussion with Status: TIMEOUT
Status: SUCCESS
Files Modified: 2
Verified: true
"""
        st, fm, vf = mod.parse_worker_output(stdout_with_quoted, None, 0)
        self.assertEqual(st, "SUCCESS")
        self.assertEqual(fm, 2)
        self.assertTrue(vf)

        # 2. Worker exits 0 but omits "Verified:" line -> must count as NOT verified
        stdout_omitted_verify = """Status: SUCCESS
Files Modified: 1
Work completed without running test.
"""
        st2, fm2, vf2 = mod.parse_worker_output(stdout_omitted_verify, None, 0)
        self.assertEqual(st2, "SUCCESS")
        self.assertFalse(vf2, "Omitted verification must count as NOT verified even on exit 0")

        # 3. End-to-end: running with omitted Verified stops and wakes
        proc = self.run_sdd_drive(
            ["--plan", str(self.plan_file), "--cwd", str(self.repo_dir)],
            env_overrides={"FAKE_WORKER_VERIFIED": "OMIT"},
        )
        self.assertNotEqual(proc.returncode, 0, "Omitted verification must cause sdd-drive to stop")

    def test_finding_9_ledger_locking_timeout_stops_with_reason(self) -> None:
        """Finding 9 / Criterion (6): Ledger locking has a timeout and stops with a reason."""
        loader = importlib.machinery.SourceFileLoader("sdd_drive", str(SCRIPT))
        spec = importlib.util.spec_from_loader("sdd_drive", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)

        ws = mod.resolve_workspace(self.plan_file, self.repo_dir)
        progress_file = ws / "progress.md"
        lockpath = mod._lock_path(progress_file)
        lockpath.parent.mkdir(parents=True, exist_ok=True)

        import fcntl
        with open(lockpath, "a+") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            proc = self.run_sdd_drive(
                ["--plan", str(self.plan_file), "--cwd", str(self.repo_dir)],
                env_overrides={"SDD_LOCK_TIMEOUT": "0.5"},
                timeout=5.0,
            )
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

        self.assertNotEqual(proc.returncode, 0, "Should exit non-zero when lock cannot be acquired")
        combined = (proc.stdout + proc.stderr).lower()
        self.assertTrue("lock" in combined or "timeout" in combined, f"Expected lock timeout message: {combined}")


if __name__ == "__main__":
    unittest.main()
