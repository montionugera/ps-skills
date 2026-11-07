#!/usr/bin/env python3
"""skills/agy-worker/hooks/agent-concurrency-guard.sh: machine-wide worker cap, T3 cap, swap deny (fake ps + fake swap)."""
import json, os, subprocess, tempfile, time, unittest
from concurrent.futures import ThreadPoolExecutor
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

class R2ReviewCapTest(unittest.TestCase):
    """Rule 7: R2 work gets ONE consolidated reviewer per session at a time."""
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(); self.addCleanup(self._tmp.cleanup)
        self.transcript = Path(self._tmp.name) / "sess.jsonl"
        self.subagents = Path(self._tmp.name) / "sess" / "subagents"
    def dispatch(self, subagent_type="code-reviewer", brief="Review the diff. RISK: R2", **env):
        tool_input = {"subagent_type": subagent_type, "prompt": brief, "description": "review"}
        e = dict(os.environ, AGENT_GUARD_PS_CMD=ps(), AGENT_GUARD_SWAP_CMD=swap(1000.0), **env)
        payload = {"tool_name": "Agent", "tool_input": tool_input, "transcript_path": str(self.transcript)}
        r = subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=e)
        return json.loads(r.stdout)["hookSpecificOutput"]
    def agent(self, name, agent_type, finished=False, age_minutes=0):
        self.subagents.mkdir(parents=True, exist_ok=True)
        meta = {"agentType": agent_type, "description": f"{name} desc", "spawnDepth": 1}
        if finished: meta["finished"] = True
        (self.subagents / f"agent-{name}.meta.json").write_text(json.dumps(meta, separators=(",", ":")))
        log = self.subagents / f"agent-{name}.jsonl"; log.write_text("{}\n")
        stamp = time.time() - age_minutes * 60; os.utime(log, (stamp, stamp))
    def test_second_reviewer_denied_while_one_runs(self):
        self.agent("a", "aios-reviewer")
        o = self.dispatch(); self.assertEqual(o["permissionDecision"], "deny"); self.assertIn("a desc", o["permissionDecisionReason"])
    def test_first_reviewer_allowed(self):
        self.assertNotIn("permissionDecision", self.dispatch())
    def test_same_message_fanout_denied_before_any_meta_exists(self):
        self.assertNotIn("permissionDecision", self.dispatch())
        self.assertEqual(self.dispatch("python-reviewer")["permissionDecision"], "deny")
    def test_rereview_allowed_after_reviewer_finished(self):
        now = int(time.time())
        self.dispatch(AGENT_GUARD_NOW=str(now)); self.agent("a", "code-reviewer", finished=True)
        self.assertNotIn("permissionDecision", self.dispatch(AGENT_GUARD_NOW=str(now + 300)))
    def test_first_label_in_the_brief_decides(self):
        self.agent("a", "code-reviewer")
        brief = "RISK: R1. Review the guard: it denies a brief with `RISK: R2` while a reviewer runs."
        self.assertNotIn("permissionDecision", self.dispatch(brief=brief))
    def test_label_outside_the_brief_is_ignored(self):
        self.agent("a", "code-reviewer")
        tool_input = {"subagent_type": "code-reviewer", "description": "RISK: R2 mention", "prompt": "RISK: R1 review"}
        e = dict(os.environ, AGENT_GUARD_PS_CMD=ps(), AGENT_GUARD_SWAP_CMD=swap(1000.0))
        payload = {"tool_name": "Agent", "tool_input": tool_input, "transcript_path": str(self.transcript)}
        r = subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=e)
        self.assertNotIn("permissionDecision", json.loads(r.stdout)["hookSpecificOutput"])
    def test_parallel_refanout_after_an_old_claim_allows_exactly_one(self):
        now = int(time.time())
        self.dispatch(AGENT_GUARD_NOW=str(now - 600))
        for trial in range(8):
            at = str(now + trial * 600)
            with ThreadPoolExecutor(max_workers=4) as ex:
                out = list(ex.map(lambda _: self.dispatch(AGENT_GUARD_NOW=at), range(4)))
            self.assertEqual(sum("permissionDecision" not in o for o in out), 1, f"trial {trial}")
    def test_denied_retries_do_not_extend_the_block(self):
        results = [self.dispatch(AGENT_GUARD_NOW=str(t)) for t in (119, 120, 178, 180)]
        self.assertEqual(["permissionDecision" in o for o in results], [False, True, True, False])
    def test_burst_across_a_minute_boundary_allows_exactly_one(self):
        base = 6000 * 60
        for trial in range(8):
            first = base + trial * 600 - 1
            with ThreadPoolExecutor(max_workers=4) as ex:
                out = list(ex.map(lambda i: self.dispatch(AGENT_GUARD_NOW=str(first + i % 2)), range(4)))
            self.assertEqual(sum("permissionDecision" not in o for o in out), 1, f"trial {trial}")
    def test_abandoned_lock_fails_open_and_clears(self):
        lock = self.subagents / ".r2-review-lock"; lock.mkdir(parents=True)
        os.utime(lock, (time.time() - 60, time.time() - 60))
        self.assertNotIn("permissionDecision", self.dispatch())
        self.assertFalse(lock.exists())
    def test_slow_lock_holder_is_waited_for_not_overrun(self):
        # A live holder that needs 2.5 s (slow CI) must not be treated as abandoned.
        import threading
        lock = self.subagents / ".r2-review-lock"; lock.mkdir(parents=True)
        (self.subagents / ".r2-review-stamp").write_text("1000")
        holder = threading.Timer(2.5, lock.rmdir); holder.start()
        out = self.dispatch(AGENT_GUARD_NOW="1010"); holder.join()
        self.assertIn("permissionDecision", out)
    def test_crashed_reviewer_stops_blocking_once_its_log_goes_stale(self):
        self.agent("a", "code-reviewer", age_minutes=45)
        self.assertNotIn("permissionDecision", self.dispatch())
    def test_r1_and_unlabelled_briefs_may_fan_out(self):
        self.agent("a", "code-reviewer")
        self.assertNotIn("permissionDecision", self.dispatch(brief="Review. RISK: R1"))
        self.assertNotIn("permissionDecision", self.dispatch(brief="Review the diff."))
    def test_r2_must_be_the_exact_label(self):
        self.agent("a", "code-reviewer")
        self.assertNotIn("permissionDecision", self.dispatch(brief="RISK: R20 is not a level"))
    def test_non_review_agents_are_never_capped(self):
        self.agent("a", "code-reviewer")
        for kind in ("aios-builder", "aios-scout", "general-purpose"):
            self.assertNotIn("permissionDecision", self.dispatch(kind))
    def test_running_builder_does_not_block_a_reviewer(self):
        self.agent("a", "aios-builder")
        self.assertNotIn("permissionDecision", self.dispatch())
    def test_off_switch(self):
        self.agent("a", "code-reviewer")
        self.assertNotIn("permissionDecision", self.dispatch(AGENT_R2_REVIEW_GUARD="off"))
if __name__ == "__main__": unittest.main()
