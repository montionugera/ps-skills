# ps-interactive-learning-builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tested orchestration skill that researches, designs, builds, independently audits, verifies, and durably catalogs interactive educational websites.

**Architecture:** Keep the new skill declarative and thin. `SKILL.md` owns the gated orchestration; four reference files own artifact, learning-design, audit, and verification detail; `ps-commu-explain` continues to own application templates, preview lifecycle, and Chrome checks. A separate private `pnusso/learning-materials` repository stores the central catalog and independent topic projects.

**Tech Stack:** Markdown skill instructions, YAML agent metadata, Python standard-library `unittest`, Bash installer, GitHub Actions, Git, and `glab` for the approved private GitLab repository.

---

### Task 1: Write the skill contract tests first

**Files:**
- Create: `skills/ps-interactive-learning-builder/tests/test_skill.py`

- [ ] **Step 1: Create the test directory and failing contract test**

Create `skills/ps-interactive-learning-builder/tests/test_skill.py` with tests that load the future skill package and assert:

```python
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
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python3 -m unittest discover -s skills/ps-interactive-learning-builder/tests -v
```

Expected: failure because `SKILL.md`, references, and metadata do not exist.

- [ ] **Step 3: Commit the failing test**

```bash
git add skills/ps-interactive-learning-builder/tests/test_skill.py
git commit -m "test: define interactive learning skill contract"
```

### Task 2: Initialize and implement the skill package

**Files:**
- Create: `skills/ps-interactive-learning-builder/SKILL.md`
- Create: `skills/ps-interactive-learning-builder/agents/openai.yaml`
- Create: `skills/ps-interactive-learning-builder/references/artifact-contract.md`
- Create: `skills/ps-interactive-learning-builder/references/learning-design.md`
- Create: `skills/ps-interactive-learning-builder/references/audit-contract.md`
- Create: `skills/ps-interactive-learning-builder/references/verification-contract.md`
- Test: `skills/ps-interactive-learning-builder/tests/test_skill.py`

- [ ] **Step 1: Initialize the official skill skeleton**

Run:

```bash
python3 /Users/pnusso/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  ps-interactive-learning-builder \
  --path skills \
  --resources references \
  --interface 'display_name=Interactive Learning Builder' \
  --interface 'short_description=Build researched interactive learning experiences' \
  --interface 'default_prompt=Use $ps-interactive-learning-builder to research, design, build, audit, and verify an interactive learning project.'
```

Expected: the skill skeleton and `agents/openai.yaml` are created without scripts or assets. Preserve the already-created test file.

- [ ] **Step 2: Write the concise orchestration skill**

Write `SKILL.md` with only `name` and `description` frontmatter. Its body must use imperative language and include these ordered gates:

1. Frame learner, topic, sources, format, root, and acceptance criteria.
2. Create or resume the central private library with explicit approval before GitLab creation or push.
3. Research authoritative sources and create stable claim IDs.
4. Synthesize the knowledge map and choose structured course, explorable reference, or hybrid.
5. Produce curriculum, build specification, and acceptance matrix.
6. Delegate the temporary app and browser lifecycle to `ps-commu-explain` with one application writer and one server/browser owner.
7. Export the durable app and compare SHA-256 manifests.
8. Assign an isolated auditor and remediate critical/high findings.
9. Run final verification, update the catalog last, and hand off durable path, exact preview URL, evidence, and cleanup command.

Link each detailed contract directly from `SKILL.md`; do not duplicate its contents.

- [ ] **Step 3: Write the four reference contracts**

Write the exact artifact paths and catalog states in `artifact-contract.md`. Write objective selection, adaptive formats, assessment alignment, and financial controls in `learning-design.md`. Write auditor isolation, five audit dimensions, severities, remediation, and re-audit rules in `audit-contract.md`. Write research, tests, 80% executable-logic coverage, accessibility, browser, manifest, catalog-ordering, and failure evidence in `verification-contract.md`.

