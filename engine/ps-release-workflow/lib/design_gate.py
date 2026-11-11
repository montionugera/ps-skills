"""Require design artifacts for feature changes to UI files."""
from fnmatch import fnmatch
from pathlib import Path
import subprocess

UI_PATTERNS = ("*.svelte", "*.tsx", "*.jsx", "*.vue", "*.css", "*.scss", "*.html")
EXCLUDE = ("/node_modules/", "/e2e/", ".test.", ".spec.", "/__tests__/", "/docs/", "/.claude/")


def ui_files_changed(worktree: Path, base_ref: str) -> list[str]:
    base = subprocess.run(["git", "merge-base", base_ref, "HEAD"], cwd=worktree,
                          check=True, capture_output=True, text=True).stdout.strip()
    result = subprocess.run(["git", "diff", "--name-only", "-z", f"{base}..HEAD"],
                            cwd=worktree, check=True, capture_output=True, text=True)
    paths = result.stdout.split("\0")
    return [path for path in paths if path and
            any(fnmatch(path, pattern) for pattern in UI_PATTERNS) and
            not any(exclusion in f"/{path}" for exclusion in EXCLUDE)]


def check_design_artifacts(feature_dir: Path, ui_files: list[str]) -> list[str]:
    if not ui_files:
        return []
    def present(name: str) -> bool:
        path = feature_dir / name
        return path.is_file() and bool(path.read_text().strip())
    missing = []
    if not present("design-brief.md"):
        missing.append("design-brief.md (missing or empty)")
    if not (present("critique.md") or present("design-critique.md")):
        missing.append("critique.md or design-critique.md (missing or empty)")
    return missing
