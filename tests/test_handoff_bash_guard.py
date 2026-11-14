#!/usr/bin/env python3
"""Unit tests for skills/handoff/hooks/handoff-bash-guard.py.

Verifies that:
1. Clean standalone `herdr-handoff.sh` invocations with an existing handoff file exit 0
   with empty stdout (never rewriting `updatedInput`, which would void Claude Code
   auto-mode verdicts with `server_input_rewritten`).
2. Piped (`| tail -15`), redirected (`2>&1`), chained (`&&`, `;`, heredoc), tilde-path
   (`~/.claude/...`), `--no-yolo`, or missing-file invocations are denied immediately
   with an explicit `permissionDecisionReason` and the exact standalone command to run.
3. Read-only inspection commands (`grep`, `git diff`, `ls`, `wc`, `bash -n`, `--help`,
   `--dry-run`) referencing `herdr-handoff.sh` are allowed silently.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "skills" / "handoff" / "hooks" / "handoff-bash-guard.py"
CANONICAL = "/Users/pasitnusso/.claude/skills/handoff/scripts/herdr-handoff.sh"


class HandoffBashGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.doc = Path(self.tmp.name) / "handoff-2026-11-08-test.md"
        self.doc.write_text("# Handoff: Test\n## 1. Main\n## 4. Next\n")
        self.guard_log = Path(self.tmp.name) / "guard.jsonl"

    def run_guard(self, command: str, cwd: str = None, extra_env: dict = None, out_mode: str = "claude"):
        env = dict(os.environ)
        env.pop("HANDOFF_BASH_GUARD", None)
        env.pop("HERDR_HANDOFF_ALLOW_NO_YOLO", None)
        env.pop("HERDR_HANDOFF_ALLOW_SUBDIR", None)
        env["HERDR_HANDOFF_GUARD_LOG"] = str(self.guard_log)
        if extra_env:
            env.update(extra_env)
        payload = {
            "session_id": "test-session",
            "cwd": cwd or self.tmp.name,
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        cmd = [sys.executable, str(GUARD)]
        if out_mode != "claude":
            cmd.extend(["--out", out_mode])
        proc = subprocess.run(
            cmd,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def assertAllowedSilently(self, res):
        self.assertIsNone(res, f"Expected silent allow (empty stdout), got: {res}")

    def assertDeniedWithReason(self, res, *expected_substrings):
        self.assertIsNotNone(res, "Expected PreToolUse deny JSON, got None")
        hook_out = res.get("hookSpecificOutput") or {}
        self.assertEqual(hook_out.get("hookEventName"), "PreToolUse")
        self.assertEqual(hook_out.get("permissionDecision"), "deny")
        self.assertNotIn("updatedInput", hook_out, "Guard must never set updatedInput")
        reason = hook_out.get("permissionDecisionReason") or ""
        self.assertIn("HANDOFF GUARD", reason)
        self.assertIn("Reason:", reason)
        for sub in expected_substrings:
            self.assertIn(sub, reason)
        return reason

    def test_unrelated_bash_commands_pass_silently(self):
        self.assertAllowedSilently(self.run_guard("git status --short"))
        self.assertAllowedSilently(self.run_guard("pytest -q 2>&1 | tail -20"))

    def test_clean_standalone_handoff_command_passes_with_zero_output(self):
        cmd = (
            f'{CANONICAL} "{self.doc}" --kind claude --mode code '
            '--topic "next slice" --prompt "continue" --running 0'
        )
        self.assertAllowedSilently(self.run_guard(cmd))

    def test_quoted_angle_brackets_in_prompt_are_not_mistaken_for_redirection(self):
        cmd = (
            f'{CANONICAL} "{self.doc}" --kind claude --mode code '
            '--prompt "<immediate next steps> >= 0.99" --running 0'
        )
        self.assertAllowedSilently(self.run_guard(cmd))
        # And when denied for another reason (--no-yolo), the quoted "<immediate next steps>" is preserved
        bad_cmd = f"{cmd} --no-yolo"
        reason = self.assertDeniedWithReason(self.run_guard(bad_cmd), "--no-yolo stalls child claim")
        self.assertIn("'<immediate next steps> >= 0.99' --running 0", reason)

    def test_inspection_and_test_commands_referencing_script_pass_silently(self):
        self.assertAllowedSilently(self.run_guard(f"grep -n 'write_ledger' {CANONICAL} | head -20"))
        self.assertAllowedSilently(self.run_guard(f"git diff {CANONICAL}"))
        self.assertAllowedSilently(self.run_guard(f"bash -n {CANONICAL}"))
        self.assertAllowedSilently(self.run_guard(f"ls -la {CANONICAL}"))
        self.assertAllowedSilently(self.run_guard(f"{CANONICAL} --help"))
        self.assertAllowedSilently(self.run_guard(f'{CANONICAL} "{self.doc}" --dry-run | head -10'))

    def test_piped_handoff_command_is_denied_with_server_held_shell_allow_explanation(self):
        # Incident 8e5e325d attempt 2 & 719d3e9d attempt 1
        cmd = f'{CANONICAL} "{self.doc}" --kind claude --mode code --running 0 2>&1 | tail -15'
        reason = self.assertDeniedWithReason(
            self.run_guard(cmd),
            "piped/redirected command",
            "serverHeldShellAllow",
            f"{CANONICAL} {self.doc} --kind claude --mode code --running 0",
        )
        self.assertNotIn("| tail", reason.splitlines()[-1])

    def test_redirected_handoff_command_is_denied_with_reason(self):
        cmd = f'{CANONICAL} "{self.doc}" --kind claude --mode code --running 0 2>&1'
        self.assertDeniedWithReason(
            self.run_guard(cmd),
            "piped/redirected command",
            f"{CANONICAL} {self.doc} --kind claude --mode code --running 0",
        )

    def test_chained_heredoc_and_handoff_command_is_denied_with_reason(self):
        # Incident 8e5e325d attempt 1
        missing = Path(self.tmp.name) / "handoff-new.md"
        cmd = (
            f"cd {self.tmp.name} && cat > {missing} << 'EOF'\n"
            "# Handoff\n"
            "EOF\n"
            f"&& {CANONICAL} {missing} --kind claude --mode code --running 0 2>&1 | tail -15"
        )
        self.assertDeniedWithReason(
            self.run_guard(cmd),
            "compound/chained command",
            "piped/redirected command",
            "handoff file not found",
            "Write",
        )

    def test_tilde_path_is_denied_and_rewritten_in_suggestion(self):
        cmd = f'~/.claude/skills/handoff/scripts/herdr-handoff.sh "{self.doc}" --kind claude --mode plan --running 0'
        self.assertDeniedWithReason(
            self.run_guard(cmd),
            "non-canonical script invocation",
            f"{CANONICAL} {self.doc} --kind claude --mode plan --running 0",
        )

    def test_no_yolo_is_denied_by_default_and_stripped_from_suggested_command(self):
        # Incident 719d3e9d -> 0df9a039
        cmd = f'{CANONICAL} "{self.doc}" --kind claude --mode code --running 0 --no-yolo'
        reason = self.assertDeniedWithReason(
            self.run_guard(cmd),
            "--no-yolo stalls child claim",
            f"{CANONICAL} {self.doc} --kind claude --mode code --running 0",
        )
        self.assertFalse(reason.splitlines()[-1].endswith("--no-yolo"))

    def test_no_yolo_is_allowed_when_explicitly_opted_in(self):
        cmd = f'{CANONICAL} "{self.doc}" --kind claude --mode code --running 0 --no-yolo'
        self.assertAllowedSilently(
            self.run_guard(cmd, extra_env={"HERDR_HANDOFF_ALLOW_NO_YOLO": "1"})
        )

    def test_allow_subdir_is_denied_by_default_and_stripped_from_suggested_command(self):
        cmd = f'{CANONICAL} "{self.doc}" --kind claude --mode code --running 0 --allow-subdir'
        reason = self.assertDeniedWithReason(
            self.run_guard(cmd),
            "--allow-subdir triggers Trust dialog",
            "no `--allow-subdir`",
            f"{CANONICAL} {self.doc} --kind claude --mode code --running 0",
        )
        self.assertFalse(reason.splitlines()[-1].endswith("--allow-subdir"))

    def test_allow_subdir_is_allowed_when_explicitly_opted_in(self):
        cmd = f'{CANONICAL} "{self.doc}" --kind claude --mode code --running 0 --allow-subdir'
        for val in ("1", "true", "TRUE"):
            with self.subTest(val=val):
                self.assertAllowedSilently(
                    self.run_guard(cmd, extra_env={"HERDR_HANDOFF_ALLOW_SUBDIR": val})
                )
        inline_cmd = f'HERDR_HANDOFF_ALLOW_SUBDIR=true {CANONICAL} "{self.doc}" --kind claude --mode code --running 0 --allow-subdir'
        self.assertAllowedSilently(self.run_guard(inline_cmd))

    def test_missing_handoff_file_is_denied_with_write_tool_instruction(self):
        missing = Path(self.tmp.name) / "does-not-exist.md"
        cmd = f'{CANONICAL} "{missing}" --kind claude --mode code --running 0'
        self.assertDeniedWithReason(
            self.run_guard(cmd),
            f"handoff file not found: {missing}",
            "Write",
        )

    def test_escape_hatch_env_disables_guard(self):
        cmd = f'{CANONICAL} "{self.doc}" --no-yolo 2>&1 | tail -5'
        self.assertAllowedSilently(self.run_guard(cmd, extra_env={"HANDOFF_BASH_GUARD": "0"}))

    def test_agy_output_mode_returns_decision_deny_and_reason(self):
        cmd = f'{CANONICAL} "{self.doc}" --running 0 | tail -5'
        res = self.run_guard(cmd, out_mode="agy")
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("HANDOFF GUARD", res.get("reason", ""))


if __name__ == "__main__":
    unittest.main()
