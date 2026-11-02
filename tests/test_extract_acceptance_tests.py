#!/usr/bin/env python3
"""Unit tests for bin/extract-acceptance-tests.

Covers:
(1) Extracts fenced blocks tagged '<lang> test:<relative/path>' and a 'Verify-Cmd:'
    line from the task, and writes the test files into WORKTREE.
(2) Refuses paths that are absolute or escape WORKTREE.
(3) Runs Verify-Cmd once and requires a valid RED: non-zero exit is accepted,
    zero exit is refused, and a Python SyntaxError in the test file is refused
    while ImportError or ModuleNotFoundError counts as RED.
(4) Records each pre-registered test's name and its assertion count in
    task-N-tests.sha256.
(5) --check-intact exits non-zero when a registered test is deleted, gets a
    skip marker (@skip, pytest.mark.skip, .skip, xit), or loses an assertion.
(6) --check-intact exits 0 when only imports or fixtures changed, and when new
    tests were added.
(7) A task with no test block exits 0 with a clear 'no acceptance tests' message
    and registers nothing.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "extract-acceptance-tests"


class TestExtractAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name).resolve()
        self.worktree = self.tmp_path / "worktree"
        self.worktree.mkdir(parents=True, exist_ok=True)
        self.sdd_dir = self.tmp_path / "sdd"
        self.sdd_dir.mkdir(parents=True, exist_ok=True)

    def run_cmd(
        self,
        args: list[str],
        cwd: Path | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [str(SCRIPT)] + args,
            cwd=str(cwd or self.worktree),
            capture_output=True,
            text=True,
            env=env,
        )

    # -------------------------------------------------------------------------
    # Criterion 1 & 4: Extract fenced test blocks, Verify-Cmd, write into WORKTREE,
    # record test names and assertion counts in task-N-tests.sha256.
    # -------------------------------------------------------------------------
    def test_extract_happy_path_python(self) -> None:
        plan_content = """# Implementation Plan

## Task 1: Add widget calculator

### Step 1: Write the failing test
Verify-Cmd: python3 -m unittest tests/test_calc.py

```python test:tests/test_calc.py
import unittest
from calc import add

class TestCalc(unittest.TestCase):
    def test_add_positive(self):
        self.assertEqual(add(1, 2), 3)

    def test_add_negative(self):
        result = add(-1, -2)
        assert result == -3
```

### Step 2: Implement
...
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertEqual(res.returncode, 0, f"STDOUT: {res.stdout}\nSTDERR: {res.stderr}")

        # Check that test file was written into WORKTREE
        target_test_file = self.worktree / "tests" / "test_calc.py"
        self.assertTrue(target_test_file.exists(), "Target test file was not created in worktree")
        self.assertIn("class TestCalc", target_test_file.read_text(encoding="utf-8"))

        # Check that task-1-tests.sha256 exists in sdd-dir
        hashfile = self.sdd_dir / "task-1-tests.sha256"
        self.assertTrue(hashfile.exists(), "task-1-tests.sha256 was not created")

        data = json.loads(hashfile.read_text(encoding="utf-8"))
        self.assertIn("files", data)
        self.assertIn("tests/test_calc.py", data["files"])
        file_entry = data["files"]["tests/test_calc.py"]
        self.assertIn("sha256", file_entry)

        tests_meta = file_entry["tests"]
        # Both methods should be recorded with assertion counts
        self.assertIn("TestCalc.test_add_positive", tests_meta)
        self.assertEqual(tests_meta["TestCalc.test_add_positive"]["assertions"], 1)

        self.assertIn("TestCalc.test_add_negative", tests_meta)
        self.assertEqual(tests_meta["TestCalc.test_add_negative"]["assertions"], 1)

    def test_extract_default_sdd_dir(self) -> None:
        """When --sdd-dir is omitted, it defaults to <worktree>/.superpowers/sdd/<plan-slug>."""
        plan_content = """## Task 2: Core feature
Verify-Cmd: python3 -c "import sys, tests.test_foo; sys.exit(1)"

```python test:tests/test_foo.py
import unittest

class TestFoo(unittest.TestCase):
    def test_foo(self):
        self.assertTrue(True)
```
"""
        plan_file = self.tmp_path / "my-plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd([str(plan_file), "2", str(self.worktree)])
        self.assertEqual(res.returncode, 0, f"STDOUT: {res.stdout}\nSTDERR: {res.stderr}")

        expected_hashfile = (
            self.worktree / ".superpowers" / "sdd" / "my-plan" / "task-2-tests.sha256"
        )
        self.assertTrue(expected_hashfile.exists(), f"Missing default hashfile: {expected_hashfile}")

    # -------------------------------------------------------------------------
    # Criterion 2: Refuse paths that are absolute or escape WORKTREE.
    # -------------------------------------------------------------------------
    def test_extract_refuses_absolute_path(self) -> None:
        plan_content = """## Task 1: Dangerous task
Verify-Cmd: python3 -m unittest /tmp/pwned.py

```python test:/tmp/pwned.py
import unittest
class TestPwn(unittest.TestCase):
    def test_pwn(self):
        self.assertTrue(True)
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertNotEqual(res.returncode, 0, "Absolute path should have been refused")
        self.assertIn("absolute", res.stderr.lower())
        self.assertFalse(Path("/tmp/pwned.py").exists())

    def test_extract_refuses_escaping_path(self) -> None:
        plan_content = """## Task 1: Traversal task
