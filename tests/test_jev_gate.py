import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from unittest import mock
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
JEV_GATE = BIN_DIR / "jev-gate"
STUB_DIR = str(Path(__file__).resolve().parent / "fixtures" / "typesafe_stub")
# Hermetic env: stub typesafe_sdk + dummy key (no network, no host ~/.zshrc dependence).
STUB_ENV = {**os.environ, "PYTHONPATH": STUB_DIR + os.pathsep + os.environ.get("PYTHONPATH", ""), "TYPESAFE_API_KEY": "stub"}
PY_BIN = "/opt/homebrew/bin/python3" if os.path.exists("/opt/homebrew/bin/python3") else sys.executable


class TestJevGate(unittest.TestCase):
    def test_help_runs(self):
        res = subprocess.run([PY_BIN, str(JEV_GATE), "--help"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("classify-task", res.stdout)
        self.assertIn("triage-diff", res.stdout)
        self.assertIn("triage-spec", res.stdout)

    def test_classify_task_mechanical_vs_risky(self):
        # 1. Mechanical test task -> high confidence agy_flash
        res1 = subprocess.run(
            [
                PY_BIN,
                str(JEV_GATE),
                "classify-task",
                "--prompt",
                "Run pytest tests/test_handoff_usage.py and fix the assertion typo on line 42",
            ],
            capture_output=True,
            text=True,
            env=STUB_ENV,
        )
        self.assertEqual(res1.returncode, 0)
        data1 = json.loads(res1.stdout)
        self.assertIn("route", data1)
        self.assertEqual(data1["route"], "agy_flash")
        self.assertGreaterEqual(data1["route_confidence"], 0.85)
        self.assertLess(data1["risky_surface_prob"], 0.35)

        # 2. Risky security/SSO/migration review -> escalates to agy_argon / claude_opus
        res2 = subprocess.run(
            [
                PY_BIN,
                str(JEV_GATE),
                "classify-task",
                "--prompt",
                "Audit the Joymify SSO JWT token validation and Postgres migration lock for auth bypass vulnerabilities",
            ],
            capture_output=True,
            text=True,
            env=STUB_ENV,
        )
        self.assertEqual(res2.returncode, 0)
        data2 = json.loads(res2.stdout)
        self.assertIn(data2["route"], ("agy_argon", "claude_opus"))

    def test_dispatch_worker_route_with_jev(self):
        loader = importlib.machinery.SourceFileLoader("dispatch_worker", str(BIN_DIR / "dispatch-agy-worker"))
        spec = importlib.util.spec_from_loader("dispatch_worker", loader)
        dw = importlib.util.module_from_spec(spec)
        loader.exec_module(dw)

        with mock.patch.dict(os.environ, STUB_ENV):
            self._assert_routes(dw)

    def _assert_routes(self, dw):
        res_mech = dw.route_with_jev("Run pytest tests/test_simple.py and fix typo")
        self.assertIsNotNone(res_mech)
        self.assertEqual(res_mech.get("route"), "agy_flash")

        res_risk = dw.route_with_jev("Audit the Joymify SSO JWT token validation for auth bypass vulnerabilities")
        self.assertIsNotNone(res_risk)
        self.assertIn(res_risk.get("route"), ("agy_argon", "claude_opus"))

        res_scout = dw.route_with_jev("Strictly read-only scouting: locate which file defines check_quota and list line numbers (make zero file edits)")
        self.assertIsNotNone(res_scout)
        self.assertEqual(res_scout.get("route"), "agy_flash")
        self.assertIn("is_scouting_prob", res_scout)
        self.assertIn(res_scout.get("recommended_effort"), ("low", "medium", "high"))


if __name__ == "__main__":
    unittest.main()
