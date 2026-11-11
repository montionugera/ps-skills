#!/usr/bin/env python3
"""F-030: the default extractor and reviewer call the Gemini API; failures reach the report and the retry rules.

No test makes a network call or reads the Keychain: urlopen and gemini_key are replaced in process."""
import contextlib
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_vault_distill import DistillCase, load_distill  # noqa: E402

ANSWER = {"lesson": True, "title": "Make check exit 2", "summary": "Exit 2 means lint failed.",
          "when": "make check fails", "rule": "Run lint first.", "why": "Saves a cycle.",
          "scope": "repo", "evidence": ["make check failed with exit 2"]}
KEY = "test-key-not-real-123"


class Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self.body).encode()


def reply(text, finish="STOP", tokens=259, parts=None):
    parts = parts or [{"text": text}]
    return {"candidates": [{"content": {"parts": parts}, "finishReason": finish}],
            "usageMetadata": {"promptTokenCount": 15, "totalTokenCount": tokens}}


class GeminiStub:
    """Mixin for DistillCase: runs a default call in process with the HTTP call and key lookup replaced."""

    def request(self):
        digest = self.dir / "digest.txt"
        digest.write_text("signals: corrections=0\nuser: make check failed with exit 2\n")
        return json.dumps({"session_id": "sess-1234abcd", "digest_path": str(digest),
                           "out_dir": str(self.dir / "out"), "project_ids": [], "tags": ["repo:demo-repo"],
                           "related": ""})

    def call_default(self, flag, stdin, body=None, error=None, key=KEY):
        """Returns (exit code, stdout, stderr); self.sent holds the Request objects the code made."""
        vd = load_distill()
        self.sent = []

        def fake_urlopen(req, timeout=None):
            self.sent.append(req)
            if error:
                raise error
            return Resp(body)

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(vd.urllib.request, "urlopen", fake_urlopen), \
                mock.patch.object(vd, "gemini_key", lambda: key), mock.patch("sys.stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = vd.extract_default() if flag == "--extract-default" else vd.review_default()
        return code, out.getvalue(), err.getvalue()


class TestGeminiApi(GeminiStub, DistillCase):
    def extract(self, **kw):
        return self.call_default("--extract-default", self.request(), **kw)

    def test_stop_reply_renders_the_draft_and_reports_tokens(self):
        code, out, _ = self.extract(body=reply(json.dumps(ANSWER), tokens=321))
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertEqual(res["tokens"], 321)
        text = Path(res["path"]).read_text()
        for section in ("## When this applies", "## Rule", "## Why", "## Source", "## Evidence"):
            self.assertIn(section, text)

    def test_thought_part_is_skipped(self):
        parts = [{"text": "thinking about it", "thought": True}, {"text": json.dumps(ANSWER)}]
        code, out, _ = self.extract(body=reply("", parts=parts))
        self.assertEqual(code, 0)
        self.assertIn("path", json.loads(out))

    def test_max_tokens_is_a_fallback_naming_it(self):
        code, out, _ = self.extract(body=reply(json.dumps(ANSWER), finish="MAX_TOKENS"))
        res = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(res["fallback"])
        self.assertIn("MAX_TOKENS", res["error"])

    def test_block_reason_and_no_candidate_are_fallbacks(self):
        code, out, _ = self.extract(body={"promptFeedback": {"blockReason": "SAFETY"}})
        self.assertEqual((code, "SAFETY" in json.loads(out)["error"]), (0, True))
        code, out, _ = self.extract(body={"candidates": []})
        self.assertTrue(json.loads(out)["fallback"])

    def test_http_403_is_a_fallback_without_the_body(self):
        body = json.dumps({"error": {"code": 403, "message": "SECRET-BODY-TEXT", "status": "PERMISSION_DENIED"}})
        err = urllib.error.HTTPError("https://x", 403, "Forbidden", {}, io.BytesIO(body.encode()))
        code, out, _ = self.extract(error=err)
        res = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(res["error"], "HTTP 403 PERMISSION_DENIED")
        self.assertNotIn("SECRET-BODY-TEXT", out)

    def test_timeout_is_a_fallback_named_by_its_class(self):
        code, out, _ = self.extract(error=TimeoutError("slow"))
        self.assertEqual((code, json.loads(out)["error"]), (0, "TimeoutError"))

    def test_no_key_is_a_fallback_and_makes_no_http_call(self):
        code, out, _ = self.extract(key="", body=reply(json.dumps(ANSWER)))
        self.assertEqual(code, 0)
        self.assertIn("no Gemini key", json.loads(out)["error"])
        self.assertEqual(self.sent, [])

    def test_key_lookup_prefers_env_then_keychain_and_failure_is_empty(self):
        vd = load_distill()
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "from-env"}):
            self.assertEqual(vd.gemini_key(), "from-env")
        done = mock.Mock(returncode=0, stdout="from-keychain\n")
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(vd.subprocess, "run", return_value=done) as run:
            self.assertEqual(vd.gemini_key(), "from-keychain")
            self.assertEqual(run.call_args[0][0][:2], ["security", "find-generic-password"])
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(vd.subprocess, "run", side_effect=OSError):
            self.assertEqual(vd.gemini_key(), "")

    def test_key_only_in_header_and_body_has_schema(self):
        self.extract(body=reply(json.dumps(ANSWER)))
        [req] = self.sent
        self.assertEqual(req.get_header("X-goog-api-key"), KEY)
        self.assertNotIn(KEY, req.full_url)
        self.assertIn("gemini-3.8-flash:generateContent", req.full_url)
        body = json.loads(req.data)
        cfg = body["generationConfig"]
        self.assertIn("responseJsonSchema", cfg)
        self.assertEqual(cfg["responseMimeType"], "application/json")

    def test_review_default_prints_verdicts_and_uses_argon(self):
        verdicts = [{"draft": "candidates/a.md", "verdict": "publish", "reason": "solid"}]
        code, out, _ = self.call_default("--review-default", json.dumps([{"draft": "candidates/a.md", "text": "x"}]),
                                         body=reply(json.dumps({"verdicts": verdicts})))
        self.assertEqual((code, json.loads(out)), (0, verdicts))
        self.assertIn("gemini-4-argon:generateContent", self.sent[0].full_url)

    def test_answer_without_lesson_key_is_a_bad_answer(self):
        code, out, err = self.extract(body=reply('{"title": "x"}'))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("lesson", err)

    def test_unparsable_answer_is_a_bad_answer(self):
        code, _, err = self.extract(body=reply("not json"))
        self.assertEqual(code, 1)
        self.assertTrue(err)

    def test_review_without_verdicts_list_is_a_bad_answer(self):
        code, _, _ = self.call_default("--review-default", "[]", body=reply('{"verdicts": 3}'))
        self.assertEqual(code, 1)

    def test_no_agy_call_remains(self):
        src = (Path(__file__).resolve().parent.parent / "bin" / "vault-distill").read_text()
        self.assertNotIn('"agy"', src)


