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
    def call(self, context, flag_exists=False, pending=(), dirty=False, agy_not_idle=False, delta_blocked=False):
        return hu.stop_would_hand_off(context, threshold=200_000, hard_cap=300_000, flag_exists=flag_exists,
                                      pending=pending, dirty=dirty, agy_not_idle=agy_not_idle,
                                      delta_blocked=delta_blocked)

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

    def test_blocked_by_delta_blocked_below_hard_cap(self):
        self.assertFalse(self.call(250_000, delta_blocked=True))

    def test_hard_cap_overrides_the_safe_point_and_delta_blocked(self):
        self.assertTrue(self.call(300_000, dirty=True, pending=["b1"], agy_not_idle=True, delta_blocked=True))


class StopThresholdsAndDeltaTest(unittest.TestCase):
    def test_default_thresholds(self):
        # AGY default: 380_000 and 520_000
        self.assertEqual(hu.stop_thresholds(is_agy=True), (380_000, 520_000))
        # Claude default: 320_000 and 480_000 (320k * 3 // 2)
        self.assertEqual(hu.stop_thresholds(is_agy=False), (320_000, 480_000))

    def test_env_overrides_thresholds(self):
        import os
        old = os.environ.copy()
        try:
            os.environ["AGY_AUTO_HANDOFF_THRESHOLD"] = "280000"
            self.assertEqual(hu.stop_thresholds(is_agy=True), (280_000, 420_000))
            os.environ["AGY_AUTO_HANDOFF_HARD_CAP"] = "400000"
            self.assertEqual(hu.stop_thresholds(is_agy=True), (280_000, 400_000))
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_min_work_delta(self):
        import os
        old = os.environ.copy()
        try:
            self.assertEqual(hu.min_work_delta(is_agy=True), 100_000)
            self.assertEqual(hu.min_work_delta(is_agy=False), 100_000)
            os.environ["AGY_AUTO_HANDOFF_MIN_DELTA"] = "40000"
            self.assertEqual(hu.min_work_delta(is_agy=True), 40_000)
            os.environ["CLAUDE_AUTO_HANDOFF_MIN_DELTA"] = "50000"
            self.assertEqual(hu.min_work_delta(is_agy=False), 50_000)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_transcript_work_delta_blocked(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / "t.jsonl"
            # Empty / missing
            self.assertEqual(hu.transcript_work_delta_blocked(str(Path(d) / "none"), 250_000, 60_000), (False, 0, 0))

            # 1-turn non-handoff session: should NOT block
            t.write_text(json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 200_000}}}) + "\n")
            blocked, first, delta = hu.transcript_work_delta_blocked(str(t), 220_000, 60_000)
            self.assertFalse(blocked)
            self.assertEqual(first, 200_000)
            self.assertEqual(delta, 20_000)

            # 2 turns non-handoff session, delta < min_delta: BLOCKED
            t.write_text(
                json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 200_000}}}) + "\n" +
                json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 230_000}}}) + "\n"
            )
            blocked, first, delta = hu.transcript_work_delta_blocked(str(t), 230_000, 60_000)
            self.assertTrue(blocked)
            self.assertEqual(first, 200_000)
            self.assertEqual(delta, 30_000)

            # 2 turns non-handoff session, delta >= min_delta: NOT blocked
            blocked, first, delta = hu.transcript_work_delta_blocked(str(t), 265_000, 60_000)
            self.assertFalse(blocked)
            self.assertEqual(first, 200_000)
            self.assertEqual(delta, 65_000)

            # Handoff boot session (user input contains Handoff file:): BLOCKED on turn 1 if delta < 60k
            t.write_text(
                json.dumps({"type": "user", "message": {"content": "Handoff file: /tmp/handoff-123.md"}}) + "\n" +
                json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 240_000}}}) + "\n"
            )
            blocked, first, delta = hu.transcript_work_delta_blocked(str(t), 250_000, 60_000)
            self.assertTrue(blocked)
            self.assertEqual(first, 240_000)
            self.assertEqual(delta, 10_000)

            # Handoff boot with delta >= 60k: NOT blocked
            blocked, first, delta = hu.transcript_work_delta_blocked(str(t), 305_000, 60_000)
            self.assertFalse(blocked)
            self.assertEqual(delta, 65_000)

            # Checkpoint resets first_ctx
            t.write_text(
                json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 240_000}}}) + "\n" +
                json.dumps({"type": "CHECKPOINT", "status": "DONE"}) + "\n" +
                json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 20_000}}}) + "\n" +
                json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 90_000}}}) + "\n"
            )
            blocked, first, delta = hu.transcript_work_delta_blocked(str(t), 90_000, 60_000)
            self.assertFalse(blocked)
            self.assertEqual(first, 20_000)
            self.assertEqual(delta, 70_000)


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

    def test_checkpoint_and_compaction_in_tool_result_or_diff_does_not_reset(self):
        import tempfile, json
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / "t.jsonl"
            lines = [
                # Turn 1: user prompt + assistant launches agent X
                json.dumps({"type": "user", "message": {"content": "start"}}),
                json.dumps({"type": "assistant", "message": {
                    "content": "Async agent launched successfully. agentId: X",
                    "usage": {"input_tokens": 100_000},
                }}),
                # Turn 2: tool result mentioning CHECKPOINT and # Resuming from a compaction inside diff
                json.dumps({"type": "user", "message": {"content": [{
                    "type": "tool_result",
                    "content": "diff --git a/foo b/foo\n+CHECKPOINT\n+# Resuming from a compaction",
                }]}}),
                # Turn 3: assistant discusses the diff
                json.dumps({"type": "assistant", "message": {
                    "content": "I see the CHECKPOINT in your code and # Resuming from a compaction",
                    "usage": {"input_tokens": 150_000},
                }}),
            ]
            t.write_text("\n".join(lines) + "\n")

            # 1. active_transcript_bytes must return the FULL size (not reset after the fake checkpoint)
            full_size = t.stat().st_size
            self.assertEqual(hu.active_transcript_bytes(str(t)), full_size)

            # 2. parse_transcript_usage_and_tasks: running agent X is NOT lost, usage is 150_000
            usage, running, last_text, banner = hu.parse_transcript_usage_and_tasks(str(t))
            self.assertEqual(running, {"X"})
            self.assertIsNotNone(usage)
            self.assertEqual(hu.usage_context(usage), 150_000)

            # 3. transcript_work_delta_blocked: first_ctx is 100_000 (not reset), delta is 50_000
            blocked, first_ctx, delta = hu.transcript_work_delta_blocked(str(t), 150_000, 60_000)
            self.assertTrue(blocked)
            self.assertEqual(first_ctx, 100_000)
            self.assertEqual(delta, 50_000)

            # 4. is_compaction_reset_line directly:
            self.assertFalse(hu.is_compaction_reset_line(lines[2]))
            self.assertFalse(hu.is_compaction_reset_line(lines[3]))
            self.assertTrue(hu.is_compaction_reset_line('{"type": "CHECKPOINT", "step_index": 1}'))
            self.assertTrue(hu.is_compaction_reset_line('{"type": "user", "message": {"content": "# Resuming from a compaction\\nsummary"}}'))
            self.assertTrue(hu.is_compaction_reset_line('{"type": "USER_INPUT", "content": "# Resuming from a compaction\\nsummary"}'))


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

    def test_transcript_last_model_handles_real_multi_sentence_user_settings_change(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / "transcript.jsonl"
            t.write_text(
                json.dumps({"type": "PLANNER_RESPONSE", "model": "gemini-4-argon-medium"}) + "\n" +
                json.dumps({
                    "type": "USER_INPUT",
                    "source": "USER_EXPLICIT",
                    "content": (
                        "<USER_REQUEST>handoff</USER_REQUEST>\n"
                        "<USER_SETTINGS_CHANGE>\n"
                        "The user changed setting `Model Selection` from None to Gemini 4 Carbon (Medium). "
                        "No need to comment on this change if the user doesn't ask about it. "
                        "If reporting what model you are, please use a human readable name instead of the exact string.\n"
                        "</USER_SETTINGS_CHANGE>"
                    ),
                }) + "\n"
            )
            self.assertEqual(hu.transcript_last_model(str(t), is_agy=True), "gemini-4-carbon-medium")


if __name__ == "__main__":
    unittest.main()
