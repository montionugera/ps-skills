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
       └─ promote          # Gate 2 → push release/<v> + open PR → main
            └─ cleanup         # REQUIRED after the PR merges: --cleanup-only <v>
```

`psrw` mirrors these steps as verbs: `psrw init`, `new-release`, `idea`, `refine`, `claim` (supports `--reopen`),
`ship` (auto-teardown unless `--keep-worktree`), `promote`, `unclaim`, `status` (surfaces reclaimable worktrees),
`hotfix`, `sync-main`, `gc` (safely prune eligible merged feature worktrees). The guard fires automatically on Claude's
own edit tools; see [`docs/lifecycle.md#guard-guarantees`](docs/lifecycle.md#guard-guarantees).

## Scripts

| Script | What it does |
| --- | --- |
| `init_repo.py` (`psrw init`) | Opt the repo in: create `.release.json`, backlog dirs, gitignore the state dir, stamp the gate-script templates (`templates/`, never over an existing script), install the routing convention. Once per repo. |
| `init_work_new_release.py` (`psrw new-release`) | Open `release/<v>`, mark `.release.json` in-progress, create the long-lived `_release` worktree. |
| `new_idea.py` (`psrw idea`) | Mint `I-NNN`, create the idea folder with spec/research skeletons, commit on `release/<v>`. |
| `promote_idea_to_refined.py` (`psrw refine`) | Promote `I-NNN` → `F-NNN`, carry the idea's content forward into the refined backlog, update catalogs. |
| `init_work_refined_backlog.py` (`psrw claim`) | Atomically claim `F-NNN` (or `--next`), create a per-feature worktree with an owner marker. Use `--reopen` to recreate the worktree for an already-shipped feature. |
| `ship_current_work_to_release.py` (`psrw ship`) | Run Gate 1 (`precheck.sh`), merge the feature branch into `release/<v>`, mark catalog shipped, and automatically tear down the worktree (unless `--keep-worktree`). |
| `promote_release.py` (`psrw promote`) | Run Gate 2 (`integration.sh`), push `release/<v>`, open a PR to `main` (default) or squash-merge locally (`--direct`). After the PR merges, `--cleanup-only <v>` archives + prunes. See *Promote lifecycle* below. |
| `unclaim.py` (`psrw unclaim`) | Abandon a claim, keeping the feature branch. |
| `status.py` (`psrw status`) | One-screen report of what is in flight, including reclaimable worktrees count. |
| `hotfix.py` (`psrw hotfix`) | Create a sibling hotfix worktree (`--sync-release` is an alias for `psrw sync-main`). |
| `sync_main.py` (`psrw sync-main`) | Merge `main` (hotfixes) into the open `release/<v>`, verify with Gate 1, roll back on failure; `--deploy` redeploys locally. |
| `gc_worktrees.py` (`psrw gc`) | Garbage collect and prune shipped/merged feature worktrees using rigorous safety (S1–S8) and liveness (L1–L3) checks. Report-only by default; `--apply` executes removal; `--force` overrides uncommitted/ignored/idle checks; `--json` emits machine-readable reports. |
| `cleanup_legacy_worktrees.py` | Interactive GC of marker-less ("legacy") worktrees, showing merged-to-main status. |
| `guard_check.py` | PreToolUse hook: blocks edits on `main` of an opted-in repo, or in a worktree owned by another session. See *Guard guarantees* in `docs/lifecycle.md`. |

## Promote lifecycle

See [`docs/lifecycle.md#promote-sequence`](docs/lifecycle.md#promote-sequence) for the full
sequence — Gate 2, the PR-based flow, `--babysit`, and the required post-merge
`--cleanup-only <version>` step.

## State-file layout

See [`docs/lifecycle.md#state-layout`](docs/lifecycle.md#state-layout) for the full
directory layout: `.release.json`, `idea_backlog/`, `refined_backlog/`, and the gitignored
`state/` and `worktrees/` dirs.

Backlog metadata (`idea_backlog/`, `refined_backlog/`, catalogs) is committed onto the
`release/<v>` branch through the long-lived `_release` worktree rather than the main
checkout (decision **D11**) — see
[`docs/lifecycle.md#d11-backlog-routing`](docs/lifecycle.md#d11-backlog-routing).

See [`docs/lifecycle.md#guard-guarantees`](docs/lifecycle.md#guard-guarantees) for what the
guard actually checks. In short: it intercepts Claude Code's own `Edit`/`Write`/`MultiEdit`/
`NotebookEdit` tool calls only — a script's own file writes never go through it, with or
without any environment override — and its ownership check guards against cross-machine
claims and hand-edited markers, not against two local Claude sessions (claims are created
with a machine-cached fallback id, so local sessions normally resolve to the same owner).
The one place the toolkit sets `PS_RELEASE_WORKFLOW_SCRIPTED=1` as an explicit override is
`promote_release.py`'s `--direct` mode, defensively, before its post-squash-merge cleanup
step runs against the main checkout.

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

## Gate concurrency

Heavy gates (Gate 1 `precheck.sh` in `psrw ship`, Gate 2 `integration.sh` in `psrw promote`) take a
machine-wide slot (`lib/gate_lock.py`) so concurrent sessions do not starve each other of CPU and memory.
A gate that cannot get a slot prints `[gate-lock] ... waiting` and retries every 5 s for up to an hour.

| Env var | Default | Meaning |
|---|---|---|
| `PSRW_GATE_SLOTS` | `2` | Max gates running at once on this machine |
| `PSRW_GATE_LOCK_DIR` | `~/.cache/psrw/gate-locks` | Where slot files live (`flock`; released by the kernel if a gate dies) |
