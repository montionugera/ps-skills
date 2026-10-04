# ps-skills

Personal [Claude Code](https://claude.com/claude-code) skills (`ps-*`) — distributable, tested, install with one command.

[![CI](https://github.com/montionugera/ps-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/montionugera/ps-skills/actions/workflows/ci.yml)

## What's inside

| Skill | What it does |
|-------|--------------|
| **ps-commu-explain** | Turns "explain X" into a fact-checked, visually rich web explanation (diagrams, animation, interactivity) served from `/tmp` and handed back as a verified localhost URL. Six-stage chain — brief → facts → storyboard → author → verify (render gate + reader gate) → handoff — gated by `scripts/lint.sh` and `scripts/verify.sh`. Mechanical steps are scripted so the model only does the judgment: `skeleton.sh` drafts `content.md` from the storyboard, `verify.sh` does one Chrome load per cycle and `verify.sh --reader-prompt` builds the reader-gate prompt, `handoff.sh` prints the handoff, and init, serve, skeleton, verify and handoff log to the workspace's `timings.log`. Self-contained: lifecycle scripts + HTML and React+TS templates. |
| **ps-interactive-learning-builder** | Orchestrates research, learning design, interactive builds, independent audits, and durable verification for traceable courses and explorable references. |
| **ps-release-workflow-init** | Opt a repo into the ship-the-release workflow (`.release.json`, backlogs, routing convention). |
| **ps-release-workflow-idea** | Capture a new idea (`I-NNN`) in the idea backlog. |
| **ps-release-workflow-refine** | Promote a solid, approved idea into the refined backlog (`F-NNN`). |
| **ps-release-workflow-claim** | Claim a refined feature and cut an isolated per-feature worktree. |
| **ps-release-workflow-ship** | Merge a finished feature into the in-progress release (Gate 1). |
| **ps-release-workflow-sync-main** | Absorb commits from `main` (squash-merged hotfixes) into the in-progress release on demand (Gate 1). |
| **ps-release-workflow-new-release** | Open a new release cycle and its `_release` worktree. |
| **ps-release-workflow-promote** | Squash-merge a full release to main and deploy (Gate 2). |
| **ps-release-workflow-guard** | The PreToolUse guard that blocks edits on `main` / foreign worktrees. |
| **ps-release-workflow-cleanup-legacy** | Housekeeping for marker-less legacy worktrees. |
| **ps-release-workflow-full-promote** | Whole release turnover in one shot: promote, babysit CI, merge, watch deploy, clean up, open the next release. |
| **ps-release-workflow-hotfix** | Cut the sibling worktree for an urgent fix straight to `main`, bypassing the release branch. |
| **ps-release-workflow-status** | Read-only one-screen report of the release, features, claims, and what to do next. |
| **ps-release-workflow-unclaim** | Abandon a claimed feature: remove its worktree and clear the claim (keeps the branch). |
| **handoff** | Compact the session into an action-first handoff doc and spawn a fresh agent tab in Herdr; ships an optional Stop hook (`hooks/auto-handoff-stop.py`) that triggers it when context grows large. |
| **agy-worker** | Offloads coding tasks to Antigravity CLI (`agy`) or Cursor CLI (`cursor-agent`) with proactive quota checking (`>30%` 5h, `>10%` weekly), auto-routing, fallback to Claude Sonnet, and standard ≤15-line reports. Binaries: `dispatch-agy-worker`, `dispatch-cursor-worker`, `dispatch-worker`. |
| **url-state-resilience** | Enforces URL-as-State, deep-linking, and reload resilience across web dashboards and SPAs; provides `check-url-state.sh` linter and `url-state-guard.py` hook for non-regression. |
| **macos-audio-hud** | Engineering standards for macOS native floating HUDs and real-time CoreAudio/AVFoundation voice companion clients (`AUVoiceProcessing`, channel 0 extraction, dynamic converters, NSRecursiveLock, floating `NSPanel`, Carbon hotkeys). |
| **rokid-glasses-companion** | Engineering standards and hardware trap mitigations for Rokid AI Smart Glasses and Android AR wearables (direct Wi-Fi WebSocket architecture, `AudioSource.MIC` + AGC/limiter, walkie-talkie echo suppression, raw key debouncing, priority 999 `KeyReceiver`). |
| **multimodal-voice-companion** | Universal protocol standards and audio contracts for real-time live voice/vision companions (WebSocket `/ws/live`, 16 kHz up / 24 kHz down linear PCM, mandatory barge-in buffer flush contracts, dual-ended RMS dBFS telemetry, reconnect resilience). |
| **agentic-vault** | Deterministic Second Brain operating system managing knowledge across 4 Big Phases and 3 Core Categories with Go static gateway (`vault-engine`), append-only capture ledger, optimistic concurrency control (OCC), and human review queues. |

The `ps-release-workflow-*` skills are thin wrappers over a shared Python engine
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
- `dispatch-worker` / `dispatch-agy-worker` / `dispatch-cursor-worker` are linked into `~/.local/bin/`. (`dispatch-codex-worker` is still linked, and only prints the "codex is disabled" refusal.)
- `ps-plugin-bridge` is linked into `~/.local/bin/` to bridge Claude plugins to Antigravity CLI.
- `ps-work` is linked into `~/.local/bin/`: `ps-work link` records a vault project's repo + feature ID, and `ps-work show` prints the project goal beside the live `psrw status --json` feature status (read-only; never writes release state into the vault).

Running `./install.sh` in an interactive terminal automatically prompts you to choose your default routing chain and on-demand preferences, writing to `~/.config/dispatch/config.env`.

Install into a non-default Claude home with `CLAUDE_HOME=/path ./install.sh`.

## Multi-Agent External Fan-out (`dispatch-worker`)

Offload token-heavy code editing and test cycles from Claude to external coding CLIs (**Antigravity CLI** or **Cursor CLI `cursor-agent`**) with quota/on-demand guarding and automated fallback to Claude internal subagents.

**Codex is disabled (2026-10-03).** The dispatcher never routes to OpenAI Codex, in any mode: `--agent codex` exits 2 with `codex is disabled`, a `--priority` chain entry naming codex is dropped with a one-line notice on stderr (a chain naming only codex exits 2), and `--agent auto` considers agy alone. The single switch is `DISABLED_AGENTS` at the top of `bin/dispatch-agy-worker`.


```bash
# Check quota and authentication status across providers
dispatch-worker --agent auto --check-quota
dispatch-cursor-worker --check-quota

# Priority chain routing (Cost-efficient Cursor On-Demand -> AGY)
dispatch-worker --priority "cursor:gemini-3.8-flash > agy" --allow-on-demand --task "Write unit test and implement feature"

# Run in an isolated temporary git worktree
dispatch-worker --agent auto --isolated --task "Refactor module X"
```

Configure default preferences in `~/.config/dispatch/config.env` or via environment variables:
```bash
# Mode: "subscription_quota_remaining" (strict flat rate, $0 extra) or "on_demand" (metered pay-as-you-go)
export AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_MODE="subscription_quota_remaining"
export AI_AGENT_AUTO_DISPATCH_SKILL_DISPATCH_ROUTING_PREFERENCE="cursor:gemini-3.8-flash > agy"
```

### Thinking tasks (`dispatch-thinker`)

`dispatch-thinker` (= `dispatch-worker --capability deep-design-v1`; `--think` uses the same routing) sends deep-reasoning work to **Claude Opus 5.5 only** (`claude -p --model claude-opus-5-5`, available when `claude` is on `PATH`). Reasoning effort defaults to **`high`** (`--effort` on CLI overrides). Claude runs least-privilege (read tools + Write/Edit only; no Bash or web). There is no fallback thinker: a failed Claude run is reported as a failure. `dispatch-thinker` exits `12` (fail closed) when Claude is unavailable or a non-Claude model is requested; plain `--think` exits `12` for a non-Claude model and `10` when Claude is unavailable. `--agent claude` pins the provider.

| Env var | Default | Purpose |
| :--- | :--- | :--- |
| `CLAUDE_THINK_MODEL` | `claude-opus-5-5` | Claude thinker model id |
| `THINK_EFFORT` | `high` | Default reasoning effort for thinking tasks (`--effort` overrides) |
| `CLAUDE_THINK_EFFORT` | unset | Claude-specific thinker effort override |
| `DISPATCH_THINKER_SKIP_CLAUDE` | unset | `1` marks Claude unavailable, so thinking mode fails closed |

## Plugin Bridge & Antigravity (agy) Context Budget (`ps-plugin-bridge`)

Bridge Claude plugins (e.g. `superpowers`, `frontend-design`) directly into Google Antigravity CLI (`~/.gemini/config/plugins`):

```bash
ps-plugin-bridge --sync   # bridge enabled Claude plugins and prune disabled ones (protects agy context budget)
ps-plugin-bridge --list   # inspect bridged plugins, skill counts, and context budget status
ps-skills-doctor --fix    # audit runtime health, repair broken symlinks, and link agy binaries
```

### One source of rules for agy (`sync-agent-rules`)

`~/.gemini/GEMINI.md` is a build output of `~/.claude/CLAUDE.md`, never a hand copy (a hand copy went
stale and agy never saw the Target Fidelity Tiers). `@file` import lines such as `@RTK.md` are resolved
inline; agy-only rules live in `~/.gemini/GEMINI.local.md`, which is appended verbatim.

```bash
bin/sync-agent-rules --check   # exit 1 + bounded diff when GEMINI.md is out of date (read-only)
bin/sync-agent-rules --write   # back up to GEMINI.md.bak-<timestamp>, then regenerate
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
  automatically and refuses to serve on failure. `scripts/skeleton.sh <slug>` drafts `app/content.md`
  (one `TODO(` line per storyboard row; lint rejects any left). `scripts/verify.sh` is the render gate
  (headless Chrome asserts, one load that also writes `page-text.txt`); `verify.sh <slug> --reader-prompt`
  prints the prompt for a Sonnet reader-gate subagent, which reads only that page text and must answer the
  brief's 3 questions with citations. `scripts/handoff.sh <slug>` prints the final handoff. Authors read
  `app/components-index.md` (a 25-line index) before grepping `components.md`.
  Modes: `/ps-commu-explain list`, `/ps-commu-explain clean`.
  Built explanations live under `/tmp/ps-commu/<slug>/` and self-destruct after 24h.
- **ps-interactive-learning-builder** — invoke `/ps-interactive-learning-builder <topic>` to create a
  source-backed course, explorable reference, or hybrid learning project with gated audit and verification.
- **ps-release-workflow** — start with `ps-release-workflow-init` in a repo, then
  idea → refine → claim → ship → promote. Hotfixes merged to `main` are merged into
  `release/<v>` automatically by `psrw ship` and `psrw promote` before they gate or deploy
  (a conflict refuses with the exact command, and `promote --babysit` refuses to merge if
  `main` advanced while CI ran); `psrw sync-main` does it on demand (`--strict` refuses
  when `origin/main` cannot be fetched), `psrw sync` pulls `release/<v>` into an in-flight
  feature worktree, and `psrw status` flags a release that is behind `main`. Emergency
  bypasses: `--no-sync-main` (ship) and `--allow-stale-main` (promote). Each skill's
  `SKILL.md` documents its preconditions.

## Development

```bash
# Python engine (350+ tests)
cd engine/ps-release-workflow
pip install -e ".[dev]"
pytest -q

# ps-commu-explain lifecycle suite (bash; macOS — uses BSD stat/lsof)
bash skills/ps-commu-explain/tests/lifecycle_test.sh

# ps-interactive-learning-builder contract, installer, and repository integration suite
python3 -m pytest skills/ps-interactive-learning-builder/tests -v

# ps-commu-explain React template builds
cd skills/ps-commu-explain/assets/template-react
npm ci && npx tsc --noEmit && npm run build

# tools/vault-engine Go test suite (>80% coverage) and full E2E lifecycle
cd tools/vault-engine
go test -cover ./pkg/...
./test_e2e.sh
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs all of these on every push and PR,
plus the root `tests/` suite (`python3 -m pytest tests -v`). The lifecycle suite runs on macOS and
everything else on Linux. A `test-coverage` job
([`.github/scripts/check_test_coverage.py`](.github/scripts/check_test_coverage.py)) fails the
build when any tracked test file is not run by a CI step, when a step uses `unittest` (it never
collects pytest-style tests), or when a test step can be skipped or have its failures ignored
(`if:`, `continue-on-error`, `|| true`). A new test suite therefore needs a CI step.

## License

[MIT](LICENSE)
