#!/usr/bin/env python3
"""Tests for skills/handoff/hooks/auto-handoff-midturn.py (PreToolUse mid-turn context check)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "skills" / "handoff" / "hooks" / "auto-handoff-midturn.py"


class MidturnTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.session = f"t-{uuid.uuid4().hex}"
        self.transcript = self.dir / "t.jsonl"
        self.log = self.dir / "log.jsonl"

    def write(self, *tokens, extra=()):
        lines = [json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": t}}}) for t in tokens]
        self.transcript.write_text("\n".join(list(lines) + list(extra)) + "\n")

    def run_hook(self, notices=True, stdin=None, **payload):
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_AUTO_HANDOFF")}
        env.update({"CLAUDE_AUTO_HANDOFF_STATE_DIR": str(self.dir), "CLAUDE_AUTO_HANDOFF_LOG": str(self.log)})
        if notices:
            env["CLAUDE_AUTO_HANDOFF_NOTICES"] = "1"
        data = stdin if stdin is not None else json.dumps(
            {"session_id": self.session, "transcript_path": str(self.transcript), **payload})
        r = subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")
        return json.loads(r.stdout) if r.stdout.strip() else None

    def test_advisor_iteration_is_not_double_counted(self):
        # top-level totals sum three iterations (~256k); the real context is the last message (129140)
        usage = {"input_tokens": 4, "cache_read_input_tokens": 250165, "cache_creation_input_tokens": 3300,
                 "iterations": [
                     {"type": "message", "input_tokens": 2, "cache_read_input_tokens": 123000, "cache_creation_input_tokens": 1000},
                     {"type": "advisor_message", "input_tokens": 127338},
                     {"type": "message", "input_tokens": 2, "cache_read_input_tokens": 126985, "cache_creation_input_tokens": 2153}]}
        self.transcript.write_text(json.dumps({"type": "assistant", "message": {"usage": usage}}) + "\n")
        self.assertIsNone(self.run_hook())
        self.assertFalse(self.log.exists())

    def test_note_never_promises_a_handoff(self):
        self.write(260_000)
        note = self.run_hook()["hookSpecificOutput"]["additionalContext"]
        self.assertIn("The Stop hook decides whether a handoff runs", note)
        self.assertIn("Do not tell the owner a handoff, new tab or tab close is happening", note)

    def test_under_lowest_level_is_silent(self):
        self.write(100_000)
        self.assertIsNone(self.run_hook())
        self.assertFalse(self.log.exists())

    def test_notice_once_per_level_then_next_level(self):
        self.write(260_000)
        out = self.run_hook()
        self.assertIn("260000", out["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.run_hook())
        self.write(260_000, 310_000)
        self.assertIn("past 300000", self.run_hook()["hookSpecificOutput"]["additionalContext"])

    def test_notices_off_by_default_logs_only(self):
        self.write(260_000)
        self.assertIsNone(self.run_hook(notices=False))
        self.assertTrue(self.log.exists())
        self.assertTrue((self.dir / f"claude-auto-handoff-{self.session}.midturn.dry").exists())
        self.assertFalse((self.dir / f"claude-auto-handoff-{self.session}.midturn").exists())

    def test_subagent_call_ignored(self):
        self.write(260_000)
        self.assertIsNone(self.run_hook(agent_id="a1"))

    def test_sidechain_and_zero_usage_skipped(self):
        side = json.dumps({"type": "assistant", "isSidechain": True, "message": {"usage": {"input_tokens": 900_000}}})
        zero = json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 0}}})
        self.write(100_000, extra=(side, zero))
        self.assertIsNone(self.run_hook())

    def test_kill_switch(self):
        self.write(260_000)
        env_out = subprocess.run(
            [sys.executable, str(HOOK)], capture_output=True, text=True, timeout=30,
            input=json.dumps({"session_id": self.session, "transcript_path": str(self.transcript)}),
            env={**os.environ, "CLAUDE_AUTO_HANDOFF": "0", "CLAUDE_AUTO_HANDOFF_NOTICES": "1",
                 "CLAUDE_AUTO_HANDOFF_STATE_DIR": str(self.dir), "CLAUDE_AUTO_HANDOFF_LOG": str(self.log)})
        self.assertEqual(env_out.stdout, "")

    def test_bad_input_never_breaks(self):
        for stdin in ("", "garbage", "[]", "null", json.dumps({"transcript_path": "/nonexistent"}),
                      json.dumps({"transcript_path": str(self.dir)})):
            self.assertIsNone(self.run_hook(stdin=stdin))

    def test_huge_line_in_tail(self):
        self.write(260_000, extra=("x" * (5 << 20),))
        self.assertIsNone(self.run_hook())  # newest usage is out of the tail: silent, no crash or hang

    def test_session_id_cannot_escape_state_dir(self):
        self.write(260_000)
        self.run_hook(session_id="../../escaped")
        self.assertFalse((self.dir.parent / "escaped.midturn").exists())
        self.assertTrue(any(p.name.startswith("claude-auto-handoff-") for p in self.dir.iterdir()))

    def test_agy_preinvocation_emits_inject_steps_ephemeral_message(self):
        conv_id = f"agy-mid-{uuid.uuid4().hex}"
        app_dir = self.dir / "agy-app"
        logs_dir = app_dir / "brain" / conv_id / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        # 560,000 bytes -> 140,000 tokens (passes AGY 100k & 128k levels)
        (logs_dir / "transcript_full.jsonl").write_text("m" * 560_000)

        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_AUTO_HANDOFF", "AGY_AUTO_HANDOFF"))}
        env.update({
            "CLAUDE_AUTO_HANDOFF_STATE_DIR": str(self.dir),
            "CLAUDE_AUTO_HANDOFF_LOG": str(self.log),
            "AGY_APP_DATA_DIR": str(app_dir),
        })
        payload = {"conversationId": conv_id, "workspacePaths": [str(self.dir)]}
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertIn("injectSteps", out)
        self.assertIn("past 128000", out["injectSteps"][0]["ephemeralMessage"])

        # Second invocation at same level returns empty object "{}"
        r2 = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(json.loads(r2.stdout), {})


    def test_agy_preinvocation_ignores_preallocated_db_wal_when_transcript_exists(self):
        conv_id = f"agy-mid-prec-{uuid.uuid4().hex}"
        app_dir = self.dir / "agy-app-prec"
        logs_dir = app_dir / "brain" / conv_id / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        # 20 KB compact transcript (~5,000 tokens, below 100k level)
        (logs_dir / "transcript.jsonl").write_text("m" * 20_000)
        conv_dir = app_dir / "conversations"
        conv_dir.mkdir(parents=True)
        # 491,520 bytes SQLite WAL pre-allocation (would be 122,880 tokens if not ignored)
        (conv_dir / f"{conv_id}.db").write_bytes(b"d" * 491_520)
        (conv_dir / f"{conv_id}.db-wal").write_bytes(b"w" * 491_520)

        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_AUTO_HANDOFF", "AGY_AUTO_HANDOFF"))}
        env.update({
            "CLAUDE_AUTO_HANDOFF_STATE_DIR": str(self.dir),
            "CLAUDE_AUTO_HANDOFF_LOG": str(self.log),
            "AGY_APP_DATA_DIR": str(app_dir),
        })
        payload = {"conversationId": conv_id, "transcriptPath": str(conv_dir / f"{conv_id}.db"), "workspacePaths": [str(self.dir)]}
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {})


if __name__ == "__main__":
    unittest.main()

