#!/usr/bin/env python3
"""Audit amendments tests for vault-distill (A1, A2, A3)."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.test_vault_distill import DistillCase, load_distill


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



if __name__ == "__main__":
    unittest.main()
