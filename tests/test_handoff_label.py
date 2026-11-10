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


class ParentNameTest(unittest.TestCase):
    """A named parent tab passes its name on; the topic is not used."""

    def test_named_parent_keeps_its_name_and_starts_the_chain_at_2(self):
        self.assertEqual(hl.compose("p", topic="ignored", source_label="Fix CI"), "Fix CI #2")

    def test_named_parent_counts_on(self):
        self.assertEqual(hl.compose("p", topic="ignored", source_label="Fix CI #4"), "Fix CI #5")

    def test_relay_and_index_prefixes_are_dropped(self):
        self.assertEqual(hl.compose("p", source_label="⏳ relay → Fix CI #2"), "Fix CI #3")
        self.assertEqual(hl.compose("p", source_label="[3] Fix CI #2"), "Fix CI #3")
        self.assertEqual(hl.compose("p", source_label="⏳ relay → [2] Fix CI"), "Fix CI #2")

    def test_legacy_project_label_keeps_only_its_topic(self):
        self.assertEqual(hl.compose("myapp", source_label="myapp · XYZ-789 push #2"), "XYZ-789 push #3")

    def test_long_parent_is_cut_at_a_word_to_16(self):
        label = hl.compose("p", source_label="ABC123 T1 await MR reviews")
        self.assertEqual(label, "ABC123 T1… #2")
        self.assertLessEqual(len(label), 16)

    def test_the_real_ledger_case(self):
        label = hl.compose("ABC-123-drop-unused-tables", topic="ABC-123 T3 chain settings",
                           source_label="ABC123 T3 app_settings - wait Ready")
        self.assertLessEqual(len(label), 16)
        self.assertTrue(label.startswith("ABC123"), label)

    def test_one_long_word_is_hard_cut(self):
        label = hl.compose("p", source_label="x" * 40)
        self.assertEqual(len(label), 16)
        self.assertTrue(label.endswith("… #2"), label)

    def test_unicode_counts_characters_not_bytes(self):
        self.assertEqual(hl.compose("p", source_label="ทดสอบ ภาษาไทย"), "ทดสอบ ภาษาไทย #2")


class DefaultParentTest(unittest.TestCase):
    """A parent with a default name falls back to topic, then title, then slug."""

    def test_shell_names_are_defaults(self):
        for shell in ("zsh", "bash", "-zsh", "fish", "", None):
            with self.subTest(shell=shell):
                self.assertEqual(hl.compose("p", topic="ship it", source_label=shell), "ship it")

    def test_herdrs_numbered_default_is_a_default(self):
        self.assertEqual(hl.compose("p", topic="ship it", source_label="3"), "ship it")

    def test_bare_project_name_is_a_default(self):
        self.assertEqual(hl.compose("myapp", topic="ship it", source_label="myapp"), "ship it")

    def test_legacy_handoff_doc_label_is_a_default_and_counts(self):
        self.assertEqual(hl.compose("p", topic="ship it", source_label="Handoff: anything"), "ship it #2")

    def test_precedence_topic_then_title_then_slug_then_project(self):
        self.assertEqual(hl.compose("p", topic="t", title="title", slug="slug"), "t")
        self.assertEqual(hl.compose("p", title="title", slug="slug"), "title")
        self.assertEqual(hl.compose("p", slug="some-slug"), "some slug")
        self.assertEqual(hl.compose("p"), "p")

    def test_title_with_a_placeholder_falls_through_to_the_slug(self):
        self.assertEqual(hl.compose("p", title="<Task Title / Slug>", slug="real-slug"), "real slug")

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
                self.assertEqual(hl.compose("p", title=title, max_len=80), want)

    def test_a_leading_repeat_of_the_project_is_stripped(self):
        self.assertEqual(hl.compose("play-joymify", title="play-joymify real audio", max_len=80), "real audio")
        self.assertEqual(hl.compose("Atlas", title="atlas: lanes"), "lanes")

    def test_partial_project_word_is_not_stripped(self):
        self.assertEqual(hl.compose("play", slug="playground-reel"), "playground reel")

    def test_topic_that_is_only_the_project_leaves_the_project(self):
        self.assertEqual(hl.compose("atlas", slug="atlas"), "atlas")

    def test_default_cap_is_16(self):
        label = hl.compose("p", topic="alpha beta gamma delta epsilon")
        self.assertEqual(label, "alpha beta…")


