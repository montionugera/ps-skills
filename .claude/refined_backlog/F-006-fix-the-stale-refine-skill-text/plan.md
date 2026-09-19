# Fix the stale refine skill text — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `skills/ps-release-workflow-refine/SKILL.md` describe what `promote_idea_to_refined.py` actually does (copy-and-carry-forward, not move-and-fresh-skeleton), pin the corrected wording with one new lint test, and remove the now-fixed bullet from `known-issues.md`.

**Architecture:** Pure prose/doc change plus one prose-lint test. No engine code changes. The test lives in `tests/test_epic_run_skill.py`, which reads skills straight from the repo checkout via the existing `_skill()` helper (`tests/test_docs_single_source.py` reads `~/.claude/skills` instead and is deliberately untouched — the installed copy is NOT refreshed by this slice, and `install.sh` must not be run).

**Tech Stack:** Markdown + YAML frontmatter; pytest (`python3 -m pytest`); plain `git`.

**Spec:** `.claude/refined_backlog/F-006-fix-the-stale-refine-skill-text/spec.md` (F-006, from idea I-005, epic E-001, slice 3 of 3 — the LAST slice).

## Global Constraints

- Worktree, never leave it: `/Users/pasitnusso/ps-skills/.claude/worktrees/F-006-fix-the-stale-refine-skill-text`. Branch `feat/F-006`. Slice base commit `cd7fcb353b32be2a2ec67a98405b368f7b04672b`.
- **Exactly three files may be touched** (plus this `plan.md`):
  1. `skills/ps-release-workflow-refine/SKILL.md` — repo root `skills/`, NOT `~/.claude/skills`.
  2. `engine/ps-release-workflow/tests/test_epic_run_skill.py` — APPEND one test only.
  3. `engine/ps-release-workflow/docs/known-issues.md` — DELETE exactly one bullet (line 27).
