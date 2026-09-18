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
- **Sibling features are developed blind to each other.** Epic branches are cut off `main`, so nothing shows one slice the others' work until the combined tree is verified at ship/promote. `psrw status` only warns when two or more siblings are claimed at once; it does not prevent it.
- **An idea created by hand carries no `epic` tag.** Only `psrw epic fanout` sets it, and `refine` only copies it forward; tagging later means editing the catalog by hand, and a drifted epic id is caught only at G-E3 (refuses) and `epic fanout` (raises).
- **`verify.sh` is gitignored and reads the installed skills.** It lives in the working tree only (`.gitignore`, machine-local), so its skill-count bump (13 to 15) cannot ride the feature branch and must be applied on the main checkout. It also counts `~/.claude/skills`, so it reports the old count until the new skills are merged and installed.

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
