#!/usr/bin/env python3
"""Tests for skills/handoff/scripts/handoff_label.py, the Herdr tab naming rules."""
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "handoff" / "scripts" / "handoff_label.py"
spec = importlib.util.spec_from_file_location("handoff_label", SCRIPT)
hl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hl)


class ComposeTest(unittest.TestCase):
    def test_precedence_topic_then_title_then_slug_then_project(self):
        self.assertEqual(hl.compose("p", topic="t", title="title", slug="slug"), "p · t")
        self.assertEqual(hl.compose("p", title="title", slug="slug"), "p · title")
        self.assertEqual(hl.compose("p", slug="some-slug"), "p · some slug")
        self.assertEqual(hl.compose("p"), "p")

    def test_title_with_a_placeholder_falls_through_to_the_slug(self):
        self.assertEqual(hl.compose("p", title="<Task Title / Slug>", slug="real-slug"), "p · real slug")

    def test_title_keeps_only_the_first_clause(self):
        cases = {
            "repair the 1.18 cleanup commit, push, then plan I-247": "repair the 1.18 cleanup commit",
            "Stampede music audition + all assets": "Stampede music audition",
            "ship one; ship two": "ship one",
            "fix tests — then celebrate": "fix tests",
            "brainstorm then build": "brainstorm",
        }
        for title, want in cases.items():
            with self.subTest(title=title):
                self.assertEqual(hl.compose("p", title=title, max_len=80), f"p · {want}")

    def test_explicit_topic_is_not_clause_split(self):
        self.assertEqual(hl.compose("p", topic="plan, then ship", max_len=80), "p · plan, then ship")

    def test_a_leading_repeat_of_the_project_is_stripped(self):
        self.assertEqual(
            hl.compose("play-joymify", title="play-joymify real audio shipped", max_len=80),
            "play-joymify · real audio shipped",
        )
        self.assertEqual(hl.compose("asset-studio", slug="asset-studio-f015-fix"), "asset-studio · f015 fix")
        self.assertEqual(hl.compose("Atlas", title="atlas: lanes"), "Atlas · lanes")

    def test_partial_project_word_is_not_stripped(self):
        self.assertEqual(hl.compose("play", slug="playground-reel"), "play · playground reel")

    def test_topic_that_is_only_the_project_leaves_the_project(self):
        self.assertEqual(hl.compose("atlas", slug="atlas"), "atlas")

    def test_length_boundaries(self):
        at_cap = "p · " + "a" * 16
        self.assertEqual(len(at_cap), 20)
        self.assertEqual(hl.compose("p", topic="a" * 16, max_len=20), at_cap)
        self.assertEqual(hl.compose("p", topic="alpha beta gamma", max_len=19), "p · alpha beta…")

    def test_single_word_over_the_cap_is_hard_cut(self):
        label = hl.compose("p", topic="x" * 100, max_len=20)
        self.assertEqual(len(label), 20)
        self.assertTrue(label.endswith("…"))

    def test_unicode_counts_characters_not_bytes(self):
        self.assertEqual(hl.compose("โปรเจกต์", topic="ทดสอบ ภาษาไทย", max_len=40), "โปรเจกต์ · ทดสอบ ภาษาไทย")

    def test_generation_survives_truncation_and_counts_toward_the_cap(self):
        label = hl.compose("p", topic="alpha beta gamma delta", source_label="p · old #4", max_len=20)
        self.assertTrue(label.endswith(" #5"), label)
        self.assertLessEqual(len(label), 20)

    def test_project_is_never_dropped_even_when_it_exceeds_the_cap(self):
        label = hl.compose("a-very-long-project-name-indeed", topic="topic", max_len=10)
        self.assertTrue(label.startswith("a-very-long-project-name-indeed"))

    def test_empty_inputs_never_crash_and_never_return_empty(self):
        self.assertEqual(hl.compose("", topic="", title="", slug="", source_label=""), "handoff")
        self.assertEqual(hl.compose("   ", topic="   "), "handoff")
        self.assertEqual(hl.compose("", topic="t"), "t")

    def test_output_is_one_line(self):
        self.assertNotIn("\n", hl.compose("p", topic="two\nlines"))


class GenerationTest(unittest.TestCase):
    def test_table(self):
        cases = [
            ("p · old", 2),
            ("p · old #2", 3),
            ("p · old #41", 42),
            ("[3] p · old #2", 3),
            ("Handoff: anything", 2),
            ("[2] Handoff: anything", 2),
            ("other · old #7", None),
            ("zsh", None),
            ("", None),
            (None, None),
        ]
        for source, want in cases:
            with self.subTest(source=source):
                self.assertEqual(hl.generation("p", source), want)


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)

    def test_prints_the_label(self):
        r = self.run_cli("--cwd-project", "p", "--topic", "t", "--source-label", "p · x #2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "p · t #3\n")

    def test_invalid_max_falls_back_to_the_default(self):
        r = self.run_cli("--cwd-project", "p", "--topic", "t", "--max", "abc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "p · t\n")


if __name__ == "__main__":
    unittest.main()
