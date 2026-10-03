"""Fail CI when a tracked test file is not run by any CI job.

Guards silent gaps:
  1. a test file outside every path a CI test step runs (it never executes);
  2. `unittest`, which never collects pytest-style tests (fixtures,
     parametrize) and so passes while skipping them;
  3. a test step that may not run or whose failure is ignored (`if:`,
     `continue-on-error`, `|| true`).

Only lines that invoke a test runner count. A runner covers the existing paths
it names (minus excluded ones), resolved against its working-directory; pytest
naming none covers the `testpaths` of its config. Pytest/unittest cover only
.py files; a named shell/JS test file covers only itself.
"""
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
TEST_FILE = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.(py|sh)|[^/]*\.(test|spec)\.[cm]?[jt]sx?)$")
PY_RUNNER = re.compile(r"\bpytest\b|\bunittest\b")
FILE_RUNNER = re.compile(r"_test\.sh\b")
# `pip install pytest` names a runner but runs nothing.
INSTALL = re.compile(r"^\s*(python3? -m )?(pip3?|npm (ci|install)|uv pip)\b")
EXCLUDE_FLAGS = {"--ignore", "--ignore-glob", "--deselect"}


def pytest_testpaths(base: Path) -> list[Path]:
    pyproject = base / "pyproject.toml"
    if pyproject.is_file():
        opts = tomllib.loads(pyproject.read_text()).get("tool", {}).get("pytest", {}).get("ini_options", {})
        if opts.get("testpaths"):
            return [base / p for p in opts["testpaths"]]
    return []


def named_paths(line: str, base: Path) -> tuple[list[Path], list[Path]]:
    """(paths the runner is given, paths excluded with --ignore/--deselect)."""
    tokens = []
    for t in line.replace("&&", " ").split():
        tokens += t.split("=", 1) if t.split("=", 1)[0] in EXCLUDE_FLAGS else [t]
    excluded = {i + 1 for i, t in enumerate(tokens) if t in EXCLUDE_FLAGS}
    given = [base / t for i, t in enumerate(tokens)
             if i not in excluded and not t.startswith("-") and t not in (".", "./") and (base / t).exists()]
    return given, [base / tokens[i].split("::")[0] for i in excluded if i < len(tokens)]


def covered(errors: list[str]) -> list[tuple[Path, str, list[Path]]]:
    """(path, kind, excluded) triples; kind 'py' covers .py files under path
    except those under an excluded path, 'file' covers path itself."""
    cover = []
    for wf in sorted(WORKFLOWS.glob("*.y*ml")):
        doc = yaml.safe_load(wf.read_text())
        wf_wd = ((doc.get("defaults") or {}).get("run") or {}).get("working-directory", ".")
        for job_name, job in (doc.get("jobs") or {}).items():
            job_wd = ((job.get("defaults") or {}).get("run") or {}).get("working-directory", wf_wd)
            for step in job.get("steps") or []:
                lines = [l for l in (step.get("run") or "").splitlines() if not INSTALL.match(l)]
                runner_lines = [l for l in lines if PY_RUNNER.search(l) or FILE_RUNNER.search(l)]
                if not runner_lines:
                    continue
                where = f"{wf.name}:{job_name}"
                if "if" in job or "if" in step or job.get("continue-on-error") or step.get("continue-on-error"):
                    errors.append(f"{where}: test step may be skipped or ignored (`if:` / `continue-on-error`)")
                base = (ROOT / step.get("working-directory", job_wd)).resolve()
                for line in runner_lines:
                    if "|| true" in line or re.search(r"\|\|\s*:", line):
                        errors.append(f"{where}: `{line.strip()}` ignores test failures")
                    if re.search(r"\bunittest\b", line):
                        errors.append(f"{where}: `unittest` skips pytest-style tests; use pytest")
                    paths, excl = named_paths(line, base)
                    excl = [p.resolve() for p in excl]
                    if FILE_RUNNER.search(line):
                        cover += [(p.resolve(), "file", []) for p in paths if p.is_file()]
                    elif paths:
                        cover += [(p.resolve(), "py", excl) for p in paths]
                    elif testpaths := pytest_testpaths(base):
                        cover += [(p.resolve(), "py", excl) for p in testpaths]
                    else:
                        errors.append(f"{where}: `{line.strip()}` names no test path and has no testpaths config")
    return cover


def under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def is_covered(path: Path, cover: list[tuple[Path, str, list[Path]]]) -> bool:
    for root, kind, excl in cover:
        if kind == "file" and path == root:
            return True
        if kind == "py" and path.suffix == ".py" and under(path, root) and not any(under(path, e) for e in excl):
            return True
    return False


def main() -> int:
    errors: list[str] = []
    cover = covered(errors)
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    tests = [f for f in tracked.splitlines() if TEST_FILE.search(f)]
    if not tests:
        errors.append("no tracked test files found — the file pattern is broken")
    for f in tests:
        if not is_covered((ROOT / f).resolve(), cover):
            errors.append(f"{f}: not run by any CI test step — add it to a job in .github/workflows/")
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)
    if errors:
        return 1
    print(f"ok: {len(tests)} test files, all run by a CI test step")
    return 0


if __name__ == "__main__":
    sys.exit(main())