Verify-Cmd: python3 -m unittest ../escape.py

```python test:../escape.py
import unittest
class TestEscape(unittest.TestCase):
    def test_escape(self):
        self.assertTrue(True)
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertNotEqual(res.returncode, 0, "Escaping path should have been refused")
        escaped_file = self.tmp_path / "escape.py"
        self.assertFalse(escaped_file.exists())

    # -------------------------------------------------------------------------
    # Criterion 3: Runs Verify-Cmd once and requires a valid RED:
    # non-zero exit is accepted, zero exit is refused, and a Python SyntaxError
    # in the test file is refused while ImportError/ModuleNotFoundError counts as RED.
    # -------------------------------------------------------------------------
    def test_extract_refuses_zero_exit(self) -> None:
        """When Verify-Cmd exits 0, extract must refuse because it's not RED."""
        plan_content = """## Task 1: Already passing task
Verify-Cmd: true

```python test:tests/test_pass.py
def test_something():
    assert True
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertNotEqual(res.returncode, 0, "Expected non-zero exit when Verify-Cmd succeeds (0)")
        self.assertTrue(
            "red" in res.stderr.lower() or "0" in res.stderr,
            f"Expected error message indicating zero exit / RED required: {res.stderr}",
        )

    def test_extract_refuses_python_syntax_error_in_test_file(self) -> None:
        """SyntaxError in test file must be refused, not accepted as valid RED."""
        plan_content = """## Task 1: Syntax broken test
Verify-Cmd: python3 -m unittest tests/test_broken.py

```python test:tests/test_broken.py
import unittest
class TestBroken(unittest.TestCase):
    def test_broken(
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertNotEqual(res.returncode, 0, "SyntaxError must be refused")
        self.assertIn("syntaxerror", res.stderr.lower())

    def test_extract_accepts_import_error_as_valid_red(self) -> None:
        """ImportError / ModuleNotFoundError is valid RED and must be accepted."""
        plan_content = """## Task 1: Missing module test
Verify-Cmd: python3 -m unittest tests/test_missing.py

```python test:tests/test_missing.py
import unittest
from nonexistent_package_xyz import awesome_function

class TestMissing(unittest.TestCase):
    def test_missing(self):
        self.assertEqual(awesome_function(), 42)
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertEqual(
            res.returncode, 0,
            f"ImportError should be accepted as valid RED.\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}",
        )
        hashfile = self.sdd_dir / "task-1-tests.sha256"
        self.assertTrue(hashfile.exists())

    # -------------------------------------------------------------------------
    # Criterion 5 & 6: --check-intact
    # (5) Exits non-zero when registered test is deleted, skipped (@skip,
    # pytest.mark.skip, .skip, xit), or loses an assertion.
    # (6) Exits 0 when only imports/fixtures changed, or new tests were added.
    # -------------------------------------------------------------------------
    def _setup_extracted_test(self) -> tuple[Path, Path]:
        plan_content = """## Task 1: Math tests
Verify-Cmd: python3 -c "import tests.test_math; raise SystemExit(1)"

```python test:tests/test_math.py
import unittest
from mymath import square