- **Do NOT touch** `engine/ps-release-workflow/scripts/`, `lib/`, any other skill, `install.sh`, `lifecycle.md`, `_catalog.json` (hand-editing forbidden outright), or anything under `~/.claude/skills`.
- **`known-issues.md` is shared with the previous slice.** Its bullet about `tests/test_epic_plan_refusals.py` is now at **line 36** and must NOT be touched, reworded or removed. Delete **only** the stale-refine-skill bullet at **line 27**.
- **Never run** `psrw ship`, `psrw promote`, `--deploy`, `git push`, PR creation, merge to main, `git commit --amend`, `install.sh`, or `rm -rf`. (The spec's Definition of Done mentions `psrw ship --no-deploy`; that step is explicitly out of scope for this execution and is left to the caller.)
- **No scratch files inside the worktree.** `.superpowers/` is NOT gitignored in this repo — any scratch artifact must go in the session scratchpad, or `git status --porcelain` will not be empty.
- ONE commit on `feat/F-006`, new commit only, message ending with:
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`

**Verified baseline (measured, not assumed):** `tests/test_epic_run_skill.py` = **17 passed**. `"moves the folder"` occurs in exactly **two live places** — `skills/ps-release-workflow-refine/SKILL.md:5` and the `known-issues.md:27` bullet being deleted. (It also appears in backlog prose — `.claude/idea_backlog/I-005-*/spec.md`, `.claude/refined_backlog/F-002-*/plan.md`, and this slice's own spec/plan — which quote the stale wording deliberately and are **not** to be touched. No acceptance grep is repo-wide, so those quotations are harmless.) No skill catalog mirrors the description (the three `_catalog.json` files are backlog catalogs, unrelated).

**Known divergence (blast radius, stated deliberately):** the *installed* copy at `~/.claude/skills/ps-release-workflow-refine/SKILL.md:5` still reads `moves the folder` and **stays stale after this slice** — `install.sh` is out of scope and must not be run. That installed copy is the surface that actually auto-triggers sessions, and no test detects repo-vs-installed divergence. Deleting the `known-issues.md` bullet therefore marks the *repo* text fixed while the installed text lags until the next install. The commit body says so.

---

### Task 1: Pin the corrected refine wording with a failing lint test

**Files:**
- Test: `engine/ps-release-workflow/tests/test_epic_run_skill.py` (APPEND at end of file; currently 121 lines)

**Interfaces:**
- Consumes: the existing module-level helper `_skill(name: str) -> tuple[str, str, str]` returning `(full text, frontmatter, body)` for `skills/ps-release-workflow-<name>/SKILL.md`. It splits on `"---"` with `maxsplit=2`, so `frontmatter` is the YAML block and `body` is everything after the closing `---`.
- Produces: nothing other tasks import. Tasks 2 and 3 are validated by this test.

- [ ] **Step 1: Write the failing test**

Append exactly this to the end of `engine/ps-release-workflow/tests/test_epic_run_skill.py`, preceded by two blank lines per the file's existing style:

```python
def test_refine_skill_describes_carry_forward_not_fresh_skeletons():
    """`_carry_forward` COPIES the idea folder and replaces only untouched skeletons;
    the skill used to claim it moved the folder and wrote fresh skeletons."""
    _, frontmatter, body = _skill("refine")
    assert "moves the folder" not in frontmatter, "description still says refine moves the idea folder"
    assert "fresh skeleton" not in body, "body still claims refine writes fresh skeletons"
    assert "does **not** copy" not in body, "body still denies the copy"
    assert "carries the idea's content forward" in body, "body never states the carry-forward"
```

- [ ] **Step 2: Run the test to verify it FAILS (red)**

Run, from `engine/ps-release-workflow`:

```bash
python3 -m pytest tests/test_epic_run_skill.py -q -k "carry_forward"
```

Expected: **1 failed** — the first assertion trips (`description still says refine moves the idea folder`), because `SKILL.md:5` still reads `Mints F-NNN, moves the folder, and commits`. A PASS here means the file was already edited; stop and investigate rather than proceeding.

---

### Task 2: Correct the refine SKILL.md description and blockquote (green)

**Files:**
- Modify: `skills/ps-release-workflow-refine/SKILL.md` — frontmatter description (lines 4–8) and the blockquote (lines 24–26)

**Interfaces:**
- Consumes: nothing.
- Produces: the exact strings Task 1's test asserts on, and the strings the spec's acceptance greps assert on.

- [ ] **Step 1: Fix the description (frontmatter)**

The `description:` is a YAML block scalar (`description: |`); keep it a block scalar and keep every other sentence byte-identical. Replace these three lines:

```yaml
  in a ps-release-workflow repo. Mints F-NNN, moves the folder, and commits
  on the release branch via the _release worktree. Refine ONLY an idea that
  already has a solid, approved spec — never auto-chain idea -> refine -> claim.
```

with these four:

```yaml
  in a ps-release-workflow repo. Mints F-NNN, copies the idea folder into
  refined_backlog/, and commits on the release branch via the _release
  worktree. Refine ONLY an idea that already has a solid, approved spec —
  never auto-chain idea -> refine -> claim.
```

This is a pure re-wrap: the only wording change is `moves the folder` → `copies the idea folder into refined_backlog/`. The opening line `Use BEFORE promoting a captured idea (I-NNN) into the refined backlog` and the closing line `Sole exception: the epic-run skill, for slices a human allowlisted.` are untouched.

**Why the surrounding sentences must survive verbatim:** `test_every_auto_chain_ban_names_epic_run_as_the_exception` (parametrized over `CHAIN_BANS`, which includes `refine`) asserts `"epic-run"` appears in BOTH the frontmatter and the body. Dropping the `Sole exception:` line would break it.

- [ ] **Step 2: Replace the stale blockquote (body)**

Replace this three-line blockquote:

```markdown
> ⚠️ Refine writes **fresh skeleton** `spec.md`/`plan.md`/`research.md` into the new
> `F-NNN` folder — it does **not** copy the idea folder's contents. Keep the canonical
> spec under `docs/superpowers/specs/`, where it travels with the feature branch.
```

with exactly this six-line blockquote (copied verbatim from the spec's Scope section — do not reflow, reword, or re-wrap it):

```markdown
> ℹ️ Refine **carries the idea's content forward**: it copies the idea folder into the new
> `F-NNN` folder (the idea folder stays where it is) and replaces only *untouched* skeletons.
> A filled-in `spec.md` arrives with its `title`/`id`/`from_idea`/`status` frontmatter
> restated for the `F-NNN`; an untouched `plan.md` gets the `F-NNN` plan skeleton; an
> untouched `research.md` is dropped (refine seeds none). Keep the canonical spec under
> `docs/superpowers/specs/`, where it travels with the feature branch.
```

The final sentence (`Keep the canonical spec under docs/superpowers/specs/ …`) is kept verbatim **on purpose** — the spec puts re-litigating that precondition prose explicitly **out of scope**.

Nothing else in the file changes: the "Precondition" section, "Run", "Then", and the "Refuses if" list are all correct against the code and stay as-is.

- [ ] **Step 3: Run the new test to verify it PASSES (green)**

```bash
python3 -m pytest tests/test_epic_run_skill.py -q -k "carry_forward"
```

Expected: **1 passed**.

- [ ] **Step 4: Run the whole skill-lint file**

```bash
python3 -m pytest tests/test_epic_run_skill.py -q
```

Expected: **18 passed** (17 baseline + 1).

- [ ] **Step 5: Confirm the frontmatter still parses and the ban lint still covers refine**

```bash
python3 -m pytest tests/test_epic_run_skill.py -q -k "ban_names_epic_run"
```

Expected: all parametrized cases pass, including `[refine]`. This is acceptance criterion 5.

---

### Task 3: Delete the now-fixed bullet from known-issues.md

**Files:**
- Modify: `engine/ps-release-workflow/docs/known-issues.md` — delete line 27 only

**Interfaces:** Consumes nothing; produces nothing.

- [ ] **Step 1: Confirm line 27 is the right bullet BEFORE deleting**

```bash
sed -n '27p' engine/ps-release-workflow/docs/known-issues.md
```

Expected: it begins ``- **`skills/ps-release-workflow-refine/SKILL.md` lines 24-26 are stale.**`` If it does not, STOP — do not delete a different line.

- [ ] **Step 2: Confirm line 36 is the previous slice's bullet and will be left alone**

```bash
sed -n '36p' engine/ps-release-workflow/docs/known-issues.md
```

Expected: the bullet mentioning `tests/test_epic_plan_refusals.py`. **This line must survive the edit untouched.** Re-run this exact command after the deletion; the same text must then appear at line **35** (one line earlier), byte-identical.

- [ ] **Step 3: Delete exactly that one line**

Remove the single line 27 (the whole bullet is one physical line). Leave the surrounding structure intact: line 26 is the `ship`'s-post-merge-rollback bullet and line 28 is a blank line before the `### Deferred from the epic-run final review` heading — after the delete, that blank line and heading must still be there.

- [ ] **Step 4: Verify the delete removed one line and only one line**

```bash
git diff --stat -- engine/ps-release-workflow/docs/known-issues.md
git diff -- engine/ps-release-workflow/docs/known-issues.md
```

Expected: `1 deletion(-)`, `0 insertions`, and the diff shows exactly one `-` line — the stale-refine-skill bullet. No `+` lines at all (a `+` line means something was reworded; revert and redo).

---

### Task 4: Full verification, then one commit

**Files:** none modified; this task only verifies and commits.

- [ ] **Step 1: Run the spec's acceptance greps (criteria 1 and 2)**

From `engine/ps-release-workflow`:

```bash
grep -n "moves the folder\|fresh skeleton\|does \*\*not\*\* copy" ../../skills/ps-release-workflow-refine/SKILL.md
grep -c "carries the idea's content forward" ../../skills/ps-release-workflow-refine/SKILL.md
```

Expected: the first prints **nothing** (exit status 1 — that is success here), the second prints **`1`**.

- [ ] **Step 2: Run the full suite (criterion 4)**

```bash
python3 -m pytest tests -q
```

Expected: **baseline + 1**. The spec's criterion 4 quotes `468 passed, 2 skipped`, but that absolute is **machine-local, not reproducible**: `tests/test_docs_single_source.py:9` parametrizes three tests over `~/.claude/skills`, which holds **13** `ps-release-workflow-*` skills on this machine versus **16** in the repo, and CI (which has no `~/.claude/skills`) collapses further. So the binding check is **baseline + exactly 1** — the pre-change full-suite run recorded in the session scratchpad is the baseline, and the absolute local number is reported as evidence, not as a pass/fail threshold. A delta other than +1 is a real failure; a different absolute is not. This takes 8–9 minutes — use a Bash timeout of `600000` ms. Do not shorten it by selecting a subset.

- [ ] **Step 3: Commit (one commit, new commit, never `--amend`)**

```bash
git add skills/ps-release-workflow-refine/SKILL.md \
        engine/ps-release-workflow/tests/test_epic_run_skill.py \
        engine/ps-release-workflow/docs/known-issues.md \
        .claude/refined_backlog/F-006-fix-the-stale-refine-skill-text/plan.md
git commit -F - <<'MSG'
docs(refine): describe carry-forward instead of fresh skeletons (F-006)

`promote_idea_to_refined.py::_carry_forward` copies the idea folder into
refined_backlog/F-NNN and replaces only untouched skeletons; the idea folder
stays in idea_backlog/. The skill said the opposite: that refine "moves the
folder" and writes fresh skeleton spec/plan/research that do not copy the
idea's contents.

- SKILL.md: description now says "copies the idea folder into refined_backlog/";
  the blockquote now states the carry-forward rules (filled spec.md kept with
  its identity frontmatter restated, untouched plan.md skeletonised, untouched
  research.md dropped).
- tests/test_epic_run_skill.py: one new prose lint pinning the corrected phrases.
- docs/known-issues.md: drop the bullet that deferred this fix.

The installed copy under ~/.claude/skills still carries the old wording; it
picks this up at the next install, which is out of scope for this slice.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
MSG
```

- [ ] **Step 4: Verify the commit is clean and scoped (criteria 6 and 7)**

```bash
git diff --stat cd7fcb35 HEAD
git status --porcelain
git log --format=%H -1
```

Expected: `git diff --stat` lists **exactly four** paths — the three in-scope files plus `plan.md` — and nothing else. `git status --porcelain` prints **nothing**. If any untracked scratch file appears, it must be moved to the session scratchpad (never `rm -rf`) before this criterion passes.

- [ ] **Step 5: Phase gate** (rule 7)

The whole slice is a < 30-line diff in one subsystem, so Tasks 1–4 share **one** gate: verify (Steps 1–2 above, real output) → independent review of the slice diff by a fresh `code-reviewer` **and** `python-reviewer` (`model: sonnet`) → act on blocking findings → re-run `python3 -m pytest tests/test_epic_run_skill.py -q` to confirm still **18 passed**. A review finding that would require touching a file outside the three-file scope is NOT actioned — it is reported as an out-of-scope note.

**STOP after this gate.** `psrw ship`, `psrw promote`, `git push`, and PR creation are out of scope for this execution and are the caller's to run.

---

## Audit trail

- Self-review (writing-plans): spec coverage checked section by section — Scope items 1/2/3 map to Tasks 2/1/3; acceptance criteria 1–7 map to Task 2 Steps 4/5 and Task 4 Steps 1/2/4. No placeholders. No cross-task name drift (only `_skill` is shared, signature copied from the file).
## Appendix — audit trail

- **2026-09-19 self-grill-audit: verdict `safe-with-fixes`** (0 CRITICAL, 0 HIGH, 4 MEDIUM, 1 LOW). Independent auditor re-derived every claim on disk and simulated red/green on a scratch copy.
  - **Corrected (MEDIUM):** the "exactly two places repo-wide" baseline was false — `"moves the folder"` also appears in backlog prose (I-005 spec, F-002 plan, this slice's own spec/plan); restated as "two live places", with those quotations flagged as deliberately untouched.
  - **Corrected (MEDIUM):** acceptance criterion 4's absolute `468 passed, 2 skipped` is machine-local (`test_docs_single_source.py` parametrizes over `~/.claude/skills`: 13 installed here vs 16 in the repo; CI has none). Task 4 Step 2 now binds on **baseline + 1**, with the absolute reported as evidence. The spec was NOT edited.
  - **Corrected (MEDIUM):** blast radius the plan had not stated — the installed copy stays stale after this slice; recorded in Global Constraints and in the commit body.
  - **Declined (MEDIUM), with rationale:** auditor proposed adding `assert "copies the idea folder into" in frontmatter` so the corrected description is positively pinned (today only a negative is asserted, so the description could regress to some *other* wrong wording and still go green). This is a fair rule-11 point, but the spec dictates the new test's four assertions verbatim and the task brief is to implement the spec exactly. Adding a fifth assertion is a re-scope. **Filed as a follow-up, not actioned here.**
  - **Noted (LOW):** auditor flagged the `Co-Authored-By` trailer model name. The executing brief specifies `Claude Sonnet 5` explicitly, so that value stands; the discrepancy is surfaced in the final report rather than silently changed.
  - **Auditor confirmations (refutation attempts that failed):** the replacement blockquote is byte-identical to the spec's dictated text (ASCII apostrophe, `ℹ️` intact); `known-issues.md` :26/:27/:28/:29/:36 line map holds and :36 lands at :35 post-delete; `tests/test_epic_run_skill.py` is 121 lines / 17 passed; all four new assertions fail before and pass after the described edits; `_skill()`'s `split("---", 2)` puts the description in `frontmatter` and the blockquote in `body` with no stray `---` introduced; `test_every_auto_chain_ban_names_epic_run_as_the_exception[refine]` survives; no other repo-checkout test reads refine's text except the namespace-slash lint (unaffected); no ASCII-only/unicode lint exists on skill files.
  - **Open (R0 items):** none. Blast radius R2 — three text files plus `plan.md`, one commit, no engine code or pipeline config; undo is `git revert` of the single commit.

### Follow-ups filed (not in this slice's scope)

- Add a positive assertion pinning the corrected refine description (`"copies the idea folder into"`), so the description cannot regress to a different wrong wording.
- Nothing detects repo-vs-installed skill divergence; `~/.claude/skills` silently lags the repo and `test_docs_single_source.py` lints the installed copy only.
