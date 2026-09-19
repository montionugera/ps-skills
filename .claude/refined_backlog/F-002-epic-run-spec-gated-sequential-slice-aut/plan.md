# epic run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Design `epic run E-NNN`, a sequential, spec-gated auto-chain that drives an epic's approved slices through refine, claim, implement, review and ship, stops at the first failed gate, and never promotes.

**Architecture:** `epic run` is a skill (`ps-release-workflow-epic-run`) that drives existing psrw verbs; psrw itself gains only two deterministic subcommands, `psrw epic plan` (read-only preflight that refuses unsafe starts) and `psrw epic sync` (merges the release branch into a slice's feature branch under the `_release` lock). All state stays in the existing catalogs, so a re-run resumes at the first unshipped slice; nothing in the code path can promote.

**Tech Stack:** Python >= 3.11 (standard library only, `dependencies = []`), pytest 9 with the existing `tests/conftest.py` fixtures, real `git` worktrees, Markdown skills. Engine: `engine/ps-release-workflow/`; skills: `skills/`.

**Spec:** `/Users/pasitnusso/workspace/tools/docs/superpowers/specs/2026-09-19-epic-run-design.md`

## Global Constraints

Exact values, copied from the spec and the codebase. Every task obeys all of them.

- **No new dependencies.** `pyproject.toml` keeps `dependencies = []`; dev extras stay `pytest`, `pytest-mock`, `pyyaml`. No new files under `lib/`.
- **Catalog writes** go only through `lib/state.py:mutate_state` (directly or via `lib/catalog.py` / `lib/epic.py` helpers). Every mutate+commit pair holds `file_lock(get_release_worktree(repo))`. **Never hold `file_lock` across a hook** (`precheck.sh`, `epic-check.sh`, deploy). `epic plan` writes nothing; `epic sync` holds the lock only for its own read-and-merge.
- **Every CLI failure is one `ERROR: ...` line on stderr and exit 1**, never a traceback (existing `scripts/epic.py:main` contract).
- **SKILL.md bodies are at most 40 non-blank lines** (`LINE_BUDGET = 40` in `tests/test_docs_single_source.py`). A `Mechanics:` link may use only these anchors: `d11-backlog-routing`, `gates`, `promote-sequence`, `state-layout`, `guard-guarantees`. The slash form `/ps-release-workflow:` is forbidden everywhere in a skill (write `ps-release-workflow:epic-run` as a heading, never with a leading slash). Frontmatter keeps exactly two `---` lines.
- **`epic run` never runs `psrw promote`, `psrw ship --deploy`, or any merge to main.** Ship is always `--no-deploy`. No task in this plan performs those either.
- **One commit per task; never `git commit --amend`.** Review fixes are a NEW commit. Every commit message ends with the line `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- **All edits happen in the claimed feature worktree** (`$WT`, created by Task 0), NEVER in the `/Users/pasitnusso/ps-skills` main checkout: the PreToolUse guard blocks Edit/Write there by filesystem location, regardless of branch.
- **Test command** (always from the engine dir of the worktree): `cd "$ENG" && python3 -m pytest <files> -q 2>&1 | tail -15`.
- **Out of scope** (spec section 8): parallel slices, cross-repo epics, a slice dependency graph, promote/deploy, an `approved` marker in spec frontmatter, any LLM dispatch inside psrw, fixing the ship rollback defect.

**Shell variables.** Shell state does not persist between steps. Start every command block that touches the worktree with:

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
ENG="$WT/engine/ps-release-workflow"
```

## Spec vs. code: mismatches found while reading the real code

Resolved in favor of the real code. Each is implemented as stated here, not as the spec words it.

1. **How `failed_verification` is represented.** It is the literal string `status == "failed_verification"` on the epic catalog entry (`lib/epic.py:mark_epic_failed`). The full status set is `open | verifying | verified | failed_verification | promoted`. `plan` refuses `verified` and `promoted` (spec) **and also `verifying`** (spec silent): ship's CAS only wins from `open|failed_verification`, so a `verifying` epic would make the last ship return `epic_outcome: null` and the chain would misreport "incomplete".
2. **The skeleton the spec wants to reuse is not the skeleton fanout writes.** `epic_fanout` writes its own inline spec text; `_is_untouched_skeleton(text, IDEA_SPEC_TEMPLATE)` (from `new_idea.py`) would never match it. Task 1 extracts `_fanout_idea_spec(title, idea_id)` as the single source that fanout writes and `plan` compares against, and `plan` also accepts an unedited `psrw idea` skeleton as a skeleton.
3. **`epic_outcome` is null for a second reason.** Besides "epic not complete", it is null when ship loses the CAS (epic already `verifying`/`verified`/`promoted`). The skill's wording covers both.
4. **Review anchor.** The spec says review `<sync-sha>..HEAD` using the post-merge sha. On a real (non-fast-forward) merge that sha is the merge commit and would hide commits made before the sync. `epic sync` prints both `sha` (post-merge, as the spec says) and `base` (the release HEAD that was merged); the skill reviews `git diff <base> HEAD`, which is exactly the slice's own work. For a fast-forward, `sha == base`.
5. **Resume rule tightened.** The spec says a claimed slice with commits beyond the sync point skips to review. A slice stopped mid-implementation would then ship half-done. The skill instead always re-dispatches the implementer on a resumed slice, telling it which plan tasks are already ticked.
6. **`epic sync` also refuses a dirty tree** (spec silent): `git merge --abort` after a merge that began on a dirty tree cannot restore the user's edits.
7. **The main checkout has no epic layer.** `main` lacks `scripts/epic.py`, `lib/epic.py` and both epic skills (they exist only on `release/1.1`), and the installed `psrw` is main's engine. This work builds on unpromoted F-001 code, so Task 0 merges `release/1.1` into the feature branch by hand (the manual form of what `epic sync` will do), and all psrw calls run from the branch's own engine.
8. **`ps-skills` has no `scripts/precheck.sh`.** `psrw epic plan` on this very repo needs `--allow-no-precheck`, and `psrw ship` on this work skips Gate 1 with only a warning. Task 5 therefore runs the full pytest suite by hand before shipping.
9. **The stale `psrw epic --help` summary is fixed in Task 2, not filed.** It is caused by adding these subcommands; only the ship rollback defect and the stale refine skill text go to `known-issues.md`.
10. **`refine` copies the idea folder, it does not move it** (`shutil.copytree`). That is why `plan` can read a refined or claimed slice's idea `spec.md`. The refine skill's "moves the folder" and "fresh skeleton" wording is stale (filed in Task 4).

## File Structure

Created:

- `skills/ps-release-workflow-epic-run/SKILL.md` — the agent-driven loop, 35 body lines, never-promote rule, `#gates` anchor.
- `engine/ps-release-workflow/tests/test_epic_run.py` — unit tests for `epic plan` and `epic sync` (real git, real catalogs).
- `engine/ps-release-workflow/tests/test_epic_run_e2e.py` — the psrw verbs a two-slice chain calls, composed, with only the LLM stubbed.
- `engine/ps-release-workflow/tests/test_epic_run_skill.py` — repo-relative lint of the new skill and of the five auto-chain bans (runs in CI, unlike `test_docs_single_source.py`).

Modified:

- `engine/ps-release-workflow/scripts/epic.py` — adds `EpicPlanError`, `EpicSyncError`, `_fanout_idea_spec`, `epic_plan`, `epic_sync`, the `plan` and `sync` subcommands; `epic_fanout` now writes its spec via `_fanout_idea_spec`.
- `engine/ps-release-workflow/bin/psrw` — one-line `epic` verb summary.
- `engine/ps-release-workflow/tests/conftest.py` — fixtures `epic_repo_raw`, `idea_spec`, `epic_repo`.
- `skills/ps-release-workflow-{idea,refine,claim,epic-open,epic-fanout}/SKILL.md` — name `epic-run` as the sanctioned exception (body and frontmatter description).
- `engine/ps-release-workflow/docs/lifecycle.md` — new subsection "Epic run: the sanctioned auto-chain" under `#gates`.
- `engine/ps-release-workflow/docs/known-issues.md` — ship rollback defect, stale refine skill text, one sentence on sibling blindness.

---

## Task 0: Preconditions

**Goal of this task:** the work has a home in the psrw lifecycle (a claimed feature worktree), and the unknowns from spec section 9 (spec visibility, session-id handoff, and nested subagent dispatch) are verified before anything is built. Nothing in this task edits repo code.

**Files:** none in the repo except backlog artifacts committed on `release/1.1` through the `_release` worktree by the psrw scripts and two plain `git commit`s there.

**Interfaces:**
- Consumes: the approved spec `/Users/pasitnusso/workspace/tools/docs/superpowers/specs/2026-09-19-epic-run-design.md`, this plan file, `release/1.1` engine at `/Users/pasitnusso/ps-skills/.claude/worktrees/_release/engine/ps-release-workflow`.
- Produces: idea `I-002`, feature `F-002` (use the ids actually printed if they differ), a claimed worktree `$WT`, and a verdict on unknowns (a), (b) and (c).

- [ ] **Step 0.1: Confirm the approved spec and restate the goal.** The spec's status line reads "revised after audit, awaiting approval"; the human approval is the instruction to write this plan. Write the goal into the task notes verbatim: "Design `epic run E-NNN`, a sequential, spec-gated auto-chain that drives an epic's approved slices through refine, claim, implement, review and ship, stops at the first failed gate, and never promotes."

- [ ] **Step 0.2: Check the release is open and see what already exists.**

```bash
REL_ENG=/Users/pasitnusso/ps-skills/.claude/worktrees/_release/engine/ps-release-workflow
cd /Users/pasitnusso/ps-skills && python3 "$REL_ENG/bin/psrw" status 2>&1 | head -25
```

Expected: a release `1.1` in progress, `F-001` shipped. If no release is in progress, STOP and ask the human to run `psrw new-release`.

- [ ] **Step 0.3: Capture the idea, then put the approved spec in it.** The approved spec satisfies the human gate that `psrw refine` otherwise assumes.

```bash
REL_ENG=/Users/pasitnusso/ps-skills/.claude/worktrees/_release/engine/ps-release-workflow
REL=/Users/pasitnusso/ps-skills/.claude/worktrees/_release
cd /Users/pasitnusso/ps-skills
git -C "$REL" status --short | head -5   # must print nothing: `add -A` below sweeps up anything dirty
git -C "$REL" log --oneline -1            # record this sha: the reset point if Task 0 is undone
python3 "$REL_ENG/bin/psrw" idea "epic run: spec-gated sequential slice auto-chain" 2>&1 | tail -4
IDEA_DIR=$(ls -d "$REL"/.claude/idea_backlog/I-*-epic-run-* | head -1)
cp /Users/pasitnusso/workspace/tools/docs/superpowers/specs/2026-09-19-epic-run-design.md "$IDEA_DIR/spec.md"
git -C "$REL" add -A
git -C "$REL" commit -F - <<'EOF'
docs(backlog): approved spec for epic run

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

Expected: `psrw idea` prints a JSON line with `"id": "I-002"`; the commit succeeds. (Edits inside `_release` are allowed by the guard; this is backlog metadata, the same route F-001 used.)

- [ ] **Step 0.4: Refine, add the plan, claim.**

```bash
REL_ENG=/Users/pasitnusso/ps-skills/.claude/worktrees/_release/engine/ps-release-workflow
REL=/Users/pasitnusso/ps-skills/.claude/worktrees/_release
cd /Users/pasitnusso/ps-skills
python3 "$REL_ENG/bin/psrw" refine I-002 2>&1 | head -3
FEAT_DIR=$(ls -d "$REL"/.claude/refined_backlog/F-*-epic-run-* | head -1)
cp /Users/pasitnusso/workspace/tools/docs/superpowers/plans/2026-09-19-epic-run.md "$FEAT_DIR/plan.md"
git -C "$REL" add -A
git -C "$REL" commit -F - <<'EOF'
docs(backlog): implementation plan for epic run

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
python3 "$REL_ENG/bin/psrw" claim F-002 2>&1 | tail -4
```

Expected: refine prints `{"ok": true, "id": "F-002", "from_idea": "I-002"}`; claim prints `Claimed F-002 (worktree: /Users/pasitnusso/ps-skills/.claude/worktrees/F-002-epic-run-...)`. The default owner is used (no `--owner`).

- [ ] **Step 0.5: Unknown (a), part 1 — a worktree cut from `main` cannot see the slice's spec/plan, and lacks the epic layer.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
cd "$WT"
ls .claude/refined_backlog/
ls engine/ps-release-workflow/scripts/epic.py 2>&1 | head -2
ls skills | grep -c epic
```

Expected: `.claude/refined_backlog/` lists only `_catalog.json` (no `F-002-...` folder); `scripts/epic.py` is `No such file`; `0` epic skills. This is the visibility gap `epic sync` exists to close, and it is also why the next step is needed.

- [ ] **Step 0.6: Unknown (a), part 2 — merge `release/1.1` (the manual form of `epic sync`) and confirm the spec/plan appear.** `epic sync` does not exist yet, so the merge is done by hand; it also brings in the F-001 epic layer this work builds on.

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
cd "$WT"
git merge --no-edit release/1.1 2>&1 | grep -E 'Fast-forward|Already up to date|CONFLICT|Merge made'
ls .claude/refined_backlog/F-002-*/
ls engine/ps-release-workflow/scripts/epic.py skills/ps-release-workflow-epic-fanout/SKILL.md
git log --oneline -1
git -C /Users/pasitnusso/ps-skills/.claude/worktrees/_release log --oneline -1
```

Expected: the `grep` prints `Fast-forward` (that line would NOT appear under a bare `| tail -3`, which shows only the diffstat summary, hence the `grep`); the folder lists `plan.md  spec.md` (an untouched `research.md` skeleton is dropped by refine); both epic files exist; the two `git log` lines show the same sha. **If `plan.md`/`spec.md` are missing after the merge, STOP: unknown (a) failed, the spec's sync design is wrong; report to the human and revise spec section 9 before any code is written.**

- [ ] **Step 0.7: Unknown (b), part 1 — offline guard check: a caller whose payload carries an unrelated session id is admitted, because the claim used the default owner.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
GUARD="$WT/engine/ps-release-workflow/scripts/guard_check.py"
cat /Users/pasitnusso/ps-skills/.git/worktrees/$(basename "$WT")/working-feature.json | grep owner
cat ~/.cache/ps-release-workflow/session-id
echo "--- subagent-like payload (unrelated session id), inside the claimed worktree"
printf '{"tool_name":"Write","tool_input":{"file_path":"%s/probe.txt"},"session_id":"some-subagent-id"}' "$WT" \
  | env -u PS_RELEASE_WORKFLOW_SCRIPTED python3 "$GUARD"; echo "exit=$?"
echo "--- control: same payload aimed at the main checkout"
printf '{"tool_name":"Write","tool_input":{"file_path":"/Users/pasitnusso/ps-skills/probe.txt"},"session_id":"some-subagent-id"}' \
  | env -u PS_RELEASE_WORKFLOW_SCRIPTED python3 "$GUARD"; echo "exit=$?"
```

Expected: the marker `owner` equals the cached machine id (unless `$CLAUDE_SESSION_ID` is exported in this shell, in which case it equals that); the first check prints `exit=0`; the control prints `BLOCKED: ... is on main of a ps-release-workflow repo` and `exit=2`. The control proves the guard is live, so `exit=0` is a real allow. (Verified while writing this plan against a scratch repo with the release-branch guard.) **Limit of this step:** it proves little about the `--resume` handoff, because the machine-cached id is always in `self_ids` (`guard_check.py:124`), so a default-owner claim is admitted whatever session id the payload carries. It only proves the guard is live and admits the default owner; the `--resume` re-own is proven (or not) by Step 0.8.

- [ ] **Step 0.8: Unknown (b), part 2 — live check with a real Claude Code subagent, and unknown (c): can a subagent dispatch a further subagent?** Two probes, both with the Agent tool, substituting the real `$WT`.

**Probe 1 (single-level Write).** Dispatch one general-purpose subagent with this prompt:

> Work only in `<WT>`. First run `python3 <WT>/engine/ps-release-workflow/bin/psrw claim F-002 --resume` and paste its output. Then use the **Write tool** (not Bash) to create `<WT>/.psrw-guard-probe` containing `probe`. Paste the Write tool's result verbatim, then delete the file with Bash `rm` and run `git -C <WT> status --short`. Report in at most 8 lines.

Expected: the resume prints `Owner is now <id>`; the Write succeeds with no `BLOCKED:` text; `git status --short` prints nothing. **If the Write is BLOCKED after the resume, STOP: unknown (b) failed; the default-owner plus `claim --resume` handoff (spec section 5) does not work and the spec must be revised.**

**Probe 2 (nested dispatch).** The skill has an implementer SUBAGENT run `subagent-driven-development`, which itself dispatches implementer and reviewer subagents: a subagent-of-a-subagent. Dispatch one general-purpose subagent with this prompt:

> Use the **Agent tool** to dispatch one general-purpose subagent whose whole task is: "Try once to dispatch ONE more trivial subagent (task: reply LEVEL3-OK) and report whether that dispatch was allowed or refused, then reply NESTED-OK." Then report, in at most 5 lines: (1) whether the Agent tool was available to you at all, (2) whether the dispatch was allowed or refused (paste any refusal or error verbatim), (3) the nested subagent's reply, including its level-3 result. Do not edit any file.

Expected: the subagent reports the Agent tool was available, the dispatch was allowed, and the nested reply is `NESTED-OK`. (The level-3 result is informative only: production use is main session, then implementer subagent, then the implementer's own subagents, i.e. two levels below the main session, which is what the probe tests; the Task 5 dry run runs the whole skill from a subagent and so needs one level more. If level 3 is refused, run the Task 5 dry run from the main session instead of from a subagent.) **STOP RULE: if nesting is refused or the Agent tool is not available inside a subagent, do NOT build the skill as written.** Revise Task 3's skill step 4 (and Task 5 Steps 5.8 and 5.10, which assume it) so the **main session dispatches the implementer and each reviewer directly**, with no subagent-of-a-subagent (the epic-run agent itself runs `writing-plans` and the per-task loop of `subagent-driven-development` in its own thread, dispatching one flat layer of subagents), and RE-AUDIT the revised plan (`self-grill-audit`) before any code is written. Record the verdict in the task notes.

If Probe 1 passes and Probe 2 passes, record "unknowns (a), (b) and (c) verified" in the task notes and continue to Task 1.

**Undo note for Task 0 (what it leaves behind).** Task 0 makes state changes outside the repo tree: idea `I-002` and feature `F-002` in the backlog, a claimed worktree, and about 6 LOCAL commits on the UNPUSHED `release/1.1` (idea, spec commit, refine, plan commit, claim, plus the by-hand merge in the feature branch). To back out: run `psrw unclaim F-002` (removes the worktree, clears the claim, keeps the branch), then, in the `_release` worktree, inspect `git log --oneline origin/release/1.1..HEAD` (or `git log --oneline -8` if unpublished) and `git reset --hard <sha-before-Task-0>` to drop exactly those local commits (recorded from `git log --oneline -1` before Step 0.3). Note that Steps 0.3 and 0.4 run `git -C "$REL" add -A`, which sweeps up ANYTHING dirty in `_release`: run `git -C "$REL" status --short` first and stop if it prints anything unrelated to this task.

---

## Task 1: `psrw epic plan` preflight

**Files:**
- Modify: `engine/ps-release-workflow/tests/conftest.py` (append after line 88, the end of the file).
- Create: `engine/ps-release-workflow/tests/test_epic_run.py`.
- Modify: `engine/ps-release-workflow/scripts/epic.py` — imports (lines 18-21), the class block (after line 26), `_rollback_epic` (line 76), the spec write in `epic_fanout` (lines 155-158), a new block immediately above `def main()` (line 212), and `main()` (lines 229-241).

**Interfaces:**
- Consumes (all exist): `lib.backlog_paths.read_release_state(repo) -> dict | None`, `get_release_worktree(repo) -> Path`, `get_backlog_catalog_path(repo, kind) -> Path`, `NoReleaseInProgressError`; `lib.catalog.find_entry(catalog, id) -> dict | None`, `CatalogEntryNotFoundError(entry_id, path)`; `lib.epic.epic_children(idea_cat, epic_id) -> list[dict]`; `lib.hooks.resolve_hook(tree, "precheck") -> Path` (existence not checked), `HookPathError`; `scripts.promote_idea_to_refined._is_untouched_skeleton(text, skeleton) -> bool`; `scripts.new_idea.SPEC_TEMPLATE`; `lib.slug.slugify`.
- Produces (used by Tasks 2, 3, 5):
  - `class EpicPlanError(Exception)`
  - `def _fanout_idea_spec(title: str, idea_id: str) -> str`
  - `def epic_plan(repo: Path, epic_id: str, slices: str, allow_no_precheck: bool = False) -> dict` returning `{"epic": str, "epic_status": str, "release": str, "allowlist": list[str], "precheck": str | None, "notes": list[str], "slices": list[{"idea": str, "feature": str | None, "state": "idea"|"refined"|"claimed"|"shipped", "claimed_by": str | None, "action": "refine"|"claim"|"resume"|"skip"}]}`
  - CLI: `psrw epic plan E-NNN --slices I-001,I-002 [--allow-no-precheck]` printing that dict as JSON.
  - Fixtures `epic_repo_raw`, `idea_spec`, `epic_repo` (conftest).

- [ ] **Step 1.1: Add the shared fixtures.** Append to `engine/ps-release-workflow/tests/conftest.py` (after the last line, `new_release(tmp_repo_with_release)` / `return tmp_repo_with_release`), keeping two blank lines before:

```python
def _release_wt(repo: Path) -> Path:
    return repo / ".claude" / "worktrees" / "_release"


@pytest.fixture
def epic_repo_raw(tmp_repo_in_release: Path, fixed_owner: str) -> Path:
    """release/1.1 open; epic E-001 fanned out into I-001 'alpha' and I-002 'beta'.

    The slice specs are the untouched fanout skeletons and there is no
    scripts/precheck.sh, so `epic plan` must refuse this repo until both are fixed."""
    from scripts.epic import epic_fanout, epic_open
    epic_open(tmp_repo_in_release, "E")
    epic_fanout(tmp_repo_in_release, "E-001", ["alpha", "beta"])
    return tmp_repo_in_release


@pytest.fixture
def idea_spec():
    """Callable (repo, idea_id) -> Path of that idea's spec.md on release/<v>."""
    def path(repo: Path, idea_id: str) -> Path:
        from lib.slug import slugify
        folder = _release_wt(repo) / ".claude" / "idea_backlog"
        catalog = json.loads((folder / "_catalog.json").read_text())
        title = next(i["title"] for i in catalog if i["id"] == idea_id)
        return folder / f"{idea_id}-{slugify(title)}" / "spec.md"
    return path


@pytest.fixture
def epic_repo(epic_repo_raw: Path, idea_spec) -> Path:
    """epic_repo_raw plus real content in both slice specs and a passing precheck.sh,
    all committed on release/<v>. `epic plan` accepts this repo as-is."""
    from lib.git_ops import commit_all
    repo = epic_repo_raw
    for idea_id in ("I-001", "I-002"):
        idea_spec(repo, idea_id).write_text(f"# {idea_id}\n\nApproved design content.\n")
    script = _release_wt(repo) / "scripts" / "precheck.sh"
    script.parent.mkdir(exist_ok=True)
    script.write_text("#!/usr/bin/env bash\nexit 0\n")
    script.chmod(0o755)
    commit_all(_release_wt(repo), "test: fill slice specs, add precheck")
    return repo
```

- [ ] **Step 1.2: Write the failing tests.** Create `engine/ps-release-workflow/tests/test_epic_run.py`:

```python
"""psrw epic plan / psrw epic sync — the deterministic half of `epic run`."""
import json
import subprocess

import pytest

from lib.backlog_paths import (
    NoReleaseInProgressError, get_backlog_catalog_path, get_release_worktree,
)
from lib.catalog import CatalogEntryNotFoundError, mark_promoted_to_main, mark_shipped
from lib.epic import mark_epic_failed, mark_epic_promoted, try_begin_verification
from lib.git_ops import commit_all
from scripts.epic import EpicPlanError, epic_plan, epic_verify
from scripts.init_work_refined_backlog import claim_feature
from scripts.new_idea import SPEC_TEMPLATE as IDEA_SPEC_TEMPLATE
from scripts.promote_idea_to_refined import promote_idea_to_refined


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def _plan_error(repo, *args, **kwargs) -> str:
    with pytest.raises(EpicPlanError) as excinfo:
        epic_plan(repo, *args, **kwargs)
    return str(excinfo.value)


# ── epic plan: the output ────────────────────────────────────────────────────

def test_plan_lists_slices_in_fanout_order_not_allowlist_order(epic_repo):
    out = epic_plan(epic_repo, "E-001", "I-002,I-001")
    assert out["allowlist"] == ["I-002", "I-001"]
    assert out["slices"] == [
        {"idea": "I-001", "feature": None, "state": "idea",
         "claimed_by": None, "action": "refine"},
        {"idea": "I-002", "feature": None, "state": "idea",
         "claimed_by": None, "action": "refine"},
    ]
    assert out["epic"] == "E-001"
    assert out["epic_status"] == "open"
    assert out["release"] == "1.1"
    assert out["precheck"].endswith("scripts/precheck.sh")
    assert out["notes"] == []


def test_plan_only_lists_allowlisted_slices(epic_repo):
    out = epic_plan(epic_repo, "E-001", "I-002")
    assert [s["idea"] for s in out["slices"]] == ["I-002"]


def test_plan_reports_every_state_and_action(epic_repo):
    repo = epic_repo
    feature = promote_idea_to_refined(repo, "I-001")["id"]
    out = epic_plan(repo, "E-001", "I-001,I-002")
    assert [(s["state"], s["action"]) for s in out["slices"]] == [
        ("refined", "claim"), ("idea", "refine")]
    assert out["slices"][0]["feature"] == feature

    claim_feature(repo, feature, owner="chain-owner")
    first = epic_plan(repo, "E-001", "I-001,I-002")["slices"][0]
    assert (first["state"], first["action"]) == ("claimed", "resume")
    assert first["claimed_by"] == "chain-owner"

    mark_shipped(get_backlog_catalog_path(repo, "refined"), feature, "1.1")
    first = epic_plan(repo, "E-001", "I-001,I-002")["slices"][0]
    assert (first["state"], first["action"]) == ("shipped", "skip")


def test_plan_names_failed_verification_without_refusing(epic_repo):
    epic_cat = get_backlog_catalog_path(epic_repo, "epic")
    assert try_begin_verification(epic_cat, "E-001", "abc123")
    mark_epic_failed(epic_cat, "E-001", "1.1", sha="abc123")
    out = epic_plan(epic_repo, "E-001", "I-001")
    assert out["epic_status"] == "failed_verification"
    assert any("psrw epic verify E-001" in note for note in out["notes"])


# ── epic plan: refusals ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["", "  ", " , ,"])
def test_plan_refuses_a_missing_or_empty_allowlist(epic_repo, raw):
    assert "--slices" in _plan_error(epic_repo, "E-001", raw)


def test_plan_refuses_when_no_release_is_in_progress(tmp_repo_with_release):
    with pytest.raises(NoReleaseInProgressError):
        epic_plan(tmp_repo_with_release, "E-001", "I-001")


def test_plan_refuses_an_unknown_epic(epic_repo):
    with pytest.raises(CatalogEntryNotFoundError):
        epic_plan(epic_repo, "E-009", "I-001")


def test_plan_refuses_a_slice_that_is_not_a_child_of_the_epic(epic_repo):
    assert "I-009" in _plan_error(epic_repo, "E-001", "I-001,I-009")


@pytest.mark.parametrize("state", ["verified", "promoted", "verifying"])
def test_plan_refuses_a_settled_or_in_flight_epic(epic_repo, state):
    epic_cat = get_backlog_catalog_path(epic_repo, "epic")
    if state == "verified":
        epic_verify(epic_repo, "E-001")
    elif state == "promoted":
        mark_epic_promoted(epic_cat, "E-001")
    else:
        assert try_begin_verification(epic_cat, "E-001", "abc123")
    assert state in _plan_error(epic_repo, "E-001", "I-001")


def test_plan_refuses_a_slice_that_is_already_promoted(epic_repo):
    feature = promote_idea_to_refined(epic_repo, "I-001")["id"]
    mark_promoted_to_main(get_backlog_catalog_path(epic_repo, "refined"), feature)
    message = _plan_error(epic_repo, "E-001", "I-001")
    assert "I-001" in message and "already promoted" in message


def test_plan_refuses_a_slice_shipped_on_another_release(epic_repo):
    feature = promote_idea_to_refined(epic_repo, "I-001")["id"]
    mark_shipped(get_backlog_catalog_path(epic_repo, "refined"), feature, "0.9")
    assert "0.9" in _plan_error(epic_repo, "E-001", "I-001")


def test_plan_refuses_an_untouched_fanout_skeleton_spec(epic_repo_raw):
    """epic_repo_raw's specs are exactly what `epic fanout` wrote, so this pins
    the skeleton comparison to fanout's real output, not to a copy of it."""
    message = _plan_error(epic_repo_raw, "E-001", "I-001", allow_no_precheck=True)
    assert "I-001" in message and "skeleton" in message


def test_plan_refuses_an_untouched_new_idea_skeleton_spec(epic_repo, idea_spec):
    spec = idea_spec(epic_repo, "I-002")
    spec.write_text(IDEA_SPEC_TEMPLATE.format(title="beta", id="I-002"))
    commit_all(get_release_worktree(epic_repo), "test: reset I-002 spec")
    message = _plan_error(epic_repo, "E-001", "I-001,I-002")
    assert "I-002" in message and "skeleton" in message


def test_plan_ignores_the_spec_of_an_already_shipped_slice(epic_repo, idea_spec):
    feature = promote_idea_to_refined(epic_repo, "I-001")["id"]
    mark_shipped(get_backlog_catalog_path(epic_repo, "refined"), feature, "1.1")
    idea_spec(epic_repo, "I-001").write_text(
        IDEA_SPEC_TEMPLATE.format(title="alpha", id="I-001"))   # skeleton again
    out = epic_plan(epic_repo, "E-001", "I-001")
    assert out["slices"][0]["action"] == "skip"


def test_plan_refuses_a_missing_idea_spec(epic_repo, idea_spec):
    idea_spec(epic_repo, "I-001").unlink()
    assert "spec.md" in _plan_error(epic_repo, "E-001", "I-001")


def test_plan_refuses_a_missing_precheck_unless_allowed(epic_repo):
    rel = get_release_worktree(epic_repo)
    (rel / "scripts" / "precheck.sh").unlink()
    commit_all(rel, "test: drop precheck")
    assert "--allow-no-precheck" in _plan_error(epic_repo, "E-001", "I-001")
    out = epic_plan(epic_repo, "E-001", "I-001", allow_no_precheck=True)
    assert out["precheck"] is None


def test_plan_refuses_an_unusable_precheck_hook_even_when_allowed(epic_repo):
    rel = get_release_worktree(epic_repo)
    release_json = json.loads((rel / ".release.json").read_text())
    release_json["hooks"] = {"precheck": "/etc/passwd"}
    (rel / ".release.json").write_text(json.dumps(release_json))
    commit_all(rel, "test: absolute precheck hook")
    assert "hooks.precheck" in _plan_error(
        epic_repo, "E-001", "I-001", allow_no_precheck=True)


# ── epic plan: read-only ─────────────────────────────────────────────────────

def test_plan_writes_nothing(epic_repo):
    rel = get_release_worktree(epic_repo)
    catalogs = [get_backlog_catalog_path(epic_repo, kind)
                for kind in ("idea", "refined", "epic")]
    before = {p: p.read_bytes() for p in catalogs if p.exists()}
    head = _git(rel, "rev-parse", "HEAD")

    epic_plan(epic_repo, "E-001", "I-001,I-002")

    assert {p: p.read_bytes() for p in catalogs if p.exists()} == before
    assert _git(rel, "status", "--porcelain") == ""
    assert _git(rel, "rev-parse", "HEAD") == head


# ── epic plan: the CLI ───────────────────────────────────────────────────────

def test_cli_plan_prints_the_json_plan(epic_repo, monkeypatch, capsys):
    from scripts.epic import main
    monkeypatch.chdir(epic_repo)
    monkeypatch.setattr("sys.argv", ["epic.py", "plan", "E-001", "--slices", "I-001,I-002"])
    assert main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["allowlist"] == ["I-001", "I-002"]
    assert [s["action"] for s in out["slices"]] == ["refine", "refine"]


def test_cli_plan_refusal_is_one_error_line_not_a_traceback(epic_repo, monkeypatch, capsys):
    from scripts.epic import main
    monkeypatch.chdir(epic_repo)
    monkeypatch.setattr("sys.argv", ["epic.py", "plan", "E-001"])
    assert main() == 1
    err = capsys.readouterr().err
    assert err.startswith("ERROR: ") and "--slices" in err and "Traceback" not in err
```

- [ ] **Step 1.3: Run them and watch them fail.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
ENG="$WT/engine/ps-release-workflow"
cd "$ENG" && python3 -m pytest tests/test_epic_run.py -q 2>&1 | tail -8
```

Expected: `ERROR tests/test_epic_run.py` with `ImportError: cannot import name 'EpicPlanError' from 'scripts.epic'` (collection error, 0 tests run).

- [ ] **Step 1.4: Implement, part 1 — imports, the error class, and the shared skeleton.** In `engine/ps-release-workflow/scripts/epic.py` make these four edits.

Edit 1, imports (currently lines 18-21). Replace

```python
from lib.git_ops import GitError, _run as git_run, commit_all
from lib.repo import find_repo_root
from lib.slug import SlugError, slugify
from lib.state import file_lock, mutate_state
```

with

```python
from lib.git_ops import GitError, _run as git_run, commit_all
from lib.hooks import HookPathError, resolve_hook
from lib.repo import find_repo_root
from lib.slug import SlugError, slugify
from lib.state import file_lock, mutate_state
from scripts.new_idea import SPEC_TEMPLATE as IDEA_SPEC_TEMPLATE
from scripts.promote_idea_to_refined import _is_untouched_skeleton
```

Edit 2, after `EpicNotVerifiableError` (ends at its closing `"""`, line 26). Replace

```python
class EpicNotVerifiableError(Exception):
    """try_begin_verification lost the CAS: without --force this means someone
    else is already verifying epic_id, or it is already verified."""
```

with the same text followed by

```python


class EpicPlanError(Exception):
    """A preflight refusal: `epic run` must not start."""
```

Edit 3, insert immediately above `def _rollback_epic(` (line 76):

```python
def _fanout_idea_spec(title: str, idea_id: str) -> str:
    """The exact spec.md `epic fanout` writes for a new slice idea. One source of
    truth: epic_fanout writes it and epic_plan compares against it, so the two
    cannot drift."""
    return (f"---\ntitle: {_yaml_quote(title)}\nid: {idea_id}\n"
            f"status: idea\n---\n\n# {title}\n")


```

Edit 4, in `epic_fanout` (lines 155-158). Replace

```python
                (folder / "spec.md").write_text(
                    f"---\ntitle: {_yaml_quote(title)}\nid: {idea['id']}\n"
                    f"status: idea\n---\n\n# {title}\n"
                )
```

with

```python
                (folder / "spec.md").write_text(_fanout_idea_spec(title, idea["id"]))
```

- [ ] **Step 1.5: Implement, part 2 — `epic_plan`.** Insert this block in `engine/ps-release-workflow/scripts/epic.py` immediately above `def main() -> int:` (keep two blank lines between the block and `def main`):

```python
# feature.status -> (slice state, action). `promoted` and any other status refuse.
_SLICE_STATE = {
    "open": ("refined", "claim"),
    "claimed": ("claimed", "resume"),
    "shipped": ("shipped", "skip"),
}


def _slice_spec_is_skeleton(rel_wt: Path, idea: dict) -> bool:
    """True when the idea's spec.md is still an untouched generated skeleton.

    Two generators exist: `epic fanout` (what every epic slice starts as) and
    `psrw idea` (IDEA_SPEC_TEMPLATE). Either one, unedited, means nobody wrote
    the slice's spec. Text that cannot be decoded is content we cannot judge, so
    it is NOT a skeleton (the conservative reading refine's carry-forward uses).
    """
    spec = (rel_wt / ".claude" / "idea_backlog"
            / f"{idea['id']}-{slugify(idea['title'])}" / "spec.md")
    try:
        text = spec.read_text()
    except FileNotFoundError:
        raise EpicPlanError(f"{idea['id']}: spec.md not found at {spec}")
    except (OSError, UnicodeDecodeError):
        return False
    skeletons = (
        _fanout_idea_spec(idea["title"], idea["id"]),
        IDEA_SPEC_TEMPLATE.format(title=idea["title"], id=idea["id"]),
    )
    return any(_is_untouched_skeleton(text, skeleton) for skeleton in skeletons)


def _plan_slice(rel_wt: Path, refined_cat: Path, version: str, idea: dict) -> dict:
    feature = None
    if idea.get("promoted_to"):
        feature = find_entry(refined_cat, idea["promoted_to"])
        if feature is None:
            raise EpicPlanError(
                f"{idea['id']} points at {idea['promoted_to']}, which is missing "
                f"from the refined catalog")
    if feature is None:
        state, action = "idea", "refine"
    else:
        status = feature.get("status")
        if status == "promoted":
            raise EpicPlanError(f"{idea['id']} ({feature['id']}) is already promoted")
        if status == "shipped" and feature.get("release_version") != version:
            raise EpicPlanError(
                f"{feature['id']} shipped on {feature.get('release_version')}, "
                f"not on {version}")
        if status not in _SLICE_STATE:
            raise EpicPlanError(f"{feature['id']} has unexpected status {status!r}")
        state, action = _SLICE_STATE[status]
    if state != "shipped" and _slice_spec_is_skeleton(rel_wt, idea):
        raise EpicPlanError(
            f"{idea['id']}: spec.md is still the untouched skeleton — write and "
            f"approve the slice spec before it goes in --slices")
    return {
        "idea": idea["id"],
        "feature": feature["id"] if feature else None,
        "state": state,
        "claimed_by": feature.get("claimed_by") if feature else None,
        "action": action,
    }


def _resolve_precheck(rel_wt: Path, allow_missing: bool) -> str | None:
    """Gate 1 script path, resolved from the _release tree (the one ship's
    post-merge Gate 1 uses). A missing script is a warning-and-skip inside ship,
    which an unattended chain must not inherit, so it refuses unless allowed. An
    unusable hooks.precheck value always refuses, like ship."""
    try:
        hook = resolve_hook(rel_wt, "precheck")
    except HookPathError as e:
        raise EpicPlanError(f"hooks.precheck is unusable: {e}")
    if hook.exists():
        return str(hook)
    if allow_missing:
        return None
    raise EpicPlanError(
        f"Gate 1 script not found at {hook}: ship would skip it with only a "
        f"warning, which an unattended chain must not. Add it, or pass "
        f"--allow-no-precheck to accept that.")


def epic_plan(repo: Path, epic_id: str, slices: str,
              allow_no_precheck: bool = False) -> dict:
    """Read-only preflight for `epic run`. Raises EpicPlanError (or the usual
    NoReleaseInProgressError / CatalogEntryNotFoundError) instead of returning a
    plan the chain must not follow. Writes nothing."""
    allowlist = list(dict.fromkeys(s.strip() for s in slices.split(",") if s.strip()))
    if not allowlist:
        raise EpicPlanError(
            "--slices is required: name the approved slice ideas, e.g. "
            "--slices I-001,I-002 (approval is never inferred)")
    state = read_release_state(repo)
    if state is None:
        raise NoReleaseInProgressError("No release in progress")
    version = state["version"]
    rel_wt = get_release_worktree(repo)
    epic_cat = get_backlog_catalog_path(repo, "epic")
    epic = find_entry(epic_cat, epic_id)
    if epic is None:
        raise CatalogEntryNotFoundError(epic_id, epic_cat)

    status = epic.get("status")
    notes: list[str] = []
    if status in ("verified", "promoted"):
        raise EpicPlanError(f"{epic_id} is already {status}; there is nothing left to run")
    if status == "verifying":
        raise EpicPlanError(
            f"{epic_id} is 'verifying': another outcome check is in flight, or a "
            f"crashed one left its claim. Wait, or clear it with: "
            f"psrw epic verify --force {epic_id}")
    if status == "failed_verification":
        notes.append(
            f"{epic_id} is failed_verification: the ship that completes the epic "
            f"re-runs the outcome check; to re-check now run: psrw epic verify {epic_id}")

    children = epic_children(get_backlog_catalog_path(repo, "idea"), epic_id)
    stray = [i for i in allowlist if i not in {c["id"] for c in children}]
    if stray:
        raise EpicPlanError(f"not slices of {epic_id}: {', '.join(stray)}")
    refined_cat = get_backlog_catalog_path(repo, "refined")
    plan = [_plan_slice(rel_wt, refined_cat, version, idea)
            for idea in children if idea["id"] in allowlist]
    return {
        "epic": epic_id,
        "epic_status": status,
        "release": version,
        "allowlist": allowlist,
        "precheck": _resolve_precheck(rel_wt, allow_no_precheck),
        "notes": notes,
        "slices": plan,
    }


```

- [ ] **Step 1.6: Implement, part 3 — the CLI.** In `main()` make two edits. Add the subparser directly after the `p_ver` block (before `args = p.parse_args()`):

```python
    p_plan = sub.add_parser(
        "plan", help="preflight for an epic run: print the ordered slice plan (read-only)")
    p_plan.add_argument("epic_id", metavar="E-NNN")
    p_plan.add_argument("--slices", default="", metavar="I-NNN,I-NNN",
                        help="comma-separated approved slice ideas (required)")
    p_plan.add_argument("--allow-no-precheck", action="store_true",
                        help="accept a repo with no Gate 1 script (ship then skips Gate 1)")

```

Then replace the dispatch and its `except` tuple

```python
        elif args.cmd == "fanout":
            result = epic_fanout(repo, args.epic_id, args.titles)
        else:
            result = epic_verify(repo, args.epic_id, force=args.force)
    except (NoReleaseInProgressError, CatalogEntryNotFoundError, GitError,
            EpicNotVerifiableError, SlugError) as e:
```

with

```python
        elif args.cmd == "fanout":
            result = epic_fanout(repo, args.epic_id, args.titles)
        elif args.cmd == "plan":
            result = epic_plan(repo, args.epic_id, args.slices,
                               allow_no_precheck=args.allow_no_precheck)
        else:
            result = epic_verify(repo, args.epic_id, force=args.force)
    except (NoReleaseInProgressError, CatalogEntryNotFoundError, GitError,
            EpicNotVerifiableError, EpicPlanError, SlugError) as e:
```

- [ ] **Step 1.7: Run the new tests and the neighbours they could break.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
ENG="$WT/engine/ps-release-workflow"
cd "$ENG" && python3 -m pytest tests/test_epic_run.py tests/test_epic_cli.py tests/test_psrw_cli.py tests/test_scripts_runnable.py -q 2>&1 | tail -6
```

Expected: `74 passed` (24 + 14 + 24 + 12), 0 failed. `test_epic_cli.py`'s fanout tests passing proves the `_fanout_idea_spec` refactor kept fanout's output and its write count.

- [ ] **Step 1.8: Prove the skeleton tests can fail.** Temporarily change the last line of `_slice_spec_is_skeleton` from `return any(...)` to `return False`, run `python3 -m pytest tests/test_epic_run.py -q 2>&1 | tail -5`, expect `2 failed` (`test_plan_refuses_an_untouched_fanout_skeleton_spec`, `test_plan_refuses_an_untouched_new_idea_skeleton_spec`), then restore the line and re-run to `24 passed`.

- [ ] **Step 1.9: Commit.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
git -C "$WT" add engine/ps-release-workflow/scripts/epic.py engine/ps-release-workflow/tests/conftest.py engine/ps-release-workflow/tests/test_epic_run.py
git -C "$WT" commit -F - <<'EOF'
feat(epic): psrw epic plan, the read-only preflight for epic run

Refuses an unsafe start (no allowlist, non-child or promoted slice, settled or
verifying epic, untouched skeleton spec, missing Gate 1 script) and otherwise
prints each allowlisted slice in fanout order with state, claimed_by and action.
epic fanout now writes its slice spec through _fanout_idea_spec so plan compares
against the same text.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 1.10: Phase gate.** (1) Verify: re-run the Step 1.7 command, expect `74 passed`. (2) Review: dispatch `code-reviewer` and `python-reviewer` in one message on `git -C "$WT" diff HEAD~1..HEAD`, giving each the goal verbatim and asking for at most 15 lines; adversarial questions to include: "can `plan` be made to write anything?", "can a skeleton spec slip past `_slice_spec_is_skeleton`?", "is any refusal reachable only as a traceback?". (3) Refactor: run `/simplify` on the diff and apply what it finds. (4) Re-verify: the Step 1.7 command again. Fix findings as a NEW commit (never amend), then advance.

---

## Task 2: `psrw epic sync`

**Files:**
- Modify: `engine/ps-release-workflow/scripts/epic.py` — module docstring (line 1), imports (the `git_ops` and `promote_idea_to_refined` import lines), class block (after `EpicPlanError`), a new block immediately above `def main()`, and `main()` (subparser, dispatch, `except` tuple).
- Modify: `engine/ps-release-workflow/bin/psrw` (the `"epic"` entry of `VERBS`, line 41).
- Modify: `engine/ps-release-workflow/tests/test_epic_run.py` (import block, then append).

**Interfaces:**
- Consumes (exist): `scripts.ship_current_work_to_release._find_marker(worktree: Path) -> dict` (raises `NotInFeatureWorktreeError`), `DirtyTreeError`, `NotInFeatureWorktreeError`; `lib.git_ops._run` (as `git_run`, returns `CompletedProcess`, `check=False` supported), `is_dirty(cwd) -> bool`; `lib.state.file_lock(target)`; `lib.repo.find_repo_root`; and from Task 1 nothing new.
- Produces (used by Tasks 3, 5):
  - `class EpicSyncError(Exception)`
  - `def epic_sync(cwd: Path) -> dict` returning `{"feature": "F-NNN", "branch": "feat/F-NNN", "release": "1.1", "base": <release HEAD sha merged>, "sha": <feature HEAD after the merge>}`
  - CLI: `psrw epic sync` (run inside the feature worktree) printing that dict as JSON; exit 1 with one `ERROR:` line on conflict, dirty tree, or outside a feature worktree.

- [ ] **Step 2.1: Extend the test imports.** In `engine/ps-release-workflow/tests/test_epic_run.py` make three edits.

Replace

```python
import json
import subprocess

import pytest
```

with

```python
import contextlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
```

Replace

```python
from lib.git_ops import commit_all
from scripts.epic import EpicPlanError, epic_plan, epic_verify
```

with

```python
from lib.git_ops import commit_all
from lib.slug import slugify
from scripts.epic import EpicPlanError, EpicSyncError, epic_plan, epic_sync, epic_verify
```

Replace

```python
from scripts.promote_idea_to_refined import promote_idea_to_refined
```

with

```python
from scripts.promote_idea_to_refined import promote_idea_to_refined
from scripts.ship_current_work_to_release import DirtyTreeError, NotInFeatureWorktreeError
```

- [ ] **Step 2.2: Append the failing sync tests** to the end of `tests/test_epic_run.py` (two blank lines before):

```python
# ── epic sync ────────────────────────────────────────────────────────────────

@pytest.fixture
def slice_worktree(epic_repo):
    """(repo, feature worktree, F-id) for slice I-001, refined then claimed."""
    feature = promote_idea_to_refined(epic_repo, "I-001")["id"]
    claimed = claim_feature(epic_repo, feature, owner="chain-owner")
    return epic_repo, Path(claimed["worktree"]), feature


def test_sync_makes_the_slice_spec_and_plan_visible(slice_worktree):
    repo, wt, feature = slice_worktree
    folder = wt / ".claude" / "refined_backlog" / f"{feature}-{slugify('alpha')}"
    assert not folder.exists(), "a worktree cut from main must not see it yet"

    result = epic_sync(wt)

    assert (folder / "spec.md").is_file() and (folder / "plan.md").is_file()
    assert result["feature"] == feature
    assert result["branch"] == f"feat/{feature}"
    assert result["release"] == "1.1"
    assert result["base"] == _git(get_release_worktree(repo), "rev-parse", "HEAD")
    assert result["sha"] == _git(wt, "rev-parse", "HEAD")


def test_sync_fast_forward_puts_the_feature_on_the_release_head(slice_worktree):
    _, wt, _ = slice_worktree
    result = epic_sync(wt)
    assert result["sha"] == result["base"]


def test_sync_merges_when_the_feature_already_has_commits(slice_worktree):
    _, wt, _ = slice_worktree
    (wt / "feature.txt").write_text("work\n")
    commit_all(wt, "feat: work before the sync")

    result = epic_sync(wt)

    assert result["sha"] != result["base"], "a real merge commit expected"
    assert _git(wt, "status", "--porcelain") == ""
    # the review anchor: `base` isolates exactly the slice's own work
    assert _git(wt, "diff", "--name-only", result["base"], "HEAD") == "feature.txt"


def test_sync_twice_is_a_no_op(slice_worktree):
    _, wt, _ = slice_worktree
    first = epic_sync(wt)
    second = epic_sync(wt)
    assert second == first


def test_sync_conflict_aborts_cleanly_and_leaves_the_feature_claimed(slice_worktree):
    repo, wt, feature = slice_worktree
    rel = get_release_worktree(repo)
    (rel / "shared.txt").write_text("release side\n")
    commit_all(rel, "test: release adds shared.txt")
    (wt / "shared.txt").write_text("feature side\n")
    commit_all(wt, "test: feature adds shared.txt")
    head = _git(wt, "rev-parse", "HEAD")

    with pytest.raises(EpicSyncError, match="shared.txt"):
        epic_sync(wt)

    assert _git(wt, "rev-parse", "HEAD") == head
    assert _git(wt, "status", "--porcelain") == ""
    assert subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                          cwd=wt, capture_output=True).returncode != 0
    catalog = json.loads(get_backlog_catalog_path(repo, "refined").read_text())
    assert next(f for f in catalog if f["id"] == feature)["status"] == "claimed"


def test_sync_refuses_outside_a_feature_worktree(slice_worktree):
    repo, _, _ = slice_worktree
    with pytest.raises(NotInFeatureWorktreeError):
        epic_sync(repo)                                  # the main checkout
    with pytest.raises(NotInFeatureWorktreeError):
        epic_sync(get_release_worktree(repo))            # the _release worktree


def test_sync_refuses_a_dirty_tree_and_keeps_the_edit(slice_worktree):
    _, wt, _ = slice_worktree
    head = _git(wt, "rev-parse", "HEAD")
    (wt / "scratch.txt").write_text("uncommitted\n")
    with pytest.raises(DirtyTreeError):
        epic_sync(wt)
    assert _git(wt, "rev-parse", "HEAD") == head
    assert (wt / "scratch.txt").read_text() == "uncommitted\n"


def test_sync_holds_the_release_lock_around_the_merge_only(slice_worktree, monkeypatch):
    repo, wt, _ = slice_worktree
    import scripts.epic as epic_mod
    events = []
    real_lock, real_run = epic_mod.file_lock, epic_mod.git_run

    @contextlib.contextmanager
    def spy_lock(target):
        events.append(("lock", Path(target).resolve()))
        with real_lock(target):
            yield
        events.append(("unlock", Path(target).resolve()))

    def spy_run(cwd, *args, **kwargs):
        if args and args[0] == "merge":
            events.append(("merge", None))
        return real_run(cwd, *args, **kwargs)

    monkeypatch.setattr(epic_mod, "file_lock", spy_lock)
    monkeypatch.setattr(epic_mod, "git_run", spy_run)

    epic_sync(wt)

    rel = get_release_worktree(repo).resolve()
    assert events == [("lock", rel), ("merge", None), ("unlock", rel)]


def test_cli_sync_prints_the_sha_and_fails_cleanly_outside_a_worktree(
        slice_worktree, monkeypatch, capsys):
    from scripts.epic import main
    repo, wt, _ = slice_worktree
    monkeypatch.setattr("sys.argv", ["epic.py", "sync"])

    monkeypatch.chdir(wt)
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["sha"] == _git(wt, "rev-parse", "HEAD")

    monkeypatch.chdir(repo)
    assert main() == 1
    err = capsys.readouterr().err
    assert err.startswith("ERROR: ") and "Traceback" not in err


def test_epic_help_lists_plan_and_sync():
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    proc = subprocess.run([sys.executable, str(scripts_dir / "epic.py"), "--help"],
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert "plan" in proc.stdout and "sync" in proc.stdout
```

- [ ] **Step 2.3: Run and watch them fail.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
ENG="$WT/engine/ps-release-workflow"
cd "$ENG" && python3 -m pytest tests/test_epic_run.py -q 2>&1 | tail -6
```

Expected: `ERROR tests/test_epic_run.py` with `ImportError: cannot import name 'EpicSyncError' from 'scripts.epic'`.

- [ ] **Step 2.4: Implement, part 1 — imports, error class, docstring.** In `engine/ps-release-workflow/scripts/epic.py`:

Replace the first line

```python
"""psrw epic — open an epic, fan it out into ideas, verify it."""
```

with

```python
"""psrw epic — open an epic, fan it out into ideas, verify it, plan or sync an epic run."""
```

Replace `from lib.git_ops import GitError, _run as git_run, commit_all` with `from lib.git_ops import GitError, _run as git_run, commit_all, is_dirty`.

Replace

```python
from scripts.promote_idea_to_refined import _is_untouched_skeleton
```

with

```python
from scripts.promote_idea_to_refined import _is_untouched_skeleton
from scripts.ship_current_work_to_release import (
    DirtyTreeError, NotInFeatureWorktreeError, _find_marker,
)
```

Replace

```python
class EpicPlanError(Exception):
    """A preflight refusal: `epic run` must not start."""
```

with the same text followed by

```python


class EpicSyncError(Exception):
    """The release merge could not complete; it was aborted and the feature
    worktree is as it was."""
```

- [ ] **Step 2.5: Implement, part 2 — `epic_sync`.** Insert immediately above `def main() -> int:` (below `epic_plan`):

```python
def epic_sync(cwd: Path) -> dict:
    """Merge the release branch's current HEAD into this feature branch.

    Feature branches are cut from main, so without this a slice sees neither the
    earlier slices' code nor its own spec/plan (those live under .claude/*_backlog
    on release/<v>). Run inside a claimed feature worktree. The read of the
    release HEAD and the merge happen under the same file_lock(_release) that
    ship holds, so a concurrent ship that is later rolled back cannot be merged
    half-way. On failure the merge is aborted and the tree is left as it was.
    """
    top = Path(git_run(Path(cwd), "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    feature_id = _find_marker(top)["feature"]
    repo = find_repo_root(top)
    state = read_release_state(repo)
    if state is None:
        raise NoReleaseInProgressError("No release in progress")
    release_branch = f"release/{state['version']}"
    feat_branch = f"feat/{feature_id}"
    rel_wt = get_release_worktree(repo)
    # A merge that starts on a dirty tree cannot be aborted back to that tree.
    if is_dirty(top):
        raise DirtyTreeError(f"{top} has uncommitted changes; commit or stash first")

    with file_lock(rel_wt):
        base = git_run(rel_wt, "rev-parse", "HEAD").stdout.strip()
        merged = git_run(
            top, "merge", "--no-edit", "-m",
            f"chore(epic): sync {release_branch} into {feat_branch}", base, check=False)
        if merged.returncode != 0:
            conflicted = git_run(top, "diff", "--name-only", "--diff-filter=U",
                                 check=False).stdout.split()
            git_run(top, "merge", "--abort", check=False)
            detail = ", ".join(conflicted) or (merged.stderr.strip() or merged.stdout.strip())
            raise EpicSyncError(
                f"merging {release_branch} ({base[:12]}) into {feat_branch} failed: "
                f"{detail}. The merge was aborted and {feature_id} stays claimed.")
    return {
        "feature": feature_id,
        "branch": feat_branch,
        "release": state["version"],
        "base": base,
        "sha": git_run(top, "rev-parse", "HEAD").stdout.strip(),
    }


```

- [ ] **Step 2.6: Implement, part 3 — the CLI.** In `main()`, add after the `p_plan` block and before `args = p.parse_args()`:

```python
    sub.add_parser(
        "sync", help="merge release/<v> into this feature branch (run in the feature worktree)")

```

Replace the dispatch tail and `except` tuple

```python
        elif args.cmd == "plan":
            result = epic_plan(repo, args.epic_id, args.slices,
                               allow_no_precheck=args.allow_no_precheck)
        else:
            result = epic_verify(repo, args.epic_id, force=args.force)
    except (NoReleaseInProgressError, CatalogEntryNotFoundError, GitError,
            EpicNotVerifiableError, EpicPlanError, SlugError) as e:
```

with

```python
        elif args.cmd == "plan":
            result = epic_plan(repo, args.epic_id, args.slices,
                               allow_no_precheck=args.allow_no_precheck)
        elif args.cmd == "sync":
            result = epic_sync(Path.cwd())
        else:
            result = epic_verify(repo, args.epic_id, force=args.force)
    except (NoReleaseInProgressError, CatalogEntryNotFoundError, GitError,
            EpicNotVerifiableError, EpicPlanError, EpicSyncError,
            DirtyTreeError, NotInFeatureWorktreeError, SlugError) as e:
```

- [ ] **Step 2.7: Fix the stale verb summary.** In `engine/ps-release-workflow/bin/psrw` replace

```python
    "epic":        Verb("epic.py", "Open an epic, fan it out into ideas, verify it", True),
```

with

```python
    "epic":        Verb("epic.py", "Open an epic, fan it out, verify it, plan or sync an epic run", True),
```

- [ ] **Step 2.8: Run everything that touches these files.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
ENG="$WT/engine/ps-release-workflow"
cd "$ENG" && python3 -m pytest tests/test_epic_run.py tests/test_epic_cli.py tests/test_psrw_cli.py tests/test_scripts_runnable.py -q 2>&1 | tail -6
```

Expected: `84 passed` (34 + 14 + 24 + 12), 0 failed.

- [ ] **Step 2.9: Commit.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
git -C "$WT" add engine/ps-release-workflow/scripts/epic.py engine/ps-release-workflow/bin/psrw engine/ps-release-workflow/tests/test_epic_run.py
git -C "$WT" commit -F - <<'EOF'
feat(epic): psrw epic sync merges release/<v> into a slice branch

Feature branches are cut from main, so a slice cannot see earlier slices or its
own spec and plan. sync reads the release HEAD and merges it under
file_lock(_release), prints base (the review anchor) and the post-merge sha,
aborts cleanly on a conflict, and refuses a dirty tree or a non-feature worktree.
Also fixes the psrw epic summary, which omitted plan and sync.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 2.10: Phase gate.** (1) Verify: re-run Step 2.8, expect `84 passed`. (2) Review: dispatch `code-reviewer` and `python-reviewer` on `git -C "$WT" diff HEAD~1..HEAD`, goal verbatim, at most 15 lines back; adversarial questions: "can the merge leave the feature tree half-merged?", "is the lock held across anything but the read-and-merge?", "what if `release/<v>` HEAD moves between the read and the merge?" (the merge uses the sha read under the lock, so it cannot). (3) `/simplify`. (4) Re-verify with Step 2.8. Fix findings as a NEW commit.

---

## Task 3: the `ps-release-workflow-epic-run` skill, its lint, and the install check

**Files:**
- Create: `skills/ps-release-workflow-epic-run/SKILL.md`.
- Create: `engine/ps-release-workflow/tests/test_epic_run_skill.py`.

**Interfaces:**
- Consumes: the verbs and JSON keys produced by Tasks 1-2 (`epic plan`: `allowlist`, `slices[].state|claimed_by|action`; `epic sync`: `base`), existing `psrw refine`, `psrw claim [--resume]`, `psrw ship --no-deploy` whose stdout has a line starting `{"ok"` with `epic_outcome` (`null` or `{"epic", "rc", "sha"}`); `docs/lifecycle.md#gates`.
- Produces: the skill directory `ps-release-workflow-epic-run` (name must equal the directory); the lint constants `SKILLS`, `ANCHORS`, `LINE_BUDGET` and helper `_skill(name) -> (text, frontmatter, body)` in `test_epic_run_skill.py` (extended in Task 4).

- [ ] **Step 3.1: Write the failing lint.** Create `engine/ps-release-workflow/tests/test_epic_run_skill.py`:

```python
"""Repo-relative lint for the epic-run skill and the auto-chain bans.

tests/test_docs_single_source.py reads ~/.claude/skills and skips wherever the
skills are not installed (CI). This file reads the skills straight from the repo
checkout, so it always runs.
"""
import re
from pathlib import Path

import pytest

TOOLKIT = Path(__file__).resolve().parent.parent
SKILLS = TOOLKIT.parent.parent / "skills"
ANCHORS = ["d11-backlog-routing", "gates", "promote-sequence",
           "state-layout", "guard-guarantees"]
LINE_BUDGET = 40

pytestmark = pytest.mark.skipif(not SKILLS.is_dir(), reason=f"{SKILLS} not present")


def _skill(name: str) -> tuple[str, str, str]:
    """(full text, frontmatter, body) of skills/ps-release-workflow-<name>/SKILL.md."""
    text = (SKILLS / f"ps-release-workflow-{name}" / "SKILL.md").read_text()
    _, frontmatter, body = text.split("---", 2)
    return text, frontmatter, body


def test_epic_run_body_is_within_the_line_budget():
    _, _, body = _skill("epic-run")
    lines = [line for line in body.strip().splitlines() if line.strip()]
    assert len(lines) <= LINE_BUDGET, f"{len(lines)} non-blank body lines (budget {LINE_BUDGET})"


def test_epic_run_frontmatter_has_name_and_description():
    text, frontmatter, _ = _skill("epic-run")
    assert [line for line in text.splitlines() if line == "---"] == ["---", "---"]
    assert "name: ps-release-workflow-epic-run" in frontmatter
    assert "description:" in frontmatter


def test_epic_run_links_only_known_lifecycle_anchors():
    text, _, _ = _skill("epic-run")
    fragments = re.findall(r"lifecycle\.md#([a-z0-9-]+)", text)
    assert "gates" in fragments
    assert set(fragments) <= set(ANCHORS)


def test_epic_run_never_promotes():
    _, _, body = _skill("epic-run")
    assert "NEVER run `psrw promote`" in body
    assert "`psrw ship --deploy`" in body and "merge anything to main" in body


def test_epic_run_uses_every_verb_the_chain_needs():
    text, _, _ = _skill("epic-run")
    for token in ("psrw epic plan", "--allow-no-precheck", "psrw refine", "psrw claim",
                  "--resume", "psrw epic sync", "psrw ship --no-deploy", '{"ok"',
                  "git diff --quiet", "git log release/", "/self-grill-audit",
                  "Never blind-retry"):
        assert token in text, f"epic-run skill never mentions {token!r}"


def test_no_skill_uses_the_slash_form_of_the_namespace():
    for skill in sorted(SKILLS.glob("ps-release-workflow-*/SKILL.md")):
        assert "/ps-release-workflow:" not in skill.read_text(), skill.parent.name
```

- [ ] **Step 3.2: Run it and watch it fail.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
ENG="$WT/engine/ps-release-workflow"
cd "$ENG" && python3 -m pytest tests/test_epic_run_skill.py -q 2>&1 | tail -10
```

Expected: `5 failed, 1 passed` — five tests fail with `FileNotFoundError: ... skills/ps-release-workflow-epic-run/SKILL.md`; only the slash-form test passes.

- [ ] **Step 3.3: Write the skill.** Create `skills/ps-release-workflow-epic-run/SKILL.md` with exactly this content (40 non-blank body lines, exactly at the budget of 40; any addition must be paid for by cutting elsewhere):

````markdown
---
name: ps-release-workflow-epic-run
description: |
  Use when the user asks to run an epic — "epic run E-NNN", "chain the approved
  slices", "drive this epic to shipped" — in a ps-release-workflow repo. Takes an
  explicit --slices allowlist of approved slice ideas through refine, claim,
  implement, review and ship --no-deploy, one at a time, stops at the first
  failed gate, and never promotes. Not for a single feature: use claim and ship.
---

# ps-release-workflow:epic-run

Drive an epic's approved slices to `shipped` on the release branch, one at a time.
The ONE sanctioned exception to "never auto-chain", only for slices the human named
in `--slices`. Approval is never inferred.

## Hard rules

- **NEVER run `psrw promote`, `psrw ship --deploy`, or merge anything to main.**
- Stop at the FIRST failed gate: report it and change nothing more. Never skip a slice.
- One chain per epic. State lives only in the catalogs; re-running resumes.

## Preflight

    psrw epic plan E-NNN --slices I-001,I-002 [--allow-no-precheck]

Run it again before EVERY slice, not once. `ERROR:` -> STOP. Otherwise it lists each
slice in order with `state`, `claimed_by`, `action`. Touch only slices in its `allowlist`.

## Per slice, in order (any failure -> STOP and report)

1. `skip` -> next slice. `refine` -> `psrw refine I-NNN`, then `psrw claim F-NNN`
   (default owner, never `--owner`).
2. `resume` -> STOP if `claimed_by` differs from this machine's owner id
   (`$CLAUDE_SESSION_ID`, else `~/.cache/ps-release-workflow/session-id`); that only
   catches another machine or an explicit owner, never another local session. Before
   `psrw claim F-NNN --resume` REQUIRE a clean tree AND `git log release/<v>..HEAD`
   inspected: commits there mean the implementer re-runs against them, never a takeover.
3. In the worktree run `psrw epic sync`. Conflict -> STOP. Keep its `base` sha.
4. Implement: dispatch a subagent that starts with `psrw claim F-NNN --resume`, then
   runs /writing-plans (plan path `.claude/refined_backlog/F-NNN/plan.md`), gets an
   independent /self-grill-audit of that plan (accepted cost), then runs
   /subagent-driven-development. It never edits `_catalog.json`. On a resumed slice,
   tell it which plan tasks are already ticked.
5. Independent whole-slice review of `git diff <base> HEAD` (code-reviewer plus the
   language reviewer); step 4's per-task reviews are per-phase and do not replace it.
   Fix; re-review. Still failing after 2 rounds -> STOP.
6. Verify: full test suite passes, tree clean and committed, else STOP. If
   `git diff --quiet <base> HEAD` (the slice added no commits) -> STOP.
7. Ship: `psrw ship --no-deploy` in the worktree. Non-zero -> STOP. Never blind-retry
   ship: read the error and fix the cause first.

## After the last slice

Parse ONLY the stdout line starting `{"ok"` from the last ship. `epic_outcome` null ->
"epic incomplete" (a slice outside the allowlist is unshipped, or another check holds
it). `rc` 0 -> verified. `rc` null -> "unverified, check skipped", never success.
Any other `rc` -> failed check. Report each slice as shipped or stopped-at-gate.

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#gates`
Flags: `psrw epic --help`
````

- [ ] **Step 3.4: Run the lint to green.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
ENG="$WT/engine/ps-release-workflow"
cd "$ENG" && python3 -m pytest tests/test_epic_run_skill.py -q 2>&1 | tail -4
```

Expected: `6 passed`.

- [ ] **Step 3.5: Install into a sandbox and run the real lint plus the skill count.** `tests/test_docs_single_source.py` reads `~/.claude/skills` and skips in CI, so an uninstalled skill is unlinted. Install into a throwaway home (never the real `~/.claude`), then lint it and count the epic skills. `PYTHONUSERBASE` keeps pytest importable under the sandbox `HOME`.

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
ENG="$WT/engine/ps-release-workflow"
H=$(mktemp -d)
UB="$(python3 -m site --user-base)"
cd "$WT" && HOME="$H" CLAUDE_HOME="$H/.claude" AGENTS_HOME="$H/.agents" GEMINI_HOME="$H/.gemini/config" \
  CURSOR_HOME="$H/.cursor" BIN_HOME="$H/.local/bin" ./install.sh -y > "$H/install.out" 2>&1; echo "install rc=$?"
ls "$H/.claude/skills" | grep -c '^ps-release-workflow-'
ls "$H/.claude/skills" | grep 'epic'
cd "$ENG" && HOME="$H" PYTHONUSERBASE="$UB" python3 -m pytest tests/test_docs_single_source.py -q 2>&1 | tail -4
cd "$ENG" && HOME="$H" PYTHONUSERBASE="$UB" python3 -m pytest tests/test_docs_single_source.py -q -k epic-run 2>&1 | tail -3
```

Expected: `install rc=0`; the count is `16` (15 on `release/1.1` plus `epic-run`); the grep lists `ps-release-workflow-epic-fanout`, `-epic-open`, `-epic-run`; the full lint prints `49 passed, 2 skipped` (the 2 skips are the exempt `full-promote`); the `-k epic-run` run prints `3 passed`. (Verified against a scratch copy of the release tree while writing this plan.) Remove the sandbox afterwards: `rm -rf "$H"`.

- [ ] **Step 3.6: Commit.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
git -C "$WT" add skills/ps-release-workflow-epic-run/SKILL.md engine/ps-release-workflow/tests/test_epic_run_skill.py
git -C "$WT" commit -F - <<'EOF'
feat(epic): ps-release-workflow-epic-run skill and its lint

The agent-driven loop over an epic's allowlisted slices: preflight with epic
plan, then per slice refine or claim, epic sync, an implementer subagent, review
of git diff <base> HEAD, verify, ship --no-deploy. Stops at the first failed gate
and carries an explicit never-promote rule. The repo-relative lint runs in CI.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 3.6b: Phase gate.** (1) Verify: Step 3.4 (`6 passed`) and the Step 3.5 lint (`49 passed, 2 skipped`). (2) Review: run `self-grill-audit` on `skills/ps-release-workflow-epic-run/SKILL.md` against the spec's sections 3-5 and 7 (does any step let a session run `promote`, skip a slice, or continue after a failure?), and dispatch `code-reviewer` plus `python-reviewer` on `git -C "$WT" diff HEAD~1..HEAD -- engine`. (3) `/simplify`. (4) Re-verify Steps 3.4 and 3.5. Fix findings as a NEW commit.

---

## Task 4: name `epic run` as the sanctioned exception in the five skills, and the docs

**Files:**
- Modify: `skills/ps-release-workflow-idea/SKILL.md` (description line 8, body lines 29-30), `skills/ps-release-workflow-refine/SKILL.md` (description line 7, body lines 18-19), `skills/ps-release-workflow-claim/SKILL.md` (description line 9, body lines 19-20), `skills/ps-release-workflow-epic-open/SKILL.md` (description lines 8-9, body line 30), `skills/ps-release-workflow-epic-fanout/SKILL.md` (description line 8, body line 26).
- Modify: `engine/ps-release-workflow/docs/lifecycle.md` (insert a subsection directly above `### Overriding the gate scripts: the \`hooks\` block`, currently line 74).
- Modify: `engine/ps-release-workflow/docs/known-issues.md` (insert before `## Test-suite cost`, line 27; one sentence on the "Sibling features" bullet, line 23).
- Modify: `engine/ps-release-workflow/tests/test_epic_run_skill.py`.

**Interfaces:**
- Consumes: `_skill(name)` and the `SKILLS` constant from Task 3.
- Produces: the constant `CHAIN_BANS` and test `test_every_auto_chain_ban_names_epic_run_as_the_exception`; each of the five skills' description and body contain the token `epic-run`.

- [ ] **Step 4.1: Write the failing test.** In `tests/test_epic_run_skill.py` replace

```python
LINE_BUDGET = 40
```

with

```python
LINE_BUDGET = 40
CHAIN_BANS = ["idea", "refine", "claim", "epic-open", "epic-fanout"]
```

and append (two blank lines before):

```python
@pytest.mark.parametrize("name", CHAIN_BANS)
def test_every_auto_chain_ban_names_epic_run_as_the_exception(name):
    """The description is the auto-trigger surface, so the exception must be in the
    frontmatter as well as the body, or a session would still refuse to chain."""
    _, frontmatter, body = _skill(name)
    assert "epic-run" in frontmatter, f"{name}: description does not name epic-run"
    assert "epic-run" in body, f"{name}: body does not name epic-run"
```

- [ ] **Step 4.2: Run it and watch it fail.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
ENG="$WT/engine/ps-release-workflow"
cd "$ENG" && python3 -m pytest tests/test_epic_run_skill.py -q 2>&1 | tail -8
```

Expected: `5 failed, 6 passed`; each failure reads `AssertionError: <name>: description does not name epic-run`.

- [ ] **Step 4.3: Edit the five skills.** Each pair is an exact-match replacement (each `old` occurs exactly once). Descriptions are the auto-trigger surface, so both the frontmatter and the body change. Bodies stay far under the 40-line budget (idea 20, refine 21, claim 29, epic-open 18, epic-fanout 19 after the edits).

`skills/ps-release-workflow-idea/SKILL.md`, replace

```
  refine only once the spec is solid. Never auto-chain idea -> refine -> claim.
```

with

```
  refine only once the spec is solid. Never auto-chain idea -> refine -> claim.
  Sole exception: the epic-run skill, for slices a human allowlisted.
```

and replace

```
Refining or claiming an idea whose spec is still the empty skeleton is the exact mistake
this gate prevents.
```

with

```
Refining or claiming an idea whose spec is still the empty skeleton is the exact mistake
this gate prevents.

**Sole exception:** the `epic-run` skill (`ps-release-workflow-epic-run`) refines and
claims slices in one chain, but only those a human listed in its `--slices` allowlist.
```

`skills/ps-release-workflow-refine/SKILL.md`, replace

```
  already has a solid, approved spec — never auto-chain idea -> refine -> claim.
```

with

```
  already has a solid, approved spec — never auto-chain idea -> refine -> claim.
  Sole exception: the epic-run skill, for slices a human allowlisted.
```

and replace

```
an `F-NNN` (and invites a premature claim + worktree) before the design is settled.
```

with

```
an `F-NNN` (and invites a premature claim + worktree) before the design is settled.
The sole exception is the `epic-run` skill, which refines only slices a human listed in
its `--slices` allowlist; `psrw epic plan` refuses a slice whose spec is still a skeleton.
```

`skills/ps-release-workflow-claim/SKILL.md`, replace

```
  After this skill: hint to implement via /subagent-driven-development.
---
```

with

```
  After this skill: hint to implement via /subagent-driven-development.
  Chained automatically only by the epic-run skill, for slices a human allowlisted.
---
```

and replace

```
idea -> refine -> claim** — each is a separate, human-approved step.
```

with

```
idea -> refine -> claim** — each is a separate, human-approved step. The sole
exception is the `epic-run` skill, for slices a human listed in its `--slices` allowlist.
```

`skills/ps-release-workflow-epic-open/SKILL.md`, replace

```
  FIRST, then fan it out with ps-release-workflow-epic-fanout.
---
```

with

```
  FIRST, then fan it out with ps-release-workflow-epic-fanout. Only the epic-run skill
  may later chain the slices, and only those a human allowlisted.
---
```

and replace

```
Only then fan out. Never auto-chain open -> fanout -> refine -> claim.
```

with

```
Only then fan out. Never auto-chain open -> fanout -> refine -> claim. The sole exception
is the `epic-run` skill, which chains refine -> claim for slices a human allowlists.
```

`skills/ps-release-workflow-epic-fanout/SKILL.md`, replace

```
  before refining it.
---
```

with

```
  before refining it. Only the epic-run skill may chain refine and claim, and only for
  slices a human allowlisted.
---
```

and replace

```
and approved spec before `psrw refine I-NNN`. Do NOT chain fanout -> refine -> claim.
```

with

```
and approved spec before `psrw refine I-NNN`. Do NOT chain fanout -> refine -> claim,
except through the `epic-run` skill, for slices a human listed in its `--slices` allowlist.
```

- [ ] **Step 4.4: Run the lint to green.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
ENG="$WT/engine/ps-release-workflow"
cd "$ENG" && python3 -m pytest tests/test_epic_run_skill.py -q 2>&1 | tail -4
```

Expected: `11 passed`.

- [ ] **Step 4.5: Add the lifecycle subsection.** `docs/lifecycle.md` has no auto-chain text, so this is an addition. In `engine/ps-release-workflow/docs/lifecycle.md` replace the heading line

```
### Overriding the gate scripts: the `hooks` block
```

with

```
### Epic run: the sanctioned auto-chain

`ps-release-workflow-epic-run` chains refine, claim, implement, review and
`ship --no-deploy` over an epic's slices, one at a time. It is the one exception to
"never auto-chain", and only for slices a human names in an explicit `--slices`
allowlist (approval lives in that list, not in any catalog field). It never runs
`promote`, `--deploy`, or a merge to main.

- **`psrw epic plan E-NNN --slices I-a,I-b`** is a read-only preflight. It prints each
  allowlisted slice in fanout order with `state` (`idea`, `refined`, `claimed`,
  `shipped`), `claimed_by` and next `action` (`refine`, `claim`, `resume`, `skip`). It
  refuses an epic that is `verified`, `promoted` or `verifying`; a slice that is not a
  child of the epic or is already promoted; a slice whose idea `spec.md` is still an
  untouched skeleton; and a repo with no Gate 1 script unless `--allow-no-precheck`
  (ship would otherwise skip Gate 1 with only a warning). A `failed_verification` epic
  is allowed, with a note.
- **`psrw epic sync`**, run inside a claimed feature worktree, merges `release/<v>`'s
  HEAD into the feature branch under `file_lock(_release)`. Feature branches are cut
  from `main`, so without it slice N cannot see slices 1..N-1 or its own spec and plan.
  It prints `base` (the release HEAD merged; `git diff <base> HEAD` is the slice's own
  work) and `sha` (the post-merge HEAD). A conflict aborts the merge and leaves the
  feature claimed; a dirty tree is refused.
- **State** lives only in the catalogs. There is no run lock, so two chains on one epic
  are unsupported, and re-running the same command resumes at the first unshipped
  slice. Gate 1 runs twice on the combined tree per slice, so each ship is slower.

### Overriding the gate scripts: the `hooks` block
```

- [ ] **Step 4.6: Record the known issues.** In `engine/ps-release-workflow/docs/known-issues.md`, first append one sentence to the "Sibling features are developed blind to each other" bullet: replace

```
`psrw status` only warns when two or more siblings are claimed at once; it does not prevent it.
```

with

```
`psrw status` only warns when two or more siblings are claimed at once; it does not prevent it. `psrw epic sync` (used by the `epic-run` skill) closes this for a chained run; a hand-run claim is still blind.
```

Then replace the heading

```
## Test-suite cost
```

with

```
- **`ship`'s post-merge rollback can drop an unrelated release commit.** When the feature branch is already contained in `release/<v>` (a slice that added no commits after `psrw epic sync`, which fast-forwards), `git merge --no-ff` prints "Already up to date" and creates no commit, so a Gate 1 failure on the merged tree runs `git reset --hard HEAD~1` against whatever release commit was last (for example a catalog commit). Pre-existing in `ship_current_work_to_release.py`; `epic run` makes it likelier. Not fixed here. Untested mitigation candidate: have `epic sync` merge with `--no-ff` so a synced feature always carries a commit.
- **`skills/ps-release-workflow-refine/SKILL.md` lines 21-23 are stale.** They say refine writes fresh skeleton `spec.md`/`plan.md`/`research.md` and does not copy the idea folder; the code carries the idea's content forward (`_carry_forward` copies the folder, replacing only untouched skeletons). The description's "moves the folder" is also wrong: the idea folder stays in place.

## Test-suite cost
```

- [ ] **Step 4.7: Re-run the real lint and the repo lint.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
ENG="$WT/engine/ps-release-workflow"
H=$(mktemp -d)
UB="$(python3 -m site --user-base)"
cd "$WT" && HOME="$H" CLAUDE_HOME="$H/.claude" AGENTS_HOME="$H/.agents" GEMINI_HOME="$H/.gemini/config" \
  CURSOR_HOME="$H/.cursor" BIN_HOME="$H/.local/bin" ./install.sh -y > "$H/install.out" 2>&1; echo "install rc=$?"
cd "$ENG" && HOME="$H" PYTHONUSERBASE="$UB" python3 -m pytest tests/test_docs_single_source.py tests/test_epic_run_skill.py -q 2>&1 | tail -4
rm -rf "$H"
```

Expected: `install rc=0` and `60 passed, 2 skipped` (49 from the real lint plus 11 from the repo lint; the 2 skips are the exempt `full-promote`). The hard requirement is 0 failed.

- [ ] **Step 4.8: Commit.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
git -C "$WT" add skills/ps-release-workflow-idea/SKILL.md skills/ps-release-workflow-refine/SKILL.md skills/ps-release-workflow-claim/SKILL.md skills/ps-release-workflow-epic-open/SKILL.md skills/ps-release-workflow-epic-fanout/SKILL.md engine/ps-release-workflow/docs/lifecycle.md engine/ps-release-workflow/docs/known-issues.md engine/ps-release-workflow/tests/test_epic_run_skill.py
git -C "$WT" commit -F - <<'EOF'
docs(epic): name epic run as the one sanctioned auto-chain exception

Five skills said never to auto-chain (idea, refine, claim, epic-open,
epic-fanout); their descriptions are the auto-trigger surface, so each now names
epic-run in both frontmatter and body, pinned by a lint. lifecycle.md gains an
"Epic run" subsection; known-issues records the ship rollback defect (zero-commit
slice plus a failing Gate 1) and the stale refine skill text.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 4.9: Phase gate.** (1) Verify: Step 4.4 (`11 passed`) and Step 4.7 (0 failed). (2) Review: `code-reviewer` on `git -C "$WT" diff HEAD~1..HEAD` with the adversarial question "does any edited skill still tell a reader to refuse the chain, or does any new sentence widen the exception beyond a human allowlist?", plus `python-reviewer` on the test change. (3) `/simplify`. (4) Re-verify with Step 4.7. Fix findings as a NEW commit.

---

## Task 5: integration — mechanics test, agent dry run, full suite, ship

**Files:**
- Create: `engine/ps-release-workflow/tests/test_epic_run_e2e.py`.
- Create (outside the repo, not committed): `${TMPDIR:-/tmp}/epic-run-scaffold.sh`, `${TMPDIR:-/tmp}/epic-run-dry/`.

**Interfaces:**
- Consumes: `epic_plan`, `epic_sync` (Tasks 1-2); existing `promote_idea_to_refined(repo, idea_id) -> dict`, `claim_feature(repo, feature_id, *, owner) -> dict` (`["worktree"]`), `ship_current_work(worktree) -> dict` (`["epic_outcome"]`); the fixture `epic_repo`; the skill from Tasks 3-4.
- Produces: the composed-mechanics test; a recorded dry-run verdict (one forced stop, one re-run to completion); a shipped feature on `release/1.1` (never promoted).

- [ ] **Step 5.1: Write the composed-mechanics test.** Create `engine/ps-release-workflow/tests/test_epic_run_e2e.py`:

```python
"""The psrw verbs an `epic run` calls, composed for a two-slice epic.

Only the LLM steps are stubbed (a commit stands in for "implement"); every psrw
call the chain makes is the real one, so this pins the mechanics the skill relies
on: slice 2 sees slice 1, sync's `base` isolates a slice's own diff, ship works on
a synced branch, the last ship records the epic outcome, and main never moves.
"""
import subprocess
from pathlib import Path

import pytest

from lib.backlog_paths import get_backlog_catalog_path, get_release_worktree
from lib.catalog import find_entry
from lib.git_ops import commit_all
from scripts.epic import EpicPlanError, epic_plan, epic_sync
from scripts.init_work_refined_backlog import claim_feature
from scripts.promote_idea_to_refined import promote_idea_to_refined
from scripts.ship_current_work_to_release import ship_current_work


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def _run_slice(repo: Path, idea_id: str, filename: str) -> dict:
    """Refine, claim, sync, 'implement' (one commit), ship: the chain minus the LLM."""
    feature = promote_idea_to_refined(repo, idea_id)["id"]
    wt = Path(claim_feature(repo, feature, owner="chain-owner")["worktree"])
    synced = epic_sync(wt)
    (wt / filename).write_text(f"{idea_id}\n")
    commit_all(wt, f"feat: {idea_id}")
    return {"feature": feature, "wt": wt, "synced": synced, "shipped": ship_current_work(wt)}


def test_two_slice_chain_ships_in_order_and_verifies_the_epic(epic_repo):
    repo = epic_repo
    rel = get_release_worktree(repo)
    main_before = _git(repo, "rev-parse", "main")

    first = _run_slice(repo, "I-001", "one.txt")
    assert first["shipped"]["epic_outcome"] is None, "epic is not complete after slice 1"
    assert [s["action"] for s in epic_plan(repo, "E-001", "I-001,I-002")["slices"]] == [
        "skip", "refine"]

    second = _run_slice(repo, "I-002", "two.txt")
    # slice 2 was cut from main, yet it saw slice 1's shipped work after sync
    assert (second["wt"] / "one.txt").read_text() == "I-001\n"
    # and `base` still isolates slice 2's own diff for review
    assert _git(second["wt"], "diff", "--name-only", second["synced"]["base"], "HEAD") == "two.txt"

    outcome = second["shipped"]["epic_outcome"]
    assert outcome["epic"] == "E-001"
    assert outcome["rc"] is None, "no epic-check.sh here: skipped, not passed"
    epic = find_entry(get_backlog_catalog_path(repo, "epic"), "E-001")
    assert epic["status"] == "verified"

    refined = get_backlog_catalog_path(repo, "refined")
    assert [find_entry(refined, f["feature"])["status"] for f in (first, second)] == [
        "shipped", "shipped"]
    assert (rel / "one.txt").is_file() and (rel / "two.txt").is_file()
    assert _git(repo, "rev-parse", "main") == main_before, "the chain never touches main"

    with pytest.raises(EpicPlanError, match="verified"):
        epic_plan(repo, "E-001", "I-001,I-002")
```

- [ ] **Step 5.2: Run it.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
ENG="$WT/engine/ps-release-workflow"
cd "$ENG" && python3 -m pytest tests/test_epic_run_e2e.py -q 2>&1 | tail -4
```

Expected: `1 passed`. This test pins the composition of code that already exists, so it passes on the first run; the next step proves it can fail.

- [ ] **Step 5.3: Prove it bites.** Temporarily replace `synced = epic_sync(wt)` in `_run_slice` with `synced = {"base": _git(wt, "rev-parse", "HEAD")}`, run the test, expect `FileNotFoundError` on `(second["wt"] / "one.txt").read_text()` (slice 2 never saw slice 1), then restore the line and re-run to `1 passed`.

- [ ] **Step 5.4: Commit the test.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
git -C "$WT" add engine/ps-release-workflow/tests/test_epic_run_e2e.py
git -C "$WT" commit -F - <<'EOF'
test(epic): two-slice chain mechanics, only the LLM stubbed

Runs the real plan, refine, claim, sync, ship calls for two slices: slice 2 sees
slice 1 after sync, base isolates each slice's diff, the last ship records the
epic outcome as verified, main never moves, and plan then refuses the finished epic.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 5.5: Write the scaffold script** to `${TMPDIR:-/tmp}/epic-run-scaffold.sh` (outside the repo; do not commit it). It builds a throwaway repo with a real `precheck.sh` and `epic-check.sh`, opens epic `E-001`, fans out two slices, and writes approved specs; slice 2's spec requires importing slice 1's file, which is only possible after `epic sync`.

```bash
#!/usr/bin/env bash
# Build a throwaway two-slice epic for the `epic run` dry run.
# Usage: scaffold.sh <dry-dir ending in /epic-run-dry> <engine dir of the branch under test>
set -euo pipefail
DRY="$1"
ENGINE="$2"
[[ "$DRY" == */epic-run-dry ]] || { echo "refusing: DRY must end in /epic-run-dry" >&2; exit 1; }
[[ -x "$ENGINE/bin/psrw" ]] || { echo "no psrw under $ENGINE" >&2; exit 1; }
[[ ! -e "$DRY" ]] || { echo "refusing: $DRY already exists; remove it first" >&2; exit 1; }

mkdir -p "$DRY/home" "$DRY/bin"
# `psrw` on PATH for the agent, pinned to the branch's engine (the installed one is main's).
printf '#!/usr/bin/env bash\nexec python3 "%s/bin/psrw" "$@"\n' "$ENGINE" > "$DRY/bin/psrw"
chmod +x "$DRY/bin/psrw"
export PATH="$DRY/bin:$PATH"
# A private HOME for THIS script only, so `psrw init` cannot append to ~/.claude/CLAUDE.md.
export HOME="$DRY/home"

git init -q -b main "$DRY/repo"
cd "$DRY/repo"
git config user.email dry@run.test
git config user.name "Dry Run"
mkdir -p scripts tests
touch tests/__init__.py
cat > tests/test_smoke.py <<'PY'
import unittest


class Smoke(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(True)
PY
cat > scripts/precheck.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
python3 -m unittest discover -s tests -t . -q
SH
cat > scripts/epic-check.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
python3 -c "import greet, farewell; assert farewell.farewell('a').endswith('Goodbye!')"
SH
chmod +x scripts/precheck.sh scripts/epic-check.sh
echo "dry run" > README.md
git add -A
git commit -qm "initial"
git init -q --bare "$DRY/origin.git"
git remote add origin "$DRY/origin.git"
git push -q -u origin main

psrw init > /dev/null
git push -q origin main
psrw new-release > /dev/null
psrw epic open "Greeting epic" > /dev/null
psrw epic fanout E-001 "greet function" "farewell function" > /dev/null

REL="$DRY/repo/.claude/worktrees/_release"
cat > "$REL"/.claude/idea_backlog/I-001-*/spec.md <<'MD'
# greet function

Approved. Add `greet.py` with `greet(name: str) -> str` returning `Hello, <name>!`,
and `tests/test_greet.py` (unittest) covering it. Touch nothing else.
MD
cat > "$REL"/.claude/idea_backlog/I-002-*/spec.md <<'MD'
# farewell function

Approved. Add `farewell.py` with `farewell(name: str) -> str` returning
`greet(name) + " Goodbye!"`, importing `greet` from `greet.py` (slice one's file), and
`tests/test_farewell.py` (unittest) covering it. Touch nothing else.
MD
git -C "$REL" add -A
git -C "$REL" commit -qm "docs: approved slice specs"
echo "scaffolded $DRY/repo (main=$(git rev-parse main))"
```

- [ ] **Step 5.6: Scaffold and check the preflight.**

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
DRY="${TMPDIR:-/tmp}/epic-run-dry"
bash "${TMPDIR:-/tmp}/epic-run-scaffold.sh" "$DRY" "$WT/engine/ps-release-workflow"
git -C "$DRY/repo" rev-parse main > "$DRY/main.sha"
cd "$DRY/repo" && PATH="$DRY/bin:$PATH" psrw epic plan E-001 --slices I-001,I-002 \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['epic_status'], d['allowlist']); [print(s) for s in d['slices']]"
```

Expected: last line of the scaffold `scaffolded .../epic-run-dry/repo (main=<sha>)`; the plan prints `open ['I-001', 'I-002']` then two slices `{'idea': 'I-00N', 'feature': None, 'state': 'idea', 'claimed_by': None, 'action': 'refine'}`.

- [ ] **Step 5.7: Set up the forced stop.** Pre-claim slice 2 under a foreign owner so the chain must refuse to take it. (Feature ids are minted in refine order, so I-002 becomes `F-001` here and I-001 will become `F-002`; use the ids printed.)

```bash
DRY="${TMPDIR:-/tmp}/epic-run-dry"
cd "$DRY/repo" && export PATH="$DRY/bin:$PATH"
psrw refine I-002 | head -1
psrw claim F-001 --owner someone-else | head -1 | cut -c1-70
psrw epic plan E-001 --slices I-001,I-002 | python3 -c "import json,sys; [print(s) for s in json.load(sys.stdin)['slices']]"
```

Expected plan lines: `I-001 ... 'state': 'idea' ... 'action': 'refine'` and `I-002 ... 'feature': 'F-001', 'state': 'claimed', 'claimed_by': 'someone-else', 'action': 'resume'`.

**Limit of this test:** the owner check only distinguishes another machine or an explicit `--owner`. Every local session shares the machine-cached owner id (`resolve_owner_id()`, `lib/owner.py:34-40`), so a stale claim left by an earlier or concurrent session on THIS machine looks identical to the chain's own. This test proves the check fires for a foreign owner and nothing more; the protection against silently taking over live local work is the skill's second requirement (clean tree AND `git log release/<v>..HEAD` inspected before `--resume`), which the dry run does not exercise.

- [ ] **Step 5.8: Run 1 — the agent follows the skill (expected to stop at slice 2).** Dispatch one general-purpose subagent with this prompt (substitute the real paths):

> You are running `epic run`. Working directory `<DRY>/repo`; run every psrw command with `PATH="<DRY>/bin:$PATH"`. Read `<WT>/skills/ps-release-workflow-epic-run/SKILL.md` and follow it literally for epic `E-001` with `--slices I-001,I-002`. Dispatch real subagents for implementation as the skill says (this exercises the nested-dispatch path that Task 0 Step 0.8 Probe 2 checked; if Probe 2 forced a revision of the skill, follow the revised skill). Do not deviate. Report at most 12 lines: per slice shipped or stopped-at-gate, the final `epic_outcome`, and **every tool result that contains `BLOCKED:` verbatim (or "no BLOCKED")**.

Expected report: slice I-001 shipped (refine, claim, sync, implement with the slice plan written at `.claude/refined_backlog/F-NNN/plan.md` and audited before execution, review, verify, `psrw ship --no-deploy`); slice I-002 STOPPED: claimed by `someone-else`, not this machine's owner id; no BLOCKED text; nothing about promote.

- [ ] **Step 5.9: Verify the stop from the outside.**

```bash
DRY="${TMPDIR:-/tmp}/epic-run-dry"
cd "$DRY/repo" && export PATH="$DRY/bin:$PATH"
psrw epic plan E-001 --slices I-001,I-002 | python3 -c "import json,sys; [print(s['idea'], s['state'], s['claimed_by'], s['action']) for s in json.load(sys.stdin)['slices']]"
python3 - <<'PY'
import json, pathlib
rel = pathlib.Path(".claude/worktrees/_release/.claude")
print([(e["id"], e["status"]) for e in json.load(open(rel / "epic_backlog/_catalog.json"))])
print([(f["id"], f["status"]) for f in json.load(open(rel / "refined_backlog/_catalog.json"))])
PY
[ "$(git rev-parse main)" = "$(cat "$DRY/main.sha")" ] && echo "main unchanged"
git -C .claude/worktrees/_release log --oneline | head -4
test -f .claude/worktrees/_release/greet.py && echo "greet.py on release"
```

Expected: I-001 `shipped ... skip`, I-002 `claimed someone-else resume`; epic still `open`; F-002 `shipped`, F-001 `claimed`; `main unchanged`; the release log shows a `merge feat/F-002 into release/1.1` commit; `greet.py on release`.

- [ ] **Step 5.10: Human takeover, then run 2 (the re-run).** The human decides to take slice 2 over (`--resume` re-owns it to the default owner), then re-runs the same command.

```bash
DRY="${TMPDIR:-/tmp}/epic-run-dry"
cd "$DRY/repo" && export PATH="$DRY/bin:$PATH"
psrw claim F-001 --resume | tail -3 | cut -c1-100
```

Expected: `Owner is now <machine id>`. Then dispatch the SAME subagent prompt as Step 5.8 again. Expected report: I-001 skipped (already shipped); I-002 resumed (owner matches), `epic sync` succeeds and `farewell.py` can import `greet` (slice 1's file), implemented, reviewed, verified, shipped; the last ship's `{"ok"` line has `epic_outcome` `{"epic": "E-001", "rc": 0, ...}`, reported as "verified"; no BLOCKED text.

- [ ] **Step 5.11: Verify the end state from the outside, then clean up.**

```bash
DRY="${TMPDIR:-/tmp}/epic-run-dry"
cd "$DRY/repo" && export PATH="$DRY/bin:$PATH"
python3 - <<'PY'
import json, pathlib
rel = pathlib.Path(".claude/worktrees/_release/.claude")
print([(e["id"], e["status"]) for e in json.load(open(rel / "epic_backlog/_catalog.json"))])
print([(f["id"], f["status"]) for f in json.load(open(rel / "refined_backlog/_catalog.json"))])
PY
[ "$(git rev-parse main)" = "$(cat "$DRY/main.sha")" ] && echo "main unchanged"
(cd .claude/worktrees/_release && python3 -m unittest discover -s tests -t . -q 2>&1 | tail -3 && python3 -c "import farewell; print(farewell.farewell('a'))")
psrw epic plan E-001 --slices I-001,I-002 2>&1 | head -1
```

Expected: `[('E-001', 'verified')]`; both features `shipped`; `main unchanged`; unittest `OK`; the last python line prints `Hello, a! Goodbye!`; the final plan call prints `ERROR: E-001 is already verified; there is nothing left to run`. Record the dry-run verdict (pass or the first deviation) in the task notes. Then remove the scratch area (it is a separate repo, so this touches nothing else): `rm -rf "${TMPDIR:-/tmp}/epic-run-dry" "${TMPDIR:-/tmp}/epic-run-scaffold.sh"`. If any expected output differs, STOP and treat it as a defect in the skill or code: fix it in a new task-scoped commit, then repeat Steps 5.5-5.11 from a fresh scaffold.

- [ ] **Step 5.12: Full suite by hand (Gate 1 does not exist in this repo).** `ps-skills` has no `scripts/precheck.sh`, so `psrw ship` skips Gate 1 with a warning; this step replaces it. The suite takes roughly 5 to 9 minutes; run it with a 10-minute timeout or in the background.

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
ENG="$WT/engine/ps-release-workflow"
cd "$ENG" && python3 -m pytest -q 2>&1 | tail -8
```

Expected: 0 failed (the total is the pre-existing count plus the new tests: 34 in `test_epic_run.py`, 1 in `test_epic_run_e2e.py`, 11 in `test_epic_run_skill.py`). Run the sandboxed install lint from Step 4.7 once more; expect 0 failed.

- [ ] **Step 5.13: Phase gate for the whole feature.** (1) Verify: Steps 5.12 and 5.11 are green with visible output. (2) Review: dispatch `code-reviewer` and `python-reviewer` on `git -C "$WT" diff release/1.1...HEAD` (the whole feature) with the goal verbatim, plus `self-grill-audit` on the skill against the dry-run transcript. (3) `/simplify`. (4) Re-verify Step 5.12. Findings become NEW commits.

- [ ] **Step 5.14: Ship to the release branch (R1: `release/1.1` only; never promote).** From inside the worktree, using the branch's own engine, and never with `--deploy`:

```bash
WT=$(ls -d /Users/pasitnusso/ps-skills/.claude/worktrees/F-*-epic-run-* | head -1)
ENG="$WT/engine/ps-release-workflow"
cd "$WT" && git status --short | head -3
python3 "$ENG/bin/psrw" ship --no-deploy 2>&1 | grep -E '^\{"ok"|Shipped|Gate 1|ERROR' | cut -c1-160
```

Expected: no uncommitted files; `Gate 1 SKIPPED` warning (no `precheck.sh` in this repo), then `Shipped F-002 to release/1.1` and a `{"ok": true, ...}` line. Report and stop; do not run `psrw promote`.

---

## Self-review

Checks below were run for real while writing this plan (against a scratch copy of the `release/1.1` tree; the location of this plan is not a git repo, so nothing was committed).

**1. Spec coverage: every spec section maps to a task.**

| Spec section | Where it is implemented or verified |
|---|---|
| Decisions (skill + verbs, `--slices` allowlist, merge release into slice, refuse without precheck, sequential, independent review, stop at first failure, `--no-deploy`, resume/skip, never promote) | Global Constraints; Task 1 (allowlist, skeleton floor, precheck refusal); Task 2 (release merge); Task 3 (skill rules) |
| 1. Components (skill, `epic plan`, `epic sync`, existing verbs unchanged, no new verb registration) | Tasks 1, 2, 3; `test_psrw_cli.py`/`test_scripts_runnable.py` re-run in Steps 1.7 and 2.8; only the summary string in `bin/psrw` changes (Step 2.7) |
| 2. `epic plan` (every refusal, output shape, read-only, `failed_verification` confirmed) | Task 1 (tests for each refusal, ordered state, `claimed_by`, read-only); mismatch 1 in "Spec vs. code" |
| 3. Per-slice loop and `epic_outcome` reading | Task 3 (skill steps 1-7 and "After the last slice"); Task 5 (dry run exercises the loop); mismatches 3-5 |
| 4. Stop conditions, locking, known limitation | Task 3 (STOP rules); Task 2 (lock test `test_sync_holds_the_release_lock_around_the_merge_only`); Task 4 Step 4.6 (rollback defect filed) |
| 5. Session and guard handling | Task 0 Steps 0.7-0.8 (verified first); Task 3 (default owner, `--resume` per subagent, owner check that catches only other machines or explicit owners, plus the clean-tree and `git log` requirement before resume); Task 5 Steps 5.8-5.10 (BLOCKED-free run) |
| 6. Testing (unit, skill lint, integration) | Tasks 1-2 (unit), Task 3 Step 3.5 (`install.sh` then the real lint, epic skill count 16), Task 5 (composed test plus the two-slice dry run with one forced stop and a re-run) |
| 7. Enforcement, honestly | Code enforces (Tasks 1-2 tests); prose-only items are named in the skill's Hard rules, pinned by `test_epic_run_never_promotes` |
| 8. Out of scope | Global Constraints (copied verbatim); no task touches them |
| 9. Risks and unknowns (subagent session id, spec visibility, five skills, stale docs, slower ships) | Task 0 (a), (b) and (c: nested dispatch, with a stop rule); Task 4 (five skills + `lifecycle.md` addition + known-issues); Task 4 Step 4.5 (slower ships sentence); stale `epic --help` fixed in Task 2 |

**2. Placeholder scan.** `grep -nE "TBD|TODO|similar to Task|appropriate error|fill in|as needed|and so on|etc\."` over the plan body above this section returned 0 hits. Every code step contains the actual code; every edit is an exact old/new pair or a named insertion point.

**3. Every cited existing symbol and path exists.** 34 symbols/paths were grepped in the `release/1.1` tree (`read_release_state`, `get_release_worktree`, `find_entry`, `epic_children`, `resolve_hook`, `HookPathError`, `_is_untouched_skeleton`, `_find_marker`, `DirtyTreeError`, `NotInFeatureWorktreeError`, `file_lock`, `is_dirty`, `mark_shipped`, `mark_promoted_to_main`, `mark_epic_failed`, `mark_epic_promoted`, `try_begin_verification`, `claim_feature`, `ship_current_work`, and the rest); each has at least one definition. Line ranges in the Files lists were re-read from the files (for example `conftest.py` is 88 lines, `known-issues.md` "Sibling features" is line 23, `## Test-suite cost` is line 27).

**4. The plan's edits were replayed mechanically.** A script parsed all 24 "replace ... with ..." pairs out of this plan text and applied them, together with the plan's inserted blocks and appended chunks (replayed by hand-coded steps that mirror the plan's prose), in plan order to a pristine copy of the release tree, then compared the result with the separately validated tree: `scripts/epic.py`, `tests/test_epic_run.py` (Tasks 1+2 combined), `tests/test_epic_run_skill.py` (Tasks 3+4 combined) and the five edited skills were byte-identical. On that replayed tree: 96 tests passed (34 + 1 + 11 + 14 + 24 + 12 across the six files run in the steps above), the sandboxed install put 16 `ps-release-workflow-*` skills in place, and `test_docs_single_source.py` plus the repo lint gave `60 passed, 2 skipped`. Two mutation checks (skeleton detection disabled; `epic_sync` bypassed in the composed test) each made the intended tests fail, and passed again once restored. The scaffold script and a manual run of the two-slice chain (forced foreign claim, takeover, sync, ship, epic `verified` with `rc` 0, `main` unchanged) matched the plan and ship outputs written in Task 5; the final `unittest` and `farewell` lines of Step 5.11 were not run.

**5. Type and name consistency.** `epic_plan(repo, epic_id, slices: str, allow_no_precheck=False) -> dict` and `epic_sync(cwd) -> dict` have one signature across the Interfaces blocks, tests, CLI wiring and the skill. Result keys (`allowlist`, `slices[].state|claimed_by|action`, `precheck`, `notes`; `feature`, `branch`, `release`, `base`, `sha`) are used identically in code, tests, `lifecycle.md` and the skill. `EpicPlanError` and `EpicSyncError` are defined before use and caught in `main()`. `claim_feature` is called with the keyword-only `owner=`, matching its real signature.

**6. Not verified, and why.**
- Task 0 unknown (b), part 2 (a live Claude Code subagent editing under a resumed claim) and the two agent runs in Task 5 cannot be executed while planning; the offline guard check (exit 0 for an unrelated session id after a default-owner claim, exit 2 for the main checkout) was run against a scratch repo and passed.
- The full pre-existing pytest suite was not run on the changed tree here (about 5 to 9 minutes); Task 5 Step 5.12 does it. Only the epic, CLI, and runnable-script tests were run (all green).
- Nested subagent dispatch (a subagent dispatching subagents) is unverified until Task 0 Step 0.8 Probe 2 runs; the skill is written on the assumption that it works, and the fallback (main session dispatches the implementer and reviewers directly) is specified there.
- The slice's own plan (written by the implementer with `writing-plans`) is independently audited only by the skill's `self-grill-audit` line, an accepted extra cost per slice; it is not exercised beyond the dry run.
- The `--no-ff` mitigation for the ship rollback defect is recorded in `known-issues.md` as untested and is not implemented.
- `ps-skills` has no `scripts/precheck.sh`, so `psrw ship` on this work skips Gate 1; Step 5.12 is the substitute.

## Audit trail

- 2026-09-19 self-grill-audit (independent, second pass): verdict **safe-with-fixes**. Corrected:
  - **Nested dispatch (high).** Task 0 Step 0.8 gains Probe 2 (a subagent dispatches a subagent; level 3 also reported) with an explicit STOP rule and fallback: if nesting is refused, the skill is not built as written; the main session dispatches the implementer and reviewers directly, and the plan is re-audited. Task 5 Step 5.8 references it.
  - **Owner check (high).** The "claimed by an owner it did not create" rule only distinguishes another machine or an explicit `--owner` (the default owner is the machine-cached id shared by every local session, `lib/owner.py:34-40`). The skill now also REQUIRES a clean tree and an inspected `git log release/<v>..HEAD` before any `--resume`; Step 5.7 keeps its foreign-owner test and states its limits.
  - **Ship retry (medium).** Skill step 6 stops when the slice added no commits (`git diff --quiet <base> HEAD`), because ship's zero-commit post-merge Gate 1 rollback (`reset --hard HEAD~1`, `ship_current_work_to_release.py:130-134`) would drop an unrelated release commit; step 7 forbids a blind ship retry.
  - **Unaudited slice plan (medium).** Step 4 pre-supplies the plan path and requires an independent `self-grill-audit` of the slice plan before execution (accepted cost).
  - **Review (medium).** Step 5 says why it stays: per-task reviews inside `subagent-driven-development` are per-phase; step 5 is the independent whole-slice review.
  - **Preflight (medium).** `psrw epic plan` is re-run before every slice.
  - **Low.** Step 0.6 wording and command fixed (`Fast-forward` does not survive `| tail -3`); Task 0 gains an undo note and a `git status` check before `add -A`; Step 0.7 states that it proves little (the cached id is always in `self_ids`, `guard_check.py:124`); the skill body is exactly at the 40-line budget and the lint test pins the new rules.
  - Replayed: the Task 3 skill text and lint in a scratch copy of the release engine: `6 passed`; `test_docs_single_source.py`: `49 passed, 2 skipped`, `-k epic-run`: `3 passed`.
