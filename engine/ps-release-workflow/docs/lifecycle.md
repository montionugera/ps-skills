# ps-release-workflow — lifecycle mechanics

Single source of truth for the explanatory mechanics behind the skills. Skills link
here rather than restating. Anything that changes what an agent *does* (flags,
recovery steps) stays inline in the skill, not here.

## D11 backlog routing
<a id="d11-backlog-routing"></a>

Backlog metadata — `idea_backlog/`, `refined_backlog/`, and both `_catalog.json`
files — is committed onto the `release/<v>` branch through the long-lived `_release`
worktree, never through the main checkout. This keeps backlog churn off `main`, lets
the guard hold `main` read-only for the whole release, and still records every
idea / refine / claim / ship as a real commit on the release branch.

Source of truth for release state: the `_release` worktree's `.release.json`. For a
repo that has promoted at least once, `main`'s copy carries only the last-promoted
version — see `lib/backlog_paths.py:14-20`.

## Gates
<a id="gates"></a>

**Gate 1 — `scripts/precheck.sh`**, run by `ship`. Resolved from the tree whose code
it verifies: the feature worktree pre-merge, then re-run from the `_release`
worktree post-merge to verify the combined result (a failure there rolls the merge
back) — never the main checkout, whose script may differ (audit A5). A missing
`precheck.sh` is a loud stderr warning, not an error, so repos without one keep
working.

**Gate 2 — `scripts/integration.sh`**, run by `promote` from the `_release` worktree,
**on by default**. Opt out with `--no-gate2`. If the gate is requested and the script
is missing, promote refuses — it never silently skips. `--allow-missing-gate2`
proceeds UNVERIFIED, for repos that never had one.

`--deploy` (local prod-style deploy) is opt-in and repo-specific. It runs from the
`_release` worktree, because the shared local DB may already be migrated ahead of
`main` by the release's own migrations. `ship`'s post-merge deploy never
skips silently: with no deploy script at `hooks.deploy_local` (default
`scripts/deploy-local.sh`) it prints `no local deploy configured: add
scripts/deploy-local.sh or hooks.deploy_local`, a notice distinct from the
`--no-deploy` one.

### Main sync: hotfixes reach the open release
<a id="main-sync"></a>

A hotfix squash-merged to `main` while `release/<v>` is open does not reach the release
by itself, so anything run from `_release` (Gate 1, the local deploy, Gate 2, the promote
PR) would run without it. `lib/main_sync.py` merges `main` (`origin/main` after a fetch
when an origin exists) into `release/<v>` in the `_release` worktree, under its file lock:

- **`ship`** syncs before merging the feature, so Gate 1 verifies release + hotfix +
  feature. Any failure resets to the pre-ship head, undoing sync and merge together.
  Its post-merge deploy re-checks and **refuses** a release still behind `main`.
- **`promote`** syncs first, before the epic gate, `--deploy` and Gate 2.
- **`psrw hotfix --sync-release`** is the last step of the hotfix flow, once the PR merged.

A conflict aborts the merge, leaves `release/<v>` untouched and prints the exact
`cd <_release> && git merge origin/main` to run. So does a `main` change to release
bookkeeping (`.release.json`, the backlog dirs, `.claude/state/`), which must never be
auto-merged over the release's own copy.

### Epic gates: G-E2 and G-E3

An **epic** (`E-NNN`) is one outcome delivered by several features. Its gates run a
repo-supplied outcome check (`hooks.epic_check`, default `scripts/epic-check.sh`, the
fourth key in the `hooks` block below) against the *combined* release tree. An epic is
**complete** when every idea tagged to it (`epic_children`) has been refined, and every
resulting feature has `status` `shipped`/`promoted` *and* `release_version` equal to the
release under test (both fields are needed because `unclaim` clears the claim but leaves
`release_version` set). Completeness gates the automatic runs: `ship` only triggers the
check once the epic is complete, and `promote` refuses an incomplete one. The hand-run
`psrw epic verify` does not check completeness at all.

