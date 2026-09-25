from __future__ import annotations

import os
import re
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

    def _run_installer(
        self, root: Path, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "CLAUDE_HOME": str(root / ".claude"),
            "AGENTS_HOME": str(root / ".agents"),
            "BIN_HOME": str(root / ".local" / "bin"),
        }
        return subprocess.run(
            ["bash", str(REPO / "install.sh"), *arguments],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _semantic_contract(self) -> str:
        paths = (
            SKILL,
            REFERENCES / "artifact-contract.md",
            REFERENCES / "learning-design.md",
            REFERENCES / "audit-contract.md",
            REFERENCES / "verification-contract.md",
        )
        return re.sub(r"\s+", " ", "\n".join(path.read_text() for path in paths)).lower()

    def _find_contract_contradictions(self, content: str) -> set[str]:
        normalized = re.sub(r"\s+", " ", content).lower()
        patterns = {
            "external write without approval": (
                r"\b(?:may|can|should|must) (?:create|push)[^.]{0,80}"
                r"\bwithout (?:explicit )?approval\b"
                r"|\bdo not require (?:explicit )?approval before "
                r"(?:creating|pushing|creating or pushing)\b"
                r"|\b(?:you )?need not require (?:explicit )?approval "
                r"(?:before|to) (?:create|creating|push|pushing)\b"
                r"|\b(?:explicit )?approval (?:is|shall be) not required\b"
            ),
            "artifact author self-acceptance": (
                r"\b(?:artifact )?authors? "
                r"(?:may|can|should|must|are allowed to) "
                r"(?:accept|approve|audit)[^.]{0,60}"
                r"\b(?:their|the) (?:own )?(?:artifacts?|work|scope)\b"
            ),
            "builder self-audit": (
                r"\bbuilders? (?:may|can|should|must|are allowed to) "
                r"(?:accept|approve|audit)[^.]{0,60}"
                r"\b(?:their|the) (?:own )?"
                r"(?:artifacts?|work|application|scope)\b"
            ),
            "catalog updated before gates": (
                r"(?<!not )(?<!never )\b"
                r"(?:(?:may|can|should|must) )?update the catalog[^.]{0,60}"
                r"\bbefore (?:all|the) (?:other |required )?gates? pass\b"
            ),
            "unsupported claims published": (
                r"\bunsupported claims? "
                r"(?:may|can|should|must|are allowed to) "
                r"(?:enter|appear in|be published in) (?:the )?application\b"
            ),
            "blocking audit findings accepted": (
                r"\bunresolved "
                r"(?:critical|high|critical or high|critical and high) findings? "
                r"(?:may|can|should|must|are allowed to|are allowed )"
                r"(?:pass|be accepted|permit|allow|advance|through)\b"
            ),
        }
        return {
            scenario
            for scenario, pattern in patterns.items()
            if re.search(pattern, normalized)
        }

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
            "Resolve the library root and remote before creation",
            "No artifact or audit dimension may be accepted solely by its author",
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

    def test_artifact_contract_defines_portable_resolution_order(self) -> None:
        content = self._read_reference("artifact-contract.md")
        for expected in (
            "explicit invocation input",
            "existing catalog or repository configuration",
            "environment variables",
            "defaults",
            "before creating or writing",
            "confirm the resolved root and remote with the user",
            "portable override",
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

    def test_audit_contract_defines_artifact_and_conflict_independence(self) -> None:
        content = self._read_reference("audit-contract.md")
        for expected in (
            "research strategy and source records",
            "claims and knowledge map",
            "curriculum, build specification, and acceptance matrix",
            "application source and assets",
            "test and browser evidence",
            "traceability and manifest evidence",
            "independence conflict",
            "record the conflict",
            "assign a different auditor",
            "No artifact or audit dimension may be accepted solely by its author",
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

    def test_verification_contract_defines_deterministic_manifest(self) -> None:
        content = self._read_reference("verification-contract.md")
        for expected in (
            "application source",
            "required assets",
            "configuration files",
            "lockfiles",
            "tests",
            "generated build directories",
            "cache directories",
            "dependency directories",
            "logs",
            "operating-system metadata",
            "preview runtime state",
            "POSIX relative paths",
            "sorted lexicographically by path",
            "<sha256>  <path>",
            "identical normalized file sets",
            "identical hashes",
            "report every missing, extra, or hash-mismatched path",
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

    def test_repository_catalog_and_ci_include_skill(self) -> None:
        readme = (REPO / "README.md").read_text()
        workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text()
        command = (
            "python3 -m unittest discover "
            "-s skills/ps-interactive-learning-builder/tests -v"
        )

        for expected in (
            "| **ps-interactive-learning-builder** |",
            "invoke `/ps-interactive-learning-builder <topic>`",
            command,
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, readme)

        job = workflow.split("  ps-interactive-learning-builder:\n", 1)[1]
        job = re.split(r"\n(?=  \S)", job, maxsplit=1)[0]
        self.assertIn("runs-on: ubuntu-latest", job)
        self.assertIn(command, job)

    def test_actual_contract_has_no_semantic_contradictions(self) -> None:
        self.assertEqual(
            self._find_contract_contradictions(self._semantic_contract()), set()
        )

    def test_contradiction_scanner_detects_unsafe_mutations(self) -> None:
        fixtures = {
            "external write without approval": (
                "Do not require explicit approval before creating or pushing.",
                "You need not require approval to push.",
            ),
            "artifact author self-acceptance": (
                "Artifact authors may audit and accept their own work.",
            ),
            "builder self-audit": (
                "Builders are allowed to approve their own application.",
            ),
            "catalog updated before gates": (
                "Update the catalog before all required gates pass.",
            ),
            "unsupported claims published": (
                "Unsupported claims are allowed to enter the application.",
            ),
            "blocking audit findings accepted": (
                "Unresolved critical or high findings are allowed through the audit gate.",
            ),
        }
        for expected, mutations in fixtures.items():
            for mutation in mutations:
                with self.subTest(expected=expected, mutation=mutation):
                    self.assertIn(
                        expected, self._find_contract_contradictions(mutation)
                    )

    def test_installer_links_skill_for_claude_and_codex(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self._run_installer(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            for destination in (
                root / ".claude" / "skills" / "ps-interactive-learning-builder",
                root / ".agents" / "skills" / "ps-interactive-learning-builder",
            ):
                self.assertTrue(destination.is_symlink())
                self.assertEqual(destination.resolve(), SKILL_DIR)

    def test_installer_preserves_foreign_symlink_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            foreign = root / "foreign"
            foreign.mkdir()
            destination = (
                root
                / ".agents"
                / "skills"
                / "ps-interactive-learning-builder"
            )
            destination.parent.mkdir(parents=True)
            destination.symlink_to(foreign)

            result = self._run_installer(root)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(destination.is_symlink())
            self.assertTrue(destination.samefile(foreign))
            self.assertIn("preserve (foreign symlink)", result.stderr)

    def test_installer_force_replaces_foreign_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            foreign = root / "foreign"
            foreign.mkdir()
            destination = (
                root
                / ".agents"
                / "skills"
                / "ps-interactive-learning-builder"
            )
            destination.parent.mkdir(parents=True)
            destination.symlink_to(foreign)

            result = self._run_installer(root, "--force")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(destination.is_symlink())
            self.assertEqual(destination.resolve(), SKILL_DIR)

    def test_installer_copy_mode_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self._run_installer(root, "--copy")
            second = self._run_installer(root, "--copy")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)

            for home in (".claude", ".agents"):
                destination = (
                    root / home / "skills" / "ps-interactive-learning-builder"
                )
                self.assertTrue(destination.is_dir())
                self.assertFalse(destination.is_symlink())
                self.assertEqual(
                    (destination / "SKILL.md").read_text(), SKILL.read_text()
                )

    def test_installer_symlink_mode_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self._run_installer(root)
            second = self._run_installer(root)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            destination = (
                root
                / ".agents"
                / "skills"
                / "ps-interactive-learning-builder"
            )
            self.assertTrue(destination.is_symlink())
            self.assertEqual(destination.resolve(), SKILL_DIR)

    def test_installer_help_documents_force(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self._run_installer(Path(temporary), "--help")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--force", result.stdout)
            self.assertIn("foreign symlinks", result.stdout)


if __name__ == "__main__":
    unittest.main()
