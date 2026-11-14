"""A lapsed agy OAuth login must make check_quota refuse agy, not report stale quota as healthy."""
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "bin" / "dispatch-agy-worker"
_EVENTS_TMP = tempfile.TemporaryDirectory()
os.environ["DISPATCH_EVENTS_FILE"] = str(Path(_EVENTS_TMP.name) / "events.jsonl")
loader = importlib.machinery.SourceFileLoader("dispatch_agy_worker_auth", str(SCRIPT_PATH))
spec = importlib.util.spec_from_loader("dispatch_agy_worker_auth", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

AUTH_FAIL = {"event": "result", "result": {"status": "ERROR", "error": "authentication failed or timed out", "num_turns": 0}}


class TestAgyAuth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "agy").mkdir()
        self.token = d / "agy" / "token"
        self.token.write_text("{}")
        self.marker = d / "state" / "agy-auth-failed"
        self.state = d / "obs.json"
        self.state.write_text(json.dumps({"rem_5h": 90, "rem_weekly": 90}))
        self.patches = [mock.patch.object(mod, "AGY_TOKEN_FILE", str(self.token)),
                        mock.patch.object(mod, "AGY_AUTH_MARKER", str(self.marker))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_auth_failed_result_blocks_check_quota(self):
        old = time.time() - 60
        os.utime(self.token, (old, old))
        cmd = ["python3", "-c", f"import json;print(json.dumps({AUTH_FAIL!r}))"]
        mod.execute_worker_process(cmd, ".", 10, stream_state={})
        self.assertTrue(self.marker.exists())
        ok, _r5, _rw, msg = mod.check_quota("agy", state_file=str(self.state))
        self.assertFalse(ok)
        self.assertIn("not logged in", msg)

    def test_fresh_login_after_failure_clears_block(self):
        self.marker.parent.mkdir(parents=True)
        self.marker.write_text("x")
        old = time.time() - 60
        os.utime(self.marker, (old, old))
        self.assertFalse(mod.agy_auth_blocked())
        self.assertFalse(self.marker.exists())

    def test_other_errors_and_success_do_not_block(self):
        self.assertFalse(mod.note_agy_auth_failure({"status": "SUCCESS", "error": "authentication"}))
        self.assertFalse(mod.note_agy_auth_failure({"status": "ERROR", "error": "rate limited"}))
        self.assertFalse(self.marker.exists())
        self.assertFalse(mod.agy_auth_blocked())

    def test_missing_token_blocks(self):
        self.token.unlink()
        self.assertTrue(mod.agy_auth_blocked())


if __name__ == "__main__":
    unittest.main()
