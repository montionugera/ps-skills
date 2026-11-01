#!/usr/bin/env python3
"""bin/agent-spend-weekly: 7-day spend vs commits, one JSON line per run (temp dirs only)."""
import json, os, subprocess, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "agent-spend-weekly"
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

def git(cwd, *args, env=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env or GIT_ENV)

def commit(cwd, msg, when=None):
    env = dict(GIT_ENV)
    if when:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = when
    git(cwd, "commit", "--allow-empty", "-m", msg, env=env)

def transcript(projects, name, ctx):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    path = Path(projects) / name / "s1.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"type": "assistant", "timestamp": stamp, "message": {"id": "m", "usage": {"input_tokens": ctx, "output_tokens": 5}}}) + "\n")

def run(tmp, *repos):
    log = Path(tmp) / "logs" / "weekly.jsonl"
    args = [sys.executable, str(SCRIPT), "--projects", str(Path(tmp) / "projects"), "--log", str(log)]
    for spec in repos:
        args += ["--repo", spec]
    return subprocess.run(args, capture_output=True, text=True), log

class AgentSpendWeeklyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        self.projects = Path(self.tmp) / "projects"
        self.projects.mkdir()

    def make_repo(self, name):
        path = Path(self.tmp) / name
        path.mkdir()
        git(path, "init", "-q", "-b", "main")
        return path

    def test_counts_tokens_and_recent_main_commits_then_appends_one_line(self):
        repo = self.make_repo("demo")
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        commit(repo, "old", when=old)
        commit(repo, "new-1")
        commit(repo, "new-2")
        transcript(self.projects, "-x-demo", 4000)

        res, log = run(self.tmp, f"demo:{repo}:*-demo*")
        self.assertEqual(res.returncode, 0, res.stderr)
        lines = log.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["window_days"], 7)
        self.assertTrue(entry["ts"].endswith("Z"))
        row = entry["repos"][0]
        self.assertEqual((row["repo"], row["commits"], row["context_tokens"]), ("demo", 2, 4000))
        self.assertEqual(row["tokens_per_commit"], 2000)
        self.assertEqual(len(res.stdout.strip().splitlines()), 2)  # header + one repo

        run(self.tmp, f"demo:{repo}:*-demo*")
        self.assertEqual(len(log.read_text().splitlines()), 2)

    def test_prefers_origin_main_over_a_stale_local_main(self):
        upstream = self.make_repo("upstream")
        commit(upstream, "base")
        clone = Path(self.tmp) / "clone"
        git(self.tmp, "clone", "-q", str(upstream), str(clone))
        commit(upstream, "landed-upstream")  # local clone/main stays behind

        res, log = run(self.tmp, f"clone:{clone}:*nothing*")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(log.read_text())["repos"][0]["commits"], 2)

    def test_failed_fetch_warns_that_the_count_may_be_stale(self):
        repo = self.make_repo("demo")
        commit(repo, "one")
        git(repo, "remote", "add", "origin", f"{self.tmp}/no-such-remote")
        res, log = run(self.tmp, f"demo:{repo}:*x*")
        self.assertEqual(json.loads(log.read_text())["repos"][0]["commits"], 1)
        self.assertIn("fetch failed", res.stderr)

    def test_missing_repo_reports_null_commits_and_keeps_the_others(self):
        repo = self.make_repo("demo")
        commit(repo, "one")
        res, log = run(self.tmp, f"gone:{self.tmp}/gone:*x*", f"demo:{repo}:*x*")
        self.assertEqual(res.returncode, 0, res.stderr)
        rows = json.loads(log.read_text())["repos"]
        self.assertIsNone(rows[0]["commits"])
        self.assertIsNone(rows[0]["tokens_per_commit"])
        self.assertEqual(rows[1]["commits"], 1)
        self.assertIn("gone", res.stderr)

    def test_zero_commits_has_no_ratio(self):
        repo = self.make_repo("demo")
        commit(repo, "old", when=(datetime.now(timezone.utc) - timedelta(days=30)).isoformat())
        transcript(self.projects, "-x-demo", 100)
        res, log = run(self.tmp, f"demo:{repo}:*-demo*")
        row = json.loads(log.read_text())["repos"][0]
        self.assertEqual(row["commits"], 0)
        self.assertIsNone(row["tokens_per_commit"])

if __name__ == "__main__":
    unittest.main()
