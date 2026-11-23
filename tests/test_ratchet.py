#!/usr/bin/env python3
"""bin/ratchet: door check, owner verdicts, frozen cases, calibrate, rounds (temp dirs only)."""
import hashlib, json, shlex, subprocess, sys, tempfile, unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "ratchet"

STUB = '''import json, os, sys
art = sys.argv[1]
out = sys.argv[sys.argv.index("--out") + 1]
json.load(open(sys.argv[sys.argv.index("--recipe") + 1]))
text = open(art).read()
if "CRASH" in text or os.path.exists("flaky.flag"):
    sys.exit(3)
ok = "BAD" not in text
json.dump({"all_pass": ok}, open(out, "w"))
sys.exit(0 if ok else 1)
'''
WEAK = '''import json, sys
json.dump({"all_pass": True}, open(sys.argv[sys.argv.index("--out") + 1], "w"))
'''
BROKEN = "import sys\nsys.exit(3)\n"
COUNTING = STUB.replace("text = open(art).read()", "text = open(art).read()\nopen('runs.log', 'a').write(art + '\\n')")
HOOK_MSG = {"ts": "2026-01-01T00:00:00+00:00", "source": "hook", "session": "s", "text": "good"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Repo:
    def __init__(self, tmp):
        self.root = Path(tmp).resolve()
        (self.root / "check.py").write_text(STUB)
        cfg = {"ledger": "ratchet", "kinds": {"mob": {
            "artifacts": "assets/mob/**/out.glb",
            "exclude": ["assets/mob/_rollback/**"],
            "input": "{dir}/recipe.quad.json",
            "check_cmd": f"{shlex.quote(sys.executable)} check.py {{artifact}} --recipe {{input}} --out {{out}}",
            "gate_files": ["check.py"],
            "slug_fields": ["bestiary_id", "tier"],
            "picture_roots": ["assets/mob"],
            "round_cap": 3}}}
        (self.root / ".ratchet.json").write_text(json.dumps(cfg))
        self.ledger = self.root / "ratchet"

    def build(self, name, text="GOOD", recipe=True, creature="mob-a", tier="mvp", max_tris=100):
        d = self.root / "assets" / "mob" / name / tier
        d.mkdir(parents=True, exist_ok=True)
        (d / "out.glb").write_text(f"{text} {name}")
        if recipe:
            (d / "recipe.quad.json").write_text(json.dumps(
                {"bestiary_id": creature, "tier": tier, "budgets": {"max_tris": max_tris}}))
        return d / "out.glb"

    def run(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              cwd=cwd or self.root, capture_output=True, text=True)

    def lines(self, name):
        p = self.ledger / name
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []

    def hook_msg(self, mid):
        self.ledger.mkdir(exist_ok=True)
        with open(self.ledger / "owner_msgs.jsonl", "a") as f:
            f.write(json.dumps({"id": mid, **HOOK_MSG}) + "\n")

    def hook_now(self, mid):
        from datetime import datetime, timezone
        self.ledger.mkdir(exist_ok=True)
        with open(self.ledger / "owner_msgs.jsonl", "a") as f:
            f.write(json.dumps({"id": mid, "ts": datetime.now(timezone.utc).isoformat(), "source": "hook",
                                "session": "s", "text": "good"}) + "\n")


class RatchetTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Repo(self._tmp.name)

    def test_no_marker_is_silent(self):  # R10
        with tempfile.TemporaryDirectory() as bare:
            for args in (["status"], ["gate", "x.glb"], ["calibrate"], ["switch", "a/b", "--what", "x"]):
                res = self.repo.run(*args, cwd=bare)
                self.assertEqual((res.returncode, res.stdout, res.stderr), (0, "", ""), args)

    def test_gate_pass_fail_error(self):  # R4, R5
        r = self.repo
        res = r.run("gate", r.build("a-v1"))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("ALLOW mob-a/mvp", res.stdout)
        res = r.run("gate", r.build("b-v1", text="BAD", creature="mob-b"))
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY check-fail", res.stderr)
        out = Path(res.stderr.split()[-1])
        self.assertTrue(out.is_absolute() and out.name.endswith(".out.json"), res.stderr)
        self.assertIs(json.loads(out.read_text())["all_pass"], False)
        res = r.run("gate", r.build("c-v1", text="CRASH", creature="mob-c"))
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY error", res.stderr)
        res = r.run("gate", r.build("d-v1", recipe=False, creature="mob-d"))
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY error", res.stderr)
        self.assertIn("input", res.stderr)

    def test_error_result_is_never_cached(self):
        r = self.repo
        art = r.build("a-v1")
        (r.root / "flaky.flag").write_text("x")
        res = r.run("gate", art)
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY error", res.stderr)
        (r.root / "flaky.flag").unlink()
        self.assertEqual(r.run("gate", art).returncode, 0)

    def test_gate_fails_closed_on_a_corrupt_ledger(self):
        r = self.repo
        art = r.build("a-v1")
        r.ledger.mkdir(exist_ok=True)
        (r.ledger / "verdicts.jsonl").write_text('{"half": ')
        res = r.run("gate", art)
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY error", res.stderr)

    def test_excluded_and_foreign_paths_are_denied(self):
        r = self.repo
        res = r.run("gate", r.build("_rollback/a-v1"))
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY error", res.stderr)
        other = r.root / "notes.txt"
        other.write_text("x")
        self.assertEqual(r.run("gate", other).returncode, 2)

    def test_rejected_freezes_case_and_blocks_the_same_file(self):  # R2
        r = self.repo
        art = r.build("a-v1")
        res = r.run("verdict", art, "rejected", "--quote", "ทดสอบข้อความไทย")
        self.assertEqual(res.returncode, 0, res.stderr)
        case = r.ledger / "cases" / sha(art)
        self.assertEqual(sha(case / "out.glb"), sha(art))
        self.assertTrue((case / "recipe.quad.json").is_file())
        v = r.lines("verdicts.jsonl")[-1]
        self.assertEqual((v["level"], v["slug"], v["sha256"]), ("rejected", "mob-a/mvp", sha(art)))
        msg = r.lines("owner_msgs.jsonl")[-1]
        self.assertEqual((msg["text"], msg["source"], msg["id"]), ("ทดสอบข้อความไทย", "agent", v["msg"]))
        res = r.run("gate", art)
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY rejected", res.stderr)

    def test_verdict_that_cannot_resolve_appends_nothing(self):  # R2 failure twin
        r = self.repo
        missing = r.root / "assets/mob/none/mvp/out.glb"
        no_input = r.build("d-v1", recipe=False, creature="mob-d")
        for art in (missing, no_input):
            res = r.run("verdict", art, "rejected", "--quote", "x")
            self.assertEqual(res.returncode, 1, art)
            self.assertEqual(r.lines("verdicts.jsonl"), [])
            self.assertEqual(r.lines("owner_msgs.jsonl"), [])
            self.assertFalse((r.ledger / "cases").exists())

    def test_satisfied_needs_a_hook_captured_message(self):  # R3
        r = self.repo
        art = r.build("a-v1")
        res = r.run("verdict", art, "satisfied", "--quote", "ok")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(r.lines("verdicts.jsonl")[-1]["level"], "for-now")
        r.hook_msg("m-hook0001")
        res = r.run("verdict", art, "satisfied", "--msg", "m-hook0001")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(r.lines("verdicts.jsonl")[-1]["level"], "satisfied")

    def test_stale_pass_is_rechecked_when_the_gate_changes(self):  # D4
        r = self.repo
        art = r.build("a-v1")
        self.assertEqual(r.run("gate", art).returncode, 0)
        (r.root / "check.py").write_text(STUB.replace('"BAD" not in text', '"GOOD" not in text'))
        res = r.run("gate", art)
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY check-fail", res.stderr)

    def test_input_change_must_be_declared(self):  # R8
        r = self.repo
        self.assertEqual(r.run("gate", r.build("a-v1")).returncode, 0)
        v2 = r.build("a-v2", max_tris=999)
        for _ in (1, 2):  # a denied gate records nothing, so a plain retry is denied again
            res = r.run("gate", v2)
            self.assertEqual(res.returncode, 2)
            self.assertIn("DENY inputs-changed", res.stderr)
        self.assertEqual(len(r.lines("shows.jsonl")), 1)
        res = r.run("gate", v2, "--inputs-changed", "boss tier needs more tris")
        self.assertEqual(res.returncode, 0, res.stderr)
        show = r.lines("shows.jsonl")[-1]
        self.assertEqual(show["inputs_why"], "boss tier needs more tris")
        self.assertIn("999", show["inputs_diff"])

    def test_pictures_are_registered_and_dry_run_records_nothing(self):  # R14 groundwork
        r = self.repo
        art = r.build("a-v1")
        pic = art.parent / "front.png"
        pic.write_bytes(b"\x89PNG fake")
        res = r.run("gate", art, "--dry-run")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(r.lines("shows.jsonl"), [])
        self.assertEqual(r.run("gate", art, "--pictures", pic).returncode, 0)
        self.assertEqual(r.lines("shows.jsonl")[-1]["pictures"], [sha(pic)])

    def test_calibrate_regression_blocks_every_show(self):  # R6, D5
        r = self.repo
        bad = r.build("b-v1", text="BAD", creature="mob-b")
        self.assertEqual(r.run("verdict", bad, "rejected", "--quote", "stretched").returncode, 0)
        res = r.run("calibrate")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(f"caught {sha(bad)[:12]}", res.stdout)
        self.assertIn(f"{sha(bad)[:12]} rejected -> caught", r.run("status").stdout)
        good = r.build("a-v1")
        self.assertEqual(r.run("gate", good).returncode, 0)
        for weaker in (WEAK, BROKEN):
            (r.root / "check.py").write_text(weaker)
            res = r.run("gate", good)
            self.assertEqual(res.returncode, 2, weaker)
            self.assertIn("DENY regression", res.stderr)
            self.assertIn(sha(bad)[:12], res.stderr)
        (r.root / "check.py").write_text(STUB)
        self.assertEqual(r.run("gate", good).returncode, 0)

    def test_blind_case_is_reported_not_blocking(self):
        r = self.repo
        art = r.build("a-v1")
        self.assertEqual(r.run("verdict", art, "rejected", "--quote", "looks wrong").returncode, 0)
        res = r.run("calibrate")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(f"blind {sha(art)[:12]}", res.stdout)
        self.assertIn(f"{sha(art)[:12]} rejected -> blind", r.run("status").stdout)
        res = r.run("gate", r.build("a-v2"))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"BLIND {sha(art)[:12]}", res.stdout)

    def test_satisfied_file_that_stops_passing_is_a_false_block(self):
        r = self.repo
        art = r.build("a-v1")
        r.hook_msg("m-hook0002")
        self.assertEqual(r.run("verdict", art, "satisfied", "--msg", "m-hook0002").returncode, 0)
        (r.root / "check.py").write_text(STUB.replace('"BAD" not in text', '"GOOD" not in text'))
        res = r.run("calibrate")
        self.assertEqual(res.returncode, 1)
        self.assertIn("false-block", res.stdout)
        self.assertIn("CALIBRATE regression", res.stdout)

    def test_round_cap_then_one_switch_then_parked(self):  # R7
        r = self.repo
        for i in (1, 2, 3):
            self.assertEqual(r.run("verdict", r.build(f"a-v{i}"), "for-now", "--quote", "meh").returncode, 0)
        v4 = r.build("a-v4")
        res = r.run("gate", v4)
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY round-cap", res.stderr)
        res = r.run("switch", "mob-a/mvp", "--what", "re-rig with auto-rig")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("SWITCHED mob-a/mvp", res.stdout)
        self.assertEqual(r.run("gate", v4).returncode, 0)
        res = r.run("switch", "mob-a/mvp", "--what", "again")
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY switch-used", res.stderr)
        for i in (4, 5, 6):
            self.assertEqual(r.run("verdict", r.build(f"a-v{i}"), "for-now", "--quote", "meh").returncode, 0)
        res = r.run("gate", r.build("a-v7"))
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY parked", res.stderr)

    def test_status_is_at_most_ten_lines(self):  # R13
        r = self.repo
        for i in range(50):
            art = r.build(f"s{i}-v1", creature=f"mob-s{i}")
            self.assertEqual(r.run("verdict", art, "for-now", "--quote", "meh").returncode, 0)
        res = r.run("status")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertLessEqual(len(res.stdout.strip().splitlines()), 10)
        self.assertIn("for-now 50", res.stdout)

    def test_corrupt_baseline_fails_closed(self):  # review I1
        r = self.repo
        bad = r.build("b-v1", text="BAD", creature="mob-b")
        self.assertEqual(r.run("verdict", bad, "rejected", "--quote", "stretched").returncode, 0)
        self.assertEqual(r.run("calibrate").returncode, 0)
        (r.ledger / "baseline.json").write_text('{"ts": ')
        (r.root / "check.py").write_text(WEAK)
        res = r.run("gate", r.build("a-v1"))
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY error", res.stderr)

    def test_deleting_the_baseline_does_not_reset_caught_cases(self):  # review I1
        r = self.repo
        bad = r.build("b-v1", text="BAD", creature="mob-b")
        self.assertEqual(r.run("verdict", bad, "rejected", "--quote", "stretched").returncode, 0)
        self.assertEqual(r.run("calibrate").returncode, 0)
        (r.ledger / "baseline.json").unlink()
        (r.root / "check.py").write_text(WEAK)
        res = r.run("gate", r.build("a-v1"))
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY regression", res.stderr)
        self.assertIn(sha(bad)[:12], res.stderr)

    def test_rejected_file_that_crashes_the_check_blocks_nothing_else(self):  # review I2
        r = self.repo
        crash = r.build("c-v1", text="CRASH", creature="mob-c")
        self.assertEqual(r.run("verdict", crash, "rejected", "--quote", "broken").returncode, 0)
        res = r.run("calibrate")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(f"error {sha(crash)[:12]}", res.stdout)
        self.assertEqual(r.run("gate", r.build("a-v1")).returncode, 0)

    def test_corrupt_config_fails_closed(self):  # review I3
        r = self.repo
        art = r.build("a-v1")
        (r.root / ".ratchet.json").write_text("{")
        res = r.run("gate", art)
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY error", res.stderr)
        self.assertNotIn("Traceback", res.stderr)

    def test_allow_is_printed_only_after_everything_succeeded(self):  # review I4
        r = self.repo
        art = r.build("a-v1")
        res = r.run("gate", art, "--pictures", art.parent / "missing.png")
        self.assertEqual(res.returncode, 2)
        self.assertNotIn("ALLOW", res.stdout)
        self.assertIn("DENY error", res.stderr)
        self.assertEqual(r.lines("shows.jsonl"), [])
        self.assertFalse((r.ledger / "inputs").exists())

    def test_rejected_is_sticky_until_the_owner_says_otherwise(self):  # review S1
        r = self.repo
        art = r.build("a-v1")
        self.assertEqual(r.run("verdict", art, "rejected", "--quote", "no").returncode, 0)
        self.assertEqual(r.run("verdict", art, "for-now", "--quote", "agent says ok").returncode, 0)
        res = r.run("gate", art)
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY rejected", res.stderr)
        r.hook_now("m-hook0003")
        self.assertEqual(r.run("verdict", art, "for-now", "--msg", "m-hook0003").returncode, 0)
        self.assertNotIn("DENY rejected", r.run("gate", art).stderr)

    def test_a_frozen_case_is_never_overwritten(self):  # review M1
        r = self.repo
        art = r.build("b-v1", text="BAD", creature="mob-b")
        self.assertEqual(r.run("verdict", art, "rejected", "--quote", "one").returncode, 0)
        case = r.ledger / "cases" / sha(art)
        before = (case / "recipe.quad.json").read_text()
        (art.parent / "recipe.quad.json").write_text(json.dumps({"bestiary_id": "mob-other", "tier": "mvp"}))
        self.assertEqual(r.run("verdict", art, "rejected", "--quote", "two").returncode, 0)
        self.assertEqual((case / "recipe.quad.json").read_text(), before)
        self.assertEqual(json.loads((case / "case.json").read_text())["slug"], "mob-b/mvp")

    def test_unknown_message_id_and_unknown_kind_are_usage_errors(self):  # review M2, M9
        r = self.repo
        art = r.build("a-v1")
        res = r.run("verdict", art, "for-now", "--msg", "m-nope")
        self.assertEqual(res.returncode, 1)
        self.assertEqual(r.lines("verdicts.jsonl"), [])
        self.assertEqual(r.run("calibrate", "--kind", "nope").returncode, 1)

    def test_status_never_runs_a_check(self):  # review M7
        r = self.repo
        art = r.build("a-v1")
        self.assertEqual(r.run("verdict", art, "rejected", "--quote", "no").returncode, 0)
        (r.root / "check.py").write_text(WEAK)  # new gate hash: nothing is cached for today's key
        listing = lambda: sorted(p.name for p in (r.ledger / "checks").glob("*"))
        before = listing()
        res = r.run("status")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"{sha(art)[:12]} rejected -> unknown", res.stdout)
        self.assertEqual(listing(), before)

    def test_only_a_later_owner_message_lifts_a_rejection(self):  # re-review I-1
        r = self.repo
        art = r.build("a-v1")
        r.hook_now("m-hook0010")
        self.assertEqual(r.run("verdict", art, "rejected", "--msg", "m-hook0010").returncode, 0)
        self.assertEqual(r.run("verdict", art, "for-now", "--msg", "m-hook0010").returncode, 0)
        self.assertIn("DENY rejected", r.run("gate", art).stderr)
        r.hook_now("m-hook0011")
        self.assertEqual(r.run("verdict", art, "no-comment", "--msg", "m-hook0011").returncode, 0)
        self.assertIn("DENY rejected", r.run("gate", art).stderr)
        self.assertEqual(r.run("verdict", art, "for-now", "--msg", "m-hook0011").returncode, 0)
        self.assertNotIn("DENY rejected", r.run("gate", art).stderr)

    def test_rejecting_marks_the_case_caught_at_once(self):  # re-review I-2
        r = self.repo
        bad = r.build("b-v1", text="BAD", creature="mob-b")
        self.assertEqual(r.run("verdict", bad, "rejected", "--quote", "stretched").returncode, 0)
        self.assertIs(json.loads((r.ledger / "cases" / sha(bad) / "case.json").read_text())["caught"], True)
        (r.root / "check.py").write_text(WEAK)
        res = r.run("gate", r.build("a-v1"))
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY regression", res.stderr)

    def test_a_current_baseline_hash_does_not_skip_the_regression_check(self):  # re-review I-2
        r = self.repo
        good = r.build("a-v1")
        (r.root / "check.py").write_text(WEAK)
        self.assertEqual(r.run("gate", good).returncode, 0)  # baseline now holds the weak gate's hash
        (r.root / "check.py").write_text(STUB)
        bad = r.build("b-v1", text="BAD", creature="mob-b")
        self.assertEqual(r.run("verdict", bad, "rejected", "--quote", "stretched").returncode, 0)
        (r.root / "check.py").write_text(WEAK)
        res = r.run("gate", good)
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY regression", res.stderr)

    def test_gate_help_and_usage_errors_never_exit_zero(self):  # re-review I-3
        r = self.repo
        art = r.build("b-v1", text="BAD", creature="mob-b")
        for args in (["gate", art, "-h"], ["gate", art, "--pictures", "-h"], ["gate"], ["gate", art, "--nope"]):
            res = r.run(*args)
            self.assertEqual(res.returncode, 2, args)
            self.assertNotIn("ALLOW", res.stdout)

    def test_an_erroring_case_is_checked_once_per_gate(self):  # re-review I-4
        r = self.repo
        (r.root / "check.py").write_text(COUNTING)
        crash = r.build("c-v1", text="CRASH", creature="mob-c")
        self.assertEqual(r.run("verdict", crash, "rejected", "--quote", "broken").returncode, 0)
        good = r.build("a-v1")
        (r.root / "runs.log").write_text("")
        self.assertEqual(r.run("gate", good).returncode, 0)
        runs = (r.root / "runs.log").read_text().splitlines()
        self.assertEqual(sum("cases" in line for line in runs), 1, runs)

    def test_bad_config_values_and_blank_reasons_are_denied(self):  # re-review minors
        r = self.repo
        self.assertEqual(r.run("gate", r.build("a-v1")).returncode, 0)
        res = r.run("gate", r.build("a-v2", max_tris=999), "--inputs-changed", "  ")
        self.assertEqual(res.returncode, 2)
        cfg = json.loads((r.root / ".ratchet.json").read_text())
        cfg["kinds"]["mob"]["round_cap"] = 0
        (r.root / ".ratchet.json").write_text(json.dumps(cfg))
        res = r.run("gate", r.build("a-v1"))
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY error", res.stderr)

    def test_a_case_folder_without_a_valid_case_file_fails_closed(self):  # re-review M6
        r = self.repo
        bad = r.build("b-v1", text="BAD", creature="mob-b")
        self.assertEqual(r.run("verdict", bad, "rejected", "--quote", "stretched").returncode, 0)
        case = r.ledger / "cases" / sha(bad) / "case.json"
        data = json.loads(case.read_text())
        for broken in ("", json.dumps({**data, "caught": "yes"})):
            case.write_text(broken)
            res = r.run("gate", r.build("a-v1"))
            self.assertEqual(res.returncode, 2, broken)
            self.assertIn("DENY error", res.stderr)
        case.unlink()
        res = r.run("gate", r.build("a-v1"))
        self.assertEqual(res.returncode, 2)
        self.assertIn("DENY error", res.stderr)


if __name__ == "__main__":
    unittest.main()