class TestNightly(DistillCase):
    def sessions(self, n, marker=""):
        paths = {f"s-{i}": self.transcript(f"s-{i}", [f"drift gate failed {i} JEV_LESSON=0.95 {marker}"]) for i in range(n)}
        self.write_inbox([self.inbox_line(sid, p) for sid, p in paths.items()])
        return list(paths)

    def cmd(self, body):
        script = self.dir / "ext.py"
        script.write_text("import json, os, sys\nreq = json.loads(sys.stdin.read())\n"
                          "open(os.environ['EXTRACT_STUB_LOG'], 'a').write(json.dumps(req) + '\\n')\n" + body)
        return f"{sys.executable} {script}"

    def report(self):
        return next((self.vault / "_inbox" / "agent" / "distill").glob("report-*.md")).read_text()

    def test_tool_failure_keeps_session_pending_and_next_one_works(self):
        body = ("if req['session_id'] == 'first':\n    print(json.dumps({'fallback': True, 'error': 'no login'}))\n"
                "else:\n    print(json.dumps({'path': None, 'tokens': 7}))\n")
        # order is by probability then insertion; use one failing sid and one good sid
        for sid in ("first", "second"):
            self.transcript(sid, [f"x {sid} JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line(s, self.dir / "transcripts" / f"{s}.jsonl") for s in ("first", "second")])
        self.distill(VAULT_DISTILL_EXTRACT_CMD=self.cmd(body))
        seen = self.seen()
        self.assertEqual((seen["first"]["state"], seen["first"]["tries"]), ("extract-pending", 1))
        self.assertEqual(seen["second"]["state"], "no-lesson")

    def test_third_tool_failure_is_invalid(self):
        self.sessions(1)
        (self.state).mkdir(parents=True)
        t = self.dir / "transcripts" / "s-0.jsonl"
        (self.state / "seen.jsonl").write_text(json.dumps(
            {"sid": "s-0", "transcript": str(t), "cwd": str(self.repo), "offset": 0, "state": "extract-pending",
             "tries": 2, "ts": 1}) + "\n")
        self.distill(VAULT_DISTILL_EXTRACT_CMD=self.cmd("print(json.dumps({'fallback': True, 'error': 'down'}))\n"))
        self.assertEqual(self.seen()["s-0"]["state"], "invalid")

    def test_two_tool_failures_stop_the_night(self):
        sids = self.sessions(5)
        self.distill(VAULT_DISTILL_EXTRACT_CMD=self.cmd("print(json.dumps({'fallback': True, 'error': 'down'}))\n"))
        self.assertEqual(len(self.calls(self.extract_log)), 2)
        self.assertEqual({self.seen()[s]["state"] for s in sids}, {"extract-pending"})
        self.assertEqual(self.report().count("extract failed: down"), 1)

    def test_extract_tokens_are_summed(self):
        self.sessions(2)
        self.distill(VAULT_DISTILL_EXTRACT_CMD=self.cmd("print(json.dumps({'path': None, 'tokens': 1000}))\n"))
        self.assertEqual(self.count(self.report(), "extract_tokens"), 2000)

    def test_jev_fallback_text_reaches_the_report(self):
        path = self.transcript("s-j", ["hello JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line("s-j", path)])
        script = self.dir / "jev.py"
        script.write_text("import json, sys\nsys.stdin.read()\nprint(json.dumps({'fallback': True, 'error': 'jev is sad'}))\n")
        self.distill(VAULT_DISTILL_JEV_CMD=f"{sys.executable} {script}")
        self.assertEqual(self.report().count("classify failed: jev is sad"), 1)

    def test_three_failures_with_same_stderr_make_one_report_line(self):
        self.sessions(3)
        self.distill(VAULT_DISTILL_EXTRACT_CMD=self.cmd("sys.stderr.write('trace\\nEXTRACT_BOOM\\n')\nsys.exit(1)\n"))
        report = self.report()
        self.assertEqual(report.count("extract failed: EXTRACT_BOOM"), 1)
        row = next(line for line in report.splitlines() if line.startswith("| extract |"))
        self.assertEqual(row.split("|")[4].strip(), "3")

    def test_secret_in_stderr_is_withheld(self):
        self.sessions(1)
        token = "ghp_" + "C" * 20
        self.distill(VAULT_DISTILL_EXTRACT_CMD=self.cmd(f"sys.stderr.write('bad {token}\\n')\nsys.exit(1)\n"))
        report = self.report()
        self.assertIn("extract failed: error text withheld", report)
        self.assertNotIn(token, report)

    def test_at_most_five_distinct_lines_per_stage_and_200_chars(self):
        self.sessions(8)
        self.distill(VAULT_DISTILL_EXTRACT_CMD=self.cmd(
            "sys.stderr.write('e' + req['session_id'] + 'z' * 300 + '\\n')\nsys.exit(1)\n"))
        lines = [ln for ln in self.report().splitlines() if ln.startswith("- extract failed: ")]
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(len(ln) <= len("- extract failed: ") + 200 for ln in lines))


if __name__ == "__main__":
    unittest.main()
