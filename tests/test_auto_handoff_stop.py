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
        self.state_dir = Path(self.tmp.name) / "state"
        self.state_dir.mkdir()
        self.log_path = Path(self.tmp.name) / "auto-handoff.log"
        self.flag = self.state_dir / f"claude-auto-handoff-{self.session}.flag"
        self.addCleanup(lambda: self.flag.unlink(missing_ok=True))

    def tearDown(self):
        # Verify temporary directories were used and no state was leaked to /tmp
        self.assertFalse((Path("/tmp") / f"claude-auto-handoff-{self.session}.flag").exists())
        self.assertFalse((Path("/tmp") / f"claude-auto-handoff-{self.session}.drain").exists())
        self.assertFalse((Path("/tmp") / f"claude-auto-handoff-{self.session}.refire").exists())

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, env=GIT_ENV)

    def run_hook(self, tokens, texts=(), env=None, cwd=None, stop_hook_active=None):
        """Runs the hook on a transcript holding texts, then one assistant turn of `tokens`."""
        transcript = Path(self.tmp.name) / "transcript.jsonl"
        lines = [json.dumps({"type": "user", "message": {"content": t}}) for t in texts]
        lines.append(json.dumps({"type": "assistant", "message": {"usage": {
            "input_tokens": 1000, "cache_read_input_tokens": tokens - 1000, "cache_creation_input_tokens": 0,
        }}}))
        transcript.write_text("\n".join(lines) + "\n")
        full_env = {k: v for k, v in GIT_ENV.items() if not k.startswith("CLAUDE_AUTO_HANDOFF")}
        full_env.setdefault("CLAUDE_AUTO_HANDOFF_STATE_DIR", str(self.state_dir))
        full_env.setdefault("CLAUDE_AUTO_HANDOFF_LOG", str(self.log_path))
        full_env.update(env or {})
        payload = {"transcript_path": str(transcript), "session_id": self.session, "cwd": cwd or str(self.repo)}
        if stop_hook_active is not None:
            payload["stop_hook_active"] = stop_hook_active
        out = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True, text=True, env=full_env, timeout=30,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout) if out.stdout.strip() else None

    def run_hook_raw(self, stdin_text="", env=None):
        full_env = {k: v for k, v in GIT_ENV.items() if not k.startswith("CLAUDE_AUTO_HANDOFF")}
        full_env.setdefault("CLAUDE_AUTO_HANDOFF_STATE_DIR", str(self.state_dir))
        full_env.setdefault("CLAUDE_AUTO_HANDOFF_LOG", str(self.log_path))
        full_env.update(env or {})
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=stdin_text,
            capture_output=True, text=True, env=full_env, timeout=30,
        )

    def read_log(self):
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text().strip().splitlines()
        return [json.loads(line) for line in lines if line.strip()]

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

    def test_notices_off_by_default_writes_log_and_emits_nothing_new(self):
        # Over threshold, but background task running: safe point not reached.
        # With default settings (CLAUDE_AUTO_HANDOFF_NOTICES not set to 1),
        # no message should be emitted (result is None), but a log entry is written.
        res = self.run_hook(210_000, [LAUNCH_AGENT])
        self.assertIsNone(res)
        self.assertFalse(self.flag.exists())
        logs = self.read_log()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["decision"], "drain-notice")
        self.assertEqual(logs[0]["session"], self.session)
        self.assertEqual(logs[0]["context"], 210_000)
        self.assertIn("background=1", logs[0]["why"])

        # Running again with background work still pending emits nothing and does not log again
        res2 = self.run_hook(215_000, [LAUNCH_AGENT])
        self.assertIsNone(res2)
        logs2 = self.read_log()
        self.assertEqual(len(logs2), 1)

    def test_notices_on_emits_drain_notice_once_only(self):
        env = {"CLAUDE_AUTO_HANDOFF_NOTICES": "1"}
        res = self.run_hook(210_000, [LAUNCH_AGENT], env=env)
        self.assertIsNotNone(res)
        self.assertEqual(res["decision"], "block")
        self.assertIn("AUTO-HANDOFF pending", res["reason"])
        self.assertIn("background=1", res["reason"])
        self.assertFalse(self.flag.exists())

        # Calling again while still pending: silent
        res2 = self.run_hook(220_000, [LAUNCH_AGENT], env=env)
        self.assertIsNone(res2)

        # Once background work finishes, handoff fires
        texts = [LAUNCH_AGENT, notification("a1b2c3d4e5")]
        res3 = self.run_hook(225_000, texts, env=env)
        self.assertFires(res3)
        self.assertIn("reached 225000 tokens", res3["reason"])

    def test_drain_notice_on_dirty_tree(self):
        env = {"CLAUDE_AUTO_HANDOFF_NOTICES": "1"}
        (self.repo / "tracked.txt").write_text("modified\n")
        res = self.run_hook(210_000, env=env)
        self.assertIsNotNone(res)
        self.assertEqual(res["decision"], "block")
        self.assertIn("AUTO-HANDOFF pending", res["reason"])
        self.assertIn("dirty_tree=True", res["reason"])
        self.assertFalse(self.flag.exists())

    def test_reminder_repeats_per_25000_growth_and_not_more_often(self):
        env = {"CLAUDE_AUTO_HANDOFF_NOTICES": "1"}
        # Initial handoff fire at safe point
        res = self.run_hook(205_000, env=env)
        self.assertFires(res)

        # Context grows but less than REFIRE_STEP (25,000): silent
        self.assertIsNone(self.run_hook(215_000, env=env))
        self.assertIsNone(self.run_hook(229_999, env=env))

        # Context reaches 230,000 (+25,000): retired reminder emitted
        res2 = self.run_hook(230_000, env=env)
        self.assertIsNotNone(res2)
        self.assertEqual(res2["decision"], "block")
        self.assertIn("retired", res2["reason"])
        self.assertIn("grown to 230000 tokens", res2["reason"])

        # Growth since last fire is less than 25,000: silent
        self.assertIsNone(self.run_hook(240_000, env=env))
        self.assertIsNone(self.run_hook(254_999, env=env))

        # Next step at 255,000 (+25,000 since 230,000): reminder emitted again
        res3 = self.run_hook(255_000, env=env)
        self.assertIsNotNone(res3)
        self.assertEqual(res3["decision"], "block")
        self.assertIn("retired", res3["reason"])
        self.assertIn("grown to 255000 tokens", res3["reason"])

    def test_reminder_follows_refire_step_env(self):
        env = {"CLAUDE_AUTO_HANDOFF_NOTICES": "1", "CLAUDE_AUTO_HANDOFF_REFIRE_STEP": "10000"}
        res = self.run_hook(200_000, env=env)
        self.assertFires(res)

        # +9,000 is under 10,000: silent
        self.assertIsNone(self.run_hook(209_000, env=env))

        # +10,000: reminder emitted
        res2 = self.run_hook(210_000, env=env)
        self.assertIsNotNone(res2)
        self.assertIn("retired", res2["reason"])

    def test_rearm_after_compaction(self):
        env = {"CLAUDE_AUTO_HANDOFF_NOTICES": "1"}
        # Initial handoff fire at safe point
        res = self.run_hook(206_000, env=env)
        self.assertFires(res)
        self.assertTrue(self.flag.exists())

        # Compaction occurs, context drops below threshold (e.g. 40,000 tokens)
        res_compact = self.run_hook(40_000, env=env)
        self.assertIsNone(res_compact)
        self.assertFalse(self.flag.exists())

        # Next crossing over threshold at safe point: handoff fires again!
        res_rearm = self.run_hook(206_000, env=env)
        self.assertFires(res_rearm)
        self.assertIn("reached 206000 tokens", res_rearm["reason"])

    def test_original_fire_behaviour_unchanged_with_switch_on_and_off(self):
        # 1. At threshold on safe point, notices OFF (default)
        res_off = self.run_hook(205_000)
        self.assertFires(res_off)
        reason_off = res_off["reason"]
        self.assertIn("reached 205000 tokens (threshold 200000)", reason_off)

        # 2. Reset session and check notices ON
        self.session = f"test-{uuid.uuid4().hex}"
        self.flag = self.state_dir / f"claude-auto-handoff-{self.session}.flag"
        res_on = self.run_hook(205_000, env={"CLAUDE_AUTO_HANDOFF_NOTICES": "1"})
        self.assertFires(res_on)
        self.assertEqual(res_on["reason"], reason_off)

        # 3. Hard cap with dirty tree, notices OFF
        self.session = f"test-{uuid.uuid4().hex}"
        self.flag = self.state_dir / f"claude-auto-handoff-{self.session}.flag"
        (self.repo / "tracked.txt").write_text("dirty\n")
        res_cap_off = self.run_hook(300_000)
        self.assertFires(res_cap_off)
        cap_reason = res_cap_off["reason"]

        # 4. Hard cap with dirty tree, notices ON
        self.session = f"test-{uuid.uuid4().hex}"
        self.flag = self.state_dir / f"claude-auto-handoff-{self.session}.flag"
        res_cap_on = self.run_hook(300_000, env={"CLAUDE_AUTO_HANDOFF_NOTICES": "1"})
        self.assertFires(res_cap_on)
        self.assertEqual(res_cap_on["reason"], cap_reason)

    def test_malformed_or_empty_stdin_exits_zero_silently(self):
        for bad_stdin in ("", "   \n\t", "not json", "{truncated json:", "[1, 2]"):
            out = self.run_hook_raw(bad_stdin)
            self.assertEqual(out.returncode, 0)
            self.assertEqual(out.stdout.strip(), "")

    def test_decision_log_never_contains_transcript_text(self):
        secret1 = "SECRET_CANARY_DRAIN_881928"
        secret2 = "SECRET_CANARY_HANDOFF_337281"
        self.run_hook(210_000, [LAUNCH_AGENT, secret1])
        texts = [LAUNCH_AGENT, notification("a1b2c3d4e5"), secret2]
        self.run_hook(220_000, texts)
        self.assertTrue(self.log_path.exists())
        log_content = self.log_path.read_text()
        self.assertNotIn(secret1, log_content)
        self.assertNotIn(secret2, log_content)

    def test_leaving_notices_off_sends_live_drain_notice(self):
        # First call with notices off logs drain notice and emits nothing
        res_off = self.run_hook(210_000, [LAUNCH_AGENT], env={"CLAUDE_AUTO_HANDOFF_NOTICES": "0"})
        self.assertIsNone(res_off)

        # Later turn on same session with notices on emits the live drain notice
        res_on = self.run_hook(212_000, [LAUNCH_AGENT], env={"CLAUDE_AUTO_HANDOFF_NOTICES": "1"})
        self.assertIsNotNone(res_on)
        self.assertIn("AUTO-HANDOFF pending", res_on["reason"])

    def test_stop_hook_active_is_silent(self):
        res = self.run_hook(250_000, stop_hook_active=True)
        self.assertIsNone(res)
        self.assertFalse(self.flag.exists())


if __name__ == "__main__":
    unittest.main()