class TestMath(unittest.TestCase):
    def test_square_positive(self):
        self.assertEqual(square(2), 4)
        self.assertTrue(square(2) > 0)

    def test_square_zero(self):
        self.assertEqual(square(0), 0)
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertEqual(res.returncode, 0, f"Setup extraction failed: {res.stderr}")
        hashfile = self.sdd_dir / "task-1-tests.sha256"
        test_file = self.worktree / "tests" / "test_math.py"
        return hashfile, test_file

    def test_check_intact_clean_passes(self) -> None:
        hashfile, _ = self._setup_extracted_test()
        res = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertEqual(res.returncode, 0, f"STDOUT: {res.stdout}\nSTDERR: {res.stderr}")

    def test_check_intact_passes_with_skip_in_docstring_or_variable(self) -> None:
        """Word 'skip' in docstrings or variables should not be flagged as a skip marker."""
        hashfile, test_file = self._setup_extracted_test()
        updated_content = """import unittest
from mymath import square

class TestMath(unittest.TestCase):
    def test_square_positive(self):
        \"\"\"We do not skip this test, testing positive square.\"\"\"
        skip_flag = False
        if not skip_flag:
            self.assertEqual(square(2), 4)
            self.assertTrue(square(2) > 0)

    def test_square_zero(self):
        self.assertEqual(square(0), 0)
"""
        test_file.write_text(updated_content, encoding="utf-8")

        res = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertEqual(
            res.returncode, 0,
            f"Docstring/variable with 'skip' should pass intact check: {res.stderr}",
        )

    def test_check_intact_passes_with_changed_imports_fixtures_and_new_tests(self) -> None:
        hashfile, test_file = self._setup_extracted_test()
        # Update test file: changed imports, added setUp fixture, added new test
        updated_content = """import unittest
import math
from mymath.advanced import square

class TestMath(unittest.TestCase):
    def setUp(self):
        self.multiplier = 1

    def test_square_positive(self):
        self.assertEqual(square(2), 4)
        self.assertTrue(square(2) > 0)

    def test_square_zero(self):
        self.assertEqual(square(0), 0)

    def test_new_square_negative(self):
        self.assertEqual(square(-3), 9)
"""
        test_file.write_text(updated_content, encoding="utf-8")

        res = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertEqual(
            res.returncode, 0,
            f"Expected exit 0 for imports/fixtures/new tests.\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}",
        )

    def test_check_intact_fails_when_test_deleted(self) -> None:
        hashfile, test_file = self._setup_extracted_test()
        # Delete test_square_zero
        updated_content = """import unittest
from mymath import square

class TestMath(unittest.TestCase):
    def test_square_positive(self):
        self.assertEqual(square(2), 4)
        self.assertTrue(square(2) > 0)
"""
        test_file.write_text(updated_content, encoding="utf-8")

        res = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertNotEqual(res.returncode, 0, "Should fail when registered test is deleted")
        self.assertTrue(
            "deleted" in res.stderr.lower() or "missing" in res.stderr.lower() or "test_square_zero" in res.stderr,
            f"Expected deletion message: {res.stderr}",
        )

    def test_check_intact_fails_on_unittest_skip_decorator(self) -> None:
        hashfile, test_file = self._setup_extracted_test()
        updated_content = """import unittest
from mymath import square

class TestMath(unittest.TestCase):
    @unittest.skip("temporarily disabled")
    def test_square_positive(self):
        self.assertEqual(square(2), 4)
        self.assertTrue(square(2) > 0)

    def test_square_zero(self):
        self.assertEqual(square(0), 0)
"""
        test_file.write_text(updated_content, encoding="utf-8")

        res = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertNotEqual(res.returncode, 0, "Should fail on @unittest.skip decorator")
        self.assertIn("skip", res.stderr.lower())

    def test_check_intact_fails_on_pytest_mark_skip(self) -> None:
        hashfile, test_file = self._setup_extracted_test()
        updated_content = """import unittest
import pytest
from mymath import square

class TestMath(unittest.TestCase):
    @pytest.mark.skip(reason="skipping")
    def test_square_positive(self):
        self.assertEqual(square(2), 4)
        self.assertTrue(square(2) > 0)

    def test_square_zero(self):
        self.assertEqual(square(0), 0)
"""
        test_file.write_text(updated_content, encoding="utf-8")

        res = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertNotEqual(res.returncode, 0, "Should fail on @pytest.mark.skip")
        self.assertIn("skip", res.stderr.lower())

    def test_check_intact_fails_on_class_level_skip(self) -> None:
        hashfile, test_file = self._setup_extracted_test()
        updated_content = """import unittest
from mymath import square

@unittest.skip("all broken")
class TestMath(unittest.TestCase):
    def test_square_positive(self):
        self.assertEqual(square(2), 4)
        self.assertTrue(square(2) > 0)

    def test_square_zero(self):
        self.assertEqual(square(0), 0)
"""
        test_file.write_text(updated_content, encoding="utf-8")

        res = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertNotEqual(res.returncode, 0, "Should fail on class-level skip")
        self.assertIn("skip", res.stderr.lower())

    def test_check_intact_fails_on_body_skip_call(self) -> None:
        hashfile, test_file = self._setup_extracted_test()
        updated_content = """import unittest
from mymath import square

class TestMath(unittest.TestCase):
    def test_square_positive(self):
        raise unittest.SkipTest("skip from body")
        self.assertEqual(square(2), 4)
        self.assertTrue(square(2) > 0)

    def test_square_zero(self):
        self.assertEqual(square(0), 0)
"""
        test_file.write_text(updated_content, encoding="utf-8")

        res = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertNotEqual(res.returncode, 0, "Should fail when test raises SkipTest")
        self.assertIn("skip", res.stderr.lower())

    def test_check_intact_fails_when_test_loses_assertion(self) -> None:
        hashfile, test_file = self._setup_extracted_test()
        # Originally test_square_positive had 2 assertions. Reduce to 1.
        updated_content = """import unittest
from mymath import square

class TestMath(unittest.TestCase):
    def test_square_positive(self):
        self.assertEqual(square(2), 4)
        # self.assertTrue(...) removed!

    def test_square_zero(self):
        self.assertEqual(square(0), 0)
"""
        test_file.write_text(updated_content, encoding="utf-8")

        res = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertNotEqual(res.returncode, 0, "Should fail when test loses an assertion")
        self.assertTrue(
            "assertion" in res.stderr.lower() or "lost" in res.stderr.lower(),
            f"Expected message about lost assertion: {res.stderr}",
        )

    def test_check_intact_passes_when_test_gains_assertion(self) -> None:
        hashfile, test_file = self._setup_extracted_test()
        # Add an additional assertion to test_square_positive (now 3 instead of 2)
        updated_content = """import unittest
from mymath import square

class TestMath(unittest.TestCase):
    def test_square_positive(self):
        self.assertEqual(square(2), 4)
        self.assertTrue(square(2) > 0)
        self.assertIsInstance(square(2), int)

    def test_square_zero(self):
        self.assertEqual(square(0), 0)
"""
        test_file.write_text(updated_content, encoding="utf-8")

        res = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertEqual(res.returncode, 0, f"Expected 0 when gaining assertions: {res.stderr}")

    def test_check_intact_js_ts_and_xit_skip(self) -> None:
        """JS/TS test blocks: verify intact checking and detection of xit/.skip markers."""
        plan_content = """## Task 1: JS API test
Verify-Cmd: node -e "process.exit(1)"

```javascript test:tests/api.test.js
describe('API', () => {
    it('fetches user', () => {
        expect(1).toBe(1);
        expect(2).toBe(2);
    });
});
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertEqual(res.returncode, 0, f"Extract JS failed: {res.stderr}")

        hashfile = self.sdd_dir / "task-1-tests.sha256"
        js_file = self.worktree / "tests" / "api.test.js"
        self.assertTrue(hashfile.exists())
        self.assertTrue(js_file.exists())

        # Clean check passes
        res_clean = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertEqual(res_clean.returncode, 0, f"JS check intact clean failed: {res_clean.stderr}")

        # Changing it('fetches user' -> xit('fetches user' should fail with skip marker
        js_file.write_text(
            """describe('API', () => {
    xit('fetches user', () => {
        expect(1).toBe(1);
        expect(2).toBe(2);
    });
});
""",
            encoding="utf-8",
        )
        res_xit = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertNotEqual(res_xit.returncode, 0, "xit should be detected as skip")
        self.assertIn("skip", res_xit.stderr.lower())

        # it.skip should also fail
        js_file.write_text(
            """describe('API', () => {
    it.skip('fetches user', () => {
        expect(1).toBe(1);
        expect(2).toBe(2);
    });
});
""",
            encoding="utf-8",
        )
        res_skip = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertNotEqual(res_skip.returncode, 0, "it.skip should be detected as skip")

        # Losing assertion in JS test should fail
        js_file.write_text(
            """describe('API', () => {
    it('fetches user', () => {
        expect(1).toBe(1);
    });
});
""",
            encoding="utf-8",
        )
        res_lost = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertNotEqual(res_lost.returncode, 0, "Lost assertion in JS should fail")

    # -------------------------------------------------------------------------
    # Criterion 7: Task with no test block exits 0 with a clear message and
    # registers nothing.
    # -------------------------------------------------------------------------
    def test_extract_no_test_blocks_exits_zero(self) -> None:
        plan_content = """# Plan

