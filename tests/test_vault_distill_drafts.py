#!/usr/bin/env python3
"""Tests for bin/vault-distill, draft stage (I-040 R9-R10f, R19, shadow mode) and the default model calls."""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_vault_distill import DistillCase, load_distill  # noqa: E402
from test_vault_distill_gemini_api import ANSWER, GeminiStub, reply  # noqa: E402

class TestDraftStage(DistillCase):
    def session(self, sid, marker, run=True, **extra):
        path = self.transcript(sid, [f"the codegen drift gate failed on {sid} JEV_LESSON=0.95 {marker}"])
        self.write_inbox([self.inbox_line(sid, path)])
        return self.distill(**extra) if run else None

    def ledger(self):
        path = self.state / "drafts.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def by_session(self, sid):
        return [(k, e) for k, e in self.ledger().items() if sid in e["sessions"]]

    def report(self):
        return next((self.vault / "_inbox" / "agent" / "distill").glob("report-*.md")).read_text()

    def subs(self):
        return [c["sub"] for c in self.calls(self.jev_log)]

    def test_quote_missing_from_digest_is_no_evidence_and_never_scored(self):
        self.session("s-ev", "EXTRACT_BAD_EVIDENCE")
        [(key, entry)] = self.by_session("s-ev")
        self.assertEqual(entry["state"], "no-evidence")
        self.assertNotIn("score-draft", self.subs())
        self.assertTrue((self.vault / "_inbox" / "agent" / "distill" / key).exists())  # stays in the inbox

    def test_low_specific_score_is_junk_not_a_candidate(self):
        self.session("s-junk", "JEV_SPECIFIC=0.3")
        [(key, entry)] = self.by_session("s-junk")
        self.assertEqual(entry["state"], "junk")
        self.assertFalse(key.startswith("candidates/"))
        self.assertEqual(self.count(self.report(), "junk"), 1)

    def test_one_off_waits_and_a_recurrence_goes_to_review_citing_both(self):
        self.session("s-one", "TITLE=Codegen_drift_gate")
        [(key, entry)] = self.by_session("s-one")
        self.assertEqual(entry["state"], "candidate")
        self.assertTrue(key.startswith("candidates/"))
        self.assertEqual(self.calls(self.review_log), [])
        self.session("s-two", "TITLE=Codegen_drift_check JEV_SAME_LESSON=0.9")
        [items] = self.calls(self.review_log)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["sessions"], ["s-one", "s-two"])
        self.assertIn("s-two", items[0]["text"])
        self.assertEqual(self.count(self.report(), "recurred"), 1)

    def test_same_session_drafts_are_never_compared(self):
        self.session("s-self", "TITLE=Alpha_lesson")
        before = self.subs().count("same-lesson")
        ledger = self.ledger()
        key = next(iter(ledger))
        self.assertEqual(before, 0)
        self.assertEqual(ledger[key]["sessions"], ["s-self"])

    def test_high_stakes_goes_to_review_alone(self):
        self.session("s-high", "JEV_HIGH_STAKES=0.9")
        [items] = self.calls(self.review_log)
        self.assertEqual([i["sessions"] for i in items], [["s-high"]])

    def test_shadow_mode_never_touches_04_knowledge(self):
        before = sorted(p.name for p in (self.vault / "04_Knowledge").rglob("*"))
        res = self.session("s-pub", "JEV_HIGH_STAKES=0.9")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(sorted(p.name for p in (self.vault / "04_Knowledge").rglob("*")), before)
        report = self.report()
        self.assertEqual(self.count(report, "would_publish"), 1)
        self.assertEqual(self.count(report, "published"), 0)
        self.assertIn("would publish: candidates/", report)
        [(_, entry)] = self.by_session("s-pub")
        self.assertEqual(entry["state"], "would-publish")

    def test_reject_verdict_is_recorded(self):
        self.session("s-rej", "JEV_HIGH_STAKES=0.9", REVIEW_STUB_VERDICT="reject")
        [(_, entry)] = self.by_session("s-rej")
        self.assertEqual(entry["state"], "rejected")
        self.assertEqual(self.count(self.report(), "rejected"), 1)

    def test_review_failure_leaves_candidates_ready_and_exits_nonzero(self):
        res = self.session("s-rf", "JEV_HIGH_STAKES=0.9", REVIEW_STUB_FAIL="1")
        self.assertNotEqual(res.returncode, 0)
        [(_, entry)] = self.by_session("s-rf")
        self.assertEqual(entry["state"], "ready")
        self.assertEqual(self.count(self.report(), "would_publish"), 0)

    def test_no_lesson_and_worker_failure_and_invalid_draft(self):
        self.session("s-nol", "EXTRACT_NO_LESSON")
        self.assertEqual(self.seen()["s-nol"]["state"], "no-lesson")
        self.session("s-fail", "EXTRACT_FAIL")
        self.assertEqual(self.seen()["s-fail"]["state"], "invalid")
        self.session("s-inv", "EXTRACT_INVALID")
        [(key, entry)] = self.by_session("s-inv")
        self.assertEqual(entry["state"], "invalid")
        self.assertTrue((self.vault / "_inbox" / "agent" / "distill" / key).exists())
        self.session("s-big", "EXTRACT_BIG")
        [(_, entry)] = self.by_session("s-big")
        self.assertEqual(entry["state"], "invalid")  # over 1,500 bytes

    def test_draft_with_a_credential_is_quarantined_and_not_scored(self):
        self.session("s-sec", "EXTRACT_SECRET")
        [(_, entry)] = self.by_session("s-sec")
        self.assertEqual(entry["state"], "private")
        self.assertNotIn("score-draft", self.subs())
        self.assertTrue((self.vault / "_inbox" / "private" / "draft-s-sec.md").exists())

    def test_failed_score_is_retried_next_run(self):
        self.session("s-uns", "", JEV_STUB_FAIL="score-draft")
        [(_, entry)] = self.by_session("s-uns")
        self.assertEqual(entry["state"], "unscored")
        self.distill()  # empty inbox: only the rescoring happens
        [(key, entry)] = self.by_session("s-uns")
        self.assertEqual(entry["state"], "candidate")
        self.assertTrue(key.startswith("candidates/"))

    def test_nightly_extraction_cap_leaves_the_rest_pending(self):
        paths = {sid: self.transcript(sid, [f"lesson {sid} JEV_LESSON=0.95"]) for sid in ("c1", "c2", "c3")}
        self.write_inbox([self.inbox_line(sid, p) for sid, p in paths.items()])
        self.distill(VAULT_DISTILL_MAX="2")
        self.assertEqual(len(self.calls(self.extract_log)), 2)
        states = sorted(r["state"] for r in self.seen().values())
        self.assertEqual(states, ["extract-pending", "extracted", "extracted"])
        self.distill(VAULT_DISTILL_MAX="2")
        self.assertEqual(len(self.calls(self.extract_log)), 3)
        self.assertEqual({r["state"] for r in self.seen().values()}, {"extracted"})

    def test_at_most_5_same_lesson_comparisons(self):
        for i in range(7):
            self.session(f"old{i}", f"TITLE=Gate_lesson_{i}")
        self.jev_log.unlink()
        self.session("s-new", "TITLE=Gate_lesson_new")
        self.assertEqual(self.subs().count("same-lesson"), 5)

    def test_candidate_older_than_60_days_moves_to_expired(self):
        self.session("s-old", "TITLE=Old_lesson")
        ledger = self.ledger()
        [key] = list(ledger)
        ledger[key]["created"] = int(time.time()) - 61 * 86400
        (self.state / "drafts.json").write_text(json.dumps(ledger))
        self.distill()
        [(new_key, entry)] = self.by_session("s-old")
        self.assertEqual(entry["state"], "expired")
        self.assertTrue((self.vault / "_inbox" / "agent" / "distill" / new_key).exists())  # moved, not deleted
        self.assertIn(f"expired: {key}", self.report())

    def test_extractor_gets_project_ids_or_repo_tag(self):
        self.session("s-tag", "")
        self.assertEqual(self.calls(self.extract_log)[0]["tags"], ["repo:demo-repo"])
        (self.vault / "_meta" / "indexes" / "projects.jsonl").write_text(
            json.dumps({"id": "PROJ-demo", "release_repo": str(self.repo)}) + "\n")
        self.session("s-proj", "")
        req = self.calls(self.extract_log)[1]
        self.assertEqual((req["project_ids"], req["tags"]), (["PROJ-demo"], []))

    def test_report_counts_bytes_per_stage(self):
        self.session("s-bytes", "JEV_HIGH_STAKES=0.9")
        report = self.report()
        for stage in ("classify", "extract", "score", "review"):
            row = next(line for line in report.splitlines() if line.startswith(f"| {stage} |"))
            self.assertGreater(int(row.split("|")[2]), 0, row)