- **G-E2 (ship-time).** When a `ship` makes its epic complete, that ship wins a
  compare-and-set (`open`/`failed_verification` to `verifying`), commits the claim on
  `release/<v>`, then runs the check **outside** the shared lock. `psrw epic verify E-NNN`
  runs the same claim-and-check path by hand, without a completeness check; `--force`
  also reclaims a stale `verifying` (a hard-killed run) or re-checks a `verified` epic. A failing check records
  `failed_verification` and warns; the merge that triggered it still stands.
- **G-E3 (promote-time).** `promote` runs `check_epics` first, before Gate 2, for every
  epic with a feature shipped into this release. An incomplete epic refuses the
  promote; `--allow-split-epic` instead records `split_approved_by` permanently
  (exempting the epic from later releases too) and lists it in the PR body. A
  complete epic that is not `verified`, or whose verification is stale, is re-checked.
  *Fresh* means only psrw's own `.claude/epic_backlog` bookkeeping changed since
  `verified_sha`; any other change re-runs the check. A missing epic-catalog entry
  refuses outright. `--allow-split-epic` never overrides a failed outcome check.
- **Environment.** The hook runs in a throwaway worktree detached at the captured sha,
  never in `_release`, with `PSRW_EPIC_ID`, `PSRW_EPIC_FEATURES` (comma-separated
  `F-NNN`), `PSRW_EPIC_SHA`, `PSRW_RELEASE_VERSION`, and `PSRW_EPIC_DIR` (output copied
  into the epic folder afterward). A missing hook warns loudly on stderr and skips —
  completeness is still enforced at promote — exactly like Gate 1.
- **Demotion.** `unclaim` of a feature whose epic is `verified` demotes the epic to
  `open` (clearing `verified_sha`, `verifying_sha`, `release_version`), because the
  completeness the verification vouched for is gone.

### Epic run: the sanctioned auto-chain

`ps-release-workflow-epic-run` chains refine, claim, implement, review and
`ship --no-deploy` over an epic's slices, one at a time. It is the one exception to
"never auto-chain", and only for slices a human names in an explicit `--slices`
allowlist (approval lives in that list, not in any catalog field). It never runs
`promote`, `--deploy`, or a merge to main.
It stops at the first failed gate (refusal, unclean tree, failed review, failed ship)
and does not retry a ship blindly.

- **`psrw epic plan E-NNN --slices I-a,I-b`** is a read-only preflight. It prints each
  allowlisted slice in fanout order with `state` (`idea`, `refined`, `claimed`,
  `shipped`), `claimed_by` and next `action` (`refine`, `claim`, `resume`, `skip`). It
  refuses an epic that is `verified`, `promoted` or `verifying`; a slice that is not a
  child of the epic or is already promoted; an unshipped slice whose idea `spec.md` is
  still an untouched skeleton (already-shipped slices are skipped, not checked); and a repo with no Gate 1
  script unless `--allow-no-precheck` (ship would otherwise skip Gate 1 with only a warning). A `failed_verification` epic
  is allowed, with a note.
- **`psrw epic sync`**, run inside a claimed feature worktree, merges `release/<v>`'s
  HEAD into the feature branch under `file_lock(_release)`. Feature branches are cut
  from `main`, so without it slice N cannot see slices 1..N-1 or its own spec and plan.
  It prints `base` (the release HEAD merged; `git diff <base> HEAD` is the slice's own
  work) and `sha` (the post-merge HEAD). A conflict aborts the merge and leaves the
  feature claimed; a dirty tree is refused.
- **State** lives only in the catalogs. There is no run lock, so two chains on one epic
  are unsupported, and re-running the same command resumes at the first unshipped
  slice. Gate 1 runs twice on the combined tree per slice, so each ship is slower.

### Overriding the gate scripts: the `hooks` block

