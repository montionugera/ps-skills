#!/usr/bin/env python3
"""Tests for bin/herdr-reap-idle.

All criteria tested against a fake herdr executable and temporary directories.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "herdr-reap-idle"

FAKE_HERDR_PY = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

calls_log = Path(os.environ["FAKE_HERDR_CALLS_LOG"])
with open(calls_log, "a", encoding="utf-8") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")

cfg_file = Path(os.environ["FAKE_HERDR_CONFIG"])
with open(cfg_file, "r", encoding="utf-8") as f:
    cfg = json.load(f)

args = sys.argv[1:]

# session list --json
if args == ["session", "list", "--json"]:
    if cfg.get("fail_session_list"):
        sys.stderr.write("fake error listing sessions\\n")
        sys.exit(1)
    if cfg.get("invalid_json_session_list"):
        sys.stdout.write("not json at all")
        sys.exit(0)
    sys.stdout.write(json.dumps({"sessions": cfg.get("sessions", [])}))
    sys.exit(0)

# --session <name> api snapshot
if len(args) == 4 and args[0] == "--session" and args[2] == "api" and args[3] == "snapshot":
    sess_name = args[1]
    if cfg.get("fail_snapshot", {}).get(sess_name):
        sys.stderr.write(f"fake error snapshot for {sess_name}\\n")
        sys.exit(1)
    if cfg.get("invalid_json_snapshot", {}).get(sess_name):
        sys.stdout.write("invalid json snapshot")
        sys.exit(0)
    snap = cfg.get("snapshots", {}).get(sess_name, {"agents": []})
    sys.stdout.write(json.dumps({"result": {"snapshot": snap}}))
    sys.exit(0)

# --session <name> pane process-info --pane <pane_id>
if len(args) == 6 and args[0] == "--session" and args[2] == "pane" and args[3] == "process-info" and args[4] == "--pane":
    sess_name = args[1]
    pane_id = args[5]
    if cfg.get("fail_process_info", {}).get(pane_id):
        sys.stderr.write(f"fake error process-info for {pane_id}\\n")
        sys.exit(1)
    if cfg.get("invalid_json_process_info", {}).get(pane_id):
        sys.stdout.write("invalid json process-info")
        sys.exit(0)
    pinfo = cfg.get("process_info", {}).get(pane_id)
    if pinfo is None:
        pinfo = {
            "foreground_process_group_id": 10001,
            "foreground_processes": [{
                "argv": ["claude"],
                "argv0": "claude",
                "cmdline": "claude",
                "cwd": "/some/cwd",
                "name": "claude",
                "pid": 10001
            }],
            "pane_id": pane_id,
            "shell_pid": 10000
        }
    sys.stdout.write(json.dumps({"id": "cli:pane:process_info", "result": {"process_info": pinfo}, "type": "pane_process_info"}))
    sys.exit(0)

# --session <name> pane close <pane_id>
if len(args) == 5 and args[0] == "--session" and args[2] == "pane" and args[3] == "close":
    sess_name = args[1]
    pane_id = args[4]
    fail_panes = cfg.get("fail_close_panes", [])
    if pane_id in fail_panes or cfg.get("fail_close_all"):
        sys.stderr.write(f"fake error closing pane {pane_id}\\n")
        sys.exit(1)
    sys.stdout.write(json.dumps({"result": {"closed": True}}))
    sys.exit(0)

sys.stderr.write(f"unexpected fake herdr args: {args}\\n")
sys.exit(1)
"""


class HerdrReapIdleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)

        # Directories
        self.bin_dir = self.tmp_path / "bin"
        self.bin_dir.mkdir(parents=True)
        self.state_dir = self.tmp_path / "state" / "herdr"
        self.state_dir.mkdir(parents=True)
        self.claude_projects_dir = self.tmp_path / "claude" / "projects"
        self.claude_projects_dir.mkdir(parents=True)
        self.dispatch_jobs_dir = self.tmp_path / "dispatch" / "jobs"
        self.dispatch_jobs_dir.mkdir(parents=True)

        # Fake herdr script
        self.fake_herdr = self.bin_dir / "herdr"
        self.fake_herdr.write_text(FAKE_HERDR_PY)
        self.fake_herdr.chmod(self.fake_herdr.stat().st_mode | stat.S_IXUSR)

        self.calls_log = self.tmp_path / "herdr_calls.jsonl"
        self.cfg_file = self.tmp_path / "herdr_cfg.json"
        self.set_herdr_config({"sessions": [], "snapshots": {}})

        self.ps_file = self.tmp_path / "ps_output.txt"
        self.ps_file.write_text("  PID  PPID COMMAND\n10001     1 claude\n")

        # Base env for running herdr-reap-idle
        self.env = os.environ.copy()
        self.env["HERDR_CMD"] = str(self.fake_herdr)
        self.env["HERDR_STATE_DIR"] = str(self.state_dir)
        self.env["CLAUDE_PROJECTS_DIR"] = str(self.claude_projects_dir)
        self.env["DISPATCH_JOBS_DIR"] = str(self.dispatch_jobs_dir)
        self.env["FAKE_HERDR_CALLS_LOG"] = str(self.calls_log)
        self.env["FAKE_HERDR_CONFIG"] = str(self.cfg_file)
        self.env["HERDR_PS_OUTPUT_FILE"] = str(self.ps_file)

    def set_herdr_config(self, cfg: dict):
        self.cfg_file.write_text(json.dumps(cfg))

    def get_herdr_calls(self) -> list[list[str]]:
        if not self.calls_log.exists():
            return []
        lines = self.calls_log.read_text().strip().splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def run_script(self, args: list[str] | None = None, env_overrides: dict | None = None):
        cmd = [sys.executable, str(SCRIPT)] + (args or [])
        run_env = self.env.copy()
        if env_overrides:
            run_env.update(env_overrides)
        return subprocess.run(cmd, capture_output=True, text=True, env=run_env)

    def test_env_off_exits_zero_and_does_nothing(self):
        """Criterion 9: HERDR_REAP_IDLE=off exits 0 and does nothing."""
        res = self.run_script(env_overrides={"HERDR_REAP_IDLE": "off"})
        self.assertEqual(res.returncode, 0)
        self.assertEqual(self.get_herdr_calls(), [])
        self.assertFalse((self.state_dir / "idle-panes.json").exists())
        self.assertFalse((self.state_dir / "reaped-panes.jsonl").exists())

    def test_dry_run_closes_nothing_and_prints(self):
        """Criterion 1: --dry-run closes nothing and prints what it would close."""
        now = time.time()
        session_id = "test-uuid-111"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": "p1",
                        "revision": 10,
                        "state_change_seq": 100,
                        "cwd": "/some/worktree",
                        "terminal_title_stripped": "Feature 1"
                    }]
                }
            }
        })
        # Pre-seed idle-panes.json with idle_since 4000s ago
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            f"tooling:p1::{session_id}": {"seq": 100, "rev": 10, "idle_since": now - 4000}
        }))
        # Transcript mtime 4000s ago
        proj_dir = self.claude_projects_dir / "proj1"
        proj_dir.mkdir(parents=True)
        trans_file = proj_dir / f"{session_id}.jsonl"
        trans_file.write_text("{\"msg\": 1}\n")
        os.utime(trans_file, (now - 4000, now - 4000))

        res = self.run_script(["--dry-run"])
        self.assertEqual(res.returncode, 0)
        self.assertIn("[dry-run] Would close session tooling pane p1", res.stdout)
        self.assertIn("claude --resume test-uuid-111", res.stdout)

        # Closes nothing
        calls = self.get_herdr_calls()
        close_calls = [c for c in calls if "close" in c]
        self.assertEqual(close_calls, [])
        self.assertFalse((self.state_dir / "reaped-panes.jsonl").exists())

    def test_first_seen_pane_has_idle_since_now_and_never_closed(self):
        """Criterion 2: A pane first seen has idle_since=now and is never closed on that run."""
        now = time.time()
        session_id = "test-uuid-222"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": "p2",
                        "revision": 5,
                        "state_change_seq": 50,
                        "cwd": "/some/worktree",
                        "terminal_title_stripped": "Feature 2"
                    }]
                }
            }
        })

        res = self.run_script()
        self.assertEqual(res.returncode, 0)

        # Should not close
        calls = self.get_herdr_calls()
        close_calls = [c for c in calls if "close" in c]
        self.assertEqual(close_calls, [])
        self.assertFalse((self.state_dir / "reaped-panes.jsonl").exists())

        # idle-panes.json should record idle_since ~ now
        idle_file = self.state_dir / "idle-panes.json"
        self.assertTrue(idle_file.exists())
        data = json.loads(idle_file.read_text())
        expected_key = f"tooling:p2::{session_id}"
        self.assertIn(expected_key, data)
        self.assertEqual(data[expected_key]["seq"], 50)
        self.assertEqual(data[expected_key]["rev"], 5)
        self.assertAlmostEqual(data[expected_key]["idle_since"], now, delta=5.0)

    def test_closes_when_idle_or_done_unfocused_unchanged_and_age_exceeded(self):
        """Criterion 3 & 8: Closes with 'herdr --session NAME pane close PANE' and logs."""
        now = time.time()
        session_id = "test-uuid-333"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "done",
                        "focused": False,
                        "pane_id": "p3",
                        "revision": 20,
                        "state_change_seq": 200,
                        "cwd": "/workspace/worktree3",
                        "terminal_title_stripped": "Feature 3"
                    }]
                }
            }
        })
        key = f"tooling:p3::{session_id}"
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            key: {"seq": 200, "rev": 20, "idle_since": now - 3650}
        }))
        # Transcript older than 3600s
        proj_dir = self.claude_projects_dir / "proj1"
        proj_dir.mkdir(parents=True)
        trans_file = proj_dir / f"{session_id}.jsonl"
        trans_file.write_text("{}\n")
        os.utime(trans_file, (now - 3700, now - 3700))

        res = self.run_script()
        self.assertEqual(res.returncode, 0)

        # Check close command
        calls = self.get_herdr_calls()
        self.assertIn(["--session", "tooling", "pane", "close", "p3"], calls)

        # Check reaped log
        reaped_file = self.state_dir / "reaped-panes.jsonl"
        self.assertTrue(reaped_file.exists())
        lines = reaped_file.read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertAlmostEqual(entry["ts"], now, delta=5.0)
        self.assertEqual(entry["session"], "tooling")
        self.assertEqual(entry["pane_id"], "p3")
        self.assertEqual(entry["cwd"], "/workspace/worktree3")
        self.assertEqual(entry["title"], "Feature 3")
        self.assertEqual(entry["resume"], f"claude --resume {session_id}")

        # Pane removed from idle-panes.json
        data = json.loads(idle_file.read_text())
        self.assertNotIn(key, data)

    def test_transcript_mtime_resets_idle_age(self):
        """Criterion 3: idle age counts transcript mtime."""
        now = time.time()
        session_id = "test-uuid-444"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": "p4",
                        "revision": 10,
                        "state_change_seq": 100,
                        "cwd": "/some/worktree",
                        "terminal_title_stripped": "Feature 4"
                    }]
                }
            }
        })
        key = f"tooling:p4::{session_id}"
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            key: {"seq": 100, "rev": 10, "idle_since": now - 5000}
        }))
        # Transcript was updated 5 minutes ago (< 3600s)
        proj_dir = self.claude_projects_dir / "proj1"
        proj_dir.mkdir(parents=True)
        trans_file = proj_dir / f"{session_id}.jsonl"
        trans_file.write_text("{}\n")
        os.utime(trans_file, (now - 300, now - 300))

        res = self.run_script()
        self.assertEqual(res.returncode, 0)

        # Should not close
        calls = self.get_herdr_calls()
        close_calls = [c for c in calls if "close" in c]
        self.assertEqual(close_calls, [])

    def test_seq_or_revision_change_resets_idle_since(self):
        """Criterion 3: seq or rev changed resets idle_since."""
        now = time.time()
        session_id = "test-uuid-555"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": "p5",
                        "revision": 11,  # changed from 10
                        "state_change_seq": 100,
                        "cwd": "/some/worktree"
                    }]
                }
            }
        })
        key = f"tooling:p5::{session_id}"
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            key: {"seq": 100, "rev": 10, "idle_since": now - 4000}
        }))

        res = self.run_script()
        self.assertEqual(res.returncode, 0)

        # Should not close
        calls = self.get_herdr_calls()
        close_calls = [c for c in calls if "close" in c]
        self.assertEqual(close_calls, [])

        # idle_since reset in state
        data = json.loads(idle_file.read_text())
        self.assertEqual(data[key]["rev"], 11)
        self.assertAlmostEqual(data[key]["idle_since"], now, delta=5.0)

    def test_never_closes_working_blocked_or_unknown_agent(self):
        """Criterion 4: Never closes working, blocked or unknown agent."""
        now = time.time()
        for status in ("working", "blocked", "unknown", "other"):
            with self.subTest(status=status):
                self.calls_log.unlink(missing_ok=True)
                session_id = f"test-uuid-{status}"
                self.set_herdr_config({
                    "sessions": [{"name": "tooling", "running": True}],
                    "snapshots": {
                        "tooling": {
                            "agents": [{
                                "agent": "claude",
                                "agent_session": {"value": session_id},
                                "agent_status": status,
                                "focused": False,
                                "pane_id": f"p-{status}",
                                "revision": 1,
                                "state_change_seq": 1,
                                "cwd": "/some/worktree"
                            }]
                        }
                    }
                })
                key = f"tooling:p-{status}::{session_id}"
                idle_file = self.state_dir / "idle-panes.json"
                idle_file.write_text(json.dumps({
                    key: {"seq": 1, "rev": 1, "idle_since": now - 5000}
                }))
                res = self.run_script()
                self.assertEqual(res.returncode, 0)
                calls = self.get_herdr_calls()
                close_calls = [c for c in calls if "close" in c]
                self.assertEqual(close_calls, [])

    def test_never_closes_focused_pane(self):
        """Criterion 4: Never closes focused pane."""
        now = time.time()
        session_id = "test-uuid-focused"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": True,
                        "pane_id": "p-focused",
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": "/some/worktree"
                    }]
                }
            }
        })
        key = f"tooling:p-focused::{session_id}"
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            key: {"seq": 1, "rev": 1, "idle_since": now - 5000}
        }))
        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        calls = self.get_herdr_calls()
        close_calls = [c for c in calls if "close" in c]
        self.assertEqual(close_calls, [])

    def test_never_closes_unfinished_subagent_under_30m(self):
        """Criterion 4: Never closes pane with unfinished subagent updated < 30m ago."""
        now = time.time()
        session_id = "test-uuid-subagent"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": "p-sub",
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": "/some/worktree"
                    }]
                }
            }
        })
        key = f"tooling:p-sub::{session_id}"
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            key: {"seq": 1, "rev": 1, "idle_since": now - 5000}
        }))

        # Create subagent meta file with finished: false, and log file updated 10m ago (600s)
        sub_dir = self.claude_projects_dir / "proj1" / session_id / "subagents"
        sub_dir.mkdir(parents=True)
        meta_file = sub_dir / "agent-1.meta.json"
        log_file = sub_dir / "agent-1.jsonl"
        meta_file.write_text(json.dumps({"finished": False}))
        log_file.write_text("{\"msg\": 1}\n")
        os.utime(meta_file, (now - 600, now - 600))
        os.utime(log_file, (now - 600, now - 600))

        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        calls = self.get_herdr_calls()
        close_calls = [c for c in calls if "close" in c]
        self.assertEqual(close_calls, [])

        # If subagent finished is True, it CAN be closed
        meta_file.write_text(json.dumps({"finished": True}))
        self.calls_log.unlink(missing_ok=True)
        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        calls = self.get_herdr_calls()
        close_calls = [c for c in calls if "close" in c]
        self.assertEqual(len(close_calls), 1)

    def test_never_closes_when_cwd_matches_running_or_pending_dispatch_job(self):
        """Criterion 4: Never closes pane whose cwd matches RUNNING or PENDING dispatch job."""
        now = time.time()
        session_id = "test-uuid-dispatch"
        cwd = str(self.tmp_path / "target_repo")
        Path(cwd).mkdir(parents=True)

        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": "p-disp",
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": cwd
                    }]
                }
            }
        })
        key = f"tooling:p-disp::{session_id}"
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            key: {"seq": 1, "rev": 1, "idle_since": now - 5000}
        }))

        job_file = self.dispatch_jobs_dir / "job1.json"
        job_file.write_text(json.dumps({"status": "RUNNING", "cwd": cwd}))

        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        calls = self.get_herdr_calls()
        close_calls = [c for c in calls if "close" in c]
        self.assertEqual(close_calls, [])

        # If job is SUCCESS, pane CAN be closed
        job_file.write_text(json.dumps({"status": "SUCCESS", "cwd": cwd}))
        self.calls_log.unlink(missing_ok=True)
        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        calls = self.get_herdr_calls()
        close_calls = [c for c in calls if "close" in c]
        self.assertEqual(len(close_calls), 1)

    def test_skips_non_claude_or_missing_session_id(self):
        """Criterion 5: Skips pane whose agent is not claude or session id is missing."""
        now = time.time()
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [
                        {
                            "agent": "agy",
                            "agent_session": {"value": "agy-123"},
                            "agent_status": "idle",
                            "focused": False,
                            "pane_id": "p-agy",
                            "revision": 1,
                            "state_change_seq": 1,
                            "cwd": "/some/worktree"
                        },
                        {
                            "agent": "claude",
                            # missing agent_session
                            "agent_status": "idle",
                            "focused": False,
                            "pane_id": "p-nosess",
                            "revision": 1,
                            "state_change_seq": 1,
                            "cwd": "/some/worktree"
                        }
                    ]
                }
            }
        })
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            "tooling:p-agy::agy-123": {"seq": 1, "rev": 1, "idle_since": now - 5000},
            "tooling:p-nosess::": {"seq": 1, "rev": 1, "idle_since": now - 5000}
        }))

        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        calls = self.get_herdr_calls()
        close_calls = [c for c in calls if "close" in c]
        self.assertEqual(close_calls, [])

    def test_herdr_failure_or_unparsable_snapshot_closes_nothing_and_exits_nonzero(self):
        """Criterion 6: Any herdr failure or unparsable snapshot closes nothing and exits non-zero."""
        # 1. session list fails
        self.set_herdr_config({"fail_session_list": True})
        res = self.run_script()
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual([c for c in self.get_herdr_calls() if "close" in c], [])

        # 2. session list invalid json
        self.calls_log.unlink(missing_ok=True)
        self.set_herdr_config({"invalid_json_session_list": True})
        res = self.run_script()
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual([c for c in self.get_herdr_calls() if "close" in c], [])

        # 3. snapshot fails
        self.calls_log.unlink(missing_ok=True)
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "fail_snapshot": {"tooling": True}
        })
        res = self.run_script()
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual([c for c in self.get_herdr_calls() if "close" in c], [])

        # 4. snapshot invalid json
        self.calls_log.unlink(missing_ok=True)
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "invalid_json_snapshot": {"tooling": True}
        })
        res = self.run_script()
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual([c for c in self.get_herdr_calls() if "close" in c], [])

    def test_close_failure_leaves_pane_out_of_reaped_log(self):
        """Criterion 7: A close failure leaves that pane out of the reaped log."""
        now = time.time()
        session_id = "test-uuid-failclose"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": "p-fail",
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": "/some/worktree"
                    }]
                }
            },
            "fail_close_panes": ["p-fail"]
        })
        key = f"tooling:p-fail::{session_id}"
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            key: {"seq": 1, "rev": 1, "idle_since": now - 5000}
        }))

        res = self.run_script()
        # Even if close command fails, pane must NOT be logged in reaped-panes.jsonl
        reaped_file = self.state_dir / "reaped-panes.jsonl"
        self.assertFalse(reaped_file.exists())
        # The pane should remain in idle-panes.json
        data = json.loads(idle_file.read_text())
        self.assertIn(key, data)

    def test_custom_max_idle_seconds_flag(self):
        """Check --max-idle-seconds flag."""
        now = time.time()
        session_id = "test-uuid-flag"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": "p-flag",
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": "/some/worktree",
                        "terminal_title_stripped": "Flag Test"
                    }]
                }
            }
        })
        key = f"tooling:p-flag::{session_id}"
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            key: {"seq": 1, "rev": 1, "idle_since": now - 1800}
        }))

        # With default 3600: not closed
        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        self.assertEqual([c for c in self.get_herdr_calls() if "close" in c], [])

        # With --max-idle-seconds 1200: closed
        res = self.run_script(["--max-idle-seconds", "1200"])
        self.assertEqual(res.returncode, 0)
        close_calls = [c for c in self.get_herdr_calls() if "close" in c]
        self.assertEqual(len(close_calls), 1)

    def test_state_key_includes_session_id_and_terminal_id(self):
        """Criterion 1: State key includes Claude session_id and terminal_id, so a new session or reused pane starts as first seen."""
        now = time.time()
        pane_id = "p-reused"
        sess_name = "tooling"
        old_session_id = "old-sess-111"
        new_session_id = "new-sess-222"
        old_terminal_id = "term-old"
        new_terminal_id = "term-new"

        # Pre-seed idle state with old session and old terminal id, idle for 5000s
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            f"{sess_name}:{pane_id}:{old_terminal_id}:{old_session_id}": {
                "seq": 1, "rev": 1, "idle_since": now - 5000
            }
        }))

        # 1. New Claude session in the same pane and terminal starts as first seen (not closed)
        self.set_herdr_config({
            "sessions": [{"name": sess_name, "running": True}],
            "snapshots": {
                sess_name: {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": new_session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": pane_id,
                        "terminal_id": old_terminal_id,
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": "/some/worktree"
                    }]
                }
            }
        })
        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        # Should not close because it's first seen under new_session_id
        close_calls = [c for c in self.get_herdr_calls() if "close" in c]
        self.assertEqual(close_calls, [])
        state = json.loads(idle_file.read_text())
        new_key = f"{sess_name}:{pane_id}:{old_terminal_id}:{new_session_id}"
        self.assertIn(new_key, state)
        self.assertAlmostEqual(state[new_key]["idle_since"], now, delta=5.0)

        # 2. Reused pane id with new terminal id starts as first seen
        self.calls_log.unlink(missing_ok=True)
        self.set_herdr_config({
            "sessions": [{"name": sess_name, "running": True}],
            "snapshots": {
                sess_name: {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": old_session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": pane_id,
                        "terminal_id": new_terminal_id,
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": "/some/worktree"
                    }]
                }
            }
        })
        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        close_calls = [c for c in self.get_herdr_calls() if "close" in c]
        self.assertEqual(close_calls, [])
        state = json.loads(idle_file.read_text())
        term_key = f"{sess_name}:{pane_id}:{new_terminal_id}:{old_session_id}"
        self.assertIn(term_key, state)

    def test_state_for_sessions_no_longer_running_is_dropped(self):
        """Criterion 2: State for sessions no longer running is dropped, not retained."""
        now = time.time()
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            "dead-session:p1:t1:sess1": {"seq": 1, "rev": 1, "idle_since": now - 5000},
            "tooling:p1:t1:sess2": {"seq": 1, "rev": 1, "idle_since": now - 5000},
        }))

        # Only "tooling" is running
        self.set_herdr_config({
            "sessions": [
                {"name": "tooling", "running": True},
                {"name": "dead-session", "running": False}
            ],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": "sess2"},
                        "agent_status": "working",
                        "focused": False,
                        "pane_id": "p1",
                        "terminal_id": "t1",
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": "/some/worktree"
                    }]
                }
            }
        })

        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        state = json.loads(idle_file.read_text())
        self.assertNotIn("dead-session:p1:t1:sess1", state)
        self.assertIn("tooling:p1:t1:sess2", state)

    def test_has_active_subagent_checks_log_mtime_not_meta_mtime(self):
        """Criterion 3: has_active_subagent uses mtime of agent-*.jsonl log, not meta file."""
        now = time.time()
        session_id = "test-uuid-subagent-log"
        pane_id = "p-sublog"
        terminal_id = "t-sublog"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": pane_id,
                        "terminal_id": terminal_id,
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": "/some/worktree"
                    }]
                }
            }
        })
        key = f"tooling:{pane_id}:{terminal_id}:{session_id}"
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            key: {"seq": 1, "rev": 1, "idle_since": now - 5000}
        }))

        sub_dir = self.claude_projects_dir / "proj1" / session_id / "subagents"
        sub_dir.mkdir(parents=True)
        meta_file = sub_dir / "agent-1.meta.json"
        log_file = sub_dir / "agent-1.jsonl"
        meta_file.write_text(json.dumps({"finished": False}))
        log_file.write_text("{\"progress\": 50}\\n")

        # Case A: meta file is old (> 30m, e.g. 3600s), but log file was updated 5m ago (300s)
        # Because subagent is active, pane must NOT be closed!
        os.utime(meta_file, (now - 3600, now - 3600))
        os.utime(log_file, (now - 300, now - 300))

        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        close_calls = [c for c in self.get_herdr_calls() if "close" in c]
        self.assertEqual(close_calls, [])

        # Case B: meta file was touched recently (100s ago), but log file has not been touched for >30m (2000s)
        # In this case subagent is NOT active, so pane CAN be closed!
        self.calls_log.unlink(missing_ok=True)
        os.utime(meta_file, (now - 100, now - 100))
        os.utime(log_file, (now - 2000, now - 2000))

        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        close_calls = [c for c in self.get_herdr_calls() if "close" in c]
        self.assertEqual(len(close_calls), 1)

    def test_skip_pane_when_claude_has_non_mcp_descendant(self):
        """Criterion 4: Skip pane when claude has descendant other than MCP sidecars."""
        now = time.time()
        session_id = "test-uuid-desc"
        pane_id = "p-desc"
        terminal_id = "t-desc"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": pane_id,
                        "terminal_id": terminal_id,
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": "/some/worktree"
                    }]
                }
            }
        })
        key = f"tooling:{pane_id}:{terminal_id}:{session_id}"
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            key: {"seq": 1, "rev": 1, "idle_since": now - 5000}
        }))

        # Non-MCP descendant running (e.g. pytest)
        self.ps_file.write_text(
            "  PID  PPID COMMAND\n"
            "10001     1 claude\n"
            "10002 10001 pytest tests/test_unit.py\n"
        )
        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        close_calls = [c for c in self.get_herdr_calls() if "close" in c]
        self.assertEqual(close_calls, [])  # Skipped!

        # Allowed MCP sidecars: graft, nimble-sidecar, process with mcp
        self.calls_log.unlink(missing_ok=True)
        self.ps_file.write_text(
            "  PID  PPID COMMAND\n"
            "10001     1 claude\n"
            "10002 10001 /Users/.../nimble-sidecar/.venv/bin/python stdio_shim.py\n"
            "10003 10001 graft mcp\n"
            "10004 10001 node /path/to/mcp-server-filesystem\n"
        )
        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        close_calls = [c for c in self.get_herdr_calls() if "close" in c]
        self.assertEqual(len(close_calls), 1)  # Closed!

    def test_skip_pane_when_foreground_process_not_claude(self):
        """Criterion 4: Skip pane when pane's foreground process is not claude."""
        now = time.time()
        session_id = "test-uuid-fg"
        pane_id = "p-fg"
        terminal_id = "t-fg"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": pane_id,
                        "terminal_id": terminal_id,
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": "/some/worktree"
                    }]
                }
            },
            "process_info": {
                pane_id: {
                    "foreground_process_group_id": 20001,
                    "foreground_processes": [{
                        "argv": ["vim", "file.py"],
                        "argv0": "vim",
                        "cmdline": "vim file.py",
                        "cwd": "/some/worktree",
                        "name": "vim",
                        "pid": 20001
                    }],
                    "pane_id": pane_id,
                    "shell_pid": 20000
                }
            }
        })
        key = f"tooling:{pane_id}:{terminal_id}:{session_id}"
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            key: {"seq": 1, "rev": 1, "idle_since": now - 5000}
        }))

        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        close_calls = [c for c in self.get_herdr_calls() if "close" in c]
        self.assertEqual(close_calls, [])  # Skipped!

    def test_skip_pane_when_process_info_cannot_be_read(self):
        """Criterion 4: If process information cannot be read for a pane, skip that pane."""
        now = time.time()
        session_id = "test-uuid-procerr"
        pane_id = "p-procerr"
        terminal_id = "t-procerr"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": pane_id,
                        "terminal_id": terminal_id,
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": "/some/worktree"
                    }]
                }
            },
            "fail_process_info": {pane_id: True}
        })
        key = f"tooling:{pane_id}:{terminal_id}:{session_id}"
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            key: {"seq": 1, "rev": 1, "idle_since": now - 5000}
        }))

        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        close_calls = [c for c in self.get_herdr_calls() if "close" in c]
        self.assertEqual(close_calls, [])  # Skipped!

    def test_dispatch_job_blocks_pane_inside_cwd_or_shared_git_common_dir(self):
        """Criterion 5: RUNNING/PENDING job blocks pane when cwd equals, is inside, or shares git common dir."""
        now = time.time()
        # Set up git repo and sibling worktree
        main_repo = self.tmp_path / "main_repo"
        main_repo.mkdir()
        subprocess.run(["git", "-C", str(main_repo), "init"], check=True, capture_output=True)
        # Create an initial commit so worktrees can be added
        (main_repo / "README.md").write_text("init\\n")
        subprocess.run(["git", "-C", str(main_repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(main_repo), "commit", "-m", "init"], check=True, capture_output=True)

        sibling_wt = self.tmp_path / "sibling_wt"
        subprocess.run(["git", "-C", str(main_repo), "worktree", "add", str(sibling_wt)], check=True, capture_output=True)

        session_id = "test-uuid-disp5"
        pane_id = "p-disp5"
        terminal_id = "t-disp5"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": pane_id,
                        "terminal_id": terminal_id,
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": str(sibling_wt)
                    }]
                }
            }
        })
        key = f"tooling:{pane_id}:{terminal_id}:{session_id}"
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            key: {"seq": 1, "rev": 1, "idle_since": now - 5000}
        }))

        # 1. Dispatch job running in main_repo (shares git common dir with sibling_wt)
        job_file = self.dispatch_jobs_dir / "job_wt.json"
        job_file.write_text(json.dumps({"status": "RUNNING", "cwd": str(main_repo)}))

        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        close_calls = [c for c in self.get_herdr_calls() if "close" in c]
        self.assertEqual(close_calls, [])  # Blocked by sibling worktree job!

        # 2. Dispatch job running inside a subdirectory of pane cwd
        sub_dir = sibling_wt / "deep" / "dir"
        sub_dir.mkdir(parents=True)
        job_file.write_text(json.dumps({"status": "RUNNING", "cwd": str(sub_dir)}))
        self.calls_log.unlink(missing_ok=True)

        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        close_calls = [c for c in self.get_herdr_calls() if "close" in c]
        self.assertEqual(close_calls, [])  # Blocked because job is inside pane cwd!

        # 3. Unrelated repo does NOT block
        unrelated = self.tmp_path / "unrelated_repo"
        unrelated.mkdir()
        subprocess.run(["git", "-C", str(unrelated), "init"], check=True, capture_output=True)
        job_file.write_text(json.dumps({"status": "RUNNING", "cwd": str(unrelated)}))
        self.calls_log.unlink(missing_ok=True)

        res = self.run_script()
        self.assertEqual(res.returncode, 0)
        close_calls = [c for c in self.get_herdr_calls() if "close" in c]
        self.assertEqual(len(close_calls), 1)  # Not blocked!

    def test_unreadable_or_unparsable_dispatch_job_file_closes_nothing_and_exits_nonzero(self):
        """Criterion 6: An unreadable or unparsable dispatch job file closes nothing and exits non-zero."""
        now = time.time()
        session_id = "test-uuid-corrupt"
        pane_id = "p-corrupt"
        terminal_id = "t-corrupt"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": pane_id,
                        "terminal_id": terminal_id,
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": "/some/worktree"
                    }]
                }
            }
        })
        key = f"tooling:{pane_id}:{terminal_id}:{session_id}"
        idle_file = self.state_dir / "idle-panes.json"
        idle_file.write_text(json.dumps({
            key: {"seq": 1, "rev": 1, "idle_since": now - 5000}
        }))

        # Write corrupt JSON dispatch job file
        bad_job = self.dispatch_jobs_dir / "bad.json"
        bad_job.write_text("{ corrupt json content")

        res = self.run_script()
        self.assertNotEqual(res.returncode, 0)
        close_calls = [c for c in self.get_herdr_calls() if "close" in c]
        self.assertEqual(close_calls, [])
        self.assertFalse((self.state_dir / "reaped-panes.jsonl").exists())

    def test_dry_run_saves_idle_state_and_ages_panes_without_removing_or_logging(self):
        """Criterion 7: --dry-run saves idle tracking state, repeated runs age panes and print '[dry-run] Would close'."""
        now = time.time()
        session_id = "test-uuid-dryage"
        pane_id = "p-dryage"
        terminal_id = "t-dryage"
        self.set_herdr_config({
            "sessions": [{"name": "tooling", "running": True}],
            "snapshots": {
                "tooling": {
                    "agents": [{
                        "agent": "claude",
                        "agent_session": {"value": session_id},
                        "agent_status": "idle",
                        "focused": False,
                        "pane_id": pane_id,
                        "terminal_id": terminal_id,
                        "revision": 1,
                        "state_change_seq": 1,
                        "cwd": "/some/worktree",
                        "terminal_title_stripped": "Dry Run Age"
                    }]
                }
            }
        })

        # Run 1: First seen on --dry-run. State should be SAVED to idle-panes.json!
        res1 = self.run_script(["--dry-run"])
        self.assertEqual(res1.returncode, 0)
        self.assertNotIn("[dry-run] Would close", res1.stdout)
        idle_file = self.state_dir / "idle-panes.json"
        self.assertTrue(idle_file.exists())
        key = f"tooling:{pane_id}:{terminal_id}:{session_id}"
        state = json.loads(idle_file.read_text())
        self.assertIn(key, state)
        self.assertAlmostEqual(state[key]["idle_since"], now, delta=5.0)

        # Age the pane to 4000s ago
        state[key]["idle_since"] = now - 4000
        idle_file.write_text(json.dumps(state))

        # Run 2: Pane aged > 3600s. Prints '[dry-run] Would close', saves state, never removes pane, never writes reaped-panes.jsonl
        res2 = self.run_script(["--dry-run"])
        self.assertEqual(res2.returncode, 0)
        self.assertIn(f"[dry-run] Would close session tooling pane {pane_id}", res2.stdout)
        self.assertFalse((self.state_dir / "reaped-panes.jsonl").exists())
        state2 = json.loads(idle_file.read_text())
        self.assertIn(key, state2)  # Never removed!

        # Run 3: Repeated dry-run still prints '[dry-run] Would close' and still tracks pane
        res3 = self.run_script(["--dry-run"])
        self.assertEqual(res3.returncode, 0)
        self.assertIn(f"[dry-run] Would close session tooling pane {pane_id}", res3.stdout)
        state3 = json.loads(idle_file.read_text())
        self.assertIn(key, state3)


if __name__ == "__main__":
    unittest.main()