class TestDefaultModelCalls(GeminiStub, DistillCase):
    """The default extractor and reviewer: one Gemini API call each, with the HTTP call replaced in process."""

    def test_extract_default_is_one_gemini_api_call_that_renders_the_draft(self):
        code, out, err = self.call_default("--extract-default", self.request(), body=reply(json.dumps(ANSWER)))
        self.assertEqual(code, 0, err)
        draft = Path(json.loads(out)["path"])
        text = draft.read_text()
        for section in ("## When this applies", "## Rule", "## Why", "## Source", "## Evidence"):
            self.assertIn(section, text)
        self.assertIn('schema: "knowledge/v1"', text)
        self.assertIn('tags: ["auto-distilled", "repo:demo-repo"]', text)
        self.assertIn("- session `sess-1234abcd`", text)
        self.assertLessEqual(len(text.encode()), 1500)
        self.assertTrue(load_distill().evidence_ok(text, Path(json.loads(self.request())["digest_path"]).read_text()))
        self.assertEqual(len(self.sent), 1)

    def test_extract_default_no_lesson_and_garbage(self):
        code, out, _ = self.call_default("--extract-default", self.request(), body=reply('{"lesson": false}', tokens=9))
        self.assertEqual(json.loads(out), {"path": None, "reason": "no-lesson", "tokens": 9})
        code, _, _ = self.call_default("--extract-default", self.request(), body=reply("not json"))
        self.assertNotEqual(code, 0)

    def test_render_draft_global_scope_and_proposed_addition(self):
        vd = load_distill()
        _, text = vd.render_draft({"title": "Use worktrees", "scope": "global", "existing_note_id": "KNOW-worktrees",
                                   "evidence": []}, {"session_id": "s1", "tags": ["repo:x"], "project_ids": ["PROJ-x"]})
        self.assertIn('tags: ["auto-distilled", "global"]', text)
        self.assertIn("project_ids: []", text)
        self.assertIn('proposed_addition_to: "KNOW-worktrees"', text)

    def test_evidence_needs_8_characters(self):
        vd = load_distill()
        draft = "## Rule\nx\n\n## Evidence\n- `exit 2`\n"
        self.assertFalse(vd.evidence_ok(draft, "make check: exit 2"))
        self.assertTrue(vd.evidence_ok(draft.replace("`exit 2`", "`check: exit 2`"), "make check: exit 2"))


if __name__ == "__main__":
    unittest.main()
