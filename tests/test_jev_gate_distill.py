#!/usr/bin/env python3
"""bin/jev-gate subcommands for vault-distill (I-040): classify-lesson, score-draft, same-lesson."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
JEV_GATE = BIN_DIR / "jev-gate"
STUB_DIR = str(Path(__file__).resolve().parent / "fixtures" / "typesafe_stub")
# Hermetic env: the stub typesafe_sdk answers JEV_<NAME>=<p> markers (no network, no host ~/.zshrc).
STUB_ENV = {**os.environ, "PYTHONPATH": STUB_DIR + os.pathsep + os.environ.get("PYTHONPATH", "")}
PY_BIN = "/opt/homebrew/bin/python3" if os.path.exists("/opt/homebrew/bin/python3") else sys.executable


class TestJevGateVaultDistill(unittest.TestCase):
    """classify-lesson, score-draft and same-lesson (I-040): output shape and fail-open."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.home = self.dir / "home"
        (self.home / ".claude").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text)
        return str(path)

    def run_gate(self, *args, key="stub"):
        env = {**STUB_ENV, "HOME": str(self.home)}
        if key is None:
            env.pop("TYPESAFE_API_KEY", None)
        else:
            env["TYPESAFE_API_KEY"] = key
        res = subprocess.run([PY_BIN, str(JEV_GATE), *args], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_help_lists_new_subcommands(self):
        res = subprocess.run([PY_BIN, str(JEV_GATE), "--help"], capture_output=True, text=True)
        for sub in ("classify-lesson", "score-draft", "same-lesson"):
            self.assertIn(sub, res.stdout)

    def test_classify_lesson_returns_probability(self):
        digest = self.write("d.txt", "user: the gate failed twice JEV_LESSON=0.95\n")
        self.assertEqual(self.run_gate("classify-lesson", "--digest", digest), {"lesson_prob": 0.95, "fallback": False})

    def test_classify_lesson_without_key_falls_back_unsure(self):
        digest = self.write("d.txt", "user: something JEV_LESSON=0.95\n")
        out = self.run_gate("classify-lesson", "--digest", digest, key=None)
        self.assertTrue(out["fallback"])
        self.assertEqual(out["lesson_prob"], 0.5)

    def test_classify_lesson_missing_digest_falls_back(self):
        out = self.run_gate("classify-lesson", "--digest", str(self.dir / "nope.txt"))
        self.assertTrue(out["fallback"])

    def test_score_draft_returns_three_scores(self):
        draft = self.write("draft.md", "# Rule\nJEV_SPECIFIC=0.3 JEV_NOVEL=0.8 JEV_HIGH_STAKES=0.9\n")
        digest = self.write("d.txt", "digest text\n")
        out = self.run_gate("score-draft", "--draft", draft, "--digest", digest)
        self.assertEqual(out, {"specific": 0.3, "novel": 0.8, "high_stakes": 0.9, "fallback": False})

    def test_score_draft_without_key_falls_back(self):
        draft = self.write("draft.md", "# Rule\n")
        digest = self.write("d.txt", "digest\n")
        out = self.run_gate("score-draft", "--draft", draft, "--digest", digest, key=None)
        self.assertEqual(out["fallback"], True)
        self.assertNotIn("specific", out)

    def test_same_lesson_returns_probability(self):
        a = self.write("a.md", "lesson a JEV_SAME_LESSON=0.9\n")
        b = self.write("b.md", "lesson b\n")
        self.assertEqual(self.run_gate("same-lesson", "--a", a, "--b", b), {"same": 0.9, "fallback": False})

    def test_same_lesson_without_key_falls_back(self):
        a = self.write("a.md", "lesson a\n")
        b = self.write("b.md", "lesson b\n")
        out = self.run_gate("same-lesson", "--a", a, "--b", b, key=None)
        self.assertEqual(out, {"same": 0.0, "fallback": True, "error": "TYPESAFE_API_KEY not set"})


if __name__ == "__main__":
    unittest.main()
