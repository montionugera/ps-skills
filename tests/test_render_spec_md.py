"""Regression tests for bin/render-spec-md.sh (raw-HTML leak + loud-failure contract)."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "render-spec-md.sh"
pytestmark = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")

METRIC_TILES = (
    '# t\n\n<div class="metric-grid">\n  <div class="metric-tile">\n'
    '    <div class="metric-label">Tempo</div>\n  </div>\n</div>\n'
)


@pytest.fixture
def home(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "spec-style.html").write_text("<style></style>")
    return tmp_path


def run(home, md_text):
    md = home / "doc.md"
    md.write_text(md_text)
    env = {**os.environ, "HOME": str(home)}
    proc = subprocess.run([str(SCRIPT), str(md)], env=env, capture_output=True, text=True)
    return proc, md.with_suffix(".html")


def test_nested_html_renders_as_elements_not_code(home):
    proc, html = run(home, METRIC_TILES)
    assert proc.returncode == 0, proc.stderr
    out = html.read_text()
    assert 'class="metric-label"' in out
    assert "&lt;div" not in out


def test_fenced_html_example_is_not_flagged(home):
    proc, _ = run(home, '# t\n\n```html\n<div class="x">hi</div>\n```\n')
    assert proc.returncode == 0, proc.stderr


def test_unfixable_indented_html_fails_loudly(home):
    proc, _ = run(home, '# t\n\nintro\n\n    text <span class="z">x</span>\n')
    assert proc.returncode == 1
    assert "RAW-HTML LEAK" in proc.stderr
    assert (home / ".claude" / "logs" / "render-spec.log").exists()


def test_missing_style_header_fails_loudly(home):
    (home / ".claude" / "spec-style.html").unlink()
    proc, _ = run(home, "# t\n")
    assert proc.returncode == 1
    assert "missing style header" in proc.stderr


def run_cli(home, arg, path_prefix=None):
    env = {**os.environ, "HOME": str(home)}
    if path_prefix:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    return subprocess.run([str(SCRIPT), str(arg)], env=env, capture_output=True, text=True)


def run_hook(home, file_path):
    env = {**os.environ, "HOME": str(home)}
    payload = '{"tool_input":{"file_path":"%s"}}' % file_path
    return subprocess.run([str(SCRIPT)], input=payload, env=env, capture_output=True, text=True)


def stub_mmdc(tmp_path, message):
    d = tmp_path / "stub"
    d.mkdir()
    exe = d / "mmdc"
    exe.write_text(f"#!/bin/sh\necho '{message}' >&2\nexit 1\n")
    exe.chmod(0o755)
    return d


MERMAID = "# t\n\n```mermaid\nflowchart LR\n A-->B\n```\n"


def test_explicit_missing_file_fails_loudly(home):
    proc = run_cli(home, home / "nope.md")
    assert proc.returncode == 1
    assert "no such file" in proc.stderr


def test_explicit_non_md_fails_loudly(home):
    txt = home / "a.txt"
    txt.write_text("x")
    proc = run_cli(home, txt)
    assert proc.returncode == 1
    assert "not a .md file" in proc.stderr


def test_explicit_blacklisted_name_still_renders(home):
    readme = home / "README.md"
    readme.write_text("# hi\n")
    assert run_cli(home, readme).returncode == 0
    assert readme.with_suffix(".html").exists()


def test_hook_skips_non_whitelisted_path_silently(home):
    md = home / "notes.md"
    md.write_text("# x\n")
    proc = run_hook(home, md)
    assert (proc.returncode, proc.stderr) == (0, "")
    assert not md.with_suffix(".html").exists()


def test_hook_problem_exits_2(home):
    d = home / "docs" / "superpowers" / "specs"
    d.mkdir(parents=True)
    md = d / "s.md"
    md.write_text('# t\n\nintro\n\n    text <span class="z">x</span>\n')
    assert run_hook(home, md).returncode == 2


def test_mermaid_syntax_error_fails_loudly(home, tmp_path):
    md = home / "m.md"
    md.write_text(MERMAID)
    proc = run_cli(home, md, stub_mmdc(tmp_path, "Parse error on line 2"))
    assert proc.returncode == 1
    assert "MERMAID SYNTAX ERROR" in proc.stderr


def test_mermaid_validator_unavailable_is_not_silent(home, tmp_path):
    md = home / "m.md"
    md.write_text(MERMAID)
    proc = run_cli(home, md, stub_mmdc(tmp_path, "Could not find Chrome (ver. 1)"))
    assert proc.returncode == 1
    assert "UNVERIFIED" in proc.stderr
