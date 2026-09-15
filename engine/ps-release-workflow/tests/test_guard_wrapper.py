"""guard_check.sh: fast-path shell wrapper around guard_check.py.

The wrapper must skip the ~60ms python spawn for edits outside any
ps-release-workflow repo, but ALWAYS fall through to python on doubt
(jq missing, empty/None path, malformed input, guarded repo).
"""
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parent.parent / "scripts" / "guard_check.sh"


def _run(stdin: str, env_extra: dict | None = None, home: Path | None = None):
    env = dict(os.environ)
    env.pop("CLAUDE_SESSION_ID", None)
    env.pop("PS_RELEASE_WORKFLOW_SCRIPTED", None)
    if home is not None:
        env["HOME"] = str(home)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(WRAPPER)],
        input=stdin, capture_output=True, text=True, env=env,
    )


@pytest.fixture
def guarded_repo(tmp_path: Path) -> Path:
    """Minimal opted-in main checkout: a .git DIRECTORY + .release.json."""
    repo = tmp_path / "guarded_repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".release.json").write_text("{}")
    return repo


def test_wrapper_is_executable():
    assert WRAPPER.exists()
    assert WRAPPER.stat().st_mode & stat.S_IXUSR


def test_non_workflow_path_allows_without_invoking_python(tmp_path: Path):
    """No .release.json anywhere up the tree → rc 0 and python NOT spawned.
    Proven with a sentinel interpreter: if python ran, rc would be 99."""
    sentinel = tmp_path / "fake-python3"
    sentinel.write_text("#!/bin/bash\nexit 99\n")
    sentinel.chmod(0o755)
    payload = json.dumps(
        {"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "plain" / "f.py")}}
    )
    r = _run(payload, env_extra={"PS_GUARD_PYTHON": str(sentinel)}, home=tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_guarded_main_checkout_edit_blocks_via_python(guarded_repo: Path, tmp_path: Path):
    """rc 2 proves the wrapper DID fall through to the real python guard."""
    payload = json.dumps(
        {"tool_name": "Edit", "tool_input": {"file_path": str(guarded_repo / "src" / "f.py")}}
    )
    r = _run(payload, home=tmp_path)
    assert r.returncode == 2, r.stderr
    assert "BLOCKED" in r.stderr


def test_write_to_not_yet_existing_file_under_guarded_repo_blocks(guarded_repo: Path, tmp_path: Path):
    """Write of a brand-new nested file: wrapper must walk from the nearest
    EXISTING ancestor and still hand off to python, which blocks."""
    new_file = guarded_repo / "brand" / "new" / "deep" / "file.py"  # none of these dirs exist
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(new_file)}})
    r = _run(payload, home=tmp_path)
    assert r.returncode == 2, r.stderr
    assert "BLOCKED" in r.stderr


def test_notebook_edit_under_guarded_repo_blocks(guarded_repo: Path, tmp_path: Path):
    payload = json.dumps(
        {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": str(guarded_repo / "a.ipynb")}}
    )
    r = _run(payload, home=tmp_path)
    assert r.returncode == 2, r.stderr


def test_malformed_stdin_allows(tmp_path: Path):
    r = _run("{definitely not json", home=tmp_path)
    assert r.returncode == 0
    assert r.stderr.strip() != ""  # a warning was emitted somewhere down the line


def test_non_mutating_tool_allows_fast(guarded_repo: Path, tmp_path: Path):
    payload = json.dumps(
        {"tool_name": "Read", "tool_input": {"file_path": str(guarded_repo / "f.py")}}
    )
    r = _run(payload, home=tmp_path)
    assert r.returncode == 0


def test_symlinked_ancestor_still_blocks_via_python(guarded_repo: Path, tmp_path: Path):
    """B1: a target reached through a symlinked directory (link -> repo/src) has
    no .release.json on its LITERAL ancestor chain, so a string-walk skips the
    real guard. The wrapper must physically resolve the start dir (pwd -P) so
    the walk runs on the real path and hands off to python, which blocks."""
    (guarded_repo / "src").mkdir()
    link = tmp_path / "link"
    link.symlink_to(guarded_repo / "src")
    payload = json.dumps(
        {"tool_name": "Edit", "tool_input": {"file_path": str(link / "f.py")}}
    )
    r = _run(payload, home=tmp_path)
    assert r.returncode == 2, r.stderr
    assert "BLOCKED" in r.stderr


def test_backslash_in_repo_dirname_falls_through_to_python(tmp_path: Path):
    """B2: jq's @tsv escapes backslash/tab/newline, so the extracted string no
    longer names a real filesystem path and the bash walk silently misses the
    repo. Any backslash in the extraction = doubt = run python (which parses
    the JSON correctly and blocks)."""
    repo = tmp_path / "weird\\dir"  # literal backslash in the directory name (APFS allows it)
    (repo / ".git").mkdir(parents=True)
    (repo / ".release.json").write_text("{}")
    payload = json.dumps(
        {"tool_name": "Edit", "tool_input": {"file_path": str(repo / "src" / "f.py")}}
    )
    r = _run(payload, home=tmp_path)
    assert r.returncode == 2, r.stderr
    assert "BLOCKED" in r.stderr


def test_no_python3_anywhere_warns_loudly_and_allows(guarded_repo: Path, tmp_path: Path):
    """Minor: python3 missing machine-wide means the guard is silently dead.
    The wrapper must still exit 0 (never brick every edit) but SCREAM on stderr."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("bash", "cat", "dirname", "jq"):
        real = shutil.which(tool)
        if real:
            (bindir / tool).symlink_to(real)
    payload = json.dumps(
        {"tool_name": "Edit", "tool_input": {"file_path": str(guarded_repo / "src" / "f.py")}}
    )
    r = _run(
        payload,
        env_extra={"PATH": str(bindir), "PS_GUARD_PYTHON": str(tmp_path / "no-such-python3")},
        home=tmp_path,
    )
    assert r.returncode == 0
    assert "DISABLED MACHINE-WIDE" in r.stderr


def test_mutating_tool_without_path_falls_through_to_python(guarded_repo: Path, tmp_path: Path):
    """Empty/missing path extraction → never decide in bash; let python judge.
    Python allows (no target), so rc 0 — but the sentinel proves python ran."""
    sentinel = tmp_path / "fake-python3"
    sentinel.write_text("#!/bin/bash\nexit 99\n")
    sentinel.chmod(0o755)
    payload = json.dumps({"tool_name": "Edit", "tool_input": {}})
    r = _run(payload, env_extra={"PS_GUARD_PYTHON": str(sentinel)}, home=tmp_path)
    assert r.returncode == 99