## Task 1: Documentation update
Just update the README file with installation instructions.

## Task 2: Code change
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertEqual(res.returncode, 0, f"Expected 0 on task without tests: {res.stderr}")
        self.assertTrue(
            "no acceptance tests" in res.stdout.lower() or "no acceptance tests" in res.stderr.lower(),
            f"Expected 'no acceptance tests' message: stdout={res.stdout}, stderr={res.stderr}",
        )
        # Registers nothing: hashfile should NOT exist
        hashfile = self.sdd_dir / "task-1-tests.sha256"
        self.assertFalse(hashfile.exists(), "No hashfile should be created when no tests exist")

    # -------------------------------------------------------------------------
    # Edge cases: Task not found, missing Verify-Cmd, multiple test blocks
    # -------------------------------------------------------------------------
    def test_extract_task_not_found(self) -> None:
        plan_content = """## Task 1: Only task
Verify-Cmd: false
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "99", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertNotEqual(res.returncode, 0, "Task not found should exit non-zero")
        self.assertIn("not found", res.stderr.lower())

    def test_extract_missing_verify_cmd_when_tests_exist(self) -> None:
        plan_content = """## Task 1: Missing verify cmd

```python test:tests/test_x.py
def test_x():
    assert True
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertNotEqual(res.returncode, 0, "Missing Verify-Cmd should exit non-zero")
        self.assertIn("verify-cmd", res.stderr.lower())

    def test_extract_multiple_test_blocks(self) -> None:
        plan_content = """## Task 1: Multi-file tests
Verify-Cmd: python3 -c "import tests.test_a, tests.test_b; raise SystemExit(1)"

```python test:tests/test_a.py
import unittest
class TestA(unittest.TestCase):
    def test_a(self):
        self.assertEqual(1, 1)
