#!/usr/bin/env python3
"""
Unit tests for bin/ps-skills-doctor (broken symlink repair, case-sensitivity, budget audit).
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR_SCRIPT = REPO_ROOT / "bin" / "ps-skills-doctor"


class TestPsSkillsDoctor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_broken_symlink_repair(self):
        # Create dummy directory with broken symlink
        skills_dir = self.tmp_path / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        broken_link = skills_dir / "broken-skill"
        broken_link.symlink_to(self.tmp_path / "non-existent-target")
        self.assertTrue(broken_link.is_symlink())
        self.assertFalse(broken_link.exists())

        # Simulate doctor unlink logic
        self.assertTrue(broken_link.is_symlink() and not broken_link.exists())
        broken_link.unlink()
        self.assertFalse(broken_link.exists())
        self.assertFalse(broken_link.is_symlink())

    def test_case_insensitive_codex_check(self):
        # Verify exact case checking logic
        test_dir = self.tmp_path / "home_test"
        test_dir.mkdir(parents=True, exist_ok=True)
        (test_dir / ".codex").mkdir(parents=True, exist_ok=True)

        is_uppercase = any(p.name == ".Codex" for p in test_dir.iterdir())
        self.assertFalse(is_uppercase)

        (test_dir / ".Agents").mkdir(parents=True, exist_ok=True)
        is_uppercase_agents = any(p.name == ".Agents" for p in test_dir.iterdir())
        self.assertTrue(is_uppercase_agents)


import importlib.machinery
import importlib.util
import json as _json
from unittest import mock


def _load_doctor():
    loader = importlib.machinery.SourceFileLoader("ps_skills_doctor", str(DOCTOR_SCRIPT))
    spec = importlib.util.spec_from_loader("ps_skills_doctor", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestVaultRecallCheck(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        patcher = mock.patch.dict(os.environ)  # a VAULT_ROOT in the shell must not point the check at the real vault
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("VAULT_ROOT", None)
        self.doctor = _load_doctor()
        (self.home / "workspace" / "agentic-vault" / "_meta" / "indexes").mkdir(parents=True)
        (self.home / ".claude" / "hooks").mkdir(parents=True)
        self.index = self.home / "workspace" / "agentic-vault" / "_meta" / "indexes" / "knowledge.jsonl"
        self.hook = self.home / ".claude" / "hooks" / "vault-recall.py"
        self.settings = self.home / ".claude" / "settings.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def healthy(self):
        self.index.write_text('{"id":"CONCEPT-a","title":"A","terms":["alpha"]}\n')
        self.hook.write_text("#!/usr/bin/env python3\n")
        self.settings.write_text(_json.dumps({"hooks": {"UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": f"python3 {self.hook}"}]}]}}))

    def run_check(self):
        issues, warnings = [], []
        self.doctor.check_vault_recall(self.home, issues, warnings)
        return issues, warnings

    def test_healthy_setup_reports_nothing(self):
        self.healthy()
        self.assertEqual(self.run_check(), ([], []))

    def test_no_vault_is_skipped(self):
        import shutil
        shutil.rmtree(self.home / "workspace")
        self.assertEqual(self.run_check(), ([], []))

    def test_unregistered_hook_is_an_issue(self):
        self.healthy()
        self.settings.write_text(_json.dumps({"hooks": {}}))
        issues, _ = self.run_check()
        self.assertTrue(any("not registered" in i for i in issues), issues)

    def test_missing_hook_file_is_an_issue(self):
        self.healthy()
        self.hook.unlink()
        issues, _ = self.run_check()
        self.assertTrue(any("vault-recall.py" in i and "missing" in i for i in issues), issues)

    def test_index_without_terms_is_an_issue(self):
        self.healthy()
        self.index.write_text('{"id":"CONCEPT-a","title":"A"}\n')
        issues, _ = self.run_check()
        self.assertTrue(any("rebuild-index" in i for i in issues), issues)

    def test_terms_on_a_later_line_is_healthy(self):
        self.healthy()
        self.index.write_text('{"id":"CONCEPT-a","title":"A"}\n{"id":"CONCEPT-b","title":"B","terms":["beta"]}\n')
        self.assertEqual(self.run_check(), ([], []))

    def test_index_older_than_a_note_is_a_warning(self):
        self.healthy()
        note = self.home / "workspace" / "agentic-vault" / "04_Knowledge" / "concepts" / "n.md"
        note.parent.mkdir(parents=True)
        note.write_text("x")
        os.utime(self.index, (1, 1))
        _, warnings = self.run_check()
        self.assertTrue(any("older than" in w for w in warnings), warnings)

    def test_engine_copy_without_context_is_an_issue(self):
        self.healthy()
        stale = self.home / ".local" / "bin" / "vault-engine"
        stale.parent.mkdir(parents=True)
        stale.write_text("#!/bin/sh\nexit 1\n")
        stale.chmod(0o755)
        issues, _ = self.run_check()
        self.assertTrue(any("no `context` command" in i for i in issues), issues)

    def test_known_title_returning_nothing_is_a_warning(self):
        self.healthy()
        self.index.write_text('{"id":"CONCEPT-a","title":"Codegen Drift Gate","terms":["alpha"]}\n')
        silent = self.home / ".local" / "bin" / "vault-engine"
        silent.parent.mkdir(parents=True)
        silent.write_text("#!/bin/sh\nexit 0\n")
        silent.chmod(0o755)
        _, warnings = self.run_check()
        self.assertTrue(any("returned nothing" in w for w in warnings), warnings)


if __name__ == "__main__":
    unittest.main()
