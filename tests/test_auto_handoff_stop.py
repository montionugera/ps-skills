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


def resume_result(agent_id):
    """The SendMessage tool result that resumes an agent that had already reported."""
    return json.dumps({"success": True, "message": f"Resuming agent {agent_id[:7]}", "resumedAgentId": agent_id})


# The incident's usage record: an advisor call adds an iteration, so the top-level totals
# double-count; the real context is the last `message` iteration (2 + 126985 + 2153).
ADVISOR_USAGE = {
    "input_tokens": 4, "cache_read_input_tokens": 250165, "cache_creation_input_tokens": 3300,
    "iterations": [
        {"type": "message", "input_tokens": 2, "cache_read_input_tokens": 123000, "cache_creation_input_tokens": 1000},
        {"type": "advisor_message", "input_tokens": 127338},
        {"type": "message", "input_tokens": 2, "cache_read_input_tokens": 126985, "cache_creation_input_tokens": 2153},
    ],
}


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

    def run_hook(self, tokens, texts=(), env=None, cwd=None, stop_hook_active=None, usage=None, last_text=None):
        """Runs the hook on a transcript holding texts, then one assistant turn of `tokens`.

        A text that is a dict is written as the transcript entry itself."""
        transcript = Path(self.tmp.name) / "transcript.jsonl"
        lines = [json.dumps(t if isinstance(t, dict) else {"type": "user", "message": {"content": t}}) for t in texts]
        message = {"usage": usage or {
            "input_tokens": 1000, "cache_read_input_tokens": tokens - 1000, "cache_creation_input_tokens": 0,
        }}
        if last_text is not None:
            message["content"] = [{"type": "text", "text": last_text}]
        lines.append(json.dumps({"type": "assistant", "message": message}))
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

    def test_no_rearm_after_compaction_with_switch_unset(self):
        self.assertFires(self.run_hook(206_000))
        self.assertIsNone(self.run_hook(40_000))
        self.assertTrue(self.flag.exists())
        self.assertIsNone(self.run_hook(206_000))

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

    def test_stop_hook_active_after_own_drain_block_is_silent(self):
        drain = self.state_dir / f"claude-auto-handoff-{self.session}.drainblock"
        drain.write_text("212000")
        res = self.run_hook(250_000, stop_hook_active=True)
        self.assertIsNone(res)
        self.assertFalse(self.flag.exists())

    def test_own_drain_block_does_not_silence_a_later_stop_blocked_by_another_hook(self):
        env = {"CLAUDE_AUTO_HANDOFF_NOTICES": "1"}
        res = self.run_hook(210_000, [LAUNCH_AGENT], env)  # our drain notice blocks
        self.assertEqual(res["decision"], "block")
        # The continuation stops cleanly: that active stop is ours, so it stays silent.
        self.assertIsNone(self.run_hook(210_000, [LAUNCH_AGENT], env, stop_hook_active=True))
        # Later the agent reported and another Stop hook blocks; the stale .drain must not mute us.
        self.assertFires(self.run_hook(250_000, [], env, stop_hook_active=True))

    def test_interrupted_drain_continuation_does_not_leave_a_stale_drainblock(self):
        env = {"CLAUDE_AUTO_HANDOFF_NOTICES": "1"}
        res = self.run_hook(210_000, [LAUNCH_AGENT], env)  # our drain notice blocks
        self.assertEqual(res["decision"], "block")
        # The owner interrupts the continuation: the next Stop is a plain one, not stop_hook_active.
        self.assertIsNone(self.run_hook(210_000, [LAUNCH_AGENT], env))
        # Later another Stop hook blocks; the leftover marker must not mute the handoff.
        self.assertFires(self.run_hook(250_000, [], env, stop_hook_active=True))

    def test_stop_hook_active_from_another_hook_still_hands_off(self):
        # Another Stop hook (mesh guard, prompt-type verify) blocked the stop: the
        # continuation's next Stop carries stop_hook_active=true but no drain marker of ours.
        res = self.run_hook(250_000, stop_hook_active=True)
        self.assertFires(res)

    def test_stop_hook_active_after_handoff_does_not_refire_within_step(self):
        self.assertFires(self.run_hook(250_000))
        self.assertIsNone(self.run_hook(255_000, stop_hook_active=True))

    def test_stop_hook_active_ignores_dry_drain_marker(self):
        # A .drain.dry marker never blocked anything (notices off), so it is not our block.
        (self.state_dir / f"claude-auto-handoff-{self.session}.drain.dry").write_text("212000")
        res = self.run_hook(250_000, stop_hook_active=True)
        self.assertFires(res)

    def test_agy_stop_accepts_no_tool_call_and_resolves_brain_transcript(self):
        conv_id = f"agy-{uuid.uuid4().hex}"
        app_dir = Path(self.tmp.name) / "agy-app"
        logs_dir = app_dir / "brain" / conv_id / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        # 600,000 bytes -> ~150,000 estimated tokens (> default 128,000 AGY threshold)
        (logs_dir / "transcript_full.jsonl").write_text("x" * 600_000)

        payload = {
            "conversationId": conv_id,
            "terminationReason": "NO_TOOL_CALL",
            "fullyIdle": True,
            "workspacePaths": [str(self.repo)],
        }
        out = self.run_hook_raw(
            json.dumps(payload),
            env={"AGY_APP_DATA_DIR": str(app_dir)},
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        res = json.loads(out.stdout)
        self.assertEqual(res["decision"], "continue")
        self.assertIn("AUTO-HANDOFF", res["reason"])
        self.assertIn("--kind agy", res["reason"])
        self.assertTrue((self.state_dir / f"agy-auto-handoff-{conv_id}.flag").exists())

    def test_agy_stop_resolves_conversation_db_and_wal_bytes(self):
        conv_id = f"agy-db-{uuid.uuid4().hex}"
        app_dir = Path(self.tmp.name) / "agy-app-db"
        conv_dir = app_dir / "conversations"
        conv_dir.mkdir(parents=True)
        (conv_dir / f"{conv_id}.db").write_bytes(b"d" * 300_000)
        (conv_dir / f"{conv_id}.db-wal").write_bytes(b"w" * 300_000)

        payload = {
            "conversationId": conv_id,
            "terminationReason": "MAX_TOKEN_BUDGET_EXCEEDED",
            "fullyIdle": True,
            "workspacePaths": [str(self.repo)],
        }
        out = self.run_hook_raw(
            json.dumps(payload),
            env={"AGY_APP_DATA_DIR": str(app_dir)},
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        res = json.loads(out.stdout)
        self.assertEqual(res["decision"], "continue")
        self.assertIn("150000 tokens", res["reason"])

    def test_agy_stop_ignores_error_termination_reason(self):
        conv_id = f"agy-err-{uuid.uuid4().hex}"
        app_dir = Path(self.tmp.name) / "agy-app-err"
        logs_dir = app_dir / "brain" / conv_id / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "transcript.jsonl").write_text("x" * 600_000)

        payload = {
            "conversationId": conv_id,
            "terminationReason": "USER_CANCELLED",
            "fullyIdle": True,
            "workspacePaths": [str(self.repo)],
        }
        out = self.run_hook_raw(
            json.dumps(payload),
            env={"AGY_APP_DATA_DIR": str(app_dir)},
        )
        self.assertEqual(out.returncode, 0)
        self.assertEqual(json.loads(out.stdout), {})

    def test_herdr_handoff_script_supports_t3code_and_help(self):
        script = HOOK.parent.parent / "scripts" / "herdr-handoff.sh"
        help_res = subprocess.run(["bash", str(script), "--help"], capture_output=True, text=True, timeout=10)
        self.assertEqual(help_res.returncode, 0)
        self.assertIn("--multiplexer", help_res.stdout)
        self.assertIn("t3code", help_res.stdout)

        handoff_doc = Path(self.tmp.name) / "handoff-2026-10-13-t3.md"
        handoff_doc.write_text("# Handoff\n## 1. Main Context\n- Original User Objective: keep full context\nImmediate Next Action: verify t3\n")
        dry_res = subprocess.run(
            ["bash", str(script), str(handoff_doc), "--kind", "agy", "--multiplexer", "t3", "--dry-run"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(dry_res.returncode, 0, dry_res.stderr)
        self.assertIn("RESOLVED_MUX=t3", dry_res.stdout)
        self.assertIn("AGENT_KIND=agy", dry_res.stdout)
        prompt_file = Path(self.tmp.name) / "handoff-2026-10-13-t3.prompt.txt"
        self.assertTrue(prompt_file.is_file())
        prompt_text = prompt_file.read_text()
        self.assertIn("BEGIN HANDOFF DOCUMENT", prompt_text)
        self.assertIn("Original User Objective: keep full context", prompt_text)

    # --- ordered replay: a resumed agent is running again (2026-10-19 incident) ---

    def test_waits_for_an_agent_resumed_after_it_reported(self):
        texts = [LAUNCH_AGENT, notification("a1b2c3d4e5"), resume_result("a1b2c3d4e5")]
        self.assertWaits(self.run_hook(210_000, texts))
        drain = [r for r in self.read_log() if r["decision"] == "drain-notice"]
        self.assertEqual(len(drain), 1)
        self.assertIn("background=1", drain[0]["why"])

    def test_fires_once_the_resumed_agent_reports_again(self):
        texts = [LAUNCH_AGENT, notification("a1b2c3d4e5"), resume_result("a1b2c3d4e5"), notification("a1b2c3d4e5")]
        self.assertFires(self.run_hook(210_000, texts))

    def test_a_notification_copy_in_an_api_request_blob_is_not_an_event(self):
        texts = [LAUNCH_AGENT, {"type": "api-request-blob", "body": notification("a1b2c3d4e5")}]
        self.assertWaits(self.run_hook(210_000, texts))

    # --- context counts the last message iteration ---

    def test_advisor_iteration_is_not_double_counted(self):
        self.assertWaits(self.run_hook(0, usage=ADVISOR_USAGE))  # 129140, not ~256k
        out = self.run_hook(0, usage=ADVISOR_USAGE, env={"CLAUDE_AUTO_HANDOFF_THRESHOLD": "129000"})
        self.assertFires(out)
        self.assertIn("129140 tokens", out["reason"])

    # --- the handoff instruction carries the hook's own count ---

    def test_handoff_instruction_carries_running_count(self):
        out = self.run_hook(300_000, [LAUNCH_AGENT, LAUNCH_BASH])
        self.assertFires(out)
        self.assertIn("--running 2", out["reason"])

    def test_handoff_instruction_says_running_zero_at_a_safe_point(self):
        out = self.run_hook(200_000)
        self.assertIn("--running 0", out["reason"])

    # --- .draining marker: the retired reminder tells the old tab to relay ---

    def reminder_after_handoff(self, second_texts):
        env = {"CLAUDE_AUTO_HANDOFF_NOTICES": "1"}
        self.assertFires(self.run_hook(300_000, [LAUNCH_AGENT], env=env))
        marker = self.state_dir / f"claude-auto-handoff-{self.session}.draining"
        return marker, self.run_hook(330_000, second_texts, env=env)

    def test_handoff_with_running_agents_writes_draining_marker_and_reminder_says_relay(self):
        marker, out = self.reminder_after_handoff([LAUNCH_AGENT])
        self.assertTrue(marker.exists())
        self.assertIn("Relay", out["reason"])
        self.assertIn("SAFE TO CLOSE", out["reason"])
        self.assertNotIn("retired", out["reason"])

    def test_draining_marker_clears_when_the_last_agent_reports(self):
        marker, out = self.reminder_after_handoff([LAUNCH_AGENT, notification("a1b2c3d4e5")])
        self.assertFalse(marker.exists())
        self.assertIn("last agent reported", out["reason"])
        self.assertIn("SAFE TO CLOSE THIS TAB", out["reason"])

    def test_relay_done_reminder_comes_once_without_waiting_for_growth(self):
        env = {"CLAUDE_AUTO_HANDOFF_NOTICES": "1"}
        self.assertFires(self.run_hook(300_000, [LAUNCH_AGENT], env=env))
        out = self.run_hook(300_100, [LAUNCH_AGENT, notification("a1b2c3d4e5")], env=env)
        self.assertIn("last agent reported", out["reason"])
        self.assertIsNone(self.run_hook(300_200, [LAUNCH_AGENT, notification("a1b2c3d4e5")], env=env))

    def test_running_hint_has_no_parentheses_inside_the_command(self):
        out = self.run_hook(300_000, [LAUNCH_AGENT])
        self.assertIn("--running 1.", out["reason"])
        self.assertNotIn("--running 1 (", out["reason"])

    def test_drain_notice_states_the_precedence_rule(self):
        out = self.run_hook(210_000, [LAUNCH_AGENT], env={"CLAUDE_AUTO_HANDOFF_NOTICES": "1"})
        self.assertIn("A newer owner instruction wins", out["reason"])

    # --- claim guard (F8) ---

    CLAIM = "Context is full; the next step happens in the new tab."

    def guard_env(self):
        return {"CLAUDE_AUTO_HANDOFF_NOTICES": "1"}

    def log_decision(self, decision, session=None):
        with open(self.log_path, "a") as f:
            f.write(json.dumps({"session": session or self.session, "decision": decision}) + "\n")

    def test_claim_guard_blocks_once_after_a_notice_with_no_handoff(self):
        self.log_decision("midturn-notice")
        out = self.run_hook(129_140, last_text=self.CLAIM, env=self.guard_env())
        self.assertEqual(out["decision"], "block")
        self.assertIn("No handoff ran", out["reason"])
        self.assertIsNone(self.run_hook(129_140, last_text=self.CLAIM, env=self.guard_env()))

    def test_claim_guard_stays_quiet_when_a_handoff_ran(self):
        self.log_decision("midturn-notice")
        self.log_decision("handoff")
        self.assertIsNone(self.run_hook(129_140, last_text=self.CLAIM, env=self.guard_env()))

    def test_claim_guard_stays_quiet_without_a_notice_for_this_session(self):
        self.log_decision("midturn-notice", session="someone-else")
        self.assertIsNone(self.run_hook(129_140, last_text=self.CLAIM, env=self.guard_env()))

    def test_claim_guard_accepts_a_manual_handoff_banner_in_the_transcript(self):
        self.log_decision("midturn-notice")
        banner = "✅  HANDOFF CONFIRMED — claude is working in tab t9"
        self.assertIsNone(self.run_hook(129_140, [banner], last_text=self.CLAIM, env=self.guard_env()))

    def test_claim_guard_is_not_satisfied_by_documentation_of_the_banner(self):
        self.log_decision("midturn-notice")
        doc = "`✅ HANDOFF CONFIRMED` followed by `⛔ KEEP THIS TAB OPEN — N agents still running`"
        out = self.run_hook(129_140, [doc], last_text=self.CLAIM, env=self.guard_env())
        self.assertEqual(out["decision"], "block")

    def test_claim_guard_ignores_ticket_prose(self):
        self.log_decision("drain-notice")
        text = "The ticket has been handed off to QA."
        self.assertIsNone(self.run_hook(129_140, last_text=text, env=self.guard_env()))

    def test_claim_guard_ignores_discussion_of_handoffs(self):
        self.log_decision("drain-notice")
        text = "The handoff hook decides when a handoff runs. SAFE TO CLOSE THIS TAB once the relay is done."
        self.assertIsNone(self.run_hook(129_140, last_text=text, env=self.guard_env()))

    def test_agy_subagent_stop_ignored_and_session_id_sanitized(self):
        conv_id = f"agy-sub-{uuid.uuid4().hex}"
        app_dir = Path(self.tmp.name) / "agy-app-sub"
        logs_dir = app_dir / "brain" / conv_id / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "transcript_full.jsonl").write_text("x" * 600_000)

        # Subagent stop with parentConversationId must be ignored
        sub_out = self.run_hook_raw(
            json.dumps({
                "conversationId": conv_id,
                "parentConversationId": "parent-123",
                "terminationReason": "NO_TOOL_CALL",
                "fullyIdle": True,
                "workspacePaths": [str(self.repo)],
            }),
            env={"AGY_APP_DATA_DIR": str(app_dir)},
        )
        self.assertEqual(json.loads(sub_out.stdout), {})

        # Path traversal in conversationId cannot escape state_dir
        sanitized_id = "escapedconv"
        esc_logs = app_dir / "brain" / sanitized_id / ".system_generated" / "logs"
        esc_logs.mkdir(parents=True)
        (esc_logs / "transcript_full.jsonl").write_text("x" * 600_000)
        esc_out = self.run_hook_raw(
            json.dumps({
                "conversationId": "../../escaped/conv",
                "terminationReason": "NO_TOOL_CALL",
                "fullyIdle": True,
                "workspacePaths": [str(self.repo)],
            }),
            env={"AGY_APP_DATA_DIR": str(app_dir)},
        )
        self.assertEqual(json.loads(esc_out.stdout)["decision"], "continue")
        self.assertFalse((self.state_dir.parent / "escaped" / "conv.flag").exists())
        self.assertTrue((self.state_dir / f"agy-auto-handoff-{sanitized_id}.flag").exists())

    def test_waits_while_t3_delegated_task_is_running_and_fires_when_completed(self):
        task_id = "node:delegated-" + "task:command%3Amcp%3Atest-123"
        launch_line = json.dumps({
            "taskId": task_id,
            "childThreadId": "thread:delegated-task:test-123",
            "status": "running",
            "workState": "working",
        })
        # While T3 delegate_task is running, hook must wait at safe point
        self.assertWaits(self.run_hook(210_000, [launch_line]))

        # When wakeup notification arrives ("Delegated task <id> reached a terminal state"), hook fires
        wakeup_line = f"Delegated task {task_id} reached a terminal state."
        self.assertFires(self.run_hook(210_000, [launch_line, wakeup_line]))

        # Or when task_status returns status="completed", hook also fires
        self.session = f"test-{uuid.uuid4().hex}"
        self.flag = self.state_dir / f"claude-auto-handoff-{self.session}.flag"
        done_line = json.dumps({
            "taskId": task_id,
            "status": "completed",
            "workState": "result_available",
        })
        res = self.run_hook(210_000, [launch_line, done_line])
        self.assertFires(res)
        self.assertIn("Main Context", res["reason"])

    def test_waits_while_agy_background_task_is_running_and_fires_when_finished(self):
        agy_task_id = "ace8d432-102c/task-69"
        launch_line = "Tool is running as a " + f"background task with task id: {agy_task_id}"
        self.assertWaits(self.run_hook(210_000, [launch_line]))

        done_line = f'Task id "{agy_task_id}" finished with result:'
        self.assertFires(self.run_hook(210_000, [launch_line, done_line]))

    def test_agy_workspace_paths_prefers_project_repo_over_skills_dirs(self):
        conv_id = f"agy-ws-{uuid.uuid4().hex}"
        app_dir = Path(self.tmp.name) / "agy-app-ws"
        logs_dir = app_dir / "brain" / conv_id / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "transcript_full.jsonl").write_text("x" * 600_000)

        # Make repo dirty, and pass a fake /skills path first in workspacePaths
        (self.repo / "tracked.txt").write_text("dirty-in-repo\n")
        payload = {
            "conversationId": conv_id,
            "terminationReason": "NO_TOOL_CALL",
            "fullyIdle": True,
            "workspacePaths": [
                "/tmp/fake-home/.gemini/antigravity-cli/skills",
                "/tmp/fake-home/.gemini/config/skills",
                str(self.repo),
            ],
        }
        out = self.run_hook_raw(
            json.dumps(payload),
            env={"AGY_APP_DATA_DIR": str(app_dir), "AGY_AUTO_HANDOFF_NOTICES": "1"},
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        res = json.loads(out.stdout)
        # Should detect dirty_tree=True on self.repo and emit drain notice rather than firing handoff
        self.assertIn("AUTO-HANDOFF pending", res["reason"])
        self.assertIn("dirty_tree=True", res["reason"])
        self.assertFalse((self.state_dir / f"agy-auto-handoff-{conv_id}.flag").exists())


    def test_agy_transcript_jsonl_takes_precedence_over_preallocated_db_wal(self):
        conv_id = f"agy-prec-{uuid.uuid4().hex}"
        app_dir = Path(self.tmp.name) / "agy-app-prec"
        logs_dir = app_dir / "brain" / conv_id / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        # 40 KB compact transcript (~10,000 tokens, well below 128k threshold)
        (logs_dir / "transcript.jsonl").write_text("x" * 40_000)
        # 800 KB full transcript (untruncated tool dumps) and 600 KB SQLite WAL pre-allocation
        (logs_dir / "transcript_full.jsonl").write_text("f" * 800_000)
        conv_dir = app_dir / "conversations"
        conv_dir.mkdir(parents=True)
        (conv_dir / f"{conv_id}.db").write_bytes(b"d" * 600_000)
        (conv_dir / f"{conv_id}.db-wal").write_bytes(b"w" * 600_000)

        payload = {
            "conversationId": conv_id,
            "transcriptPath": str(conv_dir / f"{conv_id}.db"),
            "terminationReason": "NO_TOOL_CALL",
            "fullyIdle": True,
            "workspacePaths": [str(self.repo)],
        }
        out = self.run_hook_raw(
            json.dumps(payload),
            env={"AGY_APP_DATA_DIR": str(app_dir)},
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {})
        self.assertFalse((self.state_dir / f"agy-auto-handoff-{conv_id}.flag").exists())

    def test_agy_schedule_timer_and_checkpoint_do_not_block_safe_point(self):
        timer_line = (
            "Tool is running as a "
            "background task with task id: conv-1/task-99\n"
            "Task Description: Timer: 15s, Prompt: Check status"
        )
        orphan_before_checkpoint = (
            "Tool is running as a "
            "background task with task id: conv-1/task-12"
        )
        checkpoint_line = '{"step_index":50,"source":"SYSTEM","type":"CHECKPOINT","status":"DONE"}'
        res = self.run_hook(210_000, [orphan_before_checkpoint, checkpoint_line, timer_line])
        self.assertFires(res)


    def test_t3_delegated_subagent_stop_ignored(self):
        header = json.dumps({
            "type": "queue-operation",
            "content": "Act as the implementation sub-agent for this task.\n\nImplement Wave 1.",
        })
        self.assertIsNone(self.run_hook(350_000, [header]))

    def test_agy_checkpoint_resets_active_bytes_in_stop_hook(self):
        conv_id = f"agy-stop-chk-{uuid.uuid4().hex}"
        app_dir = Path(self.tmp.name) / "agy-app-stop-chk"
        logs_dir = app_dir / "brain" / conv_id / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        pre_chk = ("x" * 800_000) + "\n"
        chk = '{"step_index":42,"source":"SYSTEM","type":"CHECKPOINT","status":"DONE"}\n'
        post_chk = ("y" * 16_000) + "\n"
        (logs_dir / "transcript.jsonl").write_text(pre_chk + chk + post_chk)
        conv_dir = app_dir / "conversations"
        conv_dir.mkdir(parents=True)
        (conv_dir / f"{conv_id}.db-wal").write_bytes(b"w" * 900_000)

        payload = {
            "conversationId": conv_id,
            "transcriptPath": str(conv_dir / f"{conv_id}.db"),
            "terminationReason": "NO_TOOL_CALL",
            "fullyIdle": True,
            "workspacePaths": [str(self.repo)],
        }
        out = self.run_hook_raw(
            json.dumps(payload),
            env={"AGY_APP_DATA_DIR": str(app_dir)},
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {})

    # --- Fix A: a multi-iteration record is measured by its last message iteration ---

    MULTI_ITERATION_USAGE = {
        # req_011CgD1q: top level sums to 256,557; the real context is 129,395.
        "input_tokens": 4, "cache_creation_input_tokens": 5147, "cache_read_input_tokens": 251406,
        "iterations": [
            {"type": "message", "input_tokens": 2, "cache_read_input_tokens": 124246,
             "cache_creation_input_tokens": 2914},
            {"type": "advisor_message", "input_tokens": 129387},
            {"type": "message", "input_tokens": 2, "cache_read_input_tokens": 127160,
             "cache_creation_input_tokens": 2233},
        ],
    }

    def test_multi_iteration_record_is_not_double_counted(self):
        transcript = Path(self.tmp.name) / "multi.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "message": {"usage": self.MULTI_ITERATION_USAGE}}) + "\n")
        out = self.run_hook_raw(json.dumps({"transcript_path": str(transcript), "session_id": self.session,
                                            "cwd": str(self.repo)}))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, "")
        self.assertFalse(self.flag.exists())

    def test_multi_iteration_record_over_threshold_reports_the_real_context(self):
        usage = {"input_tokens": 4, "cache_read_input_tokens": 420_000, "iterations": [
            {"type": "message", "input_tokens": 2, "cache_read_input_tokens": 205_000},
            {"type": "message", "input_tokens": 2, "cache_read_input_tokens": 210_000},
        ]}
        transcript = Path(self.tmp.name) / "multi2.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "message": {"usage": usage}}) + "\n")
        out = self.run_hook_raw(json.dumps({"transcript_path": str(transcript), "session_id": self.session,
                                            "cwd": str(self.repo)}))
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout)
        self.assertFires(result)
        self.assertIn("210002 tokens", result["reason"])

    def test_agy_multi_iteration_usage_is_not_double_counted(self):
        conv_id = f"agy-iter-{uuid.uuid4().hex}"
        app_dir = Path(self.tmp.name) / "agy-app-iter"
        logs_dir = app_dir / "brain" / conv_id / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "assistant", "message": {"usage": self.MULTI_ITERATION_USAGE}}) + "\n")
        payload = {"conversationId": conv_id, "terminationReason": "NO_TOOL_CALL", "fullyIdle": True,
                   "workspacePaths": [str(self.repo)]}
        # Threshold 150,000 sits between the real 129,395 and the summed 256,557.
        out = self.run_hook_raw(json.dumps(payload), env={"AGY_APP_DATA_DIR": str(app_dir),
                                                          "AGY_AUTO_HANDOFF_THRESHOLD": "150000"})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {})


if __name__ == "__main__":
    unittest.main()