```

```python test:tests/test_b.py
import unittest
class TestB(unittest.TestCase):
    def test_b(self):
        self.assertTrue(True)
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertEqual(res.returncode, 0, f"Multi-file extract failed: {res.stderr}")

        file_a = self.worktree / "tests" / "test_a.py"
        file_b = self.worktree / "tests" / "test_b.py"
        self.assertTrue(file_a.exists())
        self.assertTrue(file_b.exists())

        hashfile = self.sdd_dir / "task-1-tests.sha256"
        data = json.loads(hashfile.read_text(encoding="utf-8"))
        self.assertIn("tests/test_a.py", data["files"])
        self.assertIn("tests/test_b.py", data["files"])

        # Check intact passes
        res_intact = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertEqual(res_intact.returncode, 0, f"Check intact failed: {res_intact.stderr}")

    # -------------------------------------------------------------------------
    # Defect 4: Verify-Cmd Timeout
    # -------------------------------------------------------------------------
    def test_verify_cmd_timeout(self) -> None:
        """Verify-Cmd times out with clear error message when exceeding limit."""
        plan_content = """## Task 1: Slow runner
Verify-Cmd: python3 -c "import time; time.sleep(10)"

```python test:tests/test_slow.py
import unittest
class TestSlow(unittest.TestCase):
    def test_one(self):
        self.assertEqual(1, 1)
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir), "--verify-timeout", "0.5"]
        )
        self.assertNotEqual(res.returncode, 0, "Timed out verify command should exit non-zero")
        self.assertIn("timed out", res.stderr.lower())

    # -------------------------------------------------------------------------
    # Defect 5: Python assert True / constants and code after return do not count
    # -------------------------------------------------------------------------
    def test_python_constant_assertions_and_assert_true_do_not_count(self) -> None:
        plan_content = """## Task 1: Test constants