- [ ] **Step 4: Run tests and official validation to verify GREEN**

Run:

```bash
python3 -m unittest discover -s skills/ps-interactive-learning-builder/tests -v
python3 /Users/pnusso/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/ps-interactive-learning-builder
```

Expected: four unit tests pass and the validator prints a successful result.

- [ ] **Step 5: Commit the implementation**

```bash
git add skills/ps-interactive-learning-builder
git commit -m "feat: add interactive learning builder skill"
```

### Task 3: Integrate documentation and CI without overwriting existing changes

**Files:**
- Modify: `README.md`
- Modify: `.github/workflows/ci.yml`
- Test: `skills/ps-interactive-learning-builder/tests/test_skill.py`

- [ ] **Step 1: Add a failing repository-integration assertion**

Extend the test module with a method that asserts `README.md` contains the skill name and CI contains the test directory:

```python
    def test_repository_documents_and_runs_the_skill_tests(self) -> None:
        readme = (REPO / "README.md").read_text()
        ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("ps-interactive-learning-builder", readme)
        self.assertIn(
            "skills/ps-interactive-learning-builder/tests",
            ci,
        )
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```bash
python3 -m unittest \
  discover -s skills/ps-interactive-learning-builder/tests \
  -p test_skill.py -k repository_documents_and_runs_the_skill_tests -v
```

Expected: failure because the README and CI do not yet mention the new skill.

- [ ] **Step 3: Update README and CI narrowly**

Add one catalog row, one usage paragraph, and one development command to `README.md`. Add a Linux `unittest` CI job that runs:

```yaml
  ps-interactive-learning-builder:
    name: ps-interactive-learning-builder (unittest)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run skill contract tests
        run: python3 -m unittest discover -s skills/ps-interactive-learning-builder/tests -v
```

Preserve every pre-existing unstaged change in both files.

- [ ] **Step 4: Run integration and neighboring tests**

Run:

```bash
python3 -m unittest discover -s skills/ps-interactive-learning-builder/tests -v
python3 -m unittest discover -s skills/ps-babysit-everything/tests -v
python3 -m unittest discover -s skills/ps-agoda-pptx/tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit only the new integration hunks**

Stage the new README and CI hunks interactively or with an isolated patch so unrelated user edits remain unstaged, then commit:

```bash
git commit -m "ci: verify interactive learning skill"
```

### Task 4: Forward-test and audit the skill

**Files:**
- Modify if findings require it: `skills/ps-interactive-learning-builder/SKILL.md`
- Modify if findings require it: `skills/ps-interactive-learning-builder/references/*.md`
- Modify if findings require it: `skills/ps-interactive-learning-builder/tests/test_skill.py`

- [ ] **Step 1: Forward-test three isolated prompts**

Dispatch fresh subagents with only the skill path and one prompt each:

```text
Use $ps-interactive-learning-builder at /Users/pnusso/Workspace/ps-skills/skills/ps-interactive-learning-builder to plan an interactive OpenTelemetry learning project for backend engineers who understand HTTP but not distributed tracing. Stop before external writes.
```

```text
Use $ps-interactive-learning-builder at /Users/pnusso/Workspace/ps-skills/skills/ps-interactive-learning-builder to plan an interactive learning project for an internal codebase named Dragon Fruit. Required private sources are unavailable. Stop before external writes.
```

```text
Use $ps-interactive-learning-builder at /Users/pnusso/Workspace/ps-skills/skills/ps-interactive-learning-builder to plan a financial-statement breakdown for non-finance product managers using dated public-company data. Stop before external writes.
```

Expected: the outputs respectively exercise technical research, explicit internal-source gaps, and financial date/assumption/advice controls without producing unsupported claims.

- [ ] **Step 2: Run an independent skill audit**

Give a separate reviewer the skill directory, spec, plan, test results, and forward-test outputs. Require findings grouped by correctness, triggering, safety, maintainability, and test coverage with critical/high/medium/low severity. Fix all critical/high findings and record dispositions for medium/low findings in the implementation handoff.

