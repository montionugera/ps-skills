# ps-skills

Personal [Claude Code](https://claude.com/claude-code) skills (`ps-*`) — distributable, tested, install with one command.

[![CI](https://github.com/montionugera/ps-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/montionugera/ps-skills/actions/workflows/ci.yml)

## What's inside

| Skill | What it does |
|-------|--------------|
| **ps-commu-explain** | Turns "explain X" into a fact-checked, visually rich web explanation (diagrams, animation, interactivity) served from `/tmp` and handed back as a verified localhost URL. Self-contained: lifecycle scripts + HTML and React+TS templates. |
| **ps-interactive-learning-builder** | Orchestrates research, learning design, interactive builds, independent audits, and durable verification for traceable courses and explorable references. |
| **ps-release-workflow-init** | Opt a repo into the ship-the-release workflow (`.release.json`, backlogs, routing convention). |
| **ps-release-workflow-idea** | Capture a new idea (`I-NNN`) in the idea backlog. |
| **ps-release-workflow-refine** | Promote a solid, approved idea into the refined backlog (`F-NNN`). |
| **ps-release-workflow-claim** | Claim a refined feature and cut an isolated per-feature worktree. |
| **ps-release-workflow-ship** | Merge a finished feature into the in-progress release (Gate 1). |
| **ps-release-workflow-new-release** | Open a new release cycle and its `_release` worktree. |
| **ps-release-workflow-promote** | Squash-merge a full release to main and deploy (Gate 2). |
| **ps-release-workflow-guard** | The PreToolUse guard that blocks edits on `main` / foreign worktrees. |
| **ps-release-workflow-cleanup-legacy** | Housekeeping for marker-less legacy worktrees. |
| **ps-release-workflow-full-promote** | Whole release turnover in one shot: promote, babysit CI, merge, watch deploy, clean up, open the next release. |
| **ps-release-workflow-hotfix** | Cut the sibling worktree for an urgent fix straight to `main`, bypassing the release branch. |
| **ps-release-workflow-status** | Read-only one-screen report of the release, features, claims, and what to do next. |
| **ps-release-workflow-unclaim** | Abandon a claimed feature: remove its worktree and clear the claim (keeps the branch). |
| **handoff** | Compact the session into an action-first handoff doc and spawn a fresh agent tab in Herdr; ships an optional Stop hook (`hooks/auto-handoff-stop.py`) that triggers it when context grows large. |

The thirteen `ps-release-workflow-*` skills are thin wrappers over a shared Python engine
([`engine/ps-release-workflow`](engine/ps-release-workflow)) — they call its scripts at runtime, so the
engine is installed alongside them.

## Layout

```
ps-skills/
├── skills/                     # the ps-* skills (copied into ~/.claude/skills)
│   ├── ps-commu-explain/
│   ├── ps-interactive-learning-builder/
│   └── ps-release-workflow-*/
├── engine/
│   └── ps-release-workflow/    # Python engine for the release-workflow skills
│                               # (→ ~/.claude/ps-release-workflow)
├── install.sh
└── .github/workflows/ci.yml
```

## Install

Requires a [Claude Code](https://claude.com/claude-code) setup with a `~/.claude` directory.

```bash
git clone https://github.com/montionugera/ps-skills.git
cd ps-skills
./install.sh           # symlink skills into ~/.claude (edits in the repo go live)
# or
./install.sh --copy    # copy a snapshot instead of symlinking
```

Then restart your Claude Code session so the new skills are discovered.

- `ps-commu-explain` is self-contained and works immediately.
- `ps-release-workflow-*` use the engine installed at `~/.claude/ps-release-workflow`.

Install into a non-default Claude home with `CLAUDE_HOME=/path ./install.sh`.

## Using the skills

- **ps-commu-explain** — say *"explain X"* / *"show me how X works"*, or invoke `/ps-commu-explain <topic>`.
  Modes: `/ps-commu-explain list`, `/ps-commu-explain clean`. Built explanations live under
  `/tmp/ps-commu/<slug>/` and self-destruct after 24h.
- **ps-interactive-learning-builder** — invoke `/ps-interactive-learning-builder <topic>` to create a
  source-backed course, explorable reference, or hybrid learning project with gated audit and verification.
- **ps-release-workflow** — start with `ps-release-workflow-init` in a repo, then
  idea → refine → claim → ship → promote. Each skill's `SKILL.md` documents its preconditions.

## Development

```bash
# Python engine (350+ tests)
cd engine/ps-release-workflow
pip install -e ".[dev]"
pytest -q

# ps-commu-explain lifecycle suite (bash; macOS — uses BSD stat/lsof)
bash skills/ps-commu-explain/tests/lifecycle_test.sh

# ps-interactive-learning-builder contract, installer, and repository integration suite
python3 -m unittest discover -s skills/ps-interactive-learning-builder/tests -v

# ps-commu-explain React template builds
cd skills/ps-commu-explain/assets/template-react
npm ci && npx tsc --noEmit && npm run build
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs all four on every push and PR:
the engine and interactive-learning-builder tests on Linux, the lifecycle suite on macOS, and the
React template build on Linux.

## License

[MIT](LICENSE)
