---
title: "ps-commu-explain speed quick wins: single Chrome run, scripted content skeleton, reader-prompt and handoff scripts, cheaper check subagents"
id: I-018
status: idea
---

# ps-commu-explain speed quick wins

## Problem

A default (infographic) explainer spends much of its wall-clock time on work that is not judgment:

- **Two headless-Chrome launches per verify cycle.** `verify.sh <slug>` (asserts) and `verify.sh <slug> --dump-text` (reader-gate input) each start Chrome. The script comment puts each at ~45s on macOS (`skills/ps-commu-explain/scripts/verify.sh:235-247`). With up to 5 fix cycles (`SKILL.md` subagent budgets), that is up to ~4 extra minutes.
- **The model reads and then deletes a 281-line exemplar.** `app/content.md` ships pre-filled (`SKILL.md:46`), so every run starts by replacing it.
- **The model reads the 571-line `assets/template-infographic/components.md`** to find component snippets.
- **The model assembles mechanical text by hand:** the reader-gate prompt (Reader line, Q1-Q3 and page text pasted into the verbatim prompt, `SKILL.md:75-106`) and the final handoff (URL, questions, `list.sh` output, commands, `SKILL.md:110`).
- **Check subagents inherit the main model** (Opus), even for mechanical render and screenshot checks.
- **SKILL.md (138 lines) carries long reference paragraphs,** e.g. the 8-assert description at `SKILL.md:69`, and the model reads it on every run.

No run has been timed; the numbers above come from script comments.

## Why now

The component-system spec (`docs/superpowers/specs/2026-07-16-ps-commu-explain-component-system-design.md`) is the large, long-term fix and hasn't been started. These quick wins are small, independent script changes that pay off right away. The diagram-format idea (I-019) is separate and targets the biggest single cost, hand-written drawio XML.

## Decisions (batch-grill, 2026-09-30)

- Check-subagent model → **Haiku for render/screenshot checks, Sonnet for the reader gate.** Render checks are mechanical; the reader gate judges comprehension.
- Auto-lint PostToolUse hook → **not added.** `serve.sh` already runs `lint.sh` before serving; a hook would lint half-written drafts on every save.
- content.md skeleton → **the default.** The exemplar moves to `app/example-content.md` and stays available through `init.sh --example`.
- components reference → **a ~40-line index read up front;** the full file stays for detail.
- Baseline → **per-script timing log** (default, not asked). Compare one run before and one after.
- SKILL.md trim → **move long reference paragraphs into the scripts' `--help`** (default, not asked).
- Approach → **extend the existing scripts**, not a single do-everything `check.sh`. Each gate still fails visibly on its own.

## Design

```mermaid
flowchart LR
  B[00-brief + 01-facts + 02-storyboard] --> S[skeleton.sh writes content.md]
  S --> A[model fills sections]
  A --> V[serve.sh lints, then verify.sh: one Chrome load]
  V -->|asserts + page-text.txt| R[verify.sh --reader-prompt]
  R --> G[Sonnet reader subagent]
  G --> H[handoff.sh + model adds answers]
```

### 1. One Chrome load per verify cycle (`verify.sh`)
- A plain `verify.sh <slug>` run (infographic tier) also writes the clean page text to `<workspace>/page-text.txt`. It uses the same `--dump-dom` output the asserts already parse, and the same text extraction `--dump-text` uses today.
- `--dump-text` stays and keeps its output unchanged (backward compatible).
- Both modes already use the same `--dump-dom` DOM and the same `Preview().text` extractor (`verify.sh:367-378`). `--dump-text` is re-implemented as "run the one load, print `page-text.txt`", so both share one code path.
- Stale-text guard: `page-text.txt` is deleted at the start of each run. It is written only when the extracted text is non-empty, and never under `--url` (which may load a different doc).
- html and react tiers: no change (`--dump-text` is already unsupported on html).

