# ps-commu-explain speed quick wins: single Chrome run, scripted content skeleton, reader-prompt and handoff scripts, cheaper verify subagents, auto-lint hook — research notes

(prior art, related issues, open questions)

## Findings (2026-09-30 pipeline map; timings from script comments, not yet measured)

Take a baseline first: time one full default-tier run before changing anything.

- **Chrome launches twice per verify cycle.** Asserts and `--dump-text` each start their own headless Chrome (`--dump-dom`), at ~45s each on macOS (skills/ps-commu-explain/scripts/verify.sh:235-247, :75, :227). Get both from one page load. Saves ~45s per cycle, up to ~4 min over 5 fix cycles.
- **Model reads and deletes the 281-line exemplar** `assets/template-infographic/content.md` on every run (SKILL.md:46). Generate a `content.md` skeleton from `02-storyboard.md` + `01-facts.md` instead: section headings, Q mapping, F<n> placeholders, Receipts footer.
- **`references/components.md` is 571 lines.** Add a ~40-line index (class to snippet); load the full file only when needed.
- **Reader-gate prompt is pasted together by hand** (SKILL.md:75-106). Add `verify.sh --reader-prompt` to print the filled prompt. Script the handoff (URL, questions, `list.sh` output, re-serve command) the same way.
- **Duplicate lint.** `serve.sh` re-runs lint (scripts/serve.sh:37-45) right after the model has already run it.
- **Built-ins:** run the reader and screenshot subagents on Haiku or Sonnet at effort low. Add a PostToolUse hook that runs lint when `content.md` is written.
- **Not worth it:** verifying while the page is still being written. The check needs the finished page.
- **Stale docs:** lint.sh:22-36 still describes the Mermaid scanner, which drawio replaced (lint.sh:198).
