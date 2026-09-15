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
`main` by the release's own migrations.

### Overriding the gate scripts: the `hooks` block

A repo whose scripts do not live at the default paths can redirect them with an
optional `hooks` object in `.release.json`. Three keys, each with a default:

| key | default | used by |
| --- | --- | --- |
| `precheck` | `scripts/precheck.sh` | Gate 1, `ship` |
| `integration` | `scripts/integration.sh` | Gate 2, `promote` |
| `deploy_local` | `scripts/deploy-local.sh` | the local deploy in `ship` and `promote --deploy` |

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

1. Gate 2 runs, then `--deploy` if given.
2. `release/<v>` is pushed and a PR to `main` is opened. Release state is finalized on
   the release branch only *after* the PR exists, so a failed `gh` call leaves the
   release in progress and promote can simply be re-run.
3. Promote stops there. A human reviews and squash-merges; that merge deploys prod.
4. **After the PR merges**, `psrw promote --cleanup-only <version>` is required: it
   marks features promoted, archives the `F-NNN` folders, prunes the per-feature and
   `_release` worktrees and branches, and finalizes `.release.json` on `main`.
   It verifies the PR is merged first and refuses otherwise, because deleting the
   remote release branch would auto-close an open PR.

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
  state/claims.json                   # gitignored — F-NNN -> owner map
  worktrees/                          # gitignored
    _release/                         # long-lived, on release/<v>
    F-NNN-<slug>/                     # claimed feature worktree (owner marker)
```

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

The guard is a read path: it never generates or persists an identity as a side effect.
It bypasses entirely when `PS_RELEASE_WORKFLOW_SCRIPTED=1`, warns but allows on a
marker-less legacy worktree, and allows the `_release` worktree silently.