class SqueezeTest(unittest.TestCase):
    """A long name keeps the words that tell tabs apart (cases from the real handoff ledger)."""

    def test_a_cut_that_ends_on_a_word_keeps_that_word(self):
        self.assertEqual(hl.compose("p", source_label="ABC123 C1 MR gate"), "ABC123 C1 MR… #2")

    def test_a_trailing_space_in_the_cut_keeps_the_last_word(self):
        self.assertEqual(hl.compose("p", source_label="abc123 1056 sql test"), "abc123 1056… #2")

    def test_filler_and_the_project_name_are_dropped_first(self):
        self.assertEqual(hl.compose("myapp", source_label="myapp - fix the CI tests #2"), "fix CI tests #3")

    def test_nothing_changes_when_the_name_already_fits(self):
        self.assertEqual(hl.compose("myapp", source_label="ship the docs"), "ship the docs #2")
        self.assertEqual(hl.compose("myapp", source_label="myapp · XYZ-789 push"), "XYZ-789 push #2")

    def test_ticket_keys_lose_their_dash(self):
        self.assertEqual(hl.compose("myapp", source_label="myapp · XYZ-789 fix CI"), "XYZ789 fix CI #2")

    def test_long_words_shrink_when_that_makes_it_fit(self):
        self.assertEqual(hl.compose("p", source_label="ABC123 tracking"), "ABC123 tracki #2")

    def test_words_do_not_shrink_when_a_cut_is_needed_anyway(self):
        self.assertEqual(hl.compose("p", source_label="Acme chain G1 fix"), "Acme chain… #2")

    def test_a_cut_inside_a_word_beats_losing_most_of_the_room(self):
        self.assertEqual(hl.compose("p", source_label="ABC123 control tab"), "ABC123 contr… #2")

    def test_only_filler_and_punctuation_never_leaves_double_spaces(self):
        for source, cap in (("[2] the :", 7), ("the , , and #3", 11)):
            with self.subTest(source=source):
                label = hl.compose("fix", source_label=source, max_len=cap)
                self.assertNotIn("  ", label)
                self.assertLessEqual(len(label), cap)

    def test_a_tiny_cap_still_drops_filler(self):
        self.assertEqual(hl.compose("p", source_label="the fix", max_len=4), "fix")

    def test_squeezed_labels_never_exceed_the_cap(self):
        for name in ("ABC123 T3 app_settings - wait Ready", "a b c d e f g h i j k", "ab-12 cd-34 ef-56 gh-78"):
            with self.subTest(name=name):
                self.assertLessEqual(len(hl.compose("p", source_label=name)), 16)


class EdgeTest(unittest.TestCase):
    def test_empty_inputs_never_crash_and_never_return_empty(self):
        self.assertEqual(hl.compose("", topic="", title="", slug="", source_label=""), "handoff")
        self.assertEqual(hl.compose("   ", topic="   "), "handoff")
        self.assertEqual(hl.compose("", topic="t"), "t")

    def test_a_tiny_cap_keeps_the_name_and_never_exceeds_the_cap(self):
        self.assertEqual(hl.compose("p", source_label="abc #12", max_len=3), "abc")
        self.assertEqual(hl.compose("p", source_label="alpha", max_len=3), "al…")
        for cap in (1, 2, 3, 5):
            with self.subTest(cap=cap):
                self.assertLessEqual(len(hl.compose("", source_label="", max_len=cap)), cap)

    def test_output_is_one_line(self):
        self.assertNotIn("\n", hl.compose("p", topic="two\nlines"))
        self.assertNotIn("\n", hl.compose("p", source_label="two\nlines"))


class GenerationTest(unittest.TestCase):
    def test_table(self):
        cases = [
            ("p · old", 2),
            ("p · old #2", 3),
            ("p · old #41", 42),
            ("[3] p · old #2", 3),
            ("Handoff: anything", 2),
            ("[2] Handoff: anything", 2),
            ("⏳ relay → p · old #4", 5),
            ("other · old #7", 8),
            ("Fix CI #2", 3),
            ("zsh", None),
            ("", None),
            (None, None),
        ]
        for source, want in cases:
            with self.subTest(source=source):
                self.assertEqual(hl.generation(source), want)


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)

    def test_prints_the_label(self):
        r = self.run_cli("--cwd-project", "p", "--topic", "t", "--source-label", "p · x #2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "x #3\n")

    def test_invalid_max_falls_back_to_the_default(self):
        r = self.run_cli("--cwd-project", "p", "--topic", "alpha beta gamma delta", "--max", "abc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "alpha beta…\n")


if __name__ == "__main__":
    unittest.main()
