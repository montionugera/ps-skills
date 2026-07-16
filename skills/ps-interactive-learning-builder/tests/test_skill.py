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
    def _parse_frontmatter(self, content: str) -> tuple[dict[str, str], str]:
        lines = content.splitlines()
        self.assertGreaterEqual(len(lines), 3)
        self.assertEqual(lines[0], "---")
        closing = lines.index("---", 1)
        fields = {}
        for line in lines[1:closing]:
            key, separator, value = line.partition(":")
            self.assertEqual(separator, ":", line)
            fields[key.strip()] = value.strip()
        return fields, "\n".join(lines[closing + 1 :])

    def _read_reference(self, filename: str) -> str:
        path = REFERENCES / filename
        self.assertTrue(path.is_file(), filename)
        self.assertGreater(path.stat().st_size, 300, filename)
        return path.read_text()

    def test_skill_declares_gated_traceable_workflow(self) -> None:
        content = SKILL.read_text()
        frontmatter, body = self._parse_frontmatter(content)
        self.assertEqual(frontmatter["name"], "ps-interactive-learning-builder")
        self.assertEqual(set(frontmatter), {"name", "description"})
        description = frontmatter["description"].lower()
        for trigger in ("research", "plan", "synthesi", "build", "audit", "verif"):
            with self.subTest(trigger=trigger):
                self.assertIn(trigger, description)

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

        ordered_gates = (
            "Frame learner",
            "Create or resume",
            "Research authoritative",
            "Synthesize the knowledge map",
            "Produce curriculum",
            "Delegate the temporary app",
            "Export the durable app",
            "Assign an isolated auditor",
            "Run final verification",
        )
        positions = [body.index(gate) for gate in ordered_gates]
        self.assertEqual(positions, sorted(positions))

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
            "measurable objectives",
            "map to relevant claims",
            "interaction, exercise, or assessment",
            "assessment alignment",
            "authoritative dated sources",
            "valuation and retrieval dates",
            "currencies and units",
            "explicit assumptions and formulas",
            "base, upside, and downside scenarios",
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
            "Critical and high findings block the `audited` state",
            "Medium and low findings require an explicit disposition",
            "rerun every affected build, test, browser, manifest, and audit check",
            "independent re-audit",
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
            "every published claim has evidence",
            "access date",
            "confidence",
            "freshness check",
            "unsupported claims do not enter the application",
            "keyboard navigation",
            "semantic structure",
            "contrast",
            "focus visibility",
            "reduced-motion behavior",
            "responsive sections are inspected in Chrome",
            "zero console errors",
            "source → claim → objective → module → interaction → assessment → verification evidence",
            "durable-preview SHA-256 equivalence",
            "durable build checks",
            "no unresolved critical or high findings",
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
