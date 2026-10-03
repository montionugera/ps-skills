"""Each case is a way CI could pass while a test silently never runs."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from check_test_coverage import check  # noqa: E402

BASE_FILES = {
    "tests/test_a.py": "",
    "pkg/pyproject.toml": '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
    "pkg/tests/test_b.py": "",
    "sh/run_test.sh": "",
    "go/x/a_test.go": "",
}
BASE_STEPS = """
      - run: pip install pytest
      - run: python3 -m pytest tests -v
      - run: pytest -q
        working-directory: pkg
      - run: bash sh/run_test.sh
      - run: go test ./...
        working-directory: go
"""


def repo(tmp_path: Path, steps: str = BASE_STEPS, extra: dict[str, str] | None = None) -> Path:
    files = {**BASE_FILES, **(extra or {}),
             ".github/workflows/ci.yml": f"jobs:\n  t:\n    runs-on: ubuntu-latest\n    steps:{steps}"}
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def test_fully_covered_repo_passes(tmp_path):
    assert check(repo(tmp_path)) == []


@pytest.mark.parametrize("path", [
    "newdir/tests/test_new.py",        # no job runs this dir
    "pkg/scripts/test_x.py",           # outside pytest testpaths
    "tests/foo_test.sh",               # shell test under a pytest-only dir
    "tests/test_e2e.sh",
    "pkg/tests/y_test.go",             # go test under a pytest-only dir
])
def test_uncovered_test_file_fails(tmp_path, path):
    errors = check(repo(tmp_path, extra={path: ""}))
    assert any(path in e for e in errors), errors


@pytest.mark.parametrize("old,new,needle", [
    ("python3 -m pytest tests -v", "python3 -m unittest discover -s tests", "unittest"),
    ("python3 -m pytest tests -v", "python3 -m unittest", "unittest"),
    ("python3 -m pytest tests -v", "python3 -m pytest tests -v || true", "ignores test failures"),
    ("python3 -m pytest tests -v", 'python3 -m pytest "tests" -v', "names no test path"),
    ("python3 -m pytest tests -v", "python3 -m pytest tests --ignore tests/test_a.py", "tests/test_a.py"),
    ("python3 -m pytest tests -v", "python3 -m pytest tests --ignore=tests/test_a.py", "tests/test_a.py"),
    ("python3 -m pytest tests -v", "python3 -m pytest tests --deselect tests/test_a.py::t", "tests/test_a.py"),
    ("      - run: bash sh/run_test.sh\n",
     "      - run: bash sh/run_test.sh\n        continue-on-error: true\n", "skipped or ignored"),
    ("      - run: bash sh/run_test.sh\n",
     "      - run: bash sh/run_test.sh\n        if: false\n", "skipped or ignored"),
])
def test_bypass_fails(tmp_path, old, new, needle):
    assert old in BASE_STEPS
    errors = check(repo(tmp_path, steps=BASE_STEPS.replace(old, new)))
    assert any(needle in e for e in errors), errors


def test_install_line_does_not_count_as_runner(tmp_path):
    # `pip install pytest` once made a path-less "runner" that covered the whole repo.
    steps = "\n      - run: pip install pytest\n"
    errors = check(repo(tmp_path, steps=steps))
    assert any("tests/test_a.py" in e for e in errors), errors


def test_job_default_working_directory_is_used(tmp_path):
    steps = BASE_STEPS.replace("      - run: pytest -q\n        working-directory: pkg\n", "")
    wf = f"jobs:\n  t:\n    runs-on: ubuntu-latest\n    steps:{steps}  p:\n    runs-on: ubuntu-latest\n" \
         "    defaults:\n      run:\n        working-directory: pkg\n    steps:\n      - run: pytest -q\n"
    root = repo(tmp_path)
    (root / ".github/workflows/ci.yml").write_text(wf)
    assert check(root) == []
