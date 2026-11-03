import subprocess

import pytest

from lib.design_gate import check_design_artifacts, ui_files_changed


def test_ui_files_changed_filters_patterns_and_exclusions(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()
    git("init")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (tmp_path / "base").write_text("base")
    git("add", ".")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD")
    included = ["app.svelte", "a.tsx", "b.jsx", "c.vue", "d.css", "e.scss", "f.html"]
    excluded = ["node_modules/a.css", "e2e/a.tsx", "x.test.tsx", "x.spec.css", "__tests__/a.jsx", "docs/a.html", ".claude/a.css", "notes.txt"]
    for name in included + excluded:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    git("add", "-f", ".")
    git("commit", "-m", "changes")
    assert set(ui_files_changed(tmp_path, base)) == set(included)


def test_artifacts_require_nonempty_brief_and_one_critique(tmp_path):
    assert check_design_artifacts(tmp_path, []) == []
    assert len(check_design_artifacts(tmp_path, ["app.tsx"])) == 2
    (tmp_path / "design-brief.md").write_text("  ")
    (tmp_path / "critique.md").write_text("review")
    assert len(check_design_artifacts(tmp_path, ["app.tsx"])) == 1
    (tmp_path / "design-brief.md").write_text("brief")
    (tmp_path / "critique.md").write_text("")
    assert len(check_design_artifacts(tmp_path, ["app.tsx"])) == 1
    (tmp_path / "design-critique.md").write_text("review")
    assert check_design_artifacts(tmp_path, ["app.tsx"]) == []
