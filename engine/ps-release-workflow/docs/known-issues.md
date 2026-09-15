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
- **No schema version on any artifact.** `.release.json`'s `version` is the release number, not a schema version. Deferred to the same spec.

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
