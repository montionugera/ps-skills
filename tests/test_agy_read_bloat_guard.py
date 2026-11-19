#!/usr/bin/env python3
"""Tests for skills/handoff/hooks/agy-read-bloat-guard.py (AGY PreToolUse context bloat guard)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image

HOOK = Path(__file__).resolve().parent.parent / "skills" / "handoff" / "hooks" / "agy-read-bloat-guard.py"


class AgyReadBloatGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cache_dir = self.dir / "cache"
        self.cache_dir.mkdir(mode=0o700)

    def run_guard(self, payload, env=None):
        full_env = os.environ.copy()
        full_env["AGY_IMAGE_DOWNSCALE_CACHE_DIR"] = str(self.cache_dir)
        if env:
            full_env.update(env)
        data = json.dumps(payload) if isinstance(payload, dict) else str(payload)
        r = subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True, text=True, env=full_env, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_unbounded_transcript_is_denied(self):
        logs_dir = self.dir / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        t = logs_dir / "transcript.jsonl"
        t.write_text("x" * 30_000)

        payload = {
            "toolCall": {
                "name": "read_file",
                "args": {"Path": str(t)},
            }
        }
        r = self.run_guard(payload)
        res = json.loads(r.stdout)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("Context bloat guard: reading raw transcript JSONL", res.get("reason", ""))
        self.assertIn("transcript.jsonl", res.get("reason", ""))

    def test_wide_window_transcript_is_denied(self):
        t = self.dir / "transcript_full.jsonl"
        t.write_text("x" * 30_000)

        payload = {
            "toolCall": {
                "name": "read_file",
                "args": {"Path": str(t), "StartLine": 1, "EndLine": 120},
            }
        }
        r = self.run_guard(payload)
        res = json.loads(r.stdout)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("Context bloat guard: reading raw transcript JSONL", res.get("reason", ""))

    def test_narrow_window_transcript_is_allowed(self):
        t = self.dir / "transcript.jsonl"
        t.write_text("x" * 30_000)

        payload = {
            "toolCall": {
                "name": "read_file",
                "args": {"Path": str(t), "StartLine": 10, "EndLine": 70},
            }
        }
        r = self.run_guard(payload)
        self.assertEqual(r.stdout, "")

    def test_window_boundary_80_vs_81_inclusive(self):
        t = self.dir / "transcript.jsonl"
        t.write_text("x" * 30_000)

        # 1 to 80 is 80 lines inclusive -> allowed (empty stdout)
        r80 = self.run_guard({
            "toolCall": {
                "name": "read_file",
                "args": {"Path": str(t), "StartLine": 1, "EndLine": 80},
            }
        })
        self.assertEqual(r80.stdout, "")

        # 1 to 81 is 81 lines inclusive -> denied
        r81 = self.run_guard({
            "toolCall": {
                "name": "read_file",
                "args": {"Path": str(t), "StartLine": 1, "EndLine": 81},
            }
        })
        res81 = json.loads(r81.stdout)
        self.assertEqual(res81.get("decision"), "deny")

        # Booleans reject
        rbool = self.run_guard({
            "toolCall": {
                "name": "read_file",
                "args": {"Path": str(t), "StartLine": True, "EndLine": True},
            }
        })
        res_bool = json.loads(rbool.stdout)
        self.assertEqual(res_bool.get("decision"), "deny")

    def test_symlinked_transcript_is_denied(self):
        logs_dir = self.dir / "real_dir" / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        real_t = logs_dir / "transcript.jsonl"
        real_t.write_text("x" * 30_000)

        symlink_path = self.dir / "innocent_symlink.txt"
        symlink_path.symlink_to(real_t)

        payload = {
            "toolCall": {
                "name": "read_file",
                "args": {"Path": str(symlink_path)},
            }
        }
        r = self.run_guard(payload)
        res = json.loads(r.stdout)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("transcript.jsonl", res.get("reason", ""))

    def test_small_transcript_is_allowed(self):
        t = self.dir / "transcript.jsonl"
        t.write_text("x" * 10_000)

        payload = {
            "toolCall": {
                "name": "read_file",
                "args": {"Path": str(t)},
            }
        }
        r = self.run_guard(payload)
        self.assertEqual(r.stdout, "")

    def test_non_transcript_file_is_allowed(self):
        code_file = self.dir / "huge_script.py"
        code_file.write_text("x" * 50_000)

        payload = {
            "toolCall": {
                "name": "read_file",
                "args": {"Path": str(code_file)},
            }
        }
        r = self.run_guard(payload)
        self.assertEqual(r.stdout, "")

    def test_oversized_image_is_downscaled_and_overwritten(self):
        if not shutil.which("sips"):
            self.skipTest("sips not available on this system")

        img_path = self.dir / "large_screenshot.png"
        img = Image.new("RGB", (2000, 1500), color="blue")
        img.save(img_path)

        payload = {
            "toolCall": {
                "name": "read_file",
                "args": {"Path": str(img_path)},
            }
        }
        r = self.run_guard(payload)
        res = json.loads(r.stdout)
        self.assertEqual(res.get("decision"), "allow")
        self.assertIn("Context guard: downscaled large_screenshot.png", res.get("reason", ""))
        self.assertIn("overwrite", res)
        overwritten_path = res["overwrite"].get("Path")
        self.assertTrue(overwritten_path and os.path.isfile(overwritten_path))
        self.assertNotEqual(str(img_path), overwritten_path)

        # Verify downscaled image dimensions
        with Image.open(overwritten_path) as down_img:
            w, h = down_img.size
            self.assertTrue(w <= 1024 and h <= 1024)
            self.assertEqual(w, 1024)
            self.assertEqual(h, 768)

        # Repeated read uses cached metadata
        r2 = self.run_guard(payload)
        res2 = json.loads(r2.stdout)
        self.assertEqual(res2.get("decision"), "allow")
        self.assertEqual(res2["overwrite"].get("Path"), overwritten_path)

    def test_cached_image_dynamic_path_key_view_file_then_read_file(self):
        if not shutil.which("sips"):
            self.skipTest("sips not available on this system")

        img_path = self.dir / "dynamic_key.png"
        Image.new("RGB", (1800, 1200), color="purple").save(img_path)

        # 1. First call uses view_file with AbsolutePath
        payload_view = {
            "toolCall": {
                "name": "view_file",
                "args": {"AbsolutePath": str(img_path)},
            }
        }
        r1 = self.run_guard(payload_view)
        res1 = json.loads(r1.stdout)
        self.assertEqual(res1.get("decision"), "allow")
        self.assertIn("AbsolutePath", res1.get("overwrite", {}))
        self.assertNotIn("Path", res1.get("overwrite", {}))
        cached_file = res1["overwrite"]["AbsolutePath"]

        # 2. Second call uses read_file with Path -> MUST emit overwrite: {"Path": ...}
        payload_read = {
            "toolCall": {
                "name": "read_file",
                "args": {"Path": str(img_path)},
            }
        }
        r2 = self.run_guard(payload_read)
        res2 = json.loads(r2.stdout)
        self.assertEqual(res2.get("decision"), "allow")
        self.assertIn("Path", res2.get("overwrite", {}))
        self.assertNotIn("AbsolutePath", res2.get("overwrite", {}))
        self.assertEqual(res2["overwrite"]["Path"], cached_file)

    def test_image_within_budget_is_not_downscaled(self):
        if not shutil.which("sips"):
            self.skipTest("sips not available on this system")

        img_path = self.dir / "small_icon.png"
        img = Image.new("RGB", (400, 300), color="red")
        img.save(img_path)

        payload = {
            "toolCall": {
                "name": "read_file",
                "args": {"Path": str(img_path)},
            }
        }
        r = self.run_guard(payload)
        self.assertEqual(r.stdout, "")

    def test_kill_switches(self):
        t = self.dir / "transcript.jsonl"
        t.write_text("x" * 30_000)
        r_guard = self.run_guard({"toolCall": {"name": "read_file", "args": {"Path": str(t)}}}, env={"AGY_READ_GUARD": "0"})
        self.assertEqual(r_guard.stdout, "")

        if shutil.which("sips"):
            img_path = self.dir / "large.png"
            Image.new("RGB", (2000, 1500), color="green").save(img_path)
            r_img = self.run_guard({"toolCall": {"name": "read_file", "args": {"Path": str(img_path)}}}, env={"AGY_IMAGE_DOWNSCALE": "0"})
            self.assertEqual(r_img.stdout, "")

    def test_supports_view_file_and_absolute_path_key(self):
        t = self.dir / "transcript.jsonl"
        t.write_text("x" * 30_000)

        payload = {
            "toolCall": {
                "name": "view_file",
                "args": {"AbsolutePath": str(t)},
            }
        }
        r = self.run_guard(payload)
        res = json.loads(r.stdout)
        self.assertEqual(res.get("decision"), "deny")

    def test_invalid_and_empty_payloads_fail_open(self):
        for bad in ("", "{}", "[]", "null", "garbage", {"toolCall": {}}, {"toolCall": {"name": "run_command"}}):
            r = self.run_guard(bad)
            self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
