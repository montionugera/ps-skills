#!/usr/bin/env python3
"""Audit amendments tests for vault-distill (A1, A2, A3)."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.test_vault_distill import DISTILL, DistillCase, load_distill


class TestVaultDistillAudit(DistillCase):
    def test_a1_sibling_worktree_resolves_to_main_repo(self):
        # Temp git repo with a sibling worktree
        main_repo = self.dir / "repos" / "demo-main"
        main_repo.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=main_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=main_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=main_repo, check=True, capture_output=True)
        (main_repo / "README.md").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=main_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=main_repo, check=True, capture_output=True)

        hotfix_wt = self.dir / "repos" / "demo-hotfix-x"
        subprocess.run(["git", "worktree", "add", str(hotfix_wt)], cwd=main_repo, check=True, capture_output=True)

        self.assertEqual(load_distill().repo_root(str(hotfix_wt)), str(main_repo.resolve()))

        path = self.transcript("s-hotfix", ["fixing bug in hotfix worktree JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line("s-hotfix", path, cwd=str(hotfix_wt))])
        res = self.distill(VAULT_DISTILL_SKIP_REPOS="demo-main")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.seen()["s-hotfix"]["state"], "not-allowed")

    def test_a2_extract_pending_queued_and_not_counted_as_unsure(self):
        # Session marked extract-pending with p 0.5
        path = self.transcript("s-pend", ["unsure lesson topic JEV_LESSON=0.5"])
        self.state.mkdir(parents=True, exist_ok=True)
        rec = {
            "sid": "s-pend",
            "transcript": str(path),
            "cwd": str(self.repo),
            "offset": 0,
            "state": "extract-pending",
            "p": 0.5,
            "ts": 123456789,
        }
        (self.state / "seen.jsonl").write_text(json.dumps(rec) + "\n")

        res = self.distill()
        self.assertEqual(res.returncode, 0, res.stderr)
        report = next((self.vault / "_inbox" / "agent" / "distill").glob("report-*.md")).read_text()
        self.assertEqual(self.count(report, "extracted"), 1)
        self.assertEqual(self.count(report, "unsure"), 0)

    def test_a3_list_form_prompt_appears_in_digest(self):
        # A list-form text prompt appears in the digest
        user_list = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "please inspect the logs"}],
            },
        }
        path = self.dir / "transcripts" / "s-list.jsonl"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(user_list) + "\n")
        digest = load_distill().build_digest(str(path), 0)
        self.assertIn("user: please inspect the logs", digest)

    def test_a3_task_notification_prompt_does_not_appear_and_no_correction(self):
        # A <task-notification> prompt does not appear and is not counted as a correction
        notif = {
            "type": "user",
            "message": {
                "role": "user",
                "content": "<task-notification>Subagent completed</task-notification>",
            },
        }
        notif_correction = {
            "type": "user",
            "message": {
                "role": "user",
                "content": "<task-notification>no, that failed</task-notification>",
            },
        }
        real_user = {
            "type": "user",
            "message": {
                "role": "user",
                "content": "real prompt from human",
            },
        }
        path = self.dir / "transcripts" / "s-notif.jsonl"
        path.parent.mkdir(exist_ok=True)
        path.write_text("\n".join(json.dumps(m) for m in (notif, notif_correction, real_user)) + "\n")
        digest = load_distill().build_digest(str(path), 0)
        self.assertNotIn("<task-notification>", digest)
        self.assertIn("user: real prompt from human", digest)
        self.assertIn("corrections=0", digest)

    def test_f1_non_existent_hotfix_worktree_matches_skip_list(self):
        non_existent_cwd = str(self.dir / "repos" / "demo-repo-hotfix-x")
        self.assertEqual(load_distill().repo_root(non_existent_cwd), str(self.dir / "repos" / "demo-repo"))
        path = self.transcript("s-hotfix-dead", ["lesson in removed hotfix worktree JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line("s-hotfix-dead", path, cwd=non_existent_cwd)])
        res = self.distill(VAULT_DISTILL_SKIP_REPOS="demo-repo")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.seen()["s-hotfix-dead"]["state"], "not-allowed")

    def test_f1_empty_cwd_with_non_empty_skip_list_marked_not_allowed(self):
        path = self.transcript("s-empty-cwd", ["lesson in empty cwd session JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line("s-empty-cwd", path, cwd="")])
        res = self.distill(VAULT_DISTILL_SKIP_REPOS="demo-repo")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.seen()["s-empty-cwd"]["state"], "not-allowed")

    def test_f2_lone_surrogate_transcript_line_produces_digest_and_exits_normally(self):
        path = self.transcript("s-surrogate", ["hello \ud83d world JEV_LESSON=0.95"])

        digest = load_distill().build_digest(str(path), 0)
        self.assertIn("user: hello", digest)
        self.assertNotIn("\ud83d", digest)

        self.write_inbox([self.inbox_line("s-surrogate", path)])
        res = self.distill()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.seen()["s-surrogate"]["state"], "extracted")

    def test_f2_session_screening_exception_marked_error_and_batch_continues(self):
        vd = load_distill()
        path_bad = self.transcript("s-bad", ["bad session JEV_LESSON=0.95"])
        path_good = self.transcript("s-good", ["good session JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line("s-bad", path_bad), self.inbox_line("s-good", path_good)])

        orig_screen = vd.screen

        def flaky_screen(run, session, skip_repos):
            if session["sid"] == "s-bad":
                raise RuntimeError("unexpected failure during screening")
            return orig_screen(run, session, skip_repos)

        import unittest.mock
        with unittest.mock.patch.dict(os.environ, self.env()):
            with unittest.mock.patch.object(vd, "screen", side_effect=flaky_screen):
                run = vd.Run()
                vd.run_batch(run)

        seen = self.seen()
        self.assertIn("s-bad", seen)
        self.assertEqual(seen["s-bad"]["state"], "error")
        self.assertIn("s-good", seen)
        self.assertEqual(seen["s-good"]["state"], "extracted")

        report = next((self.vault / "_inbox" / "agent" / "distill").glob("report-*.md")).read_text()
        self.assertEqual(self.count(report, "errors"), 1)

    def test_f3_extracting_twice_keeps_both_files(self):
        answer = {"lesson": True, "title": "Same Title Lesson", "summary": "Summary",
                  "when": "When", "rule": "Rule", "why": "Why", "scope": "repo",
                  "evidence": ["test prompt"]}
        bindir = self.dir / "fakebin"
        bindir.mkdir(exist_ok=True)
        agy = bindir / "agy"
        fake_agy_script = """#!/usr/bin/env python3
