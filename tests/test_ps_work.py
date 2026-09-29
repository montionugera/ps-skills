import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


COMMAND = Path(__file__).resolve().parents[1] / "bin" / "ps-work"


@pytest.fixture
def setup(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".release.json").write_text("{}")
    vault = tmp_path / "vault"
    vault.mkdir()
    record = {
        "record_id": "PROJ-demo",
        "sha256": "abc123",
        "frontmatter": {
            "schema": "project/v1", "kind": "project", "id": "PROJ-demo",
            "title": "Easier checkout", "outcome": "Fewer abandoned carts",
        },
    }
    status = {
        "schema": "psrw-status/v1", "opted_in": True,
        "release": {"version": "1.8", "in_progress": True},
        "features": [{"id": "F-016", "title": "Checkout", "status": "claimed", "release_version": "1.8"}],
        "epics": [],
    }
    (tmp_path / "record.json").write_text(json.dumps(record))
    (tmp_path / "status.json").write_text(json.dumps(status))
    fake = tmp_path / "fake-cli"
    fake.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['FIXTURE_ROOT'])
with (root / 'calls.jsonl').open('a') as out:
    out.write(json.dumps({'command': pathlib.Path(sys.argv[0]).name, 'args': sys.argv[1:], 'vault_root': os.getenv('VAULT_ROOT')}) + '\\n')
if pathlib.Path(sys.argv[0]).name == 'vault-engine':
    if sys.argv[1] == 'read-record' and (root / 'readfail').exists():
        print('vault exploded', file=sys.stderr)
        sys.exit(3)
    if sys.argv[1] == 'read-record':
        print((root / 'record.json').read_text())
    elif sys.argv[1] == 'commit':
        if (root / 'conflict').exists():
            print('OCC_CONFLICT', file=sys.stderr)
            sys.exit(1)
        print('committed')
else:
    if (root / 'psrwfail').exists():
        print('psrw exploded', file=sys.stderr)
        sys.exit(2)
    if (root / 'sleep').exists():
        import time
        time.sleep(30)
    print((root / 'status.json').read_text())
