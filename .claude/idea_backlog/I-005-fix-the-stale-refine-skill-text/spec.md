---
title: "Fix the stale refine skill text"
id: I-005
status: idea
---

# Fix the stale refine skill text

Epic: E-001 "Test and doc hygiene deferred from the epic-run review". Chain position: 3 of 3. Independent of slices 1-2 in code.
Human-approved as drafted.

## Problem

`skills/ps-release-workflow-refine/SKILL.md` (release/1.1 head `750f52d`) describes refine behaviour the code no longer has.
Verified against `engine/ps-release-workflow/scripts/promote_idea_to_refined.py`.

Stale text 1, the description at lines 4-6: `Mints F-NNN, moves the folder, and commits on the release branch ...`
Reality: `_carry_forward` (line 189, `shutil.copytree(idea_folder, folder, dirs_exist_ok=True)` at line 198) COPIES the idea
folder to `refined_backlog/F-NNN-<slug>/`; the idea folder stays in `idea_backlog/` (the idea catalog entry is only stamped
`promoted_to`, `mark_promoted`, line 275).

Stale text 2, the blockquote at lines 24-26:

    > ⚠️ Refine writes **fresh skeleton** `spec.md`/`plan.md`/`research.md` into the new
    > `F-NNN` folder — it does **not** copy the idea folder's contents. Keep the canonical
    > spec under `docs/superpowers/specs/`, where it travels with the feature branch.

Reality (module docstring lines 6-8 and `_carry_forward`): idea-stage content IS carried forward; only untouched skeletons
are replaced. Specifically: a filled `spec.md` is kept with its `title`/`id`/`from_idea`/`status` frontmatter rewritten to the
F-NNN identity (`_rewrite_spec_identity`); an untouched idea `spec.md` becomes the F-NNN spec skeleton; an untouched
`plan.md` becomes the F-NNN plan skeleton; an untouched `research.md` is DELETED (refine no longer seeds one, so "fresh
skeleton research.md" is wrong too).

Already known and deliberately deferred: `engine/ps-release-workflow/docs/known-issues.md:27` (this slice removes that bullet).
Note the survey and the F-002 spec cite different line numbers (21-23 in F-002; 24-26 at head). 24-26 is right at head.

What is NOT stale (leave alone): the "Refuses if" list (not opted in / no release in progress / idea not found / already
promoted matches the code: `RuntimeError`, `NoReleaseInProgressError`, `IdeaNotFoundError`, `AlreadyPromotedError`);
"commits on the release branch via the _release worktree" (correct: `commit_all(wt, ...)`).

## Scope (files this slice may touch, nothing else)

1. EDIT `skills/ps-release-workflow-refine/SKILL.md`:
   - description: `Mints F-NNN, moves the folder, and commits on the release branch` becomes
     `Mints F-NNN, copies the idea folder into refined_backlog/, and commits on the release branch` (same YAML block scalar).
   - replace the lines 24-26 blockquote with:

         > ℹ️ Refine **carries the idea's content forward**: it copies the idea folder into the new
         > `F-NNN` folder (the idea folder stays where it is) and replaces only *untouched* skeletons.
         > A filled-in `spec.md` arrives with its `title`/`id`/`from_idea`/`status` frontmatter
         > restated for the `F-NNN`; an untouched `plan.md` gets the `F-NNN` plan skeleton; an
         > untouched `research.md` is dropped (refine seeds none). Keep the canonical spec under
         > `docs/superpowers/specs/`, where it travels with the feature branch.

     The last sentence is kept verbatim on purpose (see Out of scope).
2. EDIT `engine/ps-release-workflow/tests/test_epic_run_skill.py`: append one test (uses the existing `_skill("refine")`):
   `test_refine_skill_describes_carry_forward_not_fresh_skeletons` asserting `"moves the folder"` is absent from the
   frontmatter, `"fresh skeleton"` and `"does **not** copy"` are absent from the body, and `"carries the idea's content
   forward"` is present in the body (~7 lines).
3. EDIT `engine/ps-release-workflow/docs/known-issues.md`: delete the one bullet at line 27 (the stale-skill bullet). Do not
   touch any other line (slice 2 edits a different bullet, line 36).

Prototype (drafter, scratch COPY only): with the above, `tests/test_epic_run_skill.py` runs `18 passed` (17 + 1).
Diff is ~12 lines of skill text + ~7 test lines + 1 deleted doc bullet.

## Out of scope

- The precondition prose that says the approved spec lives under `docs/superpowers/specs/` (also in the idea and claim skills;
  `epic plan` actually gates on the backlog `spec.md`). That is a policy question for the human, not a stale-text fix here.
- Any other skill, `install.sh`, the installed copy under `~/.claude/skills` (do not run install), `lifecycle.md`, engine code.
- The `psrw epic --help` summary that omits `plan`/`sync` (a code-side text; filed separately).

## Acceptance criteria (from `engine/ps-release-workflow` in the slice worktree)

1. `grep -n "moves the folder\|fresh skeleton\|does \*\*not\*\* copy" ../../skills/ps-release-workflow-refine/SKILL.md` prints nothing.
2. `grep -c "carries the idea's content forward" ../../skills/ps-release-workflow-refine/SKILL.md` prints `1`.
3. `python3 -m pytest tests/test_epic_run_skill.py -q` reports `18 passed`.
4. `python3 -m pytest tests -q` reports `468 passed, 2 skipped` (467 after slice 2, plus 1).
5. The SKILL frontmatter still parses: `python3 -m pytest tests/test_epic_run_skill.py -q -k "ban_names_epic_run"` includes the
   `refine` case and passes (that lint requires `epic-run` still named in the refine frontmatter and body).
6. `git diff --stat <sync base> HEAD` lists only the three files above.
7. `git status --porcelain` empty after the commit.

## Risks

- Prose lint is brittle: the new test pins exact phrases. That is intentional (a regression catch), cheap to update.
- The SKILL description is the auto-trigger surface; rewording must not drop "Refine ONLY an idea that already has a solid,
  approved spec" or the epic-run exception (test `test_every_auto_chain_ban_names_epic_run_as_the_exception` guards this).
- `known-issues.md` is edited by two slices (S2 line 36, S3 line 27). Sequential chain with `epic sync` between them, different
  bullets, so no conflict expected; if S3's sync shows a conflict there, that is a stop-rule event.

## Definition of done

Criteria 1-7 pass with output pasted into the ledger; independent whole-slice review done; one commit, no amend;
`psrw ship --no-deploy` exit 0 with the `{"ok"` line. This is the LAST slice, so its ship triggers the epic outcome check
(see epic.md, "Epic verification": it will be skipped, not run).
