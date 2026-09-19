# Design: `epic run` — a spec-gated, sequential slice auto-chain

**Status:** revised after audit, awaiting approval · **Date:** 2026-09-19 · **Builds on:** the psrw EPIC layer (F-001, shipped to `release/1.1`)

**Goal (verbatim):** Design `epic run E-NNN`, a sequential, spec-gated auto-chain that drives an epic's approved slices through refine, claim, implement, review and ship, stops at the first failed gate, and never promotes.

## Decisions (batch-grill, 2026-09-19)

- Form → **skill + psrw verbs** — psrw has no LLM dispatch anywhere; the agent-driven part belongs in a skill, like `full-promote`.
- Spec approval → **explicit `--slices` allowlist** — approval today is only a human convention; no schema change. Plus a code-enforced floor: `plan` refuses a slice whose idea spec is still an untouched skeleton.
- Slice visibility → **merge `release/<v>` into each new slice branch** — feature branches are cut from `main`, so slice N would otherwise be blind to slices 1..N-1.
- No precheck script → **refuse to start** unless `--allow-no-precheck` — ship treats a missing script as a pass, which an unattended chain must not.
- Order → sequential · Review → independent review per slice · Failure → stop at first failed gate · Ship → always `--no-deploy` · Re-runs → skip shipped slices, resume claimed ones · Promote → never. (All defaults, not asked.)

## 1. Components

| Unit | What it does | Depends on |
|---|---|---|
| `skills/ps-release-workflow-epic-run/SKILL.md` | The agent-driven loop over slices (prose, ≤ 40 non-blank lines, anchor `#gates`). | psrw verbs below, subagents |
| `psrw epic plan E-NNN --slices I-a,I-b [--allow-no-precheck]` | Deterministic preflight. Prints JSON: the allowlist echoed back, ordered slices with state and action, or a refusal reason. Read-only. | `lib/epic.py`, `lib/catalog.py`, `lib/hooks.py` |
| `psrw epic sync` | Run inside a claimed feature worktree. Under `file_lock(rel_wt)`: read `release/<v>` HEAD and merge it into the feature branch. Prints the post-merge sha. On conflict: `git merge --abort`, exit 1, feature stays claimed. | `lib/git_ops.py`, `lib/state.py:file_lock` |
| Existing verbs | `refine`, `claim`, `ship --no-deploy`, `claim --resume`. Unchanged. | — |

`plan` and `sync` are new subcommands of `scripts/epic.py` (already a registered verb), so no new verb registration and `tests/test_psrw_cli.py`'s verb list is unchanged.

## 2. `epic plan` — the preflight

Refuses (exit 1, `ERROR:` line) when any of these hold:

- no release is in progress, or `E-NNN` does not exist
- the epic is `verified` or `promoted`. An epic in `failed_verification` is not refused; `plan` names the state and points at `psrw epic verify`. (The plan must first confirm how the code represents this state.)
- a slice in `--slices` is not a child of the epic (`epic_children`) or is already promoted
- a slice's idea `spec.md` is an untouched fanout skeleton (reusing `_is_untouched_skeleton` from `promote_idea_to_refined.py`)
- `hooks.precheck` does not resolve to an existing script, resolved from the `_release` worktree (the same tree ship's post-merge Gate 1 uses), unless `--allow-no-precheck`
- `--slices` is missing or empty (approval is never inferred)

Otherwise it prints, per slice in fanout order: `{idea, feature | null, state: idea|refined|claimed|shipped, claimed_by, action: refine|claim|resume|skip}`. It writes nothing.

## 3. The per-slice loop (the skill)

```
plan ─► for each slice in order (re-run `epic plan` before EVERY slice):
  shipped?          ─► skip
  idea?             ─► psrw refine I-NNN                 (→ F-NNN)
  refined?          ─► psrw claim F-NNN                  (default owner, so the guard admits this session)
  claimed?          ─► STOP if claimed_by differs from this machine's id (catches only
                       other machines / explicit owners); REQUIRE clean tree AND
                       `git log release/<v>..HEAD` inspected, then claim --resume;
                       commits beyond the sync point → implementer re-runs against them
  in the worktree:  ─► psrw epic sync                    (conflict → STOP; note the printed sha)
  implement         ─► subagent: writing-plans (plan path pre-supplied), independent
                       self-grill-audit of the slice plan, then subagent-driven-development
  review            ─► code-reviewer + language reviewer on <base>..HEAD only (the independent
                       whole-slice review; sdd's per-task reviews are per-phase); fix; re-review
                       (max 2 rounds → else STOP)
  verify            ─► full test suite in the worktree; tree clean and committed;
                       STOP if the slice added no commits (git diff --quiet <base> HEAD)
  ship              ─► psrw ship --no-deploy             (non-zero → STOP; never blind-retry)
after the last slice: report the epic outcome from ship's `{"ok"` JSON line.
```

**Reading `epic_outcome`:** the JSON line is mixed with Gate 1 output, so parse only the line starting `{"ok"`. `epic_outcome` is null unless every child of the epic (not just the allowlist) has shipped on this release: report null as "epic incomplete". `rc` 0 is verified; `rc` None (no `epic-check` script) is reported as "unverified, check skipped", never as success; any other value is a failed check.

State lives only in the catalogs. There is no run-state file, so re-running the same command after a stop resumes at the first unshipped slice.

## 4. Stop conditions and error handling

- **Stop, report, leave state as is:** `epic sync` conflict; review still failing after 2 rounds; test failure; `ship` non-zero; a claimed slice whose owner differs from this machine's id (see section 5 for what that check can and cannot catch); a resumed slice with a dirty tree; a slice that added no commits.
- **Ship rolls back in the normal case:** a red Gate 1 (before or after the merge) or a merge conflict leaves `release/<v>` untouched and the feature claimed. Even so, the chain never blind-retries ship: it reads the error and fixes the cause first. The exception is the zero-commit case below, which the chain guards against before shipping.
- **The one non-rollback case:** when the last slice completes the epic and the epic check fails, the merge stands and ship exits 0.
- **Locking:** `sync` takes `file_lock(rel_wt)` only for its own read-and-merge, so a concurrent ship that is later rolled back cannot be merged in half-way. The chain never holds the lock across other steps, and never across a hook.
- **Never run:** `psrw promote`, `--deploy`, any merge to main.
- **Known limitation:** ship's own post-merge rollback (`git reset --hard HEAD~1`) is unsafe when the slice added no commits after `sync` and Gate 1 then fails (it would drop an unrelated release commit). That defect exists today and the chain makes it more likely. It is recorded in `known-issues.md`, not fixed here; the chain mitigates it by STOPPING before ship when `git diff --quiet <base> HEAD` shows the slice added no commits.

## 5. Session and guard handling

The edit guard admits a caller only if the worktree marker's owner is one of the session's known ids (payload session id, `$CLAUDE_SESSION_ID`, `$CLAUDE_CODE_SESSION_ID`, the machine-cached id — `lib/owner.py:self_ids`). An invented owner matches none of them, so the chain claims with the **default owner**, and each implementer subagent still starts with `psrw claim F-NNN --resume` so the marker is re-owned to whatever identity it presents. The guard only covers Edit/Write tools, so git and Bash steps are unaffected. Because `claim --resume` cannot tell a stopped chain from a live one, `plan` reports `claimed_by` and the skill compares it to this machine's owner id. **That check is weak:** the default owner is `resolve_owner_id()`, the machine-cached id (`lib/owner.py:34-40`), shared by EVERY session on the machine, so it distinguishes only another machine or an explicit `--owner`; a stale or concurrent local session is indistinguishable from the chain itself. The skill therefore additionally REQUIRES, before any `--resume`, a clean tree AND an inspected `git log release/<v>..HEAD`: commits beyond the sync point mean the implementer re-runs against them, never a blind takeover. There is no run lock, so two chains on one epic are unsupported.

## 6. Testing

- **Unit (pytest, existing fixtures):** `epic plan` — each refusal case (including skeleton spec and missing precheck), ordered-state output, `claimed_by`, read-only (no catalog change); `epic sync` — clean merge prints the sha, conflict aborts and leaves the tree clean, refuses outside a feature worktree, takes the lock.
- **Skill lint:** `verify.sh` is gitignored and machine-local, absent from the release worktree, and already stale (it hard-codes 13 skills and 10 verbs; the repo has 15 skills and 11 verbs). The real lint is `tests/test_docs_single_source.py`, which reads `~/.claude/skills` and skips in CI. A new skill is therefore unlinted until installed: run `install.sh`, then the lint, as an explicit plan step, and count the epic skills.
- **Integration dry run:** the loop itself is prose driven by an agent and cannot be unit-tested. Validate it once end to end on a scaffolded two-slice epic in a temp repo, including one forced stop and a re-run.

## 7. Enforcement, honestly (rule 11)

Code enforces: the allowlist's shape, skeleton-spec refusal, precheck presence, epic state, and the `sync` lock. **Prose only:** stop-at-first-failure, sequential order, review-before-ship and never-promote live in the skill, which binds only an agent that reads it. Ship itself prints "promote: psrw promote" and nothing in psrw stops a caller running it. **Preflight caveat:** `plan` re-runs before every slice, but its skeleton check catches only an UNTOUCHED spec: a one-character edit defeats it, so the `--slices` allowlist (the human's explicit choice) remains the real approval, not the skeleton check. Mitigations: the skill carries an explicit "never run `psrw promote`, `--deploy` or merge to main" line, and `plan` echoes the allowlist so each step can re-check it.

## 8. Out of scope

Parallel slices · cross-repo epics · a slice dependency graph · promote/deploy · an `approved` marker in spec frontmatter · any LLM dispatch inside psrw · fixing the ship rollback defect.

## 9. Risks and unknowns

- **Nested subagent dispatch (unverified):** the skill has an implementer SUBAGENT run `subagent-driven-development`, which dispatches further subagents (subagent-of-subagent). Whether Claude Code allows that is not established. Task 0 Step 0.8 probes it. **Fallback if refused:** do not build the skill as written; revise it so the main session dispatches the implementer and each reviewer directly (one flat layer, no subagent-of-subagent), then re-audit.
- **Owner check is weak:** see section 5; only another machine or an explicit owner is detectable. Live-session takeover is guarded by the clean-tree and `git log` requirement, not by the owner comparison.
- **Slice plan runs with an extra audit:** each slice's own plan is independently audited (`self-grill-audit`) before execution, which is an accepted per-slice cost.
- **Subagent session id:** whether a Claude Code subagent's hook payload carries the parent's session id is not established. The default-owner plus `claim --resume` handoff is designed to work either way; the dry run must confirm it.
- **Spec visibility:** feature worktrees are cut from `main`, but specs and plans live under `.claude/refined_backlog/` on the release branch. `epic sync` should make them visible, but this is not verified; task 1 of the plan must check it before anything else is built.
- **Deliberate rule change, five skills not three:** `ps-release-workflow-idea` (line 8), `-refine` (7, 14-19), `-claim` (19-20), `-epic-open` (30) and `-epic-fanout` (26) all say never to auto-chain. Their frontmatter descriptions are also the auto-trigger surface. Each must name `epic run` as the sanctioned exception. `docs/lifecycle.md` has no such text, so it needs an addition, not an edit.
- **Stale docs found, filed separately:** `skills/ps-release-workflow-refine/SKILL.md:21-23` says refine writes fresh skeletons but the code carries the idea's content forward; the `psrw epic --help` summary omits `plan` and `sync`.
- **Slower ships:** Gate 1 runs twice on the combined tree, so each slice's ship takes longer.

## Appendix — audit trail

- 2026-09-19 self-grill-audit: verdict **safe-with-fixes**, no critical findings. Corrected: `sync` now holds `file_lock(rel_wt)` and prints the post-merge sha; `--owner <chain-owner>` dropped (the guard would reject an invented owner); `plan` refuses skeleton-only specs, resolves precheck from `_release`, and reports `claimed_by`; review scope is `<sync-sha>..HEAD`; resume rules tightened (dirty tree stops); `epic_outcome` parsing specified; the verify.sh claim rewritten; the "never auto-chain" list corrected to five skills; enforcement section added. Open: none that need a decision. Unverified by the auditor (static review only): how `failed_verification` is represented in code.
- 2026-09-19 self-grill-audit (second pass): verdict **safe-with-fixes**. Corrected: nested-dispatch probe with a fallback (section 9); the owner check reworded as weak, with a clean-tree and `git log` requirement before resume (sections 3-5); zero-commit ship guard and no blind ship retry (sections 3-4); slice-plan audit; `epic plan` re-run before every slice and the skeleton-check limit stated (section 7).