Verify-Cmd: python3 -c "import tests.test_const; raise SystemExit(1)"

```python test:tests/test_const.py
import unittest
class TestConst(unittest.TestCase):
    def test_consts(self):
        assert True
        assert 1
        assert "hello"
        assert 2 == 2
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertEqual(res.returncode, 0, f"Extract failed: {res.stderr}")

        hashfile = self.sdd_dir / "task-1-tests.sha256"
        data = json.loads(hashfile.read_text(encoding="utf-8"))
        test_info = data["files"]["tests/test_const.py"]["tests"]["TestConst.test_consts"]
        # Only 'assert 2 == 2' is a real assertion; assert True, assert 1, assert "hello" do not count
        self.assertEqual(test_info["assertions"], 1)

    def test_python_code_after_return_does_not_count(self) -> None:
        plan_content = """## Task 1: Test return
Verify-Cmd: python3 -c "import tests.test_ret; raise SystemExit(1)"

```python test:tests/test_ret.py
import unittest
class TestRet(unittest.TestCase):
    def test_unreachable(self):
        self.assertEqual(1, 1)
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertEqual(res.returncode, 0, f"Extract failed: {res.stderr}")
        hashfile = self.sdd_dir / "task-1-tests.sha256"

        # Now neuter the test by putting return before assertion
        ret_file = self.worktree / "tests" / "test_ret.py"
        ret_file.write_text(
            """import unittest
class TestRet(unittest.TestCase):
    def test_unreachable(self):
        return
        self.assertEqual(1, 1)
""",
            encoding="utf-8",
        )
        res_check = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertNotEqual(res_check.returncode, 0, "Test with return before assert should fail check-intact")
        self.assertIn("assertions", res_check.stderr.lower())

    # -------------------------------------------------------------------------
    # Defect 5: JS/TS commented-out assertions do not count
    # -------------------------------------------------------------------------
    def test_check_intact_js_commented_out_assertions_do_not_count(self) -> None:
        plan_content = """## Task 1: JS comments
Verify-Cmd: node -e "process.exit(1)"

```javascript test:tests/comments.test.js
describe('Commented', () => {
    it('checks values', () => {
        expect(1).toBe(1);
        expect(2).toBe(2);
    });
});
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertEqual(res.returncode, 0, f"Extract JS failed: {res.stderr}")
        hashfile = self.sdd_dir / "task-1-tests.sha256"

        # Comment out one assertion using single-line comment
        js_file = self.worktree / "tests" / "comments.test.js"
        js_file.write_text(
            """describe('Commented', () => {
    it('checks values', () => {
        // expect(1).toBe(1);
        expect(2).toBe(2);
    });
});
""",
            encoding="utf-8",
        )
        res_comment = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertNotEqual(res_comment.returncode, 0, "Commented-out expect should not count towards assertions")

        # Comment out using block comment
        js_file.write_text(
            """describe('Commented', () => {
    it('checks values', () => {
        /* expect(1).toBe(1); */
        expect(2).toBe(2);
    });
});
""",
            encoding="utf-8",
        )
        res_block = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertNotEqual(res_block.returncode, 0, "Block commented expect should not count towards assertions")

    # -------------------------------------------------------------------------
    # Defect 6: For-loop refactor with same or lower assertions
    # -------------------------------------------------------------------------
    def test_python_for_loop_refactor_same_assertions_passes(self) -> None:
        plan_content = """## Task 1: Loop refactor