### 2. Reader-gate prompt from a script (`verify.sh --reader-prompt`)
- Prints the reader-gate prompt from SKILL.md, filled with the `Reader:` line and Q1-Q3 from `00-brief.md` and the **absolute path** to `page-text.txt`, NOT its contents. The reader subagent reads the file itself, so the main model never re-types the page (output tokens are the slow part). The prompt tells the subagent to read that one file only. This isolation is prose-enforced, the same as today's "never give it the brief/facts" rule. The script never launches Chrome.
- Exits 2 with a clear message if `page-text.txt` is missing ("run verify.sh <slug> first").
- The verbatim prompt text moves out of SKILL.md into this script, which becomes the single source. SKILL.md points to the script.

### 3. content.md skeleton (`scripts/skeleton.sh <slug>`)
- Reads `02-storyboard.md` and `01-facts.md` and writes `app/content.md`: one heading per storyboard row, a plain-markdown placeholder line per section: `TODO(Q2; F3,F7): <storyboard section text>` (NOT an HTML comment; Cherry renders `<!--` as literal page text, `verify.sh:188-190`), and a Receipts footer built from the cited fact rows.
- Refuses to run if `app/content.md` already exists, unless given `--force`, so it never destroys authored work.
- `init.sh` still copies the template folder with `cp -R` (`init.sh:74-78`), then on the default infographic path moves `app/content.md` to `app/example-content.md`. Under `--example` it leaves `content.md` in place. `index.html`'s `KNOWN_DOCS` (`content.md`) needs no change because the skeleton writes that name.
- `lint.sh` today treats a missing `content.md` as fine (`lint.sh:84,184`; needed for html/react). New: when `meta_get <slug> tier` is `infographic`, a missing `app/content.md` is a defect: "missing app/content.md: run skeleton.sh <slug>". `serve.sh` inherits this through its lint gate. `init.sh --example` keeps today's behavior (exemplar as `content.md` plus the matching brief, facts and storyboard).
- `lint.sh` (infographic tier) rejects any remaining `TODO(` line. An unfilled skeleton therefore cannot be served, and the check is enforced by the gate, not by prose.
- Once its `TODO(` lines are replaced with any cited prose, the skeleton passes lint. Its structure (headings, Receipts footer) never causes a lint defect.