A repo whose scripts do not live at the default paths can redirect them with an
optional `hooks` object in `.release.json`. Four keys, each with a default:

| key | default | used by |
| --- | --- | --- |
| `precheck` | `scripts/precheck.sh` | Gate 1, `ship` |
| `integration` | `scripts/integration.sh` | Gate 2, `promote` |
| `deploy_local` | `scripts/deploy-local.sh` | the local deploy in `ship` and `promote --deploy` |
| `epic_check` | `scripts/epic-check.sh` | G-E2 (`ship`, `epic verify`) and G-E3 (`promote`) |

```json
{ "version": "1.4", "in_progress": true,
  "hooks": { "integration": "ci/integration.sh" } }
```

Fallback is **per key**: the example above still resolves Gate 1 to
`scripts/precheck.sh`. A repo with no `hooks` block behaves exactly as it did
before the block existed — every one of the toolkit's own repos is in that state.

Values must be **relative paths that stay inside the tree**. An absolute path, a
`~` prefix, a `..` segment, a symlink resolving outside the tree, a NUL byte, or a
present-but-unusable value (`""`, `null`, a number) is a **hard error naming the
offending key** — never a silent fallback to the default, because the value is
executed and a silent fallback would hide a misconfigured or hostile gate. Only an
absent key falls back. `ship` refuses the merge on a bad `precheck`, rolling back if
the merge already landed; `promote` refuses on a bad `integration` or `deploy_local`;
a bad `deploy_local` found by `ship` refuses only the post-merge deploy, since the
merge has already succeeded by then.

Each hook is read from **the tree that will execute it**, not a fixed checkout:
Gate 1 from the tree being verified (the feature worktree pre-merge, `_release`
post-merge), Gate 2 and both deploys from `_release`. `.release.json` is committed,
so its `hooks` block legitimately differs per branch.

## Promote sequence
<a id="promote-sequence"></a>

`psrw promote` is PR-based by default and is **not** the terminal step:

