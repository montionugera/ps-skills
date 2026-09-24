# ps-skills

Personal [Claude Code](https://claude.com/claude-code) skills (`ps-*`) — distributable, tested, install with one command.

[![CI](https://github.com/montionugera/ps-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/montionugera/ps-skills/actions/workflows/ci.yml)

## What's inside

| Skill | What it does |
|-------|--------------|
| **ps-commu-explain** | Turns "explain X" into a fact-checked, visually rich web explanation (diagrams, animation, interactivity) served from `/tmp` and handed back as a verified localhost URL. Six-stage chain — brief → facts → storyboard → author → verify (render gate + reader gate) → handoff — gated by `scripts/lint.sh` and `scripts/verify.sh`. Self-contained: lifecycle scripts + HTML and React+TS templates. |
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
| **agy-worker** | Offloads coding tasks to Antigravity CLI (`agy`) or Codex (`gpt-5.6-terra`) with proactive quota checking (`>30%` 5h, `>10%` weekly), auto-routing, fallback to Claude Sonnet, and standard ≤15-line reports. Binaries: `dispatch-agy-worker`, `dispatch-codex-worker`, `dispatch-worker`. |
| **url-state-resilience** | Enforces URL-as-State, deep-linking, and reload resilience across web dashboards and SPAs; provides `check-url-state.sh` linter and `url-state-guard.py` hook for non-regression. |

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

Requires a [Claude Code](https://claude.com/claude-code), Codex, or [Google Antigravity](https://github.com/google-gemini) setup.

```bash
git clone https://github.com/montionugera/ps-skills.git
cd ps-skills
./install.sh           # symlink skills into ~/.claude, ~/.agents, and ~/.gemini/config
# or
./install.sh --parity  # reconcile full parity: mirror Claude skills into Gemini & archive junk
# or
./install.sh --copy    # copy a snapshot instead of symlinking
```

Then restart your agent session so the new skills are discovered.

- `ps-commu-explain` is self-contained and works immediately.
- `ps-release-workflow-*` use the engine installed at `~/.claude/ps-release-workflow`.
- `dispatch-worker` / `dispatch-agy-worker` / `dispatch-codex-worker` / `dispatch-cursor-worker` are linked into `~/.local/bin/`.
- `ps-plugin-bridge` is linked into `~/.local/bin/` to bridge Claude plugins to Antigravity CLI.

Running `./install.sh` in an interactive terminal automatically prompts you to choose your default routing chain and on-demand preferences, writing to `~/.config/dispatch/config.env`.

Install into a non-default Claude home with `CLAUDE_HOME=/path ./install.sh`.

## Multi-Agent External Fan-out (`dispatch-worker`)

Offload token-heavy code editing and test cycles from Claude to external coding CLIs (**Antigravity CLI**, **OpenAI Codex `gpt-5.6-terra`**, or **Cursor CLI `cursor-agent`**) with quota/on-demand guarding and automated fallback to Claude internal subagents:

```bash
# Check quota and authentication status across providers
dispatch-worker --agent auto --check-quota
dispatch-cursor-worker --check-quota

# Priority chain routing (Cost-efficient Cursor On-Demand -> AGY -> Codex)
dispatch-worker --priority "cursor:gemini-3.8-flash > agy > codex" --allow-on-demand --task "Write unit test and implement feature"

# Run in an isolated temporary git worktree
dispatch-worker --agent auto --isolated --task "Refactor module X"
```

Configure default preferences in `~/.config/dispatch/config.env` or via environment variables:
```bash
# Mode: "subscription_quota_remaining" (strict flat rate, $0 extra) or "on_demand" (metered pay-as-you-go)
export AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_MODE="subscription_quota_remaining"
export AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_ROUTING_PREFERENCE="cursor:gemini-3.8-flash > agy > codex"
```

## Plugin Bridge & Antigravity (agy) Context Budget (`ps-plugin-bridge`)

Bridge Claude plugins (e.g. `superpowers`, `frontend-design`) directly into Google Antigravity CLI (`~/.gemini/config/plugins`):

```bash
ps-plugin-bridge --sync   # bridge enabled Claude plugins and prune disabled ones (protects agy context budget)
ps-plugin-bridge --list   # inspect bridged plugins, skill counts, and context budget status
ps-skills-doctor --fix    # audit runtime health, repair broken symlinks, and link agy binaries
```

### Why Antigravity (agy) Can Struggle to Detect Skills

Antigravity CLI indexes all skills from `~/.gemini/config/skills/` and all sub-plugins in `~/.gemini/config/plugins/*/skills/`. However, Antigravity enforces a **strict context budget** for skills in its prompt:
- If total discovered skills exceed ~80–100, Antigravity **alphabetically truncates** the skill list.
- Because `ps-*` and `subagent-*` start late in the alphabet, mega-plugins (such as `ecc` with 270+ skills) cause `ps-release-workflow-*` and personal skills to be silently excluded from Antigravity sessions.
- `ps-plugin-bridge --sync` automatically reads `~/.claude/settings.json`'s `enabledPlugins` and **prunes disabled plugins** from Antigravity so your skill roster remains compact, healthy, and fully visible to agy.


## Keeping in sync

After `./install.sh`, everything in `~/.claude` is a symlink into this clone, so there is one copy.

```bash
ps-skills-sync            # pull (fast-forward only) + link newly added skills + status
ps-skills-sync --push     # publish local edits: secret scan -> branch -> PR -> CI -> squash-merge
ps-skills-sync --scan     # just the secret scan
```

Automatic pull on session start (throttled to once per 6h, silent when up to date) — add to
`~/.claude/settings.json` under `hooks.SessionStart`:

```json
{ "matcher": "", "hooks": [{ "type": "command", "command": "~/.local/bin/ps-skills-sync --hook", "timeout": 20 }] }
```

It never pushes on its own (this repo is public) and never pulls over uncommitted edits — it prints a
one-line reminder instead. The `handoff` skill's Stop hook (`skills/handoff/hooks/auto-handoff-stop.py`,
linked to `~/.claude/hooks/`) is registered the same way; see that skill's `SKILL.md`.

## Using the skills

- **ps-commu-explain** — say *"explain X"* / *"show me how X works"*, or invoke `/ps-commu-explain <topic>`.
  `init.sh <slug>` scaffolds a workspace with `00-brief.md` (3 reader questions + section budget),
  `01-facts.md` (`F<n> | statement | source` rows), and `02-storyboard.md` (section → question → facts) —
  sibling to `app/`, never served. `scripts/lint.sh` gates all four authoring files (brief placeholders,
  fact citations, storyboard coverage, `app/content.md`'s component rules); `serve.sh` runs it
  automatically and refuses to serve on failure. `scripts/verify.sh` is the render gate (headless
  Chrome asserts); a reader-gate subagent, given only the rendered page text, must then answer the
  brief's 3 questions with citations. Modes: `/ps-commu-explain list`, `/ps-commu-explain clean`.
  Built explanations live under `/tmp/ps-commu/<slug>/` and self-destruct after 24h.
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
