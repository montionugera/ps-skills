# ps-release-workflow

A "ship-the-release" workflow toolkit for Claude Code sessions. It opts a repo into a
disciplined lifecycle where ideas are captured, refined into plannable features, claimed
into isolated git worktrees (one owner per worktree), shipped into an in-progress release
branch behind a per-feature gate, and finally promoted to `main` behind a whole-release
integration gate. A PreToolUse guard enforces that edits only happen inside the worktree
you claimed, so parallel sessions can't stomp on each other or on `main`.

## Lifecycle

```
init            # once per repo — opt in
  └─ new-release      # open release/<v>, create the _release worktree
       ├─ idea             # capture I-NNN into the backlog
       │    └─ refine          # promote I-NNN → F-NNN (refined backlog)
       │         └─ brainstorm/plan  # fill F-NNN/spec.md + plan.md
       ├─ claim            # claim F-NNN → isolated worktree (owner marker)
       │    └─ implement       # build inside the worktree
       │         └─ ship           # Gate 1 → merge feature into release/<v>
       └─ promote          # Gate 2 → squash-merge release/<v> → main, deploy, auto-clean
```

Slash skills mirror these steps: `/ps-release-workflow:init`, `:new-release`, `:idea`,
`:refine`, `:claim`, `:ship`, `:promote`, plus `:cleanup-legacy` and the auto-fired `:guard`.

## Scripts

| Script | What it does |
| --- | --- |
| `init_repo.py` | Opt the repo in: create `.release.json`, backlog dirs, gitignore the state dir, install the routing convention. Once per repo. |
| `init_work_new_release.py` | Open `release/<v>`, mark `.release.json` in-progress, create the long-lived `_release` worktree. |
| `new_idea.py` | Mint `I-NNN`, create the idea folder with spec/plan/research skeletons, commit on `release/<v>`. |
| `promote_idea_to_refined.py` | Promote `I-NNN` → `F-NNN`, move into the refined backlog, update catalogs. |
| `init_work_refined_backlog.py` | Atomically claim `F-NNN` (or `--next`), create a per-feature worktree with an owner marker. |
| `ship_current_work_to_release.py` | Run Gate 1 (`precheck.sh`), merge the feature branch into `release/<v>`, mark catalog shipped. |
| `promote_release.py` | Run Gate 2 (`integration.sh`), squash-merge `release/<v>` → `main`, deploy, auto-clean worktrees/branches. |
| `cleanup_legacy_worktrees.py` | Interactive GC of marker-less ("legacy") worktrees, showing merged-to-main status. |
| `guard_check.py` | PreToolUse hook: blocks edits on `main` of an opted-in repo, or in a worktree owned by another session. |

## State-file layout

```
.release.json                         # version + in_progress flag (committed)
.claude/
  idea_backlog/
    _catalog.json                     # I-NNN registry (committed on release/<v>)
    I-NNN-<slug>/spec.md plan.md research.md
  refined_backlog/
    _catalog.json                     # F-NNN registry (committed on release/<v>)
    F-NNN-<slug>/spec.md plan.md ...
    _archive/                         # promoted/closed features
  state/
    claims.json                       # gitignored — F-NNN → owner session map
  worktrees/                          # gitignored — per-feature + _release worktrees
    _release/                         # long-lived worktree on release/<v>
    F-NNN-<slug>/                     # claimed feature worktree (has owner marker)
```

Backlog metadata (`idea_backlog/`, `refined_backlog/`, catalogs) is committed onto the
`release/<v>` branch through the long-lived `_release` worktree rather than the main
checkout (decision **D11**). This keeps backlog churn off `main` and lets the guard keep
`main` read-only during a release, while still recording every idea/refine/claim/ship as a
real commit on the release branch.

The per-session owner is resolved from `$CLAUDE_SESSION_ID`. The toolkit's own scripts set
`PS_RELEASE_WORKFLOW_SCRIPTED=1` so their writes bypass the guard.

## Tests

```bash
python3 -m pytest tests/ -v
```

## Rollback branch protection

Branch protection on `main` is configured outside this toolkit. To remove it (e.g. to undo
the protection added when adopting the workflow):

```bash
gh api repos/<owner>/<repo>/branches/main/protection -X DELETE
```
