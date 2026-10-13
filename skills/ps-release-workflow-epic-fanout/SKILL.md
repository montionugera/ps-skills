---
name: ps-release-workflow-epic-fanout
description: |
  Use AFTER an epic (E-NNN) has a solid spec, to split it into slices in a
  ps-release-workflow repo. Mints one IDEA per slice, tagged to the epic, and
  commits them on the release branch via the _release worktree. Never mints a
  feature. Supports AGY parallel subagent research (Model: "flash") and downstream
  subagent dispatch (Workspace: "branch"|"share", enable_subagent_tools: true).
argument-hint: "<epic-id> <slice-title-1> <slice-title-2> ..."
---

# ps-release-workflow:epic-fanout

Split an epic into slices: one idea `I-NNN` per slice, each tagged with the epic id.

## Precondition

The epic exists (`psrw epic open`) and its `spec.md` names the slices.

## Run

    psrw epic fanout E-001 "Slice one" "Slice two" "Slice three"

## Then

Fanout mints **ideas, never features**. Each slice still needs its own brainstorm
and approved spec before `psrw refine I-NNN`. Do NOT chain fanout -> refine -> claim,
except through the `epic-run` skill, for slices a human listed in its `--slices` allowlist.
Once every slice has shipped, the repo's `hooks.epic_check` script runs against the
combined tree (`psrw epic verify E-NNN` to re-run it by hand). `E-NNN/verification.md`
is the human-written statement of what must be true; no code reads it.

### Parallel Slice Preparation in AGY (80/20 Flash-First)

When orchestrating inside Google Antigravity (`agy`):
1. **Parallel Context Gathering (`Model: "flash"`)**:
   After minting slice ideas, fan out parallel `research` subagents in a single `invoke_subagent` call to inspect relevant codebase paths and `graft` context per slice:
   ```json
   invoke_subagent(
     Subagents: [
       { "TypeName": "research", "Role": "Slice 1 Researcher", "Model": "flash", "Workspace": "inherit", "Prompt": "Explore codebase for Slice 1 (I-001)..." },
       { "TypeName": "research", "Role": "Slice 2 Researcher", "Model": "flash", "Workspace": "inherit", "Prompt": "Explore codebase for Slice 2 (I-002)..." }
     ]
   )
   ```
2. **Spec Synthesis & Review Gate (`Model: "inherit"` / Argon)**:
   Keep spec synthesis and decision grilling on the frontier `gemini-4-argon` thread. Run `self-grill-audit` using a dedicated Frontier subagent (`Model: "inherit"`).
3. **Downstream Execution Dispatch (`enable_subagent_tools: true`)**:
   When approved slices proceed to execution via `epic-run`:
   - Subagents run with `Workspace: "branch"` or `Workspace: "share"`.
   - Implementers run on `Model: "flash"` for Rounds 1–2, escalating to `Model: "inherit"` (Gemini 4 Argon) on Round 3.
   - Subagents can define and invoke their own child workers when configured with `enable_subagent_tools: true`.
   - Adversarial slice reviews use `Model: "inherit"` (Gemini 4 Argon).

## Refuses if

- no release is in progress
- the epic id does not exist
- no slice titles are given

Mechanics: `~/.claude/ps-release-workflow/docs/lifecycle.md#state-layout`
Flags: `psrw epic --help`
