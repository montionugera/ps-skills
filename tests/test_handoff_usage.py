#!/usr/bin/env python3
"""Tests for skills/handoff/hooks/handoff_usage.py, the context measure and Stop rules both hooks share."""
import importlib.util
import sys
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parent.parent / "skills" / "handoff" / "hooks" / "handoff_usage.py"
_spec = importlib.util.spec_from_file_location("handoff_usage", MODULE)
hu = importlib.util.module_from_spec(_spec)
sys.modules["handoff_usage"] = hu
_spec.loader.exec_module(hu)

# The real usage block of response req_011CgD1q (session 0396025d, 2026-10-20 13:28):
# message 127,162 -> advisor_message -> message 129,395; top level sums to 256,557.
REQ_011CGD1Q_USAGE = {
    "input_tokens": 4, "cache_creation_input_tokens": 5147, "cache_read_input_tokens": 251406,
    "output_tokens": 1066,
    "iterations": [
        {"input_tokens": 2, "output_tokens": 361, "cache_read_input_tokens": 124246,
         "cache_creation_input_tokens": 2914, "type": "message"},
        {"input_tokens": 129387, "output_tokens": 15145, "cache_read_input_tokens": 0,
         "cache_creation_input_tokens": 0, "type": "advisor_message", "model": "claude-opus-5-5"},
        {"input_tokens": 2, "output_tokens": 705, "cache_read_input_tokens": 127160,
         "cache_creation_input_tokens": 2233, "type": "message"},
    ],
}


class UsageContextTest(unittest.TestCase):
    def test_multi_iteration_record_counts_only_the_last_message_iteration(self):
        self.assertEqual(hu.usage_context(REQ_011CGD1Q_USAGE), 129_395)

    def test_trailing_advisor_iteration_is_skipped(self):
        usage = {
            "input_tokens": 9, "cache_read_input_tokens": 999_999,
            "iterations": [
                {"type": "message", "input_tokens": 1, "cache_read_input_tokens": 100_000,
                 "cache_creation_input_tokens": 500},
                {"type": "advisor_message", "input_tokens": 400_000},
            ],
        }
        self.assertEqual(hu.usage_context(usage), 100_501)

    def test_two_message_iterations_without_advisor(self):
        usage = {
            "input_tokens": 4, "cache_read_input_tokens": 240_000, "cache_creation_input_tokens": 0,
            "iterations": [
                {"type": "message", "input_tokens": 2, "cache_read_input_tokens": 119_000},
                {"type": "message", "input_tokens": 2, "cache_read_input_tokens": 121_000},
            ],
        }
        self.assertEqual(hu.usage_context(usage), 121_002)

    def test_no_iterations_falls_back_to_top_level_sum(self):
        usage = {"input_tokens": 10, "cache_read_input_tokens": 200_000, "cache_creation_input_tokens": 90}
        self.assertEqual(hu.usage_context(usage), 200_100)

    def test_iterations_without_a_message_entry_fall_back_to_top_level_sum(self):
        usage = {"input_tokens": 5, "cache_read_input_tokens": 50, "iterations": [{"type": "advisor_message"}]}
        self.assertEqual(hu.usage_context(usage), 55)

    def test_empty_or_null_fields(self):
        self.assertEqual(hu.usage_context({}), 0)
        self.assertEqual(hu.usage_context(None), 0)
        self.assertEqual(hu.usage_context({"input_tokens": None, "iterations": None}), 0)


class StopWouldHandOffTest(unittest.TestCase):
    def call(self, context, flag_exists=False, pending=(), dirty=False, agy_not_idle=False):
        return hu.stop_would_hand_off(context, threshold=200_000, hard_cap=300_000, flag_exists=flag_exists,
                                      pending=pending, dirty=dirty, agy_not_idle=agy_not_idle)

    def test_over_threshold_at_a_safe_point(self):
        self.assertTrue(self.call(250_000))

    def test_under_threshold(self):
        self.assertFalse(self.call(199_999))

    def test_already_handed_off(self):
        self.assertFalse(self.call(250_000, flag_exists=True))

    def test_blocked_by_dirty_tree_pending_work_or_agy_busy_below_hard_cap(self):
        self.assertFalse(self.call(250_000, dirty=True))
        self.assertFalse(self.call(250_000, pending=["b1"]))
        self.assertFalse(self.call(250_000, agy_not_idle=True))

    def test_hard_cap_overrides_the_safe_point(self):
        self.assertTrue(self.call(300_000, dirty=True, pending=["b1"], agy_not_idle=True))


class ParseTranscriptTest(unittest.TestCase):
    def pending(self, *lines):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.jsonl"
            path.write_text("\n".join(lines) + "\n")
            return hu.parse_transcript_usage_and_tasks(str(path))[1]

    @staticmethod
    def result(text):
        import json
        return json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": text}]}})

    def test_launch_notification_resume_leaves_the_agent_pending(self):
        launch = self.result("Async agent launched successfully.\nagentId: X")
        done = self.result("<task-id>X</task-id> done")
        resume = self.result('{"resumedAgentId":"X"}')
        self.assertEqual(self.pending(launch, done), set())
        self.assertEqual(self.pending(launch, done, resume), {"X"})


class ClaudeLowQuotaTest(unittest.TestCase):
    def test_detects_low_quota_window_and_ignores_expired_windows(self):
        import json, os, tempfile
        with tempfile.TemporaryDirectory() as d:
            snap = {
                "provider": "claude",
                "windows": [
                    {"kind": "five_hour", "remaining_percent": 2.0, "resets_at": 1000},
                    {"kind": "weekly", "remaining_percent": 8.5, "resets_at": 9999999999},
                ],
            }
            (Path(d) / "claude-statusline.json").write_text(json.dumps(snap))
            old_env = os.environ.get("HERDR_PLUGIN_STATE_DIR")
            os.environ["HERDR_PLUGIN_STATE_DIR"] = d
            try:
                low, rem, thr, kind = hu.claude_low_quota(now=2000)
                self.assertTrue(low)
                self.assertEqual(rem, 8.5)
                self.assertEqual(thr, 10.0)
                self.assertEqual(kind, "weekly")
            finally:
                if old_env is None:
                    os.environ.pop("HERDR_PLUGIN_STATE_DIR", None)
                else:
                    os.environ["HERDR_PLUGIN_STATE_DIR"] = old_env

    def test_above_threshold_returns_false(self):
        import json, os, tempfile
        with tempfile.TemporaryDirectory() as d:
            snap = {
                "provider": "claude",
                "windows": [
                    {"kind": "weekly", "remaining_percent": 20.0, "resets_at": 9999999999},
                ],
            }
            (Path(d) / "claude-statusline.json").write_text(json.dumps(snap))
            old_env = os.environ.get("HERDR_PLUGIN_STATE_DIR")
            os.environ["HERDR_PLUGIN_STATE_DIR"] = d
            try:
                low, rem, thr, kind = hu.claude_low_quota(now=2000)
                self.assertFalse(low)
                self.assertEqual(rem, 20.0)
            finally:
                if old_env is None:
                    os.environ.pop("HERDR_PLUGIN_STATE_DIR", None)
                else:
                    os.environ["HERDR_PLUGIN_STATE_DIR"] = old_env


if __name__ == "__main__":
    unittest.main()