Verify-Cmd: python3 -c "import tests.test_loop; raise SystemExit(1)"

```python test:tests/test_loop.py
import unittest
class TestLoop(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(1, 1)
        self.assertEqual(2, 2)
        self.assertEqual(3, 3)
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertEqual(res.returncode, 0, f"Extract failed: {res.stderr}")
        hashfile = self.sdd_dir / "task-1-tests.sha256"

        # Honest refactor into for loop with 3 items
        loop_file = self.worktree / "tests" / "test_loop.py"
        loop_file.write_text(
            """import unittest
class TestLoop(unittest.TestCase):
    def test_cases(self):
        for a, b in [(1, 1), (2, 2), (3, 3)]:
            self.assertEqual(a, b)
""",
            encoding="utf-8",
        )
        res_intact = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertEqual(res_intact.returncode, 0, f"Loop refactor with same assertion count should pass: {res_intact.stderr}")

    def test_python_for_loop_refactor_fewer_assertions_fails(self) -> None:
        plan_content = """## Task 1: Loop refactor fewer
Verify-Cmd: python3 -c "import tests.test_loop_fewer; raise SystemExit(1)"

```python test:tests/test_loop_fewer.py
import unittest
class TestLoopFewer(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(1, 1)
        self.assertEqual(2, 2)
        self.assertEqual(3, 3)
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertEqual(res.returncode, 0, f"Extract failed: {res.stderr}")
        hashfile = self.sdd_dir / "task-1-tests.sha256"

        # Refactor with fewer items (2 instead of 3)
        loop_file = self.worktree / "tests" / "test_loop_fewer.py"
        loop_file.write_text(
            """import unittest
class TestLoopFewer(unittest.TestCase):
    def test_cases(self):
        for a, b in [(1, 1), (2, 2)]:
            self.assertEqual(a, b)
""",
            encoding="utf-8",
        )
        res_intact = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertNotEqual(res_intact.returncode, 0, "Loop refactor with fewer assertions should fail")
        self.assertIn("TestLoopFewer.test_cases", res_intact.stderr)

    # -------------------------------------------------------------------------
    # Defect 6: Multiple blocks for same file appended in order and registered
    # -------------------------------------------------------------------------
    def test_multiple_blocks_for_same_file_appended_and_registered(self) -> None:
        plan_content = """## Task 1: Combined blocks
Verify-Cmd: python3 -c "import tests.test_combo; raise SystemExit(1)"

```python test:tests/test_combo.py
import unittest
class TestComboA(unittest.TestCase):
    def test_part_a(self):
        self.assertEqual(1, 1)
```

```python test:tests/test_combo.py
class TestComboB(unittest.TestCase):
    def test_part_b(self):
        self.assertEqual(2, 2)
```
"""
        plan_file = self.tmp_path / "plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        res = self.run_cmd(
            [str(plan_file), "1", str(self.worktree), "--sdd-dir", str(self.sdd_dir)]
        )
        self.assertEqual(res.returncode, 0, f"Extract failed: {res.stderr}")

        combo_file = self.worktree / "tests" / "test_combo.py"
        self.assertTrue(combo_file.exists())
        combo_text = combo_file.read_text(encoding="utf-8")
        self.assertIn("TestComboA", combo_text)
        self.assertIn("TestComboB", combo_text)
        self.assertTrue(combo_text.index("TestComboA") < combo_text.index("TestComboB"), "Blocks should be appended in order")

        hashfile = self.sdd_dir / "task-1-tests.sha256"
        data = json.loads(hashfile.read_text(encoding="utf-8"))
        registered_tests = data["files"]["tests/test_combo.py"]["tests"]
        self.assertIn("TestComboA.test_part_a", registered_tests)
        self.assertIn("TestComboB.test_part_b", registered_tests)

        # Check intact passes
        res_intact = self.run_cmd(["--check-intact", str(hashfile)])
        self.assertEqual(res_intact.returncode, 0, f"Check intact failed: {res_intact.stderr}")


if __name__ == "__main__":
    unittest.main()
