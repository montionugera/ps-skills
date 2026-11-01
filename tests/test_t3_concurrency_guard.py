#!/usr/bin/env python3
"""skills/agy-worker/hooks/t3-concurrency-guard.sh: deny T3 thread launches at the cap, advise below it (fake ps)."""
import json, os, subprocess, tempfile, unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "skills" / "agy-worker" / "hooks" / "t3-concurrency-guard.sh"

def fake_ps(n_t3, n_other=2):
    lines = ["PID PPID COMMAND", "1 0 /sbin/launchd", "500 1 /Applications/T3 Code (Nightly).app/Contents/MacOS/T3 Code (Nightly)", "600 1 -zsh"]
    for i in range(n_t3): lines.append(f"{700+i} 500 /opt/homebrew/bin/claude --output-format stream-json --session {i}")
    for i in range(n_other): lines.append(f"{800+i} 600 claude")
    f = tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False); f.write("#!/bin/sh\ncat <<'PS'\n" + "\n".join(lines) + "\nPS\n"); f.close(); os.chmod(f.name, 0o755); return f.name

def run(tool, n_t3, limit=4):
    env = dict(os.environ, T3_GUARD_PS_CMD=fake_ps(n_t3), T3_MAX_THREADS=str(limit))
    r = subprocess.run(["bash", str(HOOK)], input=json.dumps({"tool_name": tool, "tool_input": {}}), capture_output=True, text=True, env=env)
    return json.loads(r.stdout) if r.stdout.strip() else None

class T3GuardTest(unittest.TestCase):
    def test_denies_at_cap(self):
        out = run("mcp__t3-code__t3_thread_launch", 4)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("4 T3 Code agent threads", out["hookSpecificOutput"]["permissionDecisionReason"])
    def test_advises_below_cap_and_ignores_non_t3_claude(self):
        out = run("delegate_task", 2)
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
        self.assertIn("T3 threads running: 2 of 4", out["hookSpecificOutput"]["additionalContext"])
    def test_other_tools_pass_silently(self):
        self.assertIsNone(run("Bash", 9))

if __name__ == "__main__":
    unittest.main()