### 4. Components index
- A new `assets/template-infographic/components-index.md` (≤40 lines): one line per component **section** (each `id=` block in `components.md`, e.g. `components.md:10,20,40`). Each line lists the classes that section covers and the grep string to find it (the Read tool can't jump to HTML anchors).
- SKILL.md Stage 4 says to read the index first, then `grep -n` into `components.md` for the one section it needs.
- A test asserts that every `id=` section in `components.md` appears in the index, so the two can't drift apart.

### 5. Handoff script (`scripts/handoff.sh <slug>`)
- Prints the URL, Q1-Q3, `list.sh` output, the cleanup hint (`clean.sh` / `stop.sh <slug>`) and the re-serve command. The model adds only the reader-gate answers.

### 6. Check-subagent models (SKILL.md subagent budgets)
- Infographic render check: `verify.sh <slug>` runs in the **main thread**. Its output is about 8 PASS/FAIL lines, so a subagent there adds latency and saves nothing. Drop that subagent.
- html/react screenshot and console subagents: `model: haiku`.
- Reader-gate subagent: `model: sonnet`. `--reader-prompt` prints `Agent model: sonnet` as its first line so the value sits next to the prompt being pasted. It is still prose-enforced: the Agent tool's `model` param is only set if the main model passes it (rule 11 caveat, accepted).
- Facts subagents are unchanged (out of scope).

### 7. Timing log (`common.sh`)
- A helper `log_timing <script> <seconds>` appends `ISO-time script seconds` to `<workspace>/timings.log`. It is called by `init.sh`, `serve.sh`, `verify.sh`, `skeleton.sh` and `handoff.sh`.
- The log records script time only. Model time shows up as the gaps between entries.

### 8. SKILL.md trim
- Move the 8-assert description (`SKILL.md:69`) and the reader-gate verbatim prompt into the scripts' `--help` and the reader-prompt output. Keep one line per gate in SKILL.md.
- Update stale comments: `lint.sh:22-36` (still describes the Mermaid scanner) and `serve.sh:7-9` (the `--no-lint` note about content.md not yet being lint-clean).
- Target: SKILL.md ≤ 110 lines, with every rule the lint and verify gates enforce still stated.

### Error handling
- Every new script follows the existing conventions: `--help` from the header comment, exit 0 on success, exit 1 on a defect, exit 2 when a precondition is missing (no workspace, no Chrome, no page-text).

### Out of scope
- The diagram format and auto-layout (I-019).
- The declarative page renderer (2026-07-16 component-system spec).
- The html and react tier authoring flows.
- Facts-gathering subagents.

## Acceptance criteria

- [ ] One `verify.sh <slug>` run on an infographic page prints all assert results AND writes a non-empty `page-text.txt` with one Chrome launch. `--dump-text` prints that same file via the same code path (test in `tests/lifecycle_test.sh`, counting Chrome launches through a stub or wrapper).
- [ ] A verify run whose Chrome load fails, or that runs under `--url`, leaves no `page-text.txt` behind (test).
- [ ] `verify.sh <slug> --reader-prompt` prints the prompt with the Reader line, Q1-Q3 and the absolute `page-text.txt` path (not its contents), starts no Chrome process, and exits 2 when `page-text.txt` is missing (tests).
- [ ] `skeleton.sh <slug>` on the `init.sh --example` brief, facts and storyboard produces a `content.md` with one `TODO(` line per storyboard row. `lint.sh` rejects it until they are filled, and accepts it once each `TODO(` line is replaced with cited prose (test). No `<!--` appears in the output (test). It refuses to overwrite an existing `content.md` without `--force` (test).
- [ ] `init.sh <slug>` writes no `app/content.md` and puts the exemplar at `app/example-content.md`, and `init.sh --example <slug>` behaves as today. `test_verify_passes_template` and `test_verify_dump_text` (`lifecycle_test.sh:1177-1210`), which assume a plain init ships `content.md`, switch to `init.sh --example`. On the infographic tier, `lint.sh` flags a missing `content.md` (test).
- [ ] `components-index.md` is ≤40 lines and names every `id=` section in `components.md` (test).
- [ ] `handoff.sh <slug>` prints the URL, Q1-Q3, `list.sh` output, the cleanup hint and the re-serve command (test).
- [ ] SKILL.md runs the infographic `verify.sh` in the main thread, uses `model: haiku` for html/react screenshot/console subagents, and uses `model: sonnet` for the reader gate.
- [ ] SKILL.md is ≤110 lines, and `lint.sh --help` no longer mentions the Mermaid scanner as the infographic diagram check.
- [ ] `timings.log` gets one line per script call.
- [ ] Before/after evidence: one baseline run (timed by hand with `time` per script plus total wall clock, since `timings.log` doesn't exist yet) and one post-change run of the same explainer topic, with `timings.log` and the total wall time recorded in the feature's verification notes. The post-change run has one Chrome launch per verify cycle.
- [ ] `tests/lifecycle_test.sh` passes in full; README's ps-commu-explain row mentions the new scripts.

## Rollout note

`~/.claude/skills/ps-commu-explain` is a symlink to the **main** checkout (`/Users/pasitnusso/ps-skills/skills/ps-commu-explain`). These changes reach the live skill only after release 1.9 is promoted to main. All changes are R2 and revertable with git.

## Appendix — audit trail

- 2026-09-30 self-grill-audit: verdict safe-with-fixes. Corrected:
  - Skeleton placeholders changed from HTML comments (rendered as literal text) to `TODO(` lines that lint rejects.
  - The two lifecycle tests that assume a plain init ships `content.md` switch to `--example`.
  - lint now flags a missing `content.md` on the infographic tier.
  - `--reader-prompt` passes the page-text file path instead of pasting the page text, so the model doesn't re-type it.
  - init renames the exemplar after `cp -R`.
  - The infographic render check drops its subagent.
  - The components index is per section, not per class, so it fits ≤40 lines.
  - The Chrome-launch test is per-run instead of comparing two loads; `page-text.txt` is not written under `--url`.
  - The baseline is timed by hand.
  - Stale `serve.sh` comment added.
  - Open: none (the prose-only `model:` choice is accepted as a known limit).
