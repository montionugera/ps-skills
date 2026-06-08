# ps-skills

Personal [Claude Code](https://claude.com/claude-code) skills (`ps-*`) — distributable, tested, install with one command.

[![CI](https://github.com/montionugera/ps-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/montionugera/ps-skills/actions/workflows/ci.yml)

## What's inside

| Skill | What it does |
|-------|--------------|
| **ps-commu-explain** | Turns "explain X" into a fact-checked, visually rich web explanation (diagrams, animation, interactivity) served from `/tmp` and handed back as a verified localhost URL. Self-contained: lifecycle scripts + HTML and React+TS templates. |
| **ps-release-workflow-init** | Opt a repo into the ship-the-release workflow (`.release.json`, backlogs, routing convention). |
| **ps-release-workflow-idea** | Capture a new idea (`I-NNN`) in the idea backlog. |
| **ps-release-workflow-refine** | Promote a solid, approved idea into the refined backlog (`F-NNN`). |
| **ps-release-workflow-claim** | Claim a refined feature and cut an isolated per-feature worktree. |
| **ps-release-workflow-ship** | Merge a finished feature into the in-progress release (Gate 1). |
| **ps-release-workflow-new-release** | Open a new release cycle and its `_release` worktree. |
| **ps-release-workflow-promote** | Squash-merge a full release to main and deploy (Gate 2). |
| **ps-release-workflow-guard** | The PreToolUse guard that blocks edits on `main` / foreign worktrees. |
| **ps-release-workflow-cleanup-legacy** | Housekeeping for marker-less legacy worktrees. |

The nine `ps-release-workflow-*` skills are thin wrappers over a shared Python engine
([`engine/ps-release-workflow`](engine/ps-release-workflow)) — they call its scripts at runtime, so the
engine is installed alongside them.

## Layout

```
ps-skills/
├── skills/                     # the ps-* skills (copied into ~/.claude/skills)
│   ├── ps-commu-explain/
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
- **ps-release-workflow** — start with `ps-release-workflow-init` in a repo, then
  idea → refine → claim → ship → promote. Each skill's `SKILL.md` documents its preconditions.

## Development

```bash
# Python engine (111 tests)
cd engine/ps-release-workflow
pip install -e ".[dev]"
pytest -q

# ps-commu-explain lifecycle suite (bash; macOS — uses BSD stat/lsof)
bash skills/ps-commu-explain/tests/lifecycle_test.sh

# ps-commu-explain React template builds
cd skills/ps-commu-explain/assets/template-react
npm ci && npx tsc --noEmit && npm run build
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs all three on every push and PR:
the engine tests on Linux, the lifecycle suite on macOS, and the React template build on Linux.

## License

[MIT](LICENSE)