- [ ] **Step 3: Run the full verification suite**

Run:

```bash
python3 /Users/pnusso/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/ps-interactive-learning-builder
python3 -m unittest discover -s skills/ps-interactive-learning-builder/tests -v
python3 -m unittest discover -s skills/ps-babysit-everything/tests -v
python3 -m unittest discover -s skills/ps-agoda-pptx/tests -v
git diff --check
```

Expected: validators and tests pass with no whitespace errors.

### Task 5: Bootstrap and push the approved private learning-library root

**Files:**
- Create: `/Users/pnusso/Workspace/Main/learning-materials/catalog.yaml`
- Create: `/Users/pnusso/Workspace/Main/learning-materials/shared/quality-rubric.md`
- Create: `/Users/pnusso/Workspace/Main/learning-materials/shared/source-policy.md`
- Create: `/Users/pnusso/Workspace/Main/learning-materials/topics/.gitkeep`

- [ ] **Step 1: Verify GitLab prerequisites and project absence**

Run:

```bash
command -v glab
GITLAB_HOST=gitlab.agodadev.io glab auth status --hostname gitlab.agodadev.io
GITLAB_HOST=gitlab.agodadev.io glab repo view pnusso/learning-materials
```

Expected: `glab` is authenticated. Continue with creation only when the final command reports that the project does not exist; if it exists, inspect it and avoid overwriting remote history.

- [ ] **Step 2: Create the minimal central library using the approved contracts**

Create a versioned empty catalog, shared rubric, source policy, and topics directory. The catalog must declare schema version `1` and an empty `topics` list. The policies must encode the source-to-evidence chain, ordered states including `audited`, financial controls, independent audit severities, and the rule that catalog promotion happens last.

- [ ] **Step 3: Run acceptance checks before Git initialization**

Run:

```bash
test -f /Users/pnusso/Workspace/Main/learning-materials/catalog.yaml
test -f /Users/pnusso/Workspace/Main/learning-materials/shared/quality-rubric.md
test -f /Users/pnusso/Workspace/Main/learning-materials/shared/source-policy.md
rg -q '^version: 1$' /Users/pnusso/Workspace/Main/learning-materials/catalog.yaml
rg -q '^topics: \[\]$' /Users/pnusso/Workspace/Main/learning-materials/catalog.yaml
rg -q 'audited' /Users/pnusso/Workspace/Main/learning-materials/shared/quality-rubric.md
rg -q 'source.*claim.*objective.*module.*interaction.*assessment.*verification' \
  /Users/pnusso/Workspace/Main/learning-materials/shared/source-policy.md
```

Expected: every command exits zero.

- [ ] **Step 4: Initialize, commit, create the private project, and push**

The user approved creation and first push in this design session. Run:

```bash
git -C /Users/pnusso/Workspace/Main/learning-materials init -b main
git -C /Users/pnusso/Workspace/Main/learning-materials add .
git -C /Users/pnusso/Workspace/Main/learning-materials commit -m "chore: initialize learning materials catalog"
GITLAB_HOST=gitlab.agodadev.io glab repo create pnusso/learning-materials \
  --private \
  --source /Users/pnusso/Workspace/Main/learning-materials \
  --remote origin \
  --push
```

Expected: the private project is created, `origin` targets `gitlab.agodadev.io/pnusso/learning-materials`, and `main` is pushed.

- [ ] **Step 5: Verify the remote result with evidence**

Run:

```bash
git -C /Users/pnusso/Workspace/Main/learning-materials status --short --branch
git -C /Users/pnusso/Workspace/Main/learning-materials remote -v
GITLAB_HOST=gitlab.agodadev.io glab repo view pnusso/learning-materials
```

Expected: the working tree is clean, `main` tracks `origin/main`, and GitLab reports private visibility.
