---
name: ps-release-workflow-epic-run
description: |
  Use when the user asks to run an epic — "epic run E-NNN", "chain the approved
  slices", "drive this epic to shipped" — in a ps-release-workflow repo. Takes an
  explicit --slices allowlist of approved slice ideas through refine, claim,
  implement, review and ship --no-deploy, one at a time, stops at the first
  failed gate, and never promotes. Inside AGY, leverages native subagents (invoke_subagent,
  Model: "flash" R1-R2, Model: "inherit" Argon R3 escalation & review, enable_subagent_tools: true).
argument-hint: "E-NNN --slices I-001,I-002 [--allow-no-precheck]"
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
   /self-grill-audit of that plan (accepted cost), then /subagent-driven-development.
   - **In AGY (80/20 Progressive Escalation & Nested Dispatch)**:
     - Plan authoring & `self-grill-audit`: runs on Frontier Tier (`gemini-4-argon`, `Model: "inherit"`).
     - Nested subagent dispatch: enable via `enable_subagent_tools: true` on custom subagents (`define_subagent`), or dispatch `invoke_subagent` directly from the slice orchestrator.
     - Task Implementer: runs with `Workspace: "share"` (for disjoint files) or `Workspace: "branch"`. Use `Model: "flash"` (`gemini-3.8-flash-high`) for Round 1 & Round 2 implementation.
     - Warm Fix Loop: on Round 2, send reviewer feedback via `send_message(Recipient: "<convId>")` to the existing idle implementer.
     - Escalation: if verification or review fails on Round 2, terminate the Flash subagent (`manage_subagents(Action: "kill")`) and escalate Round 3 to Frontier Tier (`Model: "inherit"` / `gemini-4-argon`).
   - Brief the subagent: never ship, push, open a PR, promote, merge to main, or leave this worktree; never edit `_catalog.json`. On a resumed slice, tell it which plan tasks are already ticked.
5. Independent whole-slice review of `git diff <base> HEAD`:
   - Always runs on Frontier Tier (`Model: "inherit"` / `gemini-4-argon` in AGY via `code-reviewer` and language reviewer; `model: opus` in Claude Code); step 4's per-task reviews are per-phase and do not replace it.
   - Fix: the fixer first runs `psrw claim F-NNN --resume` (resuming warm via `send_message` in AGY or fresh subagent); re-review. Still failing after 2 rounds -> STOP.
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
