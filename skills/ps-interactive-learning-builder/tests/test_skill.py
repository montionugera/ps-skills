from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO = SKILL_DIR.parents[1]
SKILL = SKILL_DIR / "SKILL.md"
REFERENCES = SKILL_DIR / "references"


class InteractiveLearningBuilderSkillTest(unittest.TestCase):
    def test_skill_declares_gated_traceable_workflow(self) -> None:
        content = SKILL.read_text()
        self.assertTrue(
            content.startswith("---\nname: ps-interactive-learning-builder\n")
        )
        for expected in (
            "/Users/pnusso/Workspace/Main/learning-materials",
            "planned → researched → designed → built → audited → verified",
            "source → claim → objective → module → interaction → assessment → verification evidence",
            "ps-commu-explain",
            "Sourcegraph",
            "explicit approval",
            "structured course",
            "explorable reference",
            "hybrid",
        ):
            self.assertIn(expected, content)

    def test_references_cover_artifacts_learning_audit_and_verification(self) -> None:
        expected_files = (
            "artifact-contract.md",
            "learning-design.md",
            "audit-contract.md",
            "verification-contract.md",
        )
        for filename in expected_files:
            path = REFERENCES / filename
            self.assertTrue(path.is_file(), filename)
            self.assertGreater(path.stat().st_size, 300, filename)

        combined = "\n".join(
            (REFERENCES / filename).read_text() for filename in expected_files
        )
        for expected in (
            "08-audit-report.md",
            "09-verification-report.md",
            "critical",
            "high",
            "80%",
            "educational-not-personal-financial-advice",
            "manifest.sha256",
        ):
            self.assertIn(expected, combined)

    def test_package_has_metadata_and_no_duplicated_runtime(self) -> None:
        metadata = (SKILL_DIR / "agents" / "openai.yaml").read_text()
        self.assertIn('display_name: "Interactive Learning Builder"', metadata)
        self.assertIn("$ps-interactive-learning-builder", metadata)
        self.assertFalse((SKILL_DIR / "scripts").exists())
        self.assertFalse((SKILL_DIR / "assets").exists())

        all_text = "\n".join(
            path.read_text()
            for path in SKILL_DIR.rglob("*")
            if path.is_file() and path.suffix in {".md", ".yaml"}
        )
        for forbidden in ("TBD", "PLACEHOLDER", "python -m http.server"):
            self.assertNotIn(forbidden, all_text)

    def test_installer_links_skill_for_claude_and_codex(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {
                **os.environ,
                "CLAUDE_HOME": str(root / ".claude"),
                "AGENTS_HOME": str(root / ".agents"),
            }
            result = subprocess.run(
                ["bash", str(REPO / "install.sh")],
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for destination in (
                root / ".claude" / "skills" / "ps-interactive-learning-builder",
                root / ".agents" / "skills" / "ps-interactive-learning-builder",
            ):
                self.assertTrue(destination.is_symlink())
                self.assertEqual(destination.resolve(), SKILL_DIR)


if __name__ == "__main__":
    unittest.main()
