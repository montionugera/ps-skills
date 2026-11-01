#!/usr/bin/env python3
"""bin/agent-spend: per-message dedup of usage across main / subagent / workflow pools (temp dirs only)."""
import json, os, subprocess, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "agent-spend"

def asst(mid, ctx, out=10):
    return {"type": "assistant", "message": {"id": mid, "usage": {"cache_read_input_tokens": ctx, "cache_creation_input_tokens": 0, "input_tokens": 0, "output_tokens": out}}}

def write(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

class AgentSpendTest(unittest.TestCase):
    def test_counts_each_message_once_and_splits_pools(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "-x-repo-demo"
            # main: one message logged as two content-block lines (must count once), plus a second message
            write(proj / "s1.jsonl", [asst("m1", 1000), asst("m1", 1000), asst("m2", 500), {"type": "user"}])
            write(proj / "s1" / "subagents" / "agent-a.jsonl", [asst("a1", 2000)])
            write(proj / "s1" / "subagents" / "workflows" / "wf_1" / "agent-b.jsonl", [asst("b1", 4000), asst("b1", 4000)])
            res = subprocess.run([sys.executable, str(SCRIPT), "--json", "--projects", tmp, "*repo-demo*"], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            row = json.loads(res.stdout)[0]
            self.assertEqual(row["main"], {"files": 1, "messages": 2, "context_tokens": 1500, "output_tokens": 20})
            self.assertEqual(row["subagents"]["context_tokens"], 2000)
            self.assertEqual(row["workflows"], {"files": 1, "messages": 1, "context_tokens": 4000, "output_tokens": 10})

    def test_since_days_keeps_only_recent_messages(self):
        now = datetime.now(timezone.utc)
        iso = lambda days: (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "-x-repo-demo"
            recent = dict(asst("new", 100), timestamp=iso(1))
            old = dict(asst("old", 1000), timestamp=iso(30))
            undated = asst("undated", 10000)
            write(proj / "s1.jsonl", [recent, old, undated])
            res = subprocess.run([sys.executable, str(SCRIPT), "--json", "--since-days", "7", "--projects", tmp, "*repo-demo*"], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(json.loads(res.stdout)[0]["main"]["context_tokens"], 100)

    def test_since_days_skips_files_untouched_inside_the_window(self):
        old_stamp = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "-x-repo-demo" / "s1.jsonl"
            write(f, [asst("m1", 100)])
            os.utime(f, (old_stamp, old_stamp))
            res = subprocess.run([sys.executable, str(SCRIPT), "--json", "--since-days", "7", "--projects", tmp, "*repo-demo*"], capture_output=True, text=True)
            self.assertEqual(json.loads(res.stdout)[0]["main"]["files"], 0)

if __name__ == "__main__":
    unittest.main()
