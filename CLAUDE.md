# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Personal agent skills (`skills/ps-*` and a few others), the Python engine behind the
`ps-release-workflow-*` skills, and helper CLIs in `bin/`. `./install.sh` **symlinks** all of it into
`~/.claude/skills`, `~/.claude/ps-release-workflow`, `~/.agents`, `~/.gemini/config` and `~/.local/bin`,
so an edit in this clone goes live in every agent session straight away. The repo is **public**:
`ps-skills-sync --push` runs a secret scan before it publishes.

## This repo uses its own release workflow

`.release.json` sits at the root, so the PreToolUse guard (`engine/ps-release-workflow/scripts/guard_check.py`)
**blocks Edit/Write anywhere in the main checkout**, whatever branch is checked out. Make changes in one of these:

- a claimed feature worktree, `.claude/worktrees/F-NNN-<slug>/`, created by `psrw claim F-NNN`, or
- a sibling hotfix worktree, `../ps-skills-hotfix-<desc>`, created by `psrw hotfix`.

Backlog metadata (`.claude/{idea,refined,epic}_backlog/`, `_catalog.json`) is committed on `release/<v>`
through the long-lived `.claude/worktrees/_release` worktree, never on `main`. The `.release.json` in that
worktree is the source of truth for release state; the copy on `main` only records the last promoted version.

## Commands

```bash
# Engine: pytest, stdlib-only runtime, Python >= 3.11 (CI uses 3.13)
cd engine/ps-release-workflow && pip install -e ".[dev]"
pytest -q                                   # full suite
pytest -q -m 'not slow'                     # skip the end-to-end lifecycle tests
pytest -q tests/test_slug.py::test_simple   # a single test

# bin/ tools (dispatch-worker, mesh, ps-plugin-bridge, ps-skills-doctor, sync-agent-rules): unittest
python3 -m unittest discover -s tests -v
python3 -m unittest tests.test_dispatch_verify -v    # a single module

# Skill-specific suites
bash skills/ps-commu-explain/tests/lifecycle_test.sh            # macOS only (BSD stat/lsof)
python3 -m unittest discover -s skills/ps-interactive-learning-builder/tests -v
cd skills/ps-commu-explain/assets/template-react && npm ci && npx tsc --noEmit && npm run build
```

`.github/workflows/ci.yml` runs all five jobs on every push and PR.

## Architecture

**Skills are thin; mechanics live in the engine and in one doc.** Each `skills/ps-release-workflow-*/SKILL.md`
is a short wrapper that calls `~/.claude/ps-release-workflow/bin/psrw <verb>`. Explanations of how things work
(backlog routing, gates, the promote sequence, state layout, what the guard guarantees) live **only** in
`engine/ps-release-workflow/docs/lifecycle.md`. `tests/test_docs_single_source.py` enforces this: skill bodies
must stay within 40 lines and link to lifecycle.md instead of restating it. `full-promote` is exempt. The test
reads skills from `~/.claude/skills`, so it skips on a machine where `install.sh` has not been run.

**Engine layout** (`engine/ps-release-workflow/`):
- `bin/psrw` runs each verb **as a subprocess** of `scripts/<script>.py` (the `VERBS` table maps verb to
  script). It does not import them, because argparse's `SystemExit` would collide with psrw's own exit codes.
  A new verb means a new script plus a `VERBS` entry; a script with no verb goes in `NON_VERBS`.
- `lib/` holds the shared logic: catalog/state mutation (`state.py`, `catalog.py`), git plumbing (`git_ops.py`),
  claim ownership (`owner.py`), epic gates, main sync, release freeze, and backlog path routing.
- `scripts/guard_check.py` is the PreToolUse hook, registered in settings.json by absolute path. Exit code 2
  blocks the edit. Setting `PS_RELEASE_WORKFLOW_SCRIPTED=1` bypasses it.
- `templates/precheck.sh` (Gate 1, run by `ship`) and `templates/integration.sh` (Gate 2, run by `promote`)
  are stamped into target repos by `psrw init`. A repo can override their paths with the `hooks` block in `.release.json`.
- Tests build throwaway git repos. Use `tests/_helpers.py:git()` rather than writing another helper.

**`bin/dispatch-worker` family:** `dispatch-worker`, `dispatch-codex-worker` and `dispatch-cursor-worker` are
symlinks to `dispatch-agy-worker`, one Python file that picks its default agent from the name it was invoked
under. `dispatch-thinker` is a front end that routes thinking tasks to Claude Opus 5.5 first, then Codex. The
README documents the routing and quota rules and the env vars.

**`bin/sync-agent-rules`** generates `~/.gemini/GEMINI.md` from `~/.claude/CLAUDE.md`. Never edit GEMINI.md by hand.

**`ps-commu-explain`** is self-contained: the lifecycle scripts in `scripts/` (init, lint, serve, verify,
clean) plus HTML and React templates in `assets/`. Built explanations live under `/tmp/ps-commu/<slug>/`.
`serve.sh` refuses to serve anything that fails `lint.sh`.

## Conventions

- Specs and plans for in-flight features go in `.claude/refined_backlog/F-NNN-<slug>/{spec,plan}.md`. Standalone
  design docs go in `docs/superpowers/{specs,plans}/`. Research notes go in `research/`.
- When a change adds a skill, verb, CLI or env var, update `README.md` in the same change.
