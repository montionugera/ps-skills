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

Drive an epic's approved slices to `shipped` on the release branch, one at a time. The ONE
sanctioned exception to "never auto-chain", only for slices the human named in `--slices`. Approval is never inferred.

## Hard rules

- **NEVER run `psrw promote`, `psrw ship --deploy`, or merge anything to main.**
- Stop at the FIRST failed gate: report it and change nothing more. Never continue past a failed slice.
- One chain per epic. State lives only in the catalogs; re-running resumes.

## Preflight

    psrw epic plan E-NNN --slices I-001,I-002 [--allow-no-precheck]

Run it again before EVERY slice, not once. `ERROR:` (on stderr) -> STOP. Otherwise it lists each
slice in order with `state`, `claimed_by`, `action`. Touch only slices in its `allowlist`.

## Per slice, in order (any failure -> STOP and report)

1. `skip` -> next slice. `refine` -> `psrw refine I-NNN` (never `--allow-empty-spec`), then `psrw claim F-NNN`. `claim`
   (state `refined`) -> `psrw claim F-NNN`. Default owner, never `--owner`.
2. `resume` -> STOP if `claimed_by` differs from this machine's owner id
   (`$CLAUDE_SESSION_ID`, else `~/.cache/ps-release-workflow/session-id`); that only catches another
   machine or an explicit owner, never another local session. Before `psrw claim F-NNN --resume`
   REQUIRE a clean tree AND `git log release/<v>..HEAD` inspected: commits there mean the
   implementer re-runs against them, never a takeover.
3. In the worktree run `psrw epic sync`. Conflict -> STOP. Keep its `base` sha.
4. Implement: dispatch a subagent that starts with `psrw claim F-NNN --resume`, then runs
   /writing-plans (plan path `.claude/refined_backlog/F-NNN-<slug>/plan.md`), an independent
   /self-grill-audit of that plan (accepted cost), then /subagent-driven-development (if nested
   dispatch is unavailable, implement flat in the same subagent). Brief it: never ship, push, open a
   PR, promote, merge to main, or leave this worktree; never edit `_catalog.json`. On a resumed
   slice, tell it which plan tasks are already ticked.
5. Independent whole-slice review of `git diff <base> HEAD` (code-reviewer plus the language
   reviewer); step 4's per-task reviews are per-phase and do not replace it. Fix (the fixer first
   runs `psrw claim F-NNN --resume`); re-review. Still failing after 2 rounds -> STOP.
6. Verify: full test suite passes, tree clean and committed, else STOP. If
   `git diff --quiet <base> HEAD` (the slice added no commits) -> STOP.
7. Ship: `psrw ship --no-deploy` in the worktree. Non-zero -> STOP: report and end the run; a
   later `epic run` resumes. Never blind-retry ship in-run, not even after a fix.

## After the last slice

Parse ONLY the stdout line starting `{"ok"` from the last ship. `epic_outcome` null ->
"epic incomplete" (a slice outside the allowlist is unshipped, or another check holds
it). `rc` 0 -> verified. `rc` null -> "unverified, check skipped", never success.
Any other `rc` -> failed check. Report each slice as shipped or stopped-at-gate.

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#gates`. Flags: `psrw epic --help`
