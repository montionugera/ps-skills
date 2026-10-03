"""Fail CI when a tracked test file is not run by any CI job.

Guards silent gaps:
  1. a test file outside every path a CI test step runs (it never executes);
  2. `unittest`, which never collects pytest-style tests (fixtures,
     parametrize) and so passes while skipping them;
  3. a test step that may not run or whose failure is ignored (`if:`,
     `continue-on-error`, `|| true`).

Only lines that invoke a test runner count. A runner covers the existing paths
it names (minus --ignore/--deselect ones), resolved against its
working-directory; pytest naming none covers its config's `testpaths`.
pytest/unittest cover only .py files, `go test ./x/...` only .go files, and a
named shell test file covers only itself.
"""
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TEST_FILE = re.compile(
    r"(^|/)(test_[^/]*\.(py|sh)|[^/]*_test\.(py|sh|go)|[^/]*\.(test|spec)\.[cm]?[jt]sx?)$")
PY_RUNNER = re.compile(r"\bpytest\b|\bunittest\b")
GO_RUNNER = re.compile(r"\bgo test\b")
FILE_RUNNER = re.compile(r"(_test|\btest_[\w.-]*)\.sh\b")
# `pip install pytest` names a runner but runs nothing.
INSTALL = re.compile(r"^\s*(python3? -m )?(pip3?|npm (ci|install)|uv pip)\b")
EXCLUDE_FLAGS = {"--ignore", "--ignore-glob", "--deselect"}
SUFFIX = {"py": ".py", "go": ".go"}


def pytest_testpaths(base: Path) -> list[Path]:
    pyproject = base / "pyproject.toml"
    if pyproject.is_file():
        opts = tomllib.loads(pyproject.read_text()).get("tool", {}).get("pytest", {}).get("ini_options", {})
        return [base / p for p in opts.get("testpaths", [])]
    return []


def named_paths(line: str, base: Path) -> tuple[list[Path], list[Path]]:
    """(paths the runner is given, paths excluded with --ignore/--deselect)."""
    tokens = []
    for t in line.replace("&&", " ").split():
        tokens += t.split("=", 1) if t.split("=", 1)[0] in EXCLUDE_FLAGS else [t]
    tokens = [t.removesuffix("/...") if t != "./..." else "." for t in tokens]
    excluded = {i + 1 for i, t in enumerate(tokens) if t in EXCLUDE_FLAGS}
    given = [base / t for i, t in enumerate(tokens)
             if i not in excluded and not t.startswith("-") and (base / t).exists()
             and (t != "." or GO_RUNNER.search(line))]
    return given, [base / tokens[i].split("::")[0] for i in excluded if i < len(tokens)]


def covered(root: Path, errors: list[str]) -> list[tuple[Path, str, list[Path]]]:
    """(path, kind, excluded) triples: kind 'py'/'go' covers files of that
    language under path except under an excluded path; 'file' covers path itself."""
    cover = []
    for wf in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        doc = yaml.safe_load(wf.read_text())
        wf_wd = ((doc.get("defaults") or {}).get("run") or {}).get("working-directory", ".")
        for job_name, job in (doc.get("jobs") or {}).items():
            job_wd = ((job.get("defaults") or {}).get("run") or {}).get("working-directory", wf_wd)
            for step in job.get("steps") or []:
                lines = [l for l in (step.get("run") or "").splitlines() if not INSTALL.match(l)]
                runner_lines = [l for l in lines if PY_RUNNER.search(l) or GO_RUNNER.search(l) or FILE_RUNNER.search(l)]
                if not runner_lines:
                    continue
                where = f"{wf.name}:{job_name}"
                if "if" in job or "if" in step or job.get("continue-on-error") or step.get("continue-on-error"):
                    errors.append(f"{where}: test step may be skipped or ignored (`if:` / `continue-on-error`)")
                base = (root / step.get("working-directory", job_wd)).resolve()
                for line in runner_lines:
                    if re.search(r"\|\|\s*(true|:)", line):
                        errors.append(f"{where}: `{line.strip()}` ignores test failures")
                    if re.search(r"\bunittest\b", line):
                        errors.append(f"{where}: `unittest` skips pytest-style tests; use pytest")
                    paths, excl = named_paths(line, base)
                    excl = [p.resolve() for p in excl]
                    if FILE_RUNNER.search(line):
                        cover += [(p.resolve(), "file", []) for p in paths if p.is_file()]
                        continue
                    kind = "go" if GO_RUNNER.search(line) else "py"
                    if not paths and kind == "py":
                        paths = pytest_testpaths(base)
                    if not paths:
                        errors.append(f"{where}: `{line.strip()}` names no test path (and no pytest testpaths)")
                    cover += [(p.resolve(), kind, excl) for p in paths]
    return cover


def under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def is_covered(path: Path, cover: list[tuple[Path, str, list[Path]]]) -> bool:
    for root, kind, excl in cover:
        if kind == "file" and path == root:
            return True
        if (kind in SUFFIX and path.suffix == SUFFIX[kind] and under(path, root)
                and not any(under(path, e) for e in excl)):
            return True
    return False


def check(root: Path) -> list[str]:
    errors: list[str] = []
    cover = covered(root, errors)
    tracked = subprocess.run(["git", "ls-files"], cwd=root, check=True, capture_output=True, text=True).stdout
    tests = [f for f in tracked.splitlines() if TEST_FILE.search(f)]
    if not tests:
        errors.append("no tracked test files found — the file pattern is broken")
    for f in tests:
        if not is_covered((root / f).resolve(), cover):
            errors.append(f"{f}: not run by any CI test step — add it to a job in .github/workflows/")
    return errors


def main() -> int:
    errors = check(ROOT)
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)
    if errors:
        return 1
    print("ok: every tracked test file is run by a CI test step")
    return 0


if __name__ == "__main__":
    sys.exit(main())
