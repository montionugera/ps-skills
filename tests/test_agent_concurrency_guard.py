#!/usr/bin/env python3
"""skills/agy-worker/hooks/agent-concurrency-guard.sh: machine-wide worker cap, T3 cap, swap deny (fake ps + fake swap)."""
import json, os, subprocess, tempfile, unittest
from pathlib import Path
HOOK = Path(__file__).resolve().parent.parent / "skills" / "agy-worker" / "hooks" / "agent-concurrency-guard.sh"
def shim(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False); f.write("#!/bin/sh\ncat <<'X'\n" + text + "\nX\n"); f.close(); os.chmod(f.name, 0o755); return f.name
def ps(n_t3=0, n_py=0, n_shell=0):
    L = ["PID PPID COMMAND", "1 0 /sbin/launchd", "500 1 /Applications/T3 Code (Nightly).app/Contents/MacOS/T3 Code (Nightly)", "600 1 -zsh", "700 1 /opt/homebrew/bin/python3 dispatch-worker"]
    L += [f"{1000+i} 500 /opt/homebrew/bin/claude -p x" for i in range(n_t3)]
    L += [f"{2000+i} 700 claude -p y" for i in range(n_py)]
    L += [f"{3000+i} 600 claude" for i in range(n_shell)]
    return shim("\n".join(L))
def swap(used, total=10240.0): return shim(f"total = {total:.2f}M  used = {used:.2f}M  free = {total-used:.2f}M  (encrypted)")
def run(tool, n_t3=0, n_py=0, n_shell=0, used=1000.0, **env):
    e = dict(os.environ, AGENT_GUARD_PS_CMD=ps(n_t3, n_py, n_shell), AGENT_GUARD_SWAP_CMD=swap(used), **env)
    r = subprocess.run(["bash", str(HOOK)], input=json.dumps({"tool_name": tool, "tool_input": {}}), capture_output=True, text=True, env=e)
    return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None
class GuardTest(unittest.TestCase):
    def test_interactive_shell_sessions_do_not_count(self):
        o = run("Agent", n_shell=11); self.assertNotIn("permissionDecision", o); self.assertIn("0/8 workers", o["additionalContext"])
    def test_worker_cap_counts_python_and_t3_children(self):
        o = run("Agent", n_t3=3, n_py=5); self.assertEqual(o["permissionDecision"], "deny"); self.assertIn("8 worker agents", o["permissionDecisionReason"])
    def test_t3_cap_only_for_t3_launches(self):
        self.assertEqual(run("delegate_task", n_t3=4)["permissionDecision"], "deny")
        self.assertNotIn("permissionDecision", run("Agent", n_t3=4))
    def test_swap_deny_beats_everything(self):
        o = run("Agent", used=9100.0); self.assertEqual(o["permissionDecision"], "deny"); self.assertIn("swap is 0.89 full", o["permissionDecisionReason"])
    def test_swap_warning_in_context(self):
        o = run("Agent", used=7500.0); self.assertNotIn("permissionDecision", o); self.assertIn("Swap is 0.73 full", o["additionalContext"])
    def test_other_tools_silent(self):
        self.assertIsNone(run("Bash", n_t3=9, used=9999.0))
if __name__ == "__main__": unittest.main()