""")
    for name in ("vault-engine", "psrw"):
        path = tmp_path / name
        path.write_text(fake.read_text())
        path.chmod(0o755)

    def run(*args):
        env = {**os.environ, "FIXTURE_ROOT": str(tmp_path)}
        return subprocess.run(
            [sys.executable, str(COMMAND), *args, "--vault-engine", str(tmp_path / "vault-engine"),
             "--psrw", str(tmp_path / "psrw")], text=True, capture_output=True, env=env,
        )

    def calls():
        path = tmp_path / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    return tmp_path, repo, vault, record, status, run, calls


def test_link_uses_vault_occ_and_only_two_fields(setup):
    root, repo, vault, _, _, run, calls = setup
    result = run("link", "PROJ-demo", "--vault-root", str(vault), "--repo", str(repo), "--feature", "F-016")
    assert result.returncode == 0, result.stderr
    history = calls()
    assert [c["args"][0] for c in history] == ["status", "read-record", "commit"]
    assert all(c["vault_root"] == str(vault) for c in history if c["command"] == "vault-engine")
    commit = history[-1]["args"]
    assert commit[1:3] == ["PROJ-demo", "abc123"]
    assert json.loads(commit[4]) == {"release_repo": str(repo), "release_feature_id": "F-016"}


def test_show_joins_live_status_without_writing(setup):
    root, repo, vault, record, _, run, calls = setup
    record["frontmatter"].update(release_repo=str(repo), release_feature_id="F-016")
    (root / "record.json").write_text(json.dumps(record))
    result = run("show", "PROJ-demo", "--vault-root", str(vault), "--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["project"]["outcome"] == "Fewer abandoned carts"
    assert data["feature"]["status"] == "claimed"
    assert data["release"]["version"] == "1.8"
    assert [c["args"][0] for c in calls()] == ["read-record", "status"]


def test_show_uses_features_own_release_version(setup):
    root, repo, vault, record, status, run, _ = setup
    record["frontmatter"].update(release_repo=str(repo), release_feature_id="F-016")
    status["features"][0].update(status="shipped", release_version="1.7")
    (root / "record.json").write_text(json.dumps(record))
    (root / "status.json").write_text(json.dumps(status))
    result = run("show", "PROJ-demo", "--vault-root", str(vault))
    assert result.returncode == 0, result.stderr
    assert "Release: 1.7" in result.stdout
    assert "Release: 1.8" not in result.stdout


def test_installed_copy_discovers_sibling_commands_off_path(setup):
    root, repo, vault, record, _, _, _ = setup
    record["frontmatter"].update(release_repo=str(repo), release_feature_id="F-016")
    (root / "record.json").write_text(json.dumps(record))
    installed = root / "installed"
    installed.mkdir()
    copied = installed / "ps-work"
    copied.write_bytes(COMMAND.read_bytes())
    copied.chmod(0o755)
    for name in ("psrw", "vault-engine"):
        sibling = installed / name
        sibling.write_bytes((root / name).read_bytes())
        sibling.chmod(0o755)
    env = {**os.environ, "FIXTURE_ROOT": str(root), "PATH": "/usr/bin:/bin"}
    result = subprocess.run(
        [str(copied), "show", "PROJ-demo", "--vault-root", str(vault), "--json"],
        text=True, capture_output=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["state"] == "linked"


def test_show_missing_link_keeps_project_context(setup):
    _, _, vault, _, _, run, calls = setup
    result = run("show", "PROJ-demo", "--vault-root", str(vault), "--json")
    assert json.loads(result.stdout)["state"] == "link_missing"
    assert [c["args"][0] for c in calls()] == ["read-record"]


def test_show_invalid_link_does_not_start_psrw(setup):
    root, repo, vault, record, _, run, calls = setup
    record["frontmatter"].update(release_repo=str(repo / "child"), release_feature_id="F-016")
    (root / "record.json").write_text(json.dumps(record))
    result = run("show", "PROJ-demo", "--vault-root", str(vault), "--json")
    assert json.loads(result.stdout)["state"] == "link_invalid"
    assert [c["args"][0] for c in calls()] == ["read-record"]


def test_link_rejects_worktree_and_missing_feature(setup):
    root, repo, vault, _, status, run, calls = setup
    worktree = root / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: /some/path")
    (worktree / ".release.json").write_text("{}")
    bad = run("link", "PROJ-demo", "--vault-root", str(vault), "--repo", str(worktree), "--feature", "F-016")
    assert bad.returncode != 0
    assert calls() == []
    status["features"] = []
    (root / "status.json").write_text(json.dumps(status))
    missing = run("link", "PROJ-demo", "--vault-root", str(vault), "--repo", str(repo), "--feature", "F-016")
    assert missing.returncode != 0
    assert all(c["args"][0] != "commit" for c in calls())


@pytest.mark.parametrize("status_change,expected", [
    ({"opted_in": False}, "release_unavailable"),
    ({"features": []}, "feature_not_found"),
])
def test_show_release_states(setup, status_change, expected):
    root, repo, vault, record, status, run, _ = setup
    record["frontmatter"].update(release_repo=str(repo), release_feature_id="F-016")
    status.update(status_change)
    (root / "record.json").write_text(json.dumps(record))
    (root / "status.json").write_text(json.dumps(status))
    result = run("show", "PROJ-demo", "--vault-root", str(vault), "--json")
    assert json.loads(result.stdout)["state"] == expected


def test_malformed_child_output_and_occ_conflict(setup):
    root, repo, vault, _, _, run, calls = setup
    (root / "status.json").write_text("not-json")
    bad = run("link", "PROJ-demo", "--vault-root", str(vault), "--repo", str(repo), "--feature", "F-016")
    assert bad.returncode != 0
    assert all(c["args"][0] != "commit" for c in calls())
    (root / "status.json").write_text(json.dumps(setup[4]))
    (root / "conflict").touch()
    conflict = run("link", "PROJ-demo", "--vault-root", str(vault), "--repo", str(repo), "--feature", "F-016")
    assert conflict.returncode != 0
    assert "conflict" in conflict.stderr.lower()


def test_real_vault_link_then_show_does_not_change_sources(setup):
    if not shutil.which("go"):
        pytest.skip("Go toolchain unavailable")
    root, repo, vault, _, _, _, _ = setup
    binary = root / "real-vault-engine"
    module = COMMAND.parents[1] / "tools" / "vault-engine"
    built = subprocess.run(["go", "build", "-o", str(binary), "./cmd/vault-engine"],
                           cwd=module, text=True, capture_output=True)
    assert built.returncode == 0, built.stderr
    project_dir = vault / "02_Projects" / "PROJ-demo"
    project_dir.mkdir(parents=True)
    note = project_dir / "Project Hub.md"
    note.write_text("---\nschema: project/v1\nid: PROJ-demo\nkind: project\n"
                    "title: Easier checkout\nstatus: active\nowner: human\n"
                    "target_date: someday\noutcome: Fewer abandoned carts\n---\nProject body.\n")
    env = {**os.environ, "FIXTURE_ROOT": str(root)}
    base = [str(COMMAND), "--vault-root", str(vault), "--vault-engine", str(binary),
            "--psrw", str(root / "psrw")]
    linked = subprocess.run([str(COMMAND), "link", "PROJ-demo", *base[1:],
                             "--repo", str(repo), "--feature", "F-016"],
                            text=True, capture_output=True, env=env)
    assert linked.returncode == 0, linked.stderr
    before_note = note.read_bytes()
    before_release = (root / "status.json").read_bytes()
    shown = subprocess.run([str(COMMAND), "show", "PROJ-demo", *base[1:], "--json"],
                           text=True, capture_output=True, env=env)
    assert shown.returncode == 0, shown.stderr
    assert json.loads(shown.stdout)["feature"]["status"] == "claimed"
    assert note.read_bytes() == before_note
    assert (root / "status.json").read_bytes() == before_release


def linked(setup):
    root, repo, vault, record, _, run, _ = setup
    record["frontmatter"].update(release_repo=str(repo), release_feature_id="F-016")
    (root / "record.json").write_text(json.dumps(record))
    return root, vault, run


def test_show_psrw_nonzero_reports_message_and_unavailable(setup):
    root, vault, run = linked(setup)
    (root / "psrwfail").touch()
    result = run("show", "PROJ-demo", "--vault-root", str(vault), "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["state"] == "release_unavailable"
    assert "psrw exploded" in result.stderr


def test_show_missing_psrw_binary_is_clear_error(setup):
    root, vault, _ = linked(setup)
    env = {**os.environ, "FIXTURE_ROOT": str(root)}
    result = subprocess.run(
        [sys.executable, str(COMMAND), "show", "PROJ-demo", "--vault-root", str(vault), "--json",
         "--vault-engine", str(root / "vault-engine"), "--psrw", str(root / "nope")],
        text=True, capture_output=True, env=env)
    assert json.loads(result.stdout)["state"] == "release_unavailable"
    assert "cannot run nope" in result.stderr


def test_show_psrw_timeout_reports_unavailable(setup, monkeypatch, capsys):
    root, vault, _ = linked(setup)
    (root / "sleep").touch()
    monkeypatch.setenv("FIXTURE_ROOT", str(root))
    loader = importlib.machinery.SourceFileLoader("ps_work_mod", str(COMMAND))
    spec = importlib.util.spec_from_loader("ps_work_mod", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.setattr(module, "CHILD_TIMEOUT", 0.5)
    code = module.main(["show", "PROJ-demo", "--vault-root", str(vault), "--json",
                        "--vault-engine", str(root / "vault-engine"), "--psrw", str(root / "psrw")])
    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["state"] == "release_unavailable"
    assert "timed out" in captured.err


def test_show_non_dict_status_payload(setup):
    root, vault, run = linked(setup)
    (root / "status.json").write_text("[]")
    result = run("show", "PROJ-demo", "--vault-root", str(vault), "--json")
    assert json.loads(result.stdout)["state"] == "release_unavailable"
    assert "invalid response" in result.stderr


def test_show_vault_read_failure_fails_with_message(setup):
    root, vault, run = linked(setup)
    (root / "readfail").touch()
    result = run("show", "PROJ-demo", "--vault-root", str(vault), "--json")
    assert result.returncode == 1
    assert "vault exploded" in result.stderr


def test_show_surfaces_status_error_message(setup):
    root, vault, run = linked(setup)
    (root / "status.json").write_text(json.dumps({
        "schema": "psrw-status/v1",
        "error": {"code": "status_unavailable", "message": "state file corrupt"}}))
    result = run("show", "PROJ-demo", "--vault-root", str(vault), "--json")
    assert json.loads(result.stdout)["state"] == "release_unavailable"
    assert "state file corrupt" in result.stderr
    assert "not opted in" not in result.stderr


def test_link_accepts_symlinked_checkout_and_stores_resolved_path(setup):
    root, repo, vault, _, _, run, calls = setup
    alias = root / "alias"
    alias.symlink_to(repo)
    result = run("link", "PROJ-demo", "--vault-root", str(vault), "--repo", str(alias), "--feature", "F-016")
    assert result.returncode == 0, result.stderr
    commit = calls()[-1]["args"]
    assert json.loads(commit[4])["release_repo"] == str(repo.resolve())


def test_link_invalid_message_names_failed_check(setup):
    root, _, vault, _, _, run, _ = setup
    worktree = root / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: x")
    (worktree / ".release.json").write_text("{}")
    result = run("link", "PROJ-demo", "--vault-root", str(vault), "--repo", str(worktree), "--feature", "F-016")
    assert result.returncode != 0
    assert ".git is not a directory" in result.stderr


def test_dash_project_id_is_rejected_not_read_as_flag(setup):
    _, _, vault, _, _, run, calls = setup
    result = run("show", "--", "-rf", "--vault-root", str(vault))
    assert result.returncode != 0
    assert calls() == []
