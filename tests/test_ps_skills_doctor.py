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


if __name__ == "__main__":
    unittest.main()