1. `main` is synced into `release/<v>` (see [main sync](#main-sync)), then Gate 2 runs,
   then `--deploy` if given.
2. `release/<v>` is pushed and a PR to `main` is opened. Release state is finalized on
   the release branch only *after* the PR exists, so a failed `gh` call leaves the
   release in progress and promote can simply be re-run.
3. Promote stops there. A human reviews and squash-merges; that merge deploys prod.
4. **After the PR merges**, `psrw promote --cleanup-only <version>` is required: it
   marks features promoted, archives the `F-NNN` folders, prunes the per-feature and
   `_release` worktrees and branches, and finalizes `.release.json` on `main`.
   It verifies the PR is merged first and refuses otherwise, because deleting the
   remote release branch would auto-close an open PR.

**The release is frozen from the moment promote starts.** Promote records the freeze
in `.claude/state/release-freeze.json` under the `_release` lock, and `ship` checks it
under that same lock, so a ship either lands before promote starts (and is in the PR) or
is refused and told to ship into the next release. A finalized release (in-progress set
to false) is refused the same way. A promote that fails lifts the freeze, so fixes can
ship and promote can be re-run. That includes red checks under `--babysit`. On success the
freeze lasts until cleanup. `--babysit` also refuses to merge when the local release head
differs from the head it pushed for CI.

**Cleanup verifies what landed.** Before deleting anything, it checks every feature that
the release branch's catalog marks `shipped` on `<v>`. The feature's `shipped_sha`
(recorded by `ship`, else the `feat/F-NNN` tip) must be an ancestor of `origin`'s
`release/<v>`, the head the PR merged. A feature that fails this check is stranded.
Cleanup flags it loudly and resets it in `main`'s catalog to `claimed` (the worktree
survives) or `open`, with `release_version` cleared and `stranded_from: <v>` set. Its
branch and folder are kept, so the next release can ship it. Cleanup returns the list as
`stranded`.

Until cleanup runs, the next `psrw new-release` is blocked by the stale `_release`
worktree. `--babysit` performs steps 2-4 in one go: watch checks, finalize, merge,
clean up.

## State layout
<a id="state-layout"></a>

```
.release.json                         # version + in_progress (committed)
.claude/
  idea_backlog/
    _catalog.json                     # I-NNN registry (committed on release/<v>)
    I-NNN-<slug>/spec.md research.md
  refined_backlog/
    _catalog.json                     # F-NNN registry (committed on release/<v>)
    F-NNN-<slug>/spec.md plan.md
    _archive/                         # promoted/closed features
  epic_backlog/
    _catalog.json                     # E-NNN registry (committed on release/<v>)
    E-NNN-<slug>/spec.md verification.md
    _archive/<v>/                     # epics archived by cleanup
  state/claims.json                   # gitignored — F-NNN -> owner (+ session_id) map
  state/release-freeze.json           # gitignored — versions being promoted (ship refuses)
  worktrees/                          # gitignored
    _release/                         # long-lived, on release/<v>
    F-NNN-<slug>/                     # claimed feature worktree (owner marker)
```

### Epics in the catalogs

Absent `epic` key means a legacy entry; nothing is migrated and every predicate
tolerates its absence. The link runs through the ideas: `psrw epic fanout E-NNN` mints
**one idea per slice** with `epic: E-NNN` (never a feature), and `refine` copies the
tag onto the resulting `F-NNN`. The epic entry holds `status` (`open`, `verifying`,
`verified`, `failed_verification`, `promoted`), `release_version`, `verified_sha` /
`verified_at`, the in-flight `verifying_sha`, and `split_approved_by`. Every write goes
through `mutate_state`, and each mutate+commit pair holds the `_release` file lock
(never across a hook run). `psrw status` adds an **Epics** section (slices shipped out
of slices minted) and warns when two or more siblings of one epic are claimed at once:
epic branches are cut off `main`, so siblings are developed blind to each other.

`--cleanup-only` archives the `E-NNN-<slug>/` folder to `epic_backlog/_archive/<v>/` for
each epic touched by the release, stamping it `promoted`. It leaves an incomplete epic
that is not split-approved un-archived, with a warning, rather than losing it.

The guard only intercepts Claude Code's own `Edit`/`Write`/`MultiEdit`/`NotebookEdit`
tool calls — it never sees a script's own file writes or `git commit` subprocesses,
so `ship`, `init`, `new-release`, and the rest were never subject to it in the first
place. The one place the toolkit sets `PS_RELEASE_WORKFLOW_SCRIPTED=1` is
`promote`'s `--direct` mode, defensively, before its post-squash-merge cleanup step
runs against the main checkout.

## Guard guarantees
<a id="guard-guarantees"></a>

The PreToolUse guard enforces exactly two things:

1. **No edits on the main checkout of an opted-in repo.** Claim a feature and edit
   inside the worktree it creates. This keys off filesystem location, not branch name,
   so checking out a hotfix branch in the main checkout is still blocked.
2. **Cross-machine claim safety.** A worktree claimed on another machine will not
   accept edits here.

It does **not** provide per-session isolation between two Claude sessions on the same
machine: claims are created with a machine-cached fallback id, so local sessions
normally resolve to the same owner. The ownership check protects against
cross-machine claims and hand-edited markers, not against two local sessions.
To narrow that gap, `claim` (and `claim --resume`) also records the harness session id
(`$CLAUDE_CODE_SESSION_ID`, else `$CLAUDE_SESSION_ID`) as `session_id` in
`claims.json` and the marker. `unclaim` warns when that id differs from the current
session's, and refuses a worktree with uncommitted or untracked changes — listing
each path — unless `--force` is given.

The guard is a read path: it never generates or persists an identity as a side effect.
It bypasses entirely when `PS_RELEASE_WORKFLOW_SCRIPTED=1`, warns but allows on a
marker-less legacy worktree, and allows the `_release` worktree silently.
