#!/usr/bin/env python3
"""Tests for the closing banner of skills/handoff/scripts/herdr-handoff.sh.

A fake `herdr` on PATH answers the few calls the script makes; its pane status comes from
FAKE_STATUS. Nothing here starts an agent or a real Herdr tab."""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "handoff" / "scripts" / "herdr-handoff.sh"

FAKE_HERDR = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
case "$1 $2" in
  "status server") echo "${FAKE_SERVER_STATUS:-status: running}" ;;
  "pane current")
    [ -n "${FAKE_CALLER_WS:-}" ] && echo '{"result":{"pane":{"pane_id":"p1","tab_id":"'"$FAKE_CALLER_TAB"'","workspace_id":"'"$FAKE_CALLER_WS"'"}}}'
    ;;
  "tab get") echo '{"result":{"tab":{"tab_id":"'"$3"'","label":"'"${FAKE_SOURCE_LABEL:-zsh}"'","focused":'"${FAKE_SOURCE_FOCUSED:-true}"'}}}' ;;
  "tab create")
    [ -n "${FAKE_CREATE_FAIL:-}" ] && { echo '{"error":{"code":"boom","message":"no"}}'; exit 1; }
    ws=focused-ws; prev=""
    for a in "$@"; do [ "$prev" = "--workspace" ] && ws=$a; prev=$a; done
    if [ -n "${FAKE_WS_NOT_FOUND:-}" ] && [ "$ws" != focused-ws ]; then
      echo '{"error":{"code":"workspace_not_found","message":"workspace not found"}}'; exit 1
    fi
    echo '{"result":{"tab":{"tab_id":"t9","workspace_id":"'"${FAKE_ACTUAL_WS:-$ws}"'"},"root_pane":{"pane_id":"p9"}}}'
    ;;
  "pane list") echo '{"result":{"panes":[{"pane_id":"p9"}]}}' ;;
  "pane run")
    [ -n "${FAKE_RUN_FAIL:-}" ] && exit 1
    [ -z "${FAKE_NO_CLAIM:-}" ] && [ -n "${FAKE_CLAIM_DIR:-}" ] && mkdir -p "$FAKE_CLAIM_DIR"
    ;;
  "pane get") echo '{"result":{"pane":{"agent":"claude","agent_status":"'"$FAKE_STATUS"'"}}}' ;;
