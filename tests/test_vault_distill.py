#!/usr/bin/env python3
"""Tests for bin/vault-distill, session stage (I-040 R6-R8u, R11, R11a, R12, R13, R16)."""
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN = REPO_ROOT / "bin"
DISTILL = BIN / "vault-distill"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "vault_distill"


def load_distill():
    loader = importlib.machinery.SourceFileLoader("vault_distill", str(DISTILL))
    spec = importlib.util.spec_from_loader("vault_distill", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def stub(name):
    return f"{sys.executable} {FIXTURES / name}"


class DistillCase(unittest.TestCase):
    """Base: a throwaway vault, HOME and transcripts. No test methods here (imported by other test files)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.home = self.dir / "home"
        self.vault = self.dir / "vault"
        (self.home / ".claude").mkdir(parents=True)
        (self.vault / "_inbox" / "agent").mkdir(parents=True)
        (self.vault / "_meta" / "indexes").mkdir(parents=True)
        (self.vault / "04_Knowledge").mkdir()
        (self.vault / ".gitignore").write_text("_inbox/private/\n")
        self.live = self.vault / "_inbox" / "agent" / "session-summaries.md"
        self.state = self.home / ".claude" / "state" / "vault-distill"
        self.jev_log = self.dir / "jev.log"
        self.extract_log = self.dir / "extract.log"
        self.review_log = self.dir / "review.log"
        self.repo = self.dir / "repos" / "demo-repo"
        self.repo.mkdir(parents=True)
        self.engine = self.dir / "vault-engine"  # VAULT_ENGINE names one executable, as in vault-recall.py
        self.engine.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FIXTURES / "engine_stub.py"}" "$@"\n')
        self.engine.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def transcript(self, sid, prompts, age_seconds=7200, pad=4500, extra=()):
        """A Claude Code style transcript: user prompts, assistant text, and one tool result per turn."""
        path = self.dir / "transcripts" / f"{sid}.jsonl"
        path.parent.mkdir(exist_ok=True)
        lines = []
        for prompt in prompts:
            lines.append({"type": "user", "message": {"role": "user", "content": prompt}})
            lines.append({"type": "assistant", "message": {"content": [{"type": "text", "text": "Working on it."}]}})
            lines.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "content": "TOOL-OUTPUT-SHOULD-NOT-APPEAR " + "x" * 50}]}})
            lines.append({"type": "assistant", "message": {"content": [{"type": "text", "text": "Done: " + "y" * pad}]}})
        lines.extend(extra)
        path.write_text("".join(json.dumps(line) + "\n" for line in lines))
        then = time.time() - age_seconds
        os.utime(path, (then, then))
        return path

    def inbox_line(self, sid, transcript, cwd=None):
        cwd = cwd or str(self.repo)
        return (f"- **2026-11-10 10:00** — repo: `{os.path.basename(cwd)}` — cwd: `{cwd}` — "
                f"session: `{sid}` — transcript: `{transcript}`")

    def write_inbox(self, lines):
        header = "---\ntype: session-inbox\n---\n\n# Agent Session Inbox\n\n"
        self.live.write_text(header + "".join(line + "\n" for line in lines))

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("VAULT_DISTILL") and k not in ("TYPESAFE_API_KEY", "VAULT_ROOT", "VAULT_ENGINE")}
        env.update({
            "HOME": str(self.home), "VAULT_ROOT": str(self.vault), "VAULT_ENGINE": str(self.engine),
            "VAULT_DISTILL_JEV_CMD": stub("jev_stub.py"), "VAULT_DISTILL_EXTRACT_CMD": stub("extract_stub.py"),
            "VAULT_DISTILL_REVIEW_CMD": stub("review_stub.py"), "JEV_STUB_LOG": str(self.jev_log),
            "EXTRACT_STUB_LOG": str(self.extract_log), "REVIEW_STUB_LOG": str(self.review_log),
            "ENGINE_STUB_LOG": str(self.dir / "engine.log"),
        })
        env.update(extra)
        return env

    def distill(self, *args, **extra):
        return subprocess.run([sys.executable, str(DISTILL), *args], capture_output=True, text=True,
                              env=self.env(**extra), timeout=120)

    def calls(self, log):
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def seen(self):
        path = self.state / "seen.jsonl"
        recs = {}
        for line in (path.read_text().splitlines() if path.exists() else []):
            rec = json.loads(line)
            recs[rec["sid"]] = rec
        return recs

    def count(self, report, key):
        m = re.search(rf"^\| {key} \| (\d+) \|$", report, re.M)
        self.assertIsNotNone(m, f"{key} missing from report")
        return int(m.group(1))


class TestSessionStage(DistillCase):
    def test_secret_patterns_match_ps_skills_sync_without_home_rule(self):
        src = (BIN / "ps-skills-sync").read_text()
        shell = re.search(r"^SECRET_RE='(.*)'$", src, re.M).group(1).replace("'\"'\"'", "'")
        self.assertEqual(shell, load_distill().SECRET_RE.pattern + "|/Users/[a-z]+/")

    def test_new_files_pass_the_public_repo_secret_scan(self):
        src = (BIN / "ps-skills-sync").read_text()
        scan = re.compile(re.search(r"^SECRET_RE='(.*)'$", src, re.M).group(1).replace("'\"'\"'", "'"))
        for path in (DISTILL, Path(__file__), *FIXTURES.glob("*.py")):
            self.assertIsNone(scan.search(path.read_text()), path)

    def test_gate_outcomes_on_40_lines_for_3_sessions(self):
        paths = {sid: self.transcript(sid, [f"please fix the flaky build JEV_LESSON={p}"])
                 for sid, p in (("s-yes", 0.95), ("s-no", 0.05), ("s-mid", 0.5))}
        lines = [self.inbox_line(sid, paths[sid]) for _ in range(13) for sid in paths] + [self.inbox_line("s-yes", paths["s-yes"])]
        self.assertEqual(len(lines), 40)
        self.write_inbox(lines)
        res = self.distill("--dry-run")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.count(res.stdout, "extracted"), 1)
        self.assertEqual(self.count(res.stdout, "dropped"), 1)
        self.assertEqual(self.count(res.stdout, "unsure"), 1)
        sent = [c for c in self.calls(self.jev_log) if c["sub"] == "classify-lesson"]
        self.assertEqual(len(sent), 3)
        self.assertTrue(all(c["bytes"] <= 12000 for c in sent))
        self.assertEqual(self.calls(self.extract_log), [])  # dry run never extracts
        self.assertFalse((self.state / "seen.jsonl").exists())  # dry run records nothing

    def test_active_session_goes_back_to_live_inbox(self):
        fresh = self.transcript("s-live", ["still going JEV_LESSON=0.95"], age_seconds=300)
        for args in (("--dry-run",), ()):
            self.write_inbox([self.inbox_line("s-live", fresh)])
            res = self.distill(*args)
            self.assertIn(res.returncode, (0, 2), res.stderr)
            self.assertNotIn("s-live", self.seen())
            self.assertIn("session: `s-live`", self.live.read_text())
        self.assertEqual(self.calls(self.jev_log), [])

    def test_no_jev_key_means_all_unsure_no_extractor_and_nonzero_exit(self):
        paths = [self.transcript(f"s-{i}", [f"prompt {i} JEV_LESSON=0.95"]) for i in range(3)]
        self.write_inbox([self.inbox_line(f"s-{i}", p) for i, p in enumerate(paths)])
        env = self.env()
        env.pop("VAULT_DISTILL_JEV_CMD")  # the real bin/jev-gate, which reads TYPESAFE_API_KEY or ~/.zshrc
        res = subprocess.run([sys.executable, str(DISTILL)], capture_output=True, text=True, env=env, timeout=120)
        self.assertNotEqual(res.returncode, 0)
        report = (self.vault / "_inbox" / "agent" / "distill").glob("report-*.md")
        text = next(report).read_text()
        self.assertEqual(self.count(text, "unsure"), 3)
        self.assertEqual(self.calls(self.extract_log), [])
        self.assertEqual({r["state"] for r in self.seen().values()}, {"jev-failed"})

    def test_home_path_is_sent_but_a_credential_is_quarantined(self):
        home_path = "/Users/" + "x/repo"  # built at runtime: the public repo's own secret scan flags the literal
        token = "ghp_" + "A" * 20
        ok = self.transcript("s-home", [f"look at {home_path}/main.py JEV_LESSON=0.5"])
        bad = self.transcript("s-cred", [f"my key is {token} JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line("s-home", ok), self.inbox_line("s-cred", bad)])
        res = self.distill("--dry-run")
        self.assertIn(res.returncode, (0, 2), res.stderr)
        sent = self.calls(self.jev_log)
        self.assertEqual(len(sent), 1)  # only the home-path session went to Jev
        private = self.vault / "_inbox" / "private" / "digest-s-cred.md"
        self.assertIn(token, private.read_text())
        self.assertEqual(self.count(res.stdout, "private"), 1)

    def test_quarantine_without_gitignore_rule_writes_a_pointer_only(self):
        (self.vault / ".gitignore").write_text("")
        token = "ghp_" + "B" * 20
        bad = self.transcript("s-cred", [f"my key is {token}"])
        self.write_inbox([self.inbox_line("s-cred", bad)])
        self.distill()
        text = (self.vault / "_inbox" / "private" / "digest-s-cred.md").read_text()
        self.assertNotIn(token, text)

    def test_skip_repo_is_not_allowed_and_sends_nothing(self):
        path = self.transcript("s-skip", ["secret project work JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line("s-skip", path)])
        res = self.distill(VAULT_DISTILL_SKIP_REPOS="other, demo-repo")
        self.assertEqual(res.returncode, 0, res.stderr)
        report = next((self.vault / "_inbox" / "agent" / "distill").glob("report-*.md")).read_text()
        self.assertEqual(self.count(report, "not_allowed"), 1)
        self.assertRegex(report, r"\| classify \| 0 \|")
        self.assertEqual(self.calls(self.jev_log), [])
        self.assertEqual(self.seen()["s-skip"]["state"], "not-allowed")

    def test_worktree_cwd_resolves_to_its_repo_for_the_skip_list(self):
        path = self.transcript("s-wt", ["work in a worktree JEV_LESSON=0.95"])
        wt = str(self.repo / ".claude" / "worktrees" / "F-001-x")
        self.write_inbox([self.inbox_line("s-wt", path, cwd=wt)])
        self.distill(VAULT_DISTILL_SKIP_REPOS="demo-repo")
        self.assertEqual(self.seen()["s-wt"]["state"], "not-allowed")

    def test_unsure_twice_sends_top_3_and_marks_the_rest(self):
        probs = {"u1": 0.5, "u2": 0.6, "u3": 0.7, "u4": 0.4, "u5": 0.3}
        paths = {sid: self.transcript(sid, [f"topic {sid} JEV_LESSON={p}"]) for sid, p in probs.items()}
        self.write_inbox([self.inbox_line(sid, p) for sid, p in paths.items()])
        first = self.distill()
        self.assertNotEqual(first.returncode, 0)  # R16: more than half unsure
        self.assertEqual({r["state"] for r in self.seen().values()}, {"unsure-pending"})
        second = self.distill()  # the inbox is empty now: the pending sessions come from the seen-file
        self.assertIn(second.returncode, (0, 2), second.stderr)
        states = {sid: rec["state"] for sid, rec in self.seen().items()}
        self.assertEqual(states["u4"], "unsure")
        self.assertEqual(states["u5"], "unsure")
        self.assertTrue(all(states[s] != "unsure" for s in ("u1", "u2", "u3")), states)
        self.assertEqual(len([c for c in self.calls(self.jev_log) if c["sub"] == "classify-lesson"]), 10)

    def test_crashed_work_file_is_processed_first_and_deleted(self):
        path = self.transcript("s-crash", ["left over from a crash JEV_LESSON=0.05"])
        work = self.vault / "_inbox" / "agent" / "session-summaries.2026-11-09-234000.work.md"
        work.write_text(self.inbox_line("s-crash", path) + "\n")
        res = self.distill()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.seen()["s-crash"]["state"], "dropped")
        self.assertFalse(work.exists())
        self.assertEqual(list(self.live.parent.glob("*.work.md")), [])

    def test_rotation_renames_the_live_inbox(self):
        path = self.transcript("s-rot", ["rotate me JEV_LESSON=0.05"])
        self.write_inbox([self.inbox_line("s-rot", path)])
        self.distill()
        self.assertFalse(self.live.exists())  # the Stop hook's next append starts a fresh file
        self.assertEqual(self.seen()["s-rot"]["offset"], path.stat().st_size)

    def test_small_growth_since_offset_is_skipped(self):
        path = self.transcript("s-grow", ["first part JEV_LESSON=0.05"])
        self.write_inbox([self.inbox_line("s-grow", path)])
        self.distill()
        with open(path, "a") as handle:
            handle.write(json.dumps({"type": "user", "message": {"content": "tiny follow-up"}}) + "\n")
        os.utime(path, (time.time() - 7200, time.time() - 7200))
        self.write_inbox([self.inbox_line("s-grow", path)])
        res = self.distill()
        self.assertEqual(self.count(next(self.live.parent.glob("distill/report-*.md")).read_text(), "skipped_small"), 1)
        self.assertEqual(len(self.calls(self.jev_log)), 1, res.stdout)

    def test_digest_starts_at_the_recorded_offset(self):
        path = self.transcript("s-off", ["OLD-PROMPT-TEXT JEV_LESSON=0.05"])
        offset = path.stat().st_size
        with open(path, "a") as handle:
            for _ in range(3):
                handle.write(json.dumps({"type": "user", "message": {"content": "NEW-PROMPT-TEXT"}}) + "\n")
                handle.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "z" * 2000}]}}) + "\n")
        digest = load_distill().build_digest(str(path), offset)
        self.assertIn("NEW-PROMPT-TEXT", digest)
        self.assertNotIn("OLD-PROMPT-TEXT", digest)

    def test_missing_transcript_is_marked_no_transcript(self):
        self.write_inbox([self.inbox_line("s-gone", self.dir / "nope.jsonl")])
        self.distill()
        self.assertEqual(self.seen()["s-gone"]["state"], "no-transcript")

    def test_digest_drops_tool_output_and_counts_signals(self):
        failing = {"type": "user", "message": {"content": [
            {"type": "tool_result", "is_error": True, "content": "Error: test_x failed"}]}}
        passing = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "1 passed"}]}}
        blocked = {"type": "user", "message": {"content": [
            {"type": "tool_result", "is_error": True, "content": "PreToolUse:Edit hook error: blocked by guard_check"}]}}
        path = self.transcript("s-sig", ["no, that is wrong, use the worktree"],
                               extra=[failing, failing, passing, blocked])
        digest = load_distill().build_digest(str(path), 0)
        self.assertTrue(digest.startswith("signals: corrections=1 fail_then_pass=1 hook_blocks=1 repeated_errors=1\n"), digest[:120])
        self.assertNotIn("TOOL-OUTPUT-SHOULD-NOT-APPEAR", digest)
        self.assertIn("user: no, that is wrong", digest)

    def test_digest_is_cut_to_12000_bytes_head_and_tail(self):
        path = self.transcript("s-long", [f"prompt number {i}" for i in range(40)], pad=3000)
        digest = load_distill().build_digest(str(path), 0)
        self.assertLessEqual(len(digest.encode()), 12000)
        self.assertIn("prompt number 0", digest)
        self.assertIn("prompt number 39", digest)

    def test_kill_switch_does_nothing(self):
        path = self.transcript("s-off", ["anything JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line("s-off", path)])
        before = self.live.read_text()
        res = self.distill(VAULT_DISTILL="0")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(self.live.read_text(), before)
        self.assertFalse(self.state.exists())

    def test_report_file_and_report_flag(self):
        path = self.transcript("s-rep", ["report me JEV_LESSON=0.05"])
        self.write_inbox([self.inbox_line("s-rep", path)])
        self.distill()
        report = next((self.vault / "_inbox" / "agent" / "distill").glob("report-*.md")).read_text()
        for key in ("seen", "not_allowed", "dropped", "unsure", "no_lesson", "extracted", "no_evidence", "junk",
                    "candidates_waiting", "published", "merged", "rejected", "collisions", "archived"):
            self.count(report, key)
        self.assertEqual(self.count(report, "seen"), 1)
        self.assertIn("| classify |", report)
        res = self.distill("--report")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), report.strip())

    def test_seen_file_gets_one_line_per_session(self):
        paths = {sid: self.transcript(sid, [f"t {sid} JEV_LESSON=0.05"]) for sid in ("a1", "a2")}
        self.write_inbox([self.inbox_line(sid, p) for sid, p in paths.items()])
        self.distill()
        lines = (self.state / "seen.jsonl").read_text().splitlines()
        self.assertEqual(sorted(json.loads(line)["sid"] for line in lines), ["a1", "a2"])


if __name__ == "__main__":
    unittest.main()
