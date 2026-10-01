#!/usr/bin/env python3
"""
Tests for skills/handoff/hooks/auto-handoff-stop.py, the Stop hook that forces a
handoff once a session's context passes a threshold.

The hook is run as a subprocess against a temp transcript and a temp git repo.
Nothing here starts an agent or a Herdr tab.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "skills" / "handoff" / "hooks" / "auto-handoff-stop.py"

# The launch lines are built from pieces so that a session which merely reads this
# file does not look, to the hook, as if it had launched these tasks.
AGENT_ID = "agent" + "Id: "
LAUNCH_AGENT = "Async agent launched " + "successfully. (internal metadata)\n" + AGENT_ID + "a1b2c3d4e5 (internal ID)"
FOREGROUND_AGENT = "Done.\n" + AGENT_ID + "f0f0f0f0 (use SendMessage with to: 'f0f0f0f0' to continue this agent)"
LAUNCH_BASH = "Command running in " + "background with ID: bj91cspfy. Output is being written to: /tmp/x"
MOVED_BASH = "Command did not complete within its 600s timeout and was moved to the " + "background (ID: b8kyw9n9a)."

# Keep the temp repo and the hook's own git call away from the developer's git setup.
GIT_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
GIT_ENV.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})


def notification(task_id, status="completed"):
    return f"<task-notification>\n<task-" + f"id>{task_id}</task-id>\n<status>{status}</status>\n</task-notification>"


class AutoHandoffStopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        (self.repo / "tracked.txt").write_text("one\n")
        self.git("add", "tracked.txt")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init")
        self.session = f"test-{uuid.uuid4().hex}"
        self.flag = Path("/tmp") / f"claude-auto-handoff-{self.session}.flag"
        self.addCleanup(lambda: self.flag.unlink(missing_ok=True))

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, env=GIT_ENV)

    def run_hook(self, tokens, texts=(), env=None, cwd=None):
        """Runs the hook on a transcript holding texts, then one assistant turn of `tokens`."""
        transcript = Path(self.tmp.name) / "transcript.jsonl"
        lines = [json.dumps({"type": "user", "message": {"content": t}}) for t in texts]
        lines.append(json.dumps({"type": "assistant", "message": {"usage": {
            "input_tokens": 1000, "cache_read_input_tokens": tokens - 1000, "cache_creation_input_tokens": 0,
        }}}))
        transcript.write_text("\n".join(lines) + "\n")
        full_env = {k: v for k, v in GIT_ENV.items() if not k.startswith("CLAUDE_AUTO_HANDOFF")}
        full_env.update(env or {})
        out = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps({"transcript_path": str(transcript), "session_id": self.session, "cwd": cwd or str(self.repo)}),
            capture_output=True, text=True, env=full_env, timeout=30,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout) if out.stdout.strip() else None

    def assertFires(self, result):
        self.assertIsNotNone(result, "hook stayed silent, want a block")
        self.assertEqual(result["decision"], "block")
        self.assertIn("AUTO-HANDOFF", result["reason"])
        self.assertTrue(self.flag.exists(), "a fired hook writes its one-shot flag")

    def assertWaits(self, result):
        self.assertIsNone(result, "hook fired, want it to wait")
        self.assertFalse(self.flag.exists(), "a waiting hook must not use up its one shot")

    def test_under_threshold_is_silent(self):
        self.assertWaits(self.run_hook(199_999))

    def test_over_threshold_at_a_safe_point_fires(self):
        self.assertFires(self.run_hook(200_000))

    def test_fires_once_per_session(self):
        self.assertFires(self.run_hook(200_000))
        self.assertIsNone(self.run_hook(210_000))

    def test_waits_while_a_background_agent_is_running(self):
        self.assertWaits(self.run_hook(210_000, [LAUNCH_AGENT]))

    def test_waits_while_a_background_command_is_running(self):
        self.assertWaits(self.run_hook(210_000, [LAUNCH_BASH]))

    def test_fires_once_background_work_has_finished(self):
        texts = [LAUNCH_AGENT, LAUNCH_BASH, notification("a1b2c3d4e5"), notification("bj91cspfy")]
        self.assertFires(self.run_hook(210_000, texts))

    def test_waits_when_only_some_background_work_has_finished(self):
        self.assertWaits(self.run_hook(210_000, [LAUNCH_AGENT, LAUNCH_BASH, notification("a1b2c3d4e5")]))

    def test_waits_on_uncommitted_tracked_changes(self):
        (self.repo / "tracked.txt").write_text("two\n")
        self.assertWaits(self.run_hook(210_000))

    def test_untracked_files_do_not_block(self):
        (self.repo / "scratch.html").write_text("x")
        self.assertFires(self.run_hook(210_000))

    def test_hard_cap_fires_even_when_not_at_a_safe_point(self):
        (self.repo / "tracked.txt").write_text("two\n")
        self.assertFires(self.run_hook(300_000, [LAUNCH_AGENT]))

    def test_just_under_the_hard_cap_still_waits(self):
        self.assertWaits(self.run_hook(299_999, [LAUNCH_AGENT]))

    def test_hard_cap_follows_env(self):
        env = {"CLAUDE_AUTO_HANDOFF_HARD_CAP": "220000"}
        self.assertFires(self.run_hook(220_000, [LAUNCH_AGENT], env))

    def test_a_foreground_agent_result_is_not_background_work(self):
        self.assertFires(self.run_hook(210_000, [FOREGROUND_AGENT]))

    def test_waits_on_a_command_moved_to_the_background_by_its_timeout(self):
        self.assertWaits(self.run_hook(210_000, [MOVED_BASH]))
        self.assertFires(self.run_hook(210_000, [MOVED_BASH, notification("b8kyw9n9a")]))

    def test_a_failed_or_killed_task_counts_as_finished(self):
        texts = [LAUNCH_AGENT, LAUNCH_BASH, notification("a1b2c3d4e5", "failed"), notification("bj91cspfy", "killed")]
        self.assertFires(self.run_hook(210_000, texts))

    def test_a_hyphenated_task_id_is_matched_whole(self):
        launch = LAUNCH_BASH.replace("bj91cspfy", "bj91-cspfy")
        self.assertWaits(self.run_hook(210_000, [launch, notification("bj91")]))
        self.assertFires(self.run_hook(210_000, [launch, notification("bj91-cspfy")]))

    def test_a_cwd_that_is_not_a_git_checkout_does_not_block(self):
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        self.assertFires(self.run_hook(210_000, cwd=str(plain)))

    def test_a_missing_cwd_does_not_block(self):
        self.assertFires(self.run_hook(210_000, cwd=str(Path(self.tmp.name) / "gone")))

    def test_non_numeric_settings_fall_back_to_the_defaults(self):
        env = {"CLAUDE_AUTO_HANDOFF_THRESHOLD": "abc", "CLAUDE_AUTO_HANDOFF_HARD_CAP": "xyz"}
        self.assertWaits(self.run_hook(199_999, env=env))
        self.assertWaits(self.run_hook(299_999, [LAUNCH_AGENT], env))
        self.assertFires(self.run_hook(300_000, [LAUNCH_AGENT], env))

    def test_disabled(self):
        self.assertIsNone(self.run_hook(400_000, env={"CLAUDE_AUTO_HANDOFF": "0"}))


if __name__ == "__main__":
    unittest.main()
