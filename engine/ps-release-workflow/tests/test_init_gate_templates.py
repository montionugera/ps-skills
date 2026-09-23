"""`psrw init` stamps runnable Gate 1 / Gate 2 templates whose empty slots cannot pass silently."""
import os
import re
import subprocess
from pathlib import Path

import pytest

from scripts.init_repo import GATE_TEMPLATES, init_repo

GATE1_SLOTS = ["build_typecheck", "unit_tests", "static_ui_checks"]
GATE2_SLOTS = ["integration_real_datastore", "browser_smoke", "data_reconciliation"]


@pytest.fixture
def initialized(tmp_repo: Path, monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    init_repo(tmp_repo)
    return tmp_repo


def _run(script: Path, **env: str) -> subprocess.CompletedProcess:
    base = {"PATH": os.environ["PATH"], "HOME": str(script.parent)}
    return subprocess.run(
        ["bash", str(script)], cwd=script.parent.parent, env={**base, **env},
        capture_output=True, text=True, timeout=60,
    )


def _fill(script: Path, slot: str, body: str) -> None:
    """Replace the `unfilled` line of one slot with `body`."""
    text = script.read_text()
    pattern = re.compile(rf"(^slot_{slot}\(\) \{{\n(?:.*\n)*?)  unfilled\n", re.M)
    assert pattern.search(text), f"slot_{slot} has no unfilled line"
    script.write_text(pattern.sub(lambda m: m.group(1) + f"  {body}\n", text, count=1))


# --- stamping ---

def test_init_stamps_both_gate_scripts_executable_and_committed(initialized: Path):
    for name in ("precheck.sh", "integration.sh"):
        script = initialized / "scripts" / name
        assert script.is_file()
        assert os.access(script, os.X_OK), f"{name} is not executable"
    tracked = subprocess.run(
        ["git", "ls-files", "scripts"], cwd=initialized, capture_output=True, text=True,
    ).stdout.split()
    assert tracked == ["scripts/integration.sh", "scripts/precheck.sh"]


def test_init_never_overwrites_an_existing_gate_script(tmp_repo: Path, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_repo / "scripts").mkdir()
    mine = tmp_repo / "scripts" / "precheck.sh"
    mine.write_text("#!/bin/sh\necho mine\n")
    init_repo(tmp_repo)
    assert mine.read_text() == "#!/bin/sh\necho mine\n"
    assert (tmp_repo / "scripts" / "integration.sh").is_file()  # the absent one is still stamped


@pytest.mark.parametrize("template", sorted(GATE_TEMPLATES.values()), ids=lambda p: p.name)
def test_templates_are_strict_bash_that_parses(template: Path):
    text = template.read_text()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    assert subprocess.run(["bash", "-n", str(template)]).returncode == 0


def test_templates_label_every_slot():
    gate1 = GATE_TEMPLATES["precheck.sh"].read_text()
    gate2 = GATE_TEMPLATES["integration.sh"].read_text()
    for slot in GATE1_SLOTS:
        assert f"slot_{slot}() {{" in gate1
    for slot in GATE2_SLOTS:
        assert f"slot_{slot}() {{" in gate2
    assert "click every primary control" in gate2
    assert "fail on any page error" in gate2
    assert "row count out == row count in" in gate2
    assert "no hardcoded LIMIT" in gate2


# --- Gate 1: runnable as-is, unfilled slots are loud ---

def test_fresh_gate1_runs_and_names_every_unfilled_slot(initialized: Path):
    proc = _run(initialized / "scripts" / "precheck.sh")
    for slot in GATE1_SLOTS:
        assert f"UNFILLED GATE SLOT: {slot}" in proc.stdout
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_gate1_fails_when_a_filled_slot_fails(initialized: Path):
    script = initialized / "scripts" / "precheck.sh"
    _fill(script, "unit_tests", "false")
    proc = _run(script)
    assert proc.returncode != 0
    assert "FAILED: unit_tests" in proc.stdout


# --- Gate 2: an empty template cannot pass ---

def test_fresh_gate2_fails_and_names_every_unfilled_slot(initialized: Path):
    proc = _run(initialized / "scripts" / "integration.sh", DATABASE_URL="postgres://real/db")
    assert proc.returncode != 0
    for slot in GATE2_SLOTS:
        assert f"UNFILLED GATE SLOT: {slot}" in proc.stdout


def test_gate2_fails_not_skips_when_the_datastore_env_var_is_missing(initialized: Path):
    script = initialized / "scripts" / "integration.sh"
    for slot in GATE2_SLOTS:
        _fill(script, slot, "true")
    proc = _run(script)  # DATABASE_URL deliberately absent
    assert proc.returncode != 0
    assert "DATABASE_URL" in proc.stdout
    assert "FAILED: integration_real_datastore" in proc.stdout


def test_gate2_passes_once_every_slot_is_filled(initialized: Path):
    script = initialized / "scripts" / "integration.sh"
    for slot in GATE2_SLOTS:
        _fill(script, slot, "true")
    proc = _run(script, DATABASE_URL="postgres://real/db")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "UNFILLED" not in proc.stdout


def test_gate2_slot_declared_not_applicable_does_not_fail(initialized: Path):
    script = initialized / "scripts" / "integration.sh"
    _fill(script, "integration_real_datastore", "true")
    _fill(script, "data_reconciliation", "true")
    _fill(script, "browser_smoke", "# n/a: headless service, no UI\n  unfilled")
    proc = _run(script, DATABASE_URL="postgres://real/db")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "n/a" in proc.stdout and "headless service, no UI" in proc.stdout


def test_gate2_na_marker_needs_a_real_reason(initialized: Path):
    script = initialized / "scripts" / "integration.sh"
    _fill(script, "integration_real_datastore", "true")
    _fill(script, "data_reconciliation", "true")
    _fill(script, "browser_smoke", "# n/a: <reason>\n  unfilled")
    proc = _run(script, DATABASE_URL="postgres://real/db")
    assert proc.returncode != 0


def test_gate2_stops_a_slot_at_its_first_failing_command(initialized: Path):
    script = initialized / "scripts" / "integration.sh"
    for slot in GATE2_SLOTS:
        _fill(script, slot, "true")
    _fill_text = script.read_text().replace(
        "slot_data_reconciliation() {\n", "slot_data_reconciliation() {\n  false\n", 1)
    script.write_text(_fill_text)
    proc = _run(script, DATABASE_URL="postgres://real/db")
    assert proc.returncode != 0
    assert "FAILED: data_reconciliation" in proc.stdout


# --- review fix: "unfilled" is detected from the slot source, never from an exit code ---

@pytest.mark.parametrize("name", ["precheck.sh", "integration.sh"])
def test_a_filled_slot_exiting_64_is_a_failure_not_unfilled(initialized: Path, name: str):
    script = initialized / "scripts" / name
    slot = "unit_tests" if name == "precheck.sh" else "browser_smoke"
    _fill(script, slot, "echo REAL_FAILURE; exit 64")
    proc = _run(script, DATABASE_URL="postgres://real/db")
    assert proc.returncode != 0
    assert "REAL_FAILURE" in proc.stdout
    assert f"FAILED: {slot}" in proc.stdout
    assert f"UNFILLED GATE SLOT: {slot}" not in proc.stdout
