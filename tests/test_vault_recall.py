#!/usr/bin/env python3
"""Tests for skills/agentic-vault/hooks/vault-recall.py (UserPromptSubmit knowledge recall)."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "skills" / "agentic-vault" / "hooks" / "vault-recall.py"

STUB = """#!/usr/bin/env python3
import os, sys
key = "STUB_QUERY_FILE" if "--query" in sys.argv else "STUB_CWD_FILE"
path = os.environ.get(key)
if path and os.path.exists(path):
    sys.stdout.write(open(path).read())
"""


def note(note_id, pad=0):
    return f"- {note_id} | Title {note_id} | 04_Knowledge/concepts/{note_id}.md | matched: alpha, beta | {'s' * pad}"


def block(*lines):
    return "<vault-context>\n" + "\n".join(lines) + "\n</vault-context>\n"


class TestVaultRecall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.stub = self.dir / "vault-engine"
        self.stub.write_text(STUB)
        self.stub.chmod(self.stub.stat().st_mode | stat.S_IEXEC)
        self.query_file = self.dir / "query.txt"
        self.cwd_file = self.dir / "cwd.txt"
        self.state = self.dir / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, prompt="how do I fix the codex quota problem", session="s1", env_extra=None, engine=None):
        env = {k: v for k, v in os.environ.items()
               if k not in ("VAULT_RECALL", "VAULT_CONTEXT_BOOTSTRAP", "CLAUDE_VAULT_SUMMARY")}
        env.update({
            "VAULT_ENGINE": str(engine or self.stub),
            "VAULT_RECALL_STATE": str(self.state),
            "STUB_QUERY_FILE": str(self.query_file),
            "STUB_CWD_FILE": str(self.cwd_file),
        })
        env.update(env_extra or {})
        payload = json.dumps({"session_id": session, "prompt": prompt, "cwd": str(self.dir)})
        proc = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def context_of(self, stdout):
        return json.loads(stdout)["hookSpecificOutput"]["additionalContext"]

    def test_injects_matching_note_as_additional_context(self):
        self.query_file.write_text(block(note("CONCEPT-a")))
        out = self.run_hook()
        data = json.loads(out)
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("- CONCEPT-a | Title CONCEPT-a |", self.context_of(out))
        self.assertTrue(self.context_of(out).startswith("<vault-context>\n"))

    def test_same_note_is_injected_once_per_session(self):
        self.query_file.write_text(block(note("CONCEPT-a")))
        self.assertIn("CONCEPT-a", self.run_hook())
        self.assertEqual(self.run_hook(), "")
        self.assertIn("CONCEPT-a", self.run_hook(session="s2"))

    def test_notes_seeded_from_session_start_are_not_repeated(self):
        self.cwd_file.write_text(block(note("CONCEPT-a")))
        self.query_file.write_text(block(note("CONCEPT-a"), note("CONCEPT-b")))
        ctx = self.context_of(self.run_hook())
        self.assertNotIn("CONCEPT-a", ctx)
        self.assertIn("CONCEPT-b", ctx)

    def test_task_notification_prompt_is_silent_and_creates_no_state(self):
        self.query_file.write_text(block(note("CONCEPT-a")))
        self.assertEqual(self.run_hook(prompt="<task-notification> Task finished with result"), "")
        self.assertFalse(self.state.exists())

    def test_at_most_two_notes_per_prompt(self):
        self.query_file.write_text(block(*[note(f"CONCEPT-{i}") for i in range(5)]))
        ctx = self.context_of(self.run_hook())
        self.assertEqual(ctx.count("\n- "), 2)

    def test_session_cap_of_2400_bytes_and_six_notes(self):
        total = 0
        ids = []
        for i in range(3):
            self.query_file.write_text(block(*[note(f"CONCEPT-{i}{j}", pad=800) for j in range(3)]))
            out = self.run_hook(prompt=f"prompt number {i} about codex quota")
            if out:
                ctx = self.context_of(out)
                lines = [l for l in ctx.splitlines() if l.startswith("- ")]
                total += sum(len(l.encode()) + 1 for l in lines)
                ids += [l[2:].split(" | ")[0] for l in lines]
        self.assertLessEqual(total, 2400)
        self.assertGreater(total, 0)
        self.assertEqual(len(ids), len(set(ids)))
        state = json.loads((self.state / "s1.json").read_text())
        self.assertLessEqual(len(state["ids"]), 6)
        self.assertLessEqual(state["bytes"], 2400)

    def test_session_cap_of_six_notes(self):
        for i in range(3):
            self.query_file.write_text(block(*[note(f"CONCEPT-{i}{j}") for j in range(2)]))
            out = self.run_hook(prompt=f"prompt number {i} about codex quota")
            self.assertEqual(self.context_of(out).count("\n- "), 2)
        self.query_file.write_text(block(note("CONCEPT-99")))
        self.assertEqual(self.run_hook(prompt="a fourth prompt about codex quota"), "")
        self.assertEqual(len(json.loads((self.state / "s1.json").read_text())["ids"]), 6)

    def test_oversized_note_is_skipped_not_blocking(self):
        self.query_file.write_text(block(note("CONCEPT-big", pad=1300), note("CONCEPT-small")))
        ctx = self.context_of(self.run_hook())
        self.assertNotIn("CONCEPT-big", ctx)
        self.assertIn("CONCEPT-small", ctx)

    def test_additional_context_bytes_capped_at_1200(self):
        # A note of size 1180 would fit if used starts at 0 (1180 <= 1200),
        # but with the 33-byte wrapper it produces a 1212-byte block (> 1200).
        # Starting used at 33 ensures it is skipped (33 + 1180 = 1213 > 1200).
        # Prefix length for CONCEPT-a is 89 bytes; pad 1090 makes line 1179 bytes, size 1180 bytes.
        near_limit_oversized = note("CONCEPT-a", pad=1090)
        fits = note("CONCEPT-b", pad=500)
        self.query_file.write_text(block(near_limit_oversized, fits))
        out = self.run_hook()
        ctx = self.context_of(out)
        self.assertNotIn("CONCEPT-a", ctx)
        self.assertIn("CONCEPT-b", ctx)
        self.assertLessEqual(len(ctx.encode()), 1200)

    def test_query_passes_limit_2(self):
        arg_file = self.dir / "args.json"
        engine = self.dir / "inspecting-engine"
        engine.write_text(f"""#!/usr/bin/env python3
