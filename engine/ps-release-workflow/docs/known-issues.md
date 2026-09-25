# Known issues

Findings surfaced by review that were deliberately **not** fixed, each with why.
One line per issue. Filed here rather than chased, so they are not lost.

## Backlog artifact handling (`scripts/promote_idea_to_refined.py`)

- **A title containing a double quote produces broken YAML** in both skeleton templates and in the identity rewrite (`f'title: "{title}"'`). Pre-existing; no escaping anywhere. Fix by quoting properly or switching to a YAML emitter.
- **Retry after a failed rollback raises `FileExistsError`** at `folder.mkdir(parents=True)`, because a partially-removed `F-NNN` folder survives a failed `shutil.rmtree`. Pre-existing; recovery is to remove the folder by hand.
- **Exotic line separators desync the frontmatter split.** A lone `\r`, ` ` or `\f` inside a leading `---` block makes `splitlines()` and `split("\n")` disagree on indices, dropping one body line per stray separator. Pre-existing (reproduced against the pre-fix implementation).
- **An indented `---` inside a block scalar is treated as the closing fence**, splitting the scalar. The line survives, dedented, as the fence; no prose is destroyed. Pre-existing.
- **Bounded identity-key residual.** For a leading `---` block that fully parses as YAML, a line whose key is exactly `title`/`id`/`from_idea`/`status` has its *value* replaced. When the block really is frontmatter that is the intended behaviour; when it is a horizontal rule over prose, the words are lost. The two cases are genuinely indistinguishable, and any non-identity key in the same position is preserved.

## Contract / validation gaps

- **`F-015` has no `plan.md`.** "All three files always exist" is not an invariant, so a future reader must tolerate absence. Deferred to the hand-off contract spec, which is where a validator will live.
- **No schema version on any artifact.** `.release.json`'s `version` is the release number, not a schema version. Deferred to the same spec. The optional `epic` key on idea and refined entries, and the whole `epic_backlog/_catalog.json` shape, inherit this: there is no versioned contract, only "absent key = legacy entry".

## Epic layer

- **A hard-killed epic outcome check strands the epic in `verifying`.** An exception in the check is caught and recorded as `failed_verification`, so only a hard process kill (SIGKILL, power loss) leaves the claim behind. There is deliberately no timestamp or timeout (any threshold would be indefensible); recovery is `psrw epic verify --force E-NNN`. G-E3 refuses, naming the live claim, rather than steal an in-flight check.
- **The outcome check is machine-local and optional.** `hooks.epic_check` (default `scripts/epic-check.sh`) missing or unusable warns on stderr and skips, so a repo without it gets completeness enforcement only, never an outcome check. Mirrors Gate 1.
- **Sibling features are developed blind to each other.** Epic branches are cut off `main`, so nothing shows one slice the others' work until the combined tree is verified at ship/promote. `psrw status` only warns when two or more siblings are claimed at once; it does not prevent it. `psrw epic sync` (used by the `epic-run` skill) closes this for a chained run; a hand-run claim is still blind.
- **An idea created by hand carries no `epic` tag.** Only `psrw epic fanout` sets it, and `refine` only copies it forward; tagging later means editing the catalog by hand, and a drifted epic id is caught only at G-E3 (refuses) and `epic fanout` (raises).
- **`verify.sh` is gitignored and reads the installed skills.** It lives in the working tree only (`.gitignore`, machine-local), so its skill-count bump (13 to 16) cannot ride the feature branch and must be applied on the main checkout. It also counts `~/.claude/skills`, so it reports the old count until the new skills are merged and installed.
- **`ship`'s post-merge rollback can drop an unrelated release commit.** When the feature branch is already contained in `release/<v>` (a slice that added no commits after `psrw epic sync`, which fast-forwards), `git merge --no-ff` prints "Already up to date" and creates no commit, so a Gate 1 failure on the merged tree runs `git reset --hard HEAD~1` against whatever release commit was last (for example a catalog commit). Pre-existing in `ship_current_work_to_release.py`; `epic run` makes it likelier. Not fixed here. Untested mitigation candidate: have `epic sync` merge with `--no-ff` so a synced feature always carries a commit.

### Deferred from the epic-run final review

- `psrw epic sync` has no current-branch guard (it merges into whatever branch the worktree is on).
- `merge --abort`'s return code is discarded, while the message says the merge "was aborted".
- `epic sync` reads state before taking the lock.
- The precheck script is resolved from `_release`, not from the feature worktree.
- Refusal ordering in `epic plan`: the precheck refusal versus the other refusals is not specified or tested.
- Two `_plan_slice` refusal branches in `scripts/epic.py` are now covered by `tests/test_epic_plan_refusals.py` (the idea whose `promoted_to` feature is missing from the refined catalog; a feature with an unexpected status). The third branch this entry once counted — a slice shipped on another release — was already covered by `tests/test_epic_run.py::test_plan_refuses_a_slice_shipped_on_another_release`, so the original "three untested" count was wrong.
- Several skill assertions are presence-only (a token appearing somewhere), not placement or order.
- `CHAIN_BANS` and `LINE_BUDGET` pin the current instances, not the seed that stamps them out.
- The e2e test cannot detect a promote: promote pushes `release/<v>` and opens a PR without moving local `main`, so never-promote rests on the skill lint alone.

## Test-suite cost

- **The 6-minute budget is measured against an unstable baseline.** Identical suites (352 tests,
  same count, same commits) have been observed at **5m15s and 8m51s** on the same machine — a
  70% swing from environmental load alone, since the intervening change was string-only. Cost is
  dominated by real-git operations. Before treating a budget breach as a regression, re-measure;
  and consider whether a wall-clock budget is the right gate at all versus counting git
  subprocess calls, which is deterministic.

## Toolkit surface

- ~~11 slash-command references in script output~~ — **fixed 2026-08-15** (`824074d`). All of
  `status.py`'s "Next:" hints, `guard_check.py`'s recovery text, `new_idea.py` and
  `lib/backlog_paths.py` now print `psrw <verb>`.

## Release sync / freeze follow-ups (filed 2026-09-24, fix/psrw-release-sync)

- **Overlaps in-flight F-012 (hotfix-to-release auto-sync, `feat/F-012`).** `lib/main_sync.py` here and F-012's `main_sync` primitive solve the same problem; reconcile before either merges.
- **`promote --deploy` still skips silently when no deploy script exists** (the `deploy.exists()` gate in `_promote_release`); only `ship` got the "no local deploy configured" notice.
- **`unclaim --force` discards with no backup.** It now lists what it deletes; saving a patch under `.claude/state/` first would make the loss recoverable.
- **Gitignored files in a worktree (`.env`, local config) are deleted by `unclaim` without a mention,** even without `--force` — `git worktree remove` does not count them as dirty.
- **The `tmp_repo_with_release` fixture commits `.claude/state/`** (a real `psrw init` gitignores it), so cleanup's reset-to-origin/main path is untestable with it; `tests/test_release_freeze.py` works around it locally.
