"""Tests for bin/pandoc-shim: dedent nested HTML only for markdown->HTML renders."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SHIM = Path(__file__).resolve().parent.parent / "bin" / "pandoc-shim"
REAL = shutil.which("pandoc")
pytestmark = pytest.mark.skipif(REAL is None, reason="pandoc not installed")

TILES = '# t\n\n<div class="metric-grid">\n  <div class="metric-tile">\n    <div class="metric-label">X</div>\n  </div>\n</div>\n'


def pandoc(tmp_path, *args, shim=True, env_extra=None):
    env = {**os.environ, "PANDOC_REAL": REAL, **(env_extra or {})}
    exe = str(SHIM) if shim else REAL
    return subprocess.run([exe, *args], cwd=tmp_path, env=env, capture_output=True, text=True)


@pytest.fixture
def doc(tmp_path):
    (tmp_path / "a.md").write_text(TILES)
    return tmp_path


def test_unshimmed_pandoc_leaks_baseline(doc):
    out = pandoc(doc, "a.md", "-t", "html", shim=False).stdout
    assert "&lt;div" in out  # proves the bug the shim exists for


def test_html_output_is_dedented(doc):
    out = pandoc(doc, "a.md", "-t", "html").stdout
    assert 'class="metric-label"' in out and "&lt;div" not in out


def test_o_html_form(doc):
    r = pandoc(doc, "a.md", "-s", "-o", "a.html")
    assert r.returncode == 0
    html = (doc / "a.html").read_text()
    assert 'class="metric-label"' in html and "&lt;div" not in html


def test_non_html_output_untouched(doc):
    out = pandoc(doc, "a.md", "-t", "plain").stdout
    assert out == pandoc(doc, "a.md", "-t", "plain", shim=False).stdout


def test_output_md_path_not_rewritten(doc):
    r = pandoc(doc, "a.md", "-t", "html", "-o", "out.md")
    assert r.returncode == 0 and (doc / "out.md").exists()
    assert (doc / "a.md").read_text() == TILES  # source never modified


def test_fenced_indented_html_preserved(doc):
    (doc / "f.md").write_text("# t\n\n```html\n    <div>keep</div>\n```\n")
    assert pandoc(doc, "f.md", "-t", "html").stdout == pandoc(doc, "f.md", "-t", "html", shim=False).stdout


def test_exit_code_propagates(doc):
    r = pandoc(doc, "missing.md", "-t", "html")
    assert r.returncode != 0


def test_bypass_env(doc):
    out = pandoc(doc, "a.md", "-t", "html", env_extra={"PANDOC_SHIM_OFF": "1"}).stdout
    assert "&lt;div" in out


def test_t_wins_over_o_extension(doc):
    pandoc(doc, "a.md", "-t", "plain", "-o", "x.html")
    assert (doc / "x.html").read_text() == pandoc(doc, "a.md", "-t", "plain", shim=False).stdout


@pytest.mark.parametrize("fmt", [["-t", "html5"], ["--to=html5"], ["-thtml"], ["-f", "gfm", "-s", "-o", "g.html"]])
def test_html_variants_dedented(doc, fmt):
    r = pandoc(doc, "a.md", *fmt)
    out = (doc / "g.html").read_text() if "g.html" in fmt else r.stdout
    assert 'class="metric-label"' in out and "&lt;div" not in out


def test_stdin_and_zero_args_work_under_system_bash(doc):
    r = subprocess.run(["/bin/bash", str(SHIM), "-t", "html"], input="# hi\n", cwd=doc,
                       env={**os.environ, "PANDOC_REAL": REAL}, capture_output=True, text=True)
    assert r.returncode == 0 and "<h1" in r.stdout
    r0 = subprocess.run(["/bin/bash", str(SHIM)], input="# hi\n", cwd=doc,
                        env={**os.environ, "PANDOC_REAL": REAL}, capture_output=True, text=True)
    assert r0.returncode == 0 and "<h1" in r0.stdout


def test_option_value_md_not_rewritten(doc):
    (doc / "inc.md").write_text("<style></style>\n")
    r = pandoc(doc, "a.md", "-t", "html", "-V", "k=v", "--css", "inc.md")
    assert r.returncode == 0


def test_real_pandoc_found_via_path_without_override(doc, tmp_path):
    link_dir = tmp_path / "shimbin"
    link_dir.mkdir()
    (link_dir / "pandoc").symlink_to(SHIM)
    env = {k: v for k, v in os.environ.items() if k != "PANDOC_REAL"}
    real_dir = os.path.dirname(REAL)
    env["PATH"] = os.pathsep.join([str(link_dir), str(link_dir), real_dir, "/usr/bin", "/bin"])
    r = subprocess.run(["pandoc", "a.md", "-t", "html"], cwd=doc, env=env, capture_output=True, text=True)
    assert r.returncode == 0
    assert 'class="metric-label"' in r.stdout and "&lt;div" not in r.stdout


def test_temp_dir_removed(doc, tmp_path):
    tdir = tmp_path / "tmpd"
    tdir.mkdir()
    pandoc(doc, "a.md", "-t", "html", env_extra={"TMPDIR": str(tdir)})
    assert list(tdir.iterdir()) == []