esac
exit 0
"""


class HerdrHandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        (d / "bin").mkdir()
        herdr = d / "bin" / "herdr"
        herdr.write_text(FAKE_HERDR)
        herdr.chmod(herdr.stat().st_mode | stat.S_IXUSR)
        t3 = d / "bin" / "t3"  # the T3 fallback must never reach the real CLI
        t3.write_text("#!/usr/bin/env bash\nexit 0\n")
        t3.chmod(t3.stat().st_mode | stat.S_IXUSR)
        self.log = d / "herdr.log"
        self.doc = d / "handoff-2026-10-19-test.md"
        self.doc.write_text("# Handoff\n## 1. Main Context\n## 4. Next\n")
        self.ledger = d / "state" / "ledger.jsonl"

    def run_script(self, *args, status="working", timeout=2, extra_env=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("HERDR", "T3", "CLAUDE"))}
        env.update({
            "PATH": f"{Path(self.tmp.name) / 'bin'}:{env['PATH']}", "FAKE_LOG": str(self.log),
            "FAKE_STATUS": status, "HERDR_TAB_ID": "t1", "T3CODE_HOME": self.tmp.name,
            "HERDR_HANDOFF_CONFIRM_TIMEOUT": str(timeout), "FAKE_CLAIM_DIR": f"{self.doc}.claim",
            "HERDR_HANDOFF_LEDGER": str(self.ledger),
        })
        env.update(extra_env or {})
        r = subprocess.run(
            ["bash", str(SCRIPT), str(self.doc), "--kind", "claude", "--mode", "plan", "--multiplexer", "herdr",
             "--cwd", self.tmp.name, *args],
            capture_output=True, text=True, env=env, timeout=60,
        )
        return r

    def reset_claim(self):
        shutil.rmtree(f"{self.doc}.claim", ignore_errors=True)

    def tab_create_line(self):
        return next(l for l in self.log.read_text().splitlines() if l.startswith("tab create"))

    def test_new_tab_is_pinned_to_the_callers_workspace(self):
        r = self.run_script("--running", "1", extra_env={"HERDR_WORKSPACE_ID": "w7"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--workspace w7", self.tab_create_line())

    def test_new_tab_omits_workspace_when_not_inside_herdr(self):
        r = self.run_script("--running", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("--workspace", self.tab_create_line())

    def test_running_agents_keep_the_tab_open_and_never_say_safe(self):
        r = self.run_script("--running", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("KEEP THIS TAB OPEN", r.stdout)
        self.assertIn("2 agents still running", r.stdout)
        self.assertNotIn("SAFE", r.stdout)
        self.assertNotIn("Closing THIS tab", r.stdout)

    def test_running_agents_win_over_close_source(self):
        r = self.run_script("--running", "1", "--close-source")
        self.assertIn("KEEP THIS TAB OPEN", r.stdout)
        self.assertNotIn("Closing THIS tab", r.stdout)

    def test_running_zero_closes_the_source_tab(self):
        r = self.run_script("--running", "0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Closing THIS tab (t1)", r.stdout)
        self.assertNotIn("KEEP", r.stdout)

    def test_leading_zero_is_decimal_not_octal(self):
        r = self.run_script("--running", "08")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("KEEP THIS TAB OPEN — 8 agents still running", r.stdout)
        self.assertNotIn("Closing THIS tab", r.stdout)

    def test_non_numeric_confirm_timeout_falls_back(self):
        r = self.run_script("--running", "1", timeout="abc")
        self.assertIn("HANDOFF CONFIRMED", r.stdout)
        self.assertNotIn("syntax error", r.stderr)

    def test_running_must_be_a_number(self):
        r = self.run_script("--running", "two")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--running", r.stderr)

    def test_no_flag_states_the_count_is_unknown_and_never_says_safe(self):
        r = self.run_script()
        self.assertIn("count unknown", r.stdout)
        self.assertNotIn("SAFE", r.stdout)

    def test_status_unknown_keeps_polling_and_only_warns_at_timeout(self):
        r = self.run_script("--running", "0", status="unknown", timeout=3, extra_env={"FAKE_NO_CLAIM": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("status unknown", r.stdout)
        self.assertNotIn("HANDOFF CONFIRMED", r.stdout)
        self.assertNotIn("Closing THIS tab", r.stdout)
        polls = [line for line in self.log.read_text().splitlines() if line.startswith("pane get")]
        self.assertGreaterEqual(len(polls), 3)

    def test_a_live_agent_without_a_claim_never_confirms_or_closes(self):
        for status in ("idle", "blocked", "working"):
            with self.subTest(status=status):
                r = self.run_script("--running", "0", status=status, timeout=1, extra_env={"FAKE_NO_CLAIM": "1"})
                self.assertEqual(r.returncode, 1)
                self.assertNotIn("HANDOFF CONFIRMED", r.stdout)
                self.assertNotIn("Closing THIS tab", r.stdout)

    def test_a_dead_agent_stops_waiting_early(self):
        r = self.run_script("--running", "0", status="exited", timeout=30, extra_env={"FAKE_NO_CLAIM": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("DO NOT CLOSE THIS TAB", r.stdout)

    def test_the_claim_confirms_whatever_the_pane_status_says(self):
        for status in ("unknown", "", "idle", "blocked", "working"):
            with self.subTest(status=status):
                self.reset_claim()
                r = self.run_script("--running", "1", status=status)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertRegex(r.stdout, r"HANDOFF CONFIRMED .{1,8}? \w+ is \w+ in tab")


    def test_auto_switches_claude_to_agy_yolo_with_argon_model_when_quota_is_low(self):
        import json
        quota_dir = Path(self.tmp.name) / "quota"
        quota_dir.mkdir(parents=True, exist_ok=True)
        (quota_dir / "claude-statusline.json").write_text(json.dumps({
            "provider": "claude",
            "windows": [{"kind": "weekly", "remaining_percent": 5.0, "resets_at": 9999999999}],
        }))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("HERDR", "T3", "CLAUDE"))}
        env.update({
            "PATH": f"{Path(self.tmp.name) / 'bin'}:{env['PATH']}",
            "FAKE_LOG": str(self.log),
            "FAKE_STATUS": "working",
            "HERDR_TAB_ID": "t1",
            "T3CODE_HOME": self.tmp.name,
            "HERDR_HANDOFF_CONFIRM_TIMEOUT": "2",
            "FAKE_CLAIM_DIR": f"{self.doc}.claim",
            "HERDR_PLUGIN_STATE_DIR": str(quota_dir),
        })
        r = subprocess.run(
            ["bash", str(SCRIPT), str(self.doc), "--kind", "claude", "--mode", "plan", "--no-yolo",
             "--multiplexer", "herdr", "--cwd", self.tmp.name, "--running", "1"],
            capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Auto-switching handoff to agy (yolo, model: gemini-4-argon-medium)", r.stdout)
        log_text = self.log.read_text()
        self.assertIn("agy --dangerously-skip-permissions --model gemini-4-argon-medium -i", log_text)

    def test_agy_code_mode_uses_flash_high_model(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("HERDR", "T3", "CLAUDE"))}
        env.update({
            "PATH": f"{Path(self.tmp.name) / 'bin'}:{env['PATH']}",
            "FAKE_LOG": str(self.log),
            "FAKE_STATUS": "working",
            "HERDR_TAB_ID": "t1",
            "T3CODE_HOME": self.tmp.name,
            "HERDR_HANDOFF_CONFIRM_TIMEOUT": "2",
            "FAKE_CLAIM_DIR": f"{self.doc}.claim",
        })
        r = subprocess.run(
            ["bash", str(SCRIPT), str(self.doc), "--kind", "agy", "--mode", "code",
             "--multiplexer", "herdr", "--cwd", self.tmp.name, "--running", "1"],
            capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        log_text = self.log.read_text()
        self.assertIn("agy --dangerously-skip-permissions --model gemini-3.8-flash-high -i", log_text)

    # --- workspace pinning -------------------------------------------------

    def create_args(self):
        return [l for l in self.log.read_text().splitlines() if l.startswith("tab create")]

    def test_the_tab_opens_in_the_callers_workspace_not_the_focused_one(self):
        r = self.run_script("--running", "1", extra_env={"HERDR_WORKSPACE_ID": "wParent"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--workspace wParent", self.create_args()[0])
        self.assertIn("📍 Workspace: wParent", r.stdout)

    def test_live_caller_beats_stale_env(self):
        r = self.run_script("--running", "0", extra_env={
            "HERDR_PANE_ID": "p1", "HERDR_WORKSPACE_ID": "wStale", "HERDR_TAB_ID": "tStale",
            "FAKE_CALLER_WS": "wLive", "FAKE_CALLER_TAB": "tLive"})
        self.assertIn("--workspace wLive", self.create_args()[0])
        self.assertIn("Closing THIS tab (tLive)", r.stdout)

    def test_env_is_the_fallback_when_the_live_lookup_returns_nothing(self):
        self.run_script("--running", "1", extra_env={"HERDR_PANE_ID": "p1", "HERDR_WORKSPACE_ID": "wEnv"})
        self.assertIn("--workspace wEnv", self.create_args()[0])

    def test_a_vanished_workspace_retries_once_and_warns(self):
        r = self.run_script("--running", "1", extra_env={"HERDR_WORKSPACE_ID": "wGone", "FAKE_WS_NOT_FOUND": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.create_args()), 2)
        self.assertNotIn("--workspace", self.create_args()[1])
        self.assertIn("wGone", r.stdout)
        self.assertIn("⚠️", r.stdout)

    def test_landing_in_another_workspace_warns(self):
        r = self.run_script("--running", "1", extra_env={"HERDR_WORKSPACE_ID": "wP", "FAKE_ACTUAL_WS": "wX"})
        self.assertIn("⚠️", r.stdout)
        self.assertIn("wX", r.stdout)
        self.assertNotIn("📍 Workspace", r.stdout)

    # --- focus policy ------------------------------------------------------

    def test_focus_follows_only_when_the_user_is_on_the_parent_tab(self):
        self.run_script("--running", "1", extra_env={"FAKE_SOURCE_FOCUSED": "true"})
        self.assertIn(" --focus", self.create_args()[-1])
        self.reset_claim()
        self.run_script("--running", "1", extra_env={"FAKE_SOURCE_FOCUSED": "false"})
        self.assertIn(" --no-focus", self.create_args()[-1])

    def test_explicit_no_focus_wins(self):
        self.run_script("--running", "1", "--no-focus", extra_env={"FAKE_SOURCE_FOCUSED": "true"})
        self.assertIn(" --no-focus", self.create_args()[0])

    # --- naming ------------------------------------------------------------

    def test_label_comes_from_the_doc_title_and_project(self):
        self.doc.write_text("# Handoff: repair the commit, then plan\n## 1\n## 4\n")
        r = self.run_script("--running", "1")
        self.assertIn(f"{Path(self.tmp.name).name} · repair the commit", self.create_args()[0])

    def test_topic_flag_and_generation(self):
        project = Path(self.tmp.name).name
        self.run_script("--running", "1", "--topic", "ship it", extra_env={
            "FAKE_SOURCE_LABEL": f"{project} · old #2", "HERDR_HANDOFF_LABEL_MAX": "80"})
        self.assertIn(f"--label {project} · ship it #3", self.create_args()[0])

    def test_explicit_label_is_verbatim(self):
        self.run_script("--running", "1", "--label", "Exact Name")
        self.assertIn("--label Exact Name", self.create_args()[0])

    def test_claude_session_gets_the_same_name(self):
        self.run_script("--running", "1", "--label", "Exact Name")
        run = [l for l in self.log.read_text().splitlines() if l.startswith("pane run")][0]
        self.assertIn("--name Exact\\ Name", run)

    def test_a_tab_kept_open_says_it_is_relaying(self):
        self.run_script("--running", "1", "--label", "Next")
        self.assertIn("tab rename t1 ⏳ relay → Next", self.log.read_text())

    def test_a_closing_tab_is_not_renamed(self):
        self.run_script("--running", "0")
        self.assertNotIn("tab rename", self.log.read_text())

    def test_dry_run_reports_label_and_workspace(self):
        r = self.run_script("--dry-run", "--label", "L", extra_env={"HERDR_WORKSPACE_ID": "wP"})
        self.assertIn("TAB_LABEL=L", r.stdout)
        self.assertIn("TARGET_WORKSPACE=wP", r.stdout)
        self.assertFalse(self.log.exists() and self.create_args())

    # --- claim normalisation -----------------------------------------------

    def test_placeholder_is_filled_in_the_doc_and_the_prompt(self):
        self.doc.write_text("# Handoff: x\nmkdir \"<this-file's-own-absolute-path>.claim\"\n## 1\n## 4\n")
        self.run_script("--running", "1")
        self.assertIn(f'mkdir "{self.doc}.claim"', self.doc.read_text())
        self.assertNotIn("<this-file", self.doc.read_text())
        self.assertNotIn("<this-file", self.doc.with_suffix(".prompt.txt").read_text())

    def test_a_missing_claim_section_is_inserted_after_the_title(self):
        self.doc.write_text("# Handoff: x\n## 1. Main\n## 4. Next\n")
        self.run_script("--running", "1")
        lines = self.doc.read_text().splitlines()
        self.assertEqual(lines[0], "# Handoff: x")
        self.assertIn("## 0. Claim This Handoff", self.doc.read_text())
        self.assertIn(f'mkdir "{self.doc}.claim"', self.doc.with_suffix(".prompt.txt").read_text())

    def test_dry_run_leaves_the_doc_byte_identical(self):
        original = "# Handoff: x\nno claim <this-file's-own-absolute-path>\n"
        self.doc.write_text(original)
        self.run_script("--dry-run")
        self.assertEqual(self.doc.read_text(), original)

    def test_an_already_claimed_doc_refuses_to_spawn(self):
        claim = Path(f"{self.doc}.claim")
        claim.mkdir()
        (claim / "owner").write_text("someone pid 1\n")
        r = self.run_script("--running", "0")
        self.assertEqual(r.returncode, 1)
        self.assertIn("already claimed", (r.stdout + r.stderr).lower())
        self.assertIn("someone pid 1", r.stdout + r.stderr)
        self.assertEqual(self.create_args() if self.log.exists() else [], [])

    # --- robustness --------------------------------------------------------

    def test_a_stopped_server_is_not_mistaken_for_a_running_one(self):
        env = {"FAKE_SERVER_STATUS": "status: not running"}
        r = self.run_script("--running", "0", extra_env=env)
        self.assertFalse(self.create_args() if self.log.exists() else [])
        self.assertNotIn("Creating Herdr tab", r.stdout)

    def test_a_failed_tab_create_reports_the_doc_and_exits_1(self):
        r = self.run_script("--running", "0", extra_env={"FAKE_CREATE_FAIL": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("❌", r.stderr)
        self.assertIn(str(self.doc), r.stderr)

    def test_a_failed_pane_run_reports_the_doc_and_exits_1(self):
        r = self.run_script("--running", "0", extra_env={"FAKE_RUN_FAIL": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("❌", r.stderr)
        self.assertNotIn("Closing THIS tab", r.stdout)

    def run_without_cwd(self, *args, extra_env=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("HERDR", "T3", "CLAUDE"))}
        env.update({
            "PATH": f"{Path(self.tmp.name) / 'bin'}:{env['PATH']}", "FAKE_LOG": str(self.log),
            "FAKE_STATUS": "working", "T3CODE_HOME": self.tmp.name, "FAKE_CLAIM_DIR": f"{self.doc}.claim",
            "HERDR_HANDOFF_CONFIRM_TIMEOUT": "2", "HERDR_HANDOFF_LEDGER": str(self.ledger),
        })
        env.update(extra_env or {})
        return subprocess.run(
            ["bash", str(SCRIPT), str(self.doc), "--kind", "claude", "--mode", "plan", "--multiplexer", "herdr",
             "--dry-run", *args],
            capture_output=True, text=True, env=env, timeout=60, cwd="/",
        )

    def test_doc_worktree_header_sets_the_cwd(self):
        target = Path(self.tmp.name) / "wt"
        target.mkdir()
        self.doc.write_text(f"# Handoff: x\n**Worktree:** `{target}` | **Branch:** `b`\n")
        self.assertIn(f"TARGET_CWD={target}", self.run_without_cwd().stdout)

    def test_doc_repo_header_sets_the_cwd(self):
        target = Path(self.tmp.name) / "repo"
        target.mkdir()
        self.doc.write_text(f"# Handoff: x\n**Repo:** `{target}` | **Branch:** `b`\n")
        self.assertIn(f"TARGET_CWD={target}", self.run_without_cwd().stdout)

    def test_explicit_cwd_beats_the_doc(self):
        target = Path(self.tmp.name) / "wt"
        target.mkdir()
        self.doc.write_text(f"# Handoff: x\n**Worktree:** `{target}`\n")
        self.assertIn("TARGET_CWD=/tmp", self.run_without_cwd("--cwd", "/tmp").stdout)

    def test_a_missing_or_placeholder_doc_path_is_ignored(self):
        for value in ("/no/such/dir", "<path>"):
            with self.subTest(value=value):
                self.doc.write_text(f"# Handoff: x\n**Worktree:** `{value}`\n")
                self.assertIn("TARGET_CWD=/\n", self.run_without_cwd().stdout)

    def test_doc_lint_warns_on_stderr_but_never_blocks(self):
        self.doc.write_text("# Handoff: x\n" + "y" * 13000 + "\n")
        r = self.run_script("--running", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("## 1", r.stderr)
        self.assertIn("## 4", r.stderr)
        self.assertIn("bytes", r.stderr)

    def test_drift_warning_counts_commits_the_install_is_missing(self):
        repo = Path(self.tmp.name) / "repo"
        scripts = repo / "skills" / "handoff" / "scripts"
        scripts.mkdir(parents=True)
        copy = scripts / SCRIPT.name
        copy.write_text(SCRIPT.read_text())
        (scripts / "handoff_label.py").write_text((SCRIPT.parent / "handoff_label.py").read_text())
        git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
        git("init", "-q")
        git("-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
        (scripts / "new.txt").write_text("x")
        git("add", ".")
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fix")
        git("update-ref", "refs/remotes/origin/main", "HEAD")
        git("reset", "-q", "--hard", "HEAD~1")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("HERDR", "T3", "CLAUDE"))}
        env.update({"PATH": f"{Path(self.tmp.name) / 'bin'}:{env['PATH']}", "FAKE_LOG": str(self.log),
                    "FAKE_STATUS": "working", "HERDR_TAB_ID": "t1", "T3CODE_HOME": self.tmp.name,
                    "HERDR_HANDOFF_CONFIRM_TIMEOUT": "2", "FAKE_CLAIM_DIR": f"{self.doc}.claim",
                    "HERDR_HANDOFF_LEDGER": str(self.ledger)})
        r = subprocess.run(["bash", str(copy), str(self.doc), "--kind", "claude", "--mode", "plan",
                            "--multiplexer", "herdr", "--cwd", self.tmp.name, "--running", "1"],
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertIn("1 commit", r.stdout + r.stderr)
        self.assertIn("origin/main", r.stdout + r.stderr)

    def test_no_drift_warning_outside_a_git_checkout(self):
        scripts = Path(self.tmp.name) / "plain"
        scripts.mkdir()
        copy = scripts / SCRIPT.name
        copy.write_text(SCRIPT.read_text())
        (scripts / "handoff_label.py").write_text((SCRIPT.parent / "handoff_label.py").read_text())
        env = {k: v for k, v in os.environ.items() if not k.startswith(("HERDR", "T3", "CLAUDE"))}
        env.update({"PATH": f"{Path(self.tmp.name) / 'bin'}:{env['PATH']}", "FAKE_LOG": str(self.log),
                    "FAKE_STATUS": "working", "HERDR_TAB_ID": "t1", "T3CODE_HOME": self.tmp.name,
                    "HERDR_HANDOFF_CONFIRM_TIMEOUT": "2", "FAKE_CLAIM_DIR": f"{self.doc}.claim",
                    "HERDR_HANDOFF_LEDGER": str(self.ledger)})
        r = subprocess.run(["bash", str(copy), str(self.doc), "--kind", "claude", "--mode", "plan",
                            "--multiplexer", "herdr", "--cwd", self.tmp.name, "--running", "1"],
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("origin/main", r.stdout + r.stderr)

    # --- ledger ------------------------------------------------------------

    def ledger_rows(self):
        return [json.loads(line) for line in self.ledger.read_text().splitlines()]

    def test_ledger_records_a_claimed_handoff(self):
        self.run_script("--running", "1", "--label", "L", extra_env={"HERDR_WORKSPACE_ID": "wP"})
        row = self.ledger_rows()[0]
        self.assertEqual(row["outcome"], "claimed")
        self.assertEqual((row["label"], row["tab"], row["source_tab"]), ("L", "t9", "t1"))
        self.assertEqual((row["workspace_expected"], row["workspace_actual"]), ("wP", "wP"))
        self.assertIsInstance(row["confirm_secs"], int)

    def test_ledger_records_an_unclaimed_handoff(self):
        self.run_script("--running", "0", timeout=1, extra_env={"FAKE_NO_CLAIM": "1"})
        self.assertEqual(self.ledger_rows()[0]["outcome"], "unclaimed")

    def test_unwritable_ledger_does_not_change_the_result(self):
        blocker = Path(self.tmp.name) / "file"
        blocker.write_text("")
        r = self.run_script("--running", "1", extra_env={"HERDR_HANDOFF_LEDGER": f"{blocker}/x/ledger.jsonl"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("HANDOFF CONFIRMED", r.stdout)


if __name__ == "__main__":
    unittest.main()