import json, sys
print("Here is the answer:")
print(open(sys.argv[0] + ".reply").read())
"""
        agy.write_text(fake_agy_script)
        (bindir / "agy.reply").write_text(json.dumps(answer))
        agy.chmod(0o755)

        digest = self.dir / "digest.txt"
        digest.write_text("signals: corrections=0\nuser: test prompt\n")
        req = json.dumps({"session_id": "sess-1234abcd", "digest_path": str(digest),
                          "out_dir": str(self.dir / "out"), "project_ids": [], "tags": ["repo:demo-repo"],
                          "related": ""})

        curr_path = os.environ.get("PATH", "")
        env = {**self.env(), "PATH": f"{bindir}{os.pathsep}{curr_path}"}
        res1 = subprocess.run([sys.executable, str(DISTILL), "--extract-default"],
                              input=req, capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(res1.returncode, 0, f"res1 failed: err={res1.stderr} out={res1.stdout}")
        p1 = Path(json.loads(res1.stdout)["path"])

        res2 = subprocess.run([sys.executable, str(DISTILL), "--extract-default"],
                              input=req, capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(res2.returncode, 0, f"res2 failed: err={res2.stderr} out={res2.stdout}")
        p2 = Path(json.loads(res2.stdout)["path"])

        self.assertNotEqual(p1, p2)
        self.assertTrue(p1.exists())
        self.assertTrue(p2.exists())
        self.assertTrue(str(p2).endswith("-2.md"))

    def test_f4_oversized_draft_with_secret_is_quarantined_and_removed(self):
        token = "ghp_" + ("x" * 25)
        oversized_content = (
            '---\nschema: "knowledge/v1"\nid: "KNOW-secret-lesson"\nkind: "knowledge"\ntitle: "Secret Lesson"\n'
            'status: "draft"\ntags: ["auto-distilled"]\nproject_ids: []\n---\n\n'
            f"Here is a secret token: {token}\n\n"
            + ("padding line for oversized draft\n" * 100)
        )
        self.assertGreater(len(oversized_content.encode()), 1500)

        vd = load_distill()
        import unittest.mock
        with unittest.mock.patch.dict(os.environ, self.env()):
            run = vd.Run()
            draft_path = run.distill / "draft-oversized.md"
            draft_path.parent.mkdir(parents=True, exist_ok=True)
            draft_path.write_text(oversized_content)

            entry = {"sid": "s-secret", "digest": str(self.dir / "digest.txt"), "state": "new"}
            key = "draft-oversized.md"
            vd.admit_draft(run, key, entry)

            self.assertEqual(entry["state"], "private")
            self.assertFalse(draft_path.exists())
            self.assertEqual(run.counts["private"], 1)
            self.assertTrue((run.vault / "_inbox" / "private" / "draft-s-secret.md").exists())

    def test_f5_gitignore_quarantine_requires_exact_match(self):
        vd = load_distill()
        import unittest.mock
        with unittest.mock.patch.dict(os.environ, self.env()):
            run = vd.Run()
            (run.vault / ".gitignore").write_text("#_inbox/private/\n")
            vd.quarantine(run, "test-comment", "sensitive content")
            out = (run.vault / "_inbox" / "private" / "test-comment.md").read_text()
            self.assertIn("content withheld", out)

            (run.vault / ".gitignore").write_text("!_inbox/private/\n")
            vd.quarantine(run, "test-negated", "sensitive content")
            out = (run.vault / "_inbox" / "private" / "test-negated.md").read_text()
            self.assertIn("content withheld", out)

            (run.vault / ".gitignore").write_text("  _inbox/private/  \n")
            vd.quarantine(run, "test-exact", "sensitive content")
            out = (run.vault / "_inbox" / "private" / "test-exact.md").read_text()
            self.assertEqual(out, "sensitive content")

            (run.vault / ".gitignore").write_text("/_inbox/private/\n")
            vd.quarantine(run, "test-leading-slash", "sensitive content")
            out = (run.vault / "_inbox" / "private" / "test-leading-slash.md").read_text()
            self.assertEqual(out, "sensitive content")

    def test_gap_a_majority_errors_exit_code_2_and_report_written(self):
        vd = load_distill()
        # Direct check on exit_code_for
        run_unit = vd.Run()
        run_unit.counts["seen"] = 2
        run_unit.counts["errors"] = 2
        self.assertEqual(vd.exit_code_for(run_unit), 2)
        run_unit.counts["seen"] = 3
        run_unit.counts["errors"] = 1
        self.assertEqual(vd.exit_code_for(run_unit), 0)

        # Integration: two sessions that both raise -> exit code 2 and the report is still written
        p1 = self.transcript("s-a1", ["err1 JEV_LESSON=0.95"])
        p2 = self.transcript("s-a2", ["err2 JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line("s-a1", p1), self.inbox_line("s-a2", p2)])

        import io
        import unittest.mock

        def failing_screen(run, session, skip_repos):
            raise RuntimeError("screen failed")

        with unittest.mock.patch("sys.stdout", io.StringIO()), unittest.mock.patch("sys.stderr", io.StringIO()):
            with unittest.mock.patch.dict(os.environ, self.env()):
                with unittest.mock.patch.object(vd, "screen", side_effect=failing_screen):
                    run = vd.Run()
                    vd.run_batch(run)

        self.assertEqual(run.exit_code, 2)
        reports = list((self.vault / "_inbox" / "agent" / "distill").glob("report-*.md"))
        self.assertEqual(len(reports), 1)
        self.assertIn("exit: 2", reports[0].read_text())

        # One erroring session out of three -> exit code stays 0
        p3 = self.transcript("s-a3", ["ok3 JEV_LESSON=0.95"])
        p4 = self.transcript("s-a4", ["ok4 JEV_LESSON=0.95"])
        p5 = self.transcript("s-a5", ["err5 JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line("s-a3", p3), self.inbox_line("s-a4", p4), self.inbox_line("s-a5", p5)])

        orig_screen = vd.screen

        def one_error_screen(run, session, skip_repos):
            if session["sid"] == "s-a5":
                raise RuntimeError("one error")
            return orig_screen(run, session, skip_repos)

        with unittest.mock.patch("sys.stdout", io.StringIO()), unittest.mock.patch("sys.stderr", io.StringIO()):
            with unittest.mock.patch.dict(os.environ, self.env()):
                with unittest.mock.patch.object(vd, "screen", side_effect=one_error_screen):
                    run2 = vd.Run()
                    vd.run_batch(run2)

        self.assertEqual(run2.exit_code, 0)

    def test_gap_b_exception_logged_to_notes_and_traceback_printed(self):
        vd = load_distill()
        path_bad = self.transcript("s-b-bad", ["bad session JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line("s-b-bad", path_bad)])

        def failing_screen(run, session, skip_repos):
            raise TypeError("type failure in screening")

        import io
        import unittest.mock
        stderr_capture = io.StringIO()
        with unittest.mock.patch("sys.stdout", io.StringIO()), unittest.mock.patch("sys.stderr", stderr_capture):
            with unittest.mock.patch.dict(os.environ, self.env()):
                with unittest.mock.patch.object(vd, "screen", side_effect=failing_screen):
                    run = vd.Run()
                    vd.run_batch(run)

        # Check run.notes
        self.assertTrue(any("s-b-bad: TypeError: type failure in screening" in note for note in run.notes))
        # Check report
        report = next((self.vault / "_inbox" / "agent" / "distill").glob("report-*.md")).read_text()
        self.assertIn("s-b-bad", report)
        self.assertIn("TypeError", report)
        # Check traceback printed to stderr
        self.assertIn("Traceback (most recent call last):", stderr_capture.getvalue())
        self.assertIn("type failure in screening", stderr_capture.getvalue())

    def test_gap_c_extraction_exception_handled_and_batch_continues(self):
        vd = load_distill()
        path1 = self.transcript("s-c-bad", ["c bad session JEV_LESSON=0.99"])
        path2 = self.transcript("s-c-good", ["c good session JEV_LESSON=0.90"])
        self.write_inbox([self.inbox_line("s-c-bad", path1), self.inbox_line("s-c-good", path2)])

        orig_extract = vd.extract_session

        def failing_extract(run, session):
            if session["sid"] == "s-c-bad":
                raise RuntimeError("extract failed for s-c-bad")
            return orig_extract(run, session)

        import io
        import unittest.mock
        with unittest.mock.patch("sys.stdout", io.StringIO()), unittest.mock.patch("sys.stderr", io.StringIO()):
            with unittest.mock.patch.dict(os.environ, self.env()):
                with unittest.mock.patch.object(vd, "extract_session", side_effect=failing_extract):
                    run = vd.Run()
                    vd.run_batch(run)

        seen = self.seen()
        self.assertIn("s-c-bad", seen)
        self.assertEqual(seen["s-c-bad"]["state"], "error")
        self.assertIn("s-c-good", seen)
        self.assertEqual(seen["s-c-good"]["state"], "extracted")

        report_files = list((self.vault / "_inbox" / "agent" / "distill").glob("report-*.md"))
        self.assertEqual(len(report_files), 1)
        report = report_files[0].read_text()
        self.assertEqual(self.count(report, "errors"), 1)
        self.assertEqual(self.count(report, "extracted"), 1)
        self.assertIn("s-c-bad", report)
        self.assertIn("RuntimeError", report)








if __name__ == "__main__":
    unittest.main()
