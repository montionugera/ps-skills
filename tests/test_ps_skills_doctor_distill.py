#!/usr/bin/env python3
"""bin/ps-skills-doctor save-side vault checks (I-040): Jev key, cron line, last vault-distill run."""
import importlib.machinery
import importlib.util
import json as _json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

DOCTOR_SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "ps-skills-doctor"


def _load_doctor():
    loader = importlib.machinery.SourceFileLoader("ps_skills_doctor", str(DOCTOR_SCRIPT))
    spec = importlib.util.spec_from_loader("ps_skills_doctor", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestVaultDistillCheck(unittest.TestCase):
    """Save-side readiness (I-040): Jev key, cron line, last run age and exit code."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("VAULT_ROOT", None)
        os.environ.pop("TYPESAFE_API_KEY", None)
        self.doctor = _load_doctor()
        (self.home / "workspace" / "agentic-vault" / "_meta").mkdir(parents=True)
        self.last = self.home / ".claude" / "state" / "vault-distill" / "last-run.json"
        self.last.parent.mkdir(parents=True)
        self.cron = "40 23 * * * PATH=/usr/bin:/bin ~/.local/bin/vault-distill\n"

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_check(self, crontab):
        issues, warnings = [], []
        self.doctor.check_vault_distill(self.home, issues, warnings, crontab=crontab)
        return issues, warnings

    def record(self, hours_ago, code=0):
        self.last.write_text(_json.dumps({"ts": time.time() - hours_ago * 3600, "exit": code, "report": "r.md"}))

    def test_healthy(self):
        os.environ["TYPESAFE_API_KEY"] = "k"
        self.record(2)
        self.assertEqual(self.run_check(self.cron), ([], []))

    def test_key_in_zshrc_counts(self):
        (self.home / ".zshrc").write_text('export TYPESAFE_API_KEY="abc"\n')
        self.record(2)
        self.assertEqual(self.run_check(self.cron), ([], []))

    def test_missing_key_is_a_warning(self):
        (self.home / ".zshrc").write_text("export TYPESAFE_API_KEY=$FROM_ELSEWHERE\n")
        self.record(2)
        issues, warnings = self.run_check(self.cron)
        self.assertEqual(issues, [])
        self.assertTrue(any("no Jev key" in w for w in warnings), warnings)

    def test_no_cron_line_is_a_warning(self):
        os.environ["TYPESAFE_API_KEY"] = "k"
        issues, warnings = self.run_check("55 23 * * * other-job\n")
        self.assertEqual(issues, [])
        self.assertTrue(any("no cron line" in w for w in warnings), warnings)

    def test_cron_without_a_run_is_a_warning(self):
        os.environ["TYPESAFE_API_KEY"] = "k"
        issues, warnings = self.run_check(self.cron)
        self.assertEqual(issues, [])
        self.assertTrue(any("no run is recorded" in w for w in warnings), warnings)

    def test_stale_run_is_an_issue(self):
        os.environ["TYPESAFE_API_KEY"] = "k"
        self.record(40)
        issues, _ = self.run_check(self.cron)
        self.assertTrue(any("40 hours ago" in i for i in issues), issues)

    def test_degraded_run_is_a_warning(self):
        os.environ["TYPESAFE_API_KEY"] = "k"
        self.record(2, code=2)
        issues, warnings = self.run_check(self.cron)
        self.assertEqual(issues, [])
        self.assertTrue(any("exited 2" in w for w in warnings), warnings)

    def test_no_vault_is_skipped(self):
        shutil.rmtree(self.home / "workspace")
        self.assertEqual(self.run_check(""), ([], []))


if __name__ == "__main__":
    unittest.main()