import json, sys
open({repr(str(arg_file))}, "w").write(json.dumps(sys.argv[1:]))
""")
        engine.chmod(engine.stat().st_mode | stat.S_IEXEC)
        self.run_hook(engine=engine)
        args = json.loads(arg_file.read_text())
        self.assertIn("--limit", args)
        idx = args.index("--limit")
        self.assertEqual(args[idx + 1], "2")

    def test_slow_engine_times_out_and_is_recorded(self):
        slow = self.dir / "slow-engine"
        slow.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(5)\n")
        slow.chmod(slow.stat().st_mode | stat.S_IEXEC)
        start = time.time()
        self.assertIn("recall is down", self.context_of(self.run_hook(engine=slow)))
        self.assertLess(time.time() - start, 4)
        self.assertEqual([r["kind"] for r in self.rows("errors.jsonl")], ["timeout"])

    def test_corrupt_state_is_reset(self):
        self.query_file.write_text(block(note("CONCEPT-a")))
        self.state.mkdir(parents=True)
        (self.state / "s1.json").write_text("{broken")
        self.assertIn("CONCEPT-a", self.run_hook())

    def rows(self, name):
        path = self.state / name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_failing_engine_is_recorded_once_per_session(self):
        out = self.run_hook(engine="/usr/bin/false")
        self.assertEqual(self.context_of(out).count("\n"), 0)
        self.assertIn("recall is down", self.context_of(out))
        errors = self.rows("errors.jsonl")
        self.assertEqual([(r["kind"], r["session_id"]) for r in errors], [("exit", "s1")])
        self.assertEqual(set(errors[0]), {"ts", "session_id", "kind", "detail"})
        self.assertEqual(self.run_hook(engine="/usr/bin/false"), "")
        self.assertEqual(len(self.rows("errors.jsonl")), 1)
        self.assertEqual(self.rows("heartbeat.jsonl"), [])
        self.assertIn("recall is down", self.context_of(self.run_hook(engine="/usr/bin/false", session="s2")))
        self.assertEqual(len(self.rows("errors.jsonl")), 2)

    def test_missing_engine_is_recorded(self):
        out = self.run_hook(engine=self.dir / "nope")
        self.assertIn("recall is down", self.context_of(out))
        self.assertEqual([r["kind"] for r in self.rows("errors.jsonl")], ["missing"])

    def test_working_engine_leaves_one_heartbeat_per_session(self):
        self.query_file.write_text(block(note("CONCEPT-a")))
        self.run_hook()
        self.query_file.write_text(block(note("CONCEPT-b")))
        self.run_hook(prompt="a second prompt about codex quota")
        beats = self.rows("heartbeat.jsonl")
        self.assertEqual([(b["session_id"], b["ok"]) for b in beats], [("s1", True)])
        self.assertIn("ts", beats[0])
        self.assertEqual(self.rows("errors.jsonl"), [])

    def test_query_failure_after_a_good_seed_adds_no_error(self):
        flaky = self.dir / "flaky-engine"
        flaky.write_text("#!/bin/sh\ncase \"$*\" in *--query*) exit 1;; esac\n")
        flaky.chmod(flaky.stat().st_mode | stat.S_IEXEC)
        self.assertEqual(self.run_hook(engine=flaky), "")
        self.assertEqual(len(self.rows("heartbeat.jsonl")), 1)
        self.assertEqual(self.rows("errors.jsonl"), [])

    def test_opt_out_env_vars_are_silent(self):
        self.query_file.write_text(block(note("CONCEPT-a")))
        for key in ("VAULT_RECALL", "VAULT_CONTEXT_BOOTSTRAP", "CLAUDE_VAULT_SUMMARY"):
            self.assertEqual(self.run_hook(env_extra={key: "0"}), "", key)

    def test_short_and_slash_prompts_are_silent(self):
        self.query_file.write_text(block(note("CONCEPT-a")))
        self.assertEqual(self.run_hook(prompt="fix it"), "")
        self.assertEqual(self.run_hook(prompt="/model something long enough"), "")

    def test_demoted_notes_are_dropped(self):
        self.query_file.write_text(block(note("CONCEPT-a"), note("CONCEPT-b")))
        self.state.mkdir(parents=True)
        (self.state / "usage.json").write_text(json.dumps({"demoted": ["CONCEPT-a"]}))
        ctx = self.context_of(self.run_hook())
        self.assertNotIn("CONCEPT-a", ctx)
        self.assertIn("CONCEPT-b", ctx)

    def test_injections_are_logged(self):
        self.query_file.write_text(block(note("CONCEPT-a")))
        self.run_hook()
        rows = [json.loads(l) for l in (self.state / "injections.jsonl").read_text().splitlines()]
        self.assertEqual([(r["session_id"], r["note_id"]) for r in rows], [("s1", "CONCEPT-a")])

    def test_garbage_stdin_is_silent(self):
        proc = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True, timeout=10)
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_precision_eval_script(self):
        script = REPO_ROOT / "tools" / "vault-engine" / "precision_eval.sh"
        self.assertTrue(script.is_file() and os.access(script, os.X_OK))
        engine = self.dir / "stub-engine"
        engine.write_text("#!/usr/bin/env bash\necho '- NOTE-1 | Title 1 | path | '\necho '- NOTE-2 | Title 2 | path | '\n")
        engine.chmod(engine.stat().st_mode | stat.S_IEXEC)
        eval_set = self.dir / "set.jsonl"
        eval_set.write_text(
            json.dumps({"prompt": "p1", "relevant_ids": ["NOTE-1"]}) + "\n" +
            json.dumps({"prompt": "p2", "relevant_ids": ["NOTE-1"]}) + "\n"
        )
        env = {**os.environ, "VAULT_ENGINE": str(engine)}
        res80 = subprocess.run([str(script), str(eval_set), "80"], capture_output=True, text=True, env=env)
        self.assertEqual(res80.returncode, 1)
        self.assertIn("precision: 2/4 = 50.0% (min 80%)", res80.stdout)
        res50 = subprocess.run([str(script), str(eval_set), "50"], capture_output=True, text=True, env=env)
        self.assertEqual(res50.returncode, 0)
        self.assertIn("precision: 2/4 = 50.0% (min 50%)", res50.stdout)


if __name__ == "__main__":
    unittest.main()
