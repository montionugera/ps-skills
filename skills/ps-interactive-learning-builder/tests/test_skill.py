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
    def _read_reference(self, filename: str) -> str:
        path = REFERENCES / filename
        self.assertTrue(path.is_file(), filename)
        self.assertGreater(path.stat().st_size, 300, filename)
        return path.read_text()

    def test_skill_declares_gated_traceable_workflow(self) -> None:
        content = SKILL.read_text()
        self.assertTrue(
            content.startswith("---\nname: ps-interactive-learning-builder\n")
        )
        for expected in (
            "/Users/pnusso/Workspace/Main/learning-materials",
            "gitlab.agodadev.io/pnusso/learning-materials",
            "planned → researched → designed → built → audited → verified",
            "source → claim → objective → module → interaction → assessment → verification evidence",
            "ps-commu-explain",
            "Sourcegraph",
            "explicit approval",
            "remote creation",
            "push",
            "stable claim IDs",
            "structured course",
            "explorable reference",
            "hybrid",
        ):
            self.assertIn(expected, content)

    def test_artifact_contract_defines_paths_states_and_claim_ids(self) -> None:
        content = self._read_reference("artifact-contract.md")
        for expected in (
            "topics/<topic-slug>/",
            "research/01-brief.md",
            "research/02-research-strategy.md",
            "research/03-factsheet.md",
            "research/04-knowledge-map.md",
            "design/05-curriculum.md",
            "design/06-build-spec.md",
            "design/07-acceptance-matrix.md",
            "app/",
            "verification/08-audit-report.md",
            "verification/09-verification-report.md",
            "verification/manifest.sha256",
            "planned → researched → designed → built → audited → verified",
            "stable claim IDs",
        ):
            self.assertIn(expected, content)

    def test_learning_design_contract_defines_modes_and_financial_controls(self) -> None:
        content = self._read_reference("learning-design.md")
        for expected in (
            "structured course",
            "explorable reference",
            "hybrid",
            "valuation and retrieval dates",
            "explicit assumptions and formulas",
            "sensitivity analysis",
            "educational-not-personal-financial-advice",
        ):
            self.assertIn(expected, content)

    def test_audit_contract_defines_isolation_and_severities(self) -> None:
        content = self._read_reference("audit-contract.md")
        for expected in (
            "did not author",
            "Source and factual integrity",
            "Learning effectiveness",
            "Technical and security quality",
            "Accessibility and user experience",
            "Traceability and reproducibility",
            "critical",
            "high",
            "medium",
            "low",
            "cannot be the sole auditor",
        ):
            self.assertIn(expected, content)

    def test_verification_contract_defines_tests_ordering_and_failure_evidence(
        self,
    ) -> None:
        content = self._read_reference("verification-contract.md")
        for expected in (
            "unit tests",
            "integration tests",
            "end-to-end tests",
            "80%",
            "catalog update is the final operation",
            "preserve completed artifacts and raw evidence",
            "08-audit-report.md",
            "09-verification-report.md",
            "manifest.sha256",
        ):
            self.assertIn(expected, content)

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
