---
title: "vault recall precision: skip automated prompts, fix rule-only summaries, down-weight generic terms"
id: F-028
status: refined
from_idea: I-041
---

# Vault recall precision (follow-up to F-027, slice 1 of I-039)

Owner's goal, verbatim: "want it help auto save knowledge + auto retrieve knowledge to session", "make sure it is token efficient", "consider speed , session result, knowledge reusability , scale , robust, production grade", "visibility + readiness", "auto integrate + publish if pass".

This feature serves "auto retrieve" and "token efficient" only. Speed is kept by the existing 50 ms benchmark (I-039 R2p). The lasting check on session result is the usage loop of slice 3 (I-039 R14/R15), not this feature.

## Problem (measured 2026-11-11, the day slice 1 went live)

Automatic retrieval finds the right note on focused prompts (private recall set: 23/25). On real traffic most of what it injects is off topic.

1. **Automated prompts trigger the hook.** Background-task notifications (text starting with `<`) reach the hook as prompts. Seen twice in live sessions: each notification injected 3 unrelated notes and used up the session's 6-note budget.
2. **11 of the 27 index summaries are `---`.** Those notes open with headings and then a horizontal rule. `SummaryLine` skips blanks and headings only, so the rule becomes the summary.
3. **Word overlap does not tell relevant from off topic.** The last 300 typed prompts were replayed through `context --query`: 70 inject at least one note, 164 notes in all. An in-session reviewer labelled all 451 prompt-note pairs that pass today's threshold before any rule was tried: 48 are relevant. Of the 164 injected notes, 39 are relevant (23.8%).
4. **Long prompts are the worst case.** 25 of the 300 prompts have more than 80 terms (handoff documents). They produce 290 of the 451 pairs, and 8% of those are relevant. A long text matches some title word of almost every note.

No single feature of today's score separates the two groups (score, number of title matches and matched-term count are each at most 25% relevant in their best band), so raising the threshold alone tops out near 29% precision.

## Requirements

- P1. When the prompt starts with `<` after leading whitespace, the hook shall emit nothing and exit 0 without calling the engine or creating session state.
- P2. When the engine derives a note summary, it shall skip blank lines, headings, horizontal rules (`---`, `***`, `___`) and fenced code blocks (the fence lines and everything between them), and use the first remaining line. After `rebuild-index` on the real vault no summary is a rule.
- P3. When `context --query` scores a query, the engine shall:
  - a. take the query terms as today; where there are more than 80, keep only the first 20;
  - b. then drop terms made only of digits and terms in the query noise list (Appendix A). The list applies to queries only; index terms are not changed;
  - c. where the index holds at least 20 active notes, weight each matched term by note rarity, `field weight × ln((N+1)/(df+0.5)) / ln((N+1)/0.5)`, with field weight 3 for title, 2 for tag, 1 for body, `N` the number of active notes and `df` the number of active notes that contain the term in title, tags or body, and return a note when its score is at least 2.5 and at least one title or tag term matched;
  - d. where the index holds fewer than 20 active notes, score as today (weights 3/2/1, threshold 4).
- P3h. The hook shall inject at most 2 notes for one prompt and ask the engine for 2 (`--limit 2`).
- P3s. While the index holds 2,000 notes, `context --query` shall still complete in at most 50 ms at p95 (the existing Go benchmark).
- P4. `tools/vault-engine/precision_eval.sh <set.jsonl> <min_percent>` shall run each line's prompt (first 2,000 characters) through `context --query --limit 2`, count an injected note as relevant only when its id is in that line's `relevant_ids`, print injected, relevant and the percentage, and exit non-zero below `min_percent` or when nothing is injected. `recall_eval.sh` shall use the same limit of 2.
- P5. Pass, measured with the installed engine after `rebuild-index`: `recall_eval.sh ~/.claude/state/vault-recall/recall_set.jsonl 21` and `precision_eval.sh ~/.claude/state/vault-recall/precision_set.jsonl 80` both exit 0. If both cannot hold, report the numbers; do not edit either set.

## Acceptance criteria

- [ ] Given a hook payload whose prompt is `<task-notification>…`, when the hook runs, then it prints nothing, exits 0 and creates no file in the state directory.
- [ ] Given a note body of two headings, a `---` line and a prose line, when `SummaryLine` runs, then it returns the prose line; given a body that opens with a fenced block, it returns the first line after the block.
- [ ] Given a 20-note test index where one title word is in every title and another is in one title, when a query holds both words, then only the note with the rare word is returned.
- [ ] Given a query of 100 terms whose only matching term is the 50th, when `context --query` runs on a 20-note index, then nothing is returned.
- [ ] Given a query whose only matching terms are `2026` and a noise-list word, then nothing is returned.
- [ ] Given an index of fewer than 20 notes, the existing `context` tests pass unchanged apart from queries that relied on a noise word.
- [ ] The Go benchmark at 2,000 notes stays at or under 50 ms.
- [ ] P5 on the real vault.

## Expected result and its cost

Simulated with an exact copy of the scorer (`precision_sim.py` in this folder; it reproduces the live engine on all 25 recall prompts and on the 70/164 replay):

| Rule | Recall set | Prompts that inject (of 300) | Notes injected | Relevant | Precision | Prompts given a relevant note |
|---|---|---|---|---|---|---|
| Today | 23/25 | 70 | 164 | 39 | 23.8% | 28 |
| P3 + P3h | 21/25 | 14 | 17 | 15 | 88.2% | 12 |

The price of precision is coverage: 32 of the 300 prompts have a relevant note, today's rule reaches 28 of them and the new rule 12. Recall sits exactly on its floor of 21. Three constants set this trade and each moves the result smoothly: threshold 2.25 gives 71% precision with the same 15 relevant notes, 2.75 gives 94% but recall 20/25; a noise list cut at 3% of prompts instead of 2% gives 71%; injecting 3 notes instead of 2 gives 75%. The long-prompt limit is flat between 40 and 100 terms and the head size between 10 and 40. Split in halves, precision is 83% and 91%.

Sample size is small (17 injected notes), so 88% carries a wide margin; the installed engine is measured again under P5.

## Rollout

`vault-recall.py` is a symlink into the `_release` worktree, so the hook change is live when the feature merges. The engine is a copied binary: build it, replace all three copies by copy-then-rename (`~/.local/bin`, `~/.gemini/antigravity-cli/bin`, `~/workspace/agentic-vault/_meta/bin`), run `vault-engine rebuild-index`, then run P5. Undo: restore the `*.bak` binaries and revert the merge. After a background task finishes in a live session, `injections.jsonl` must show no new line for that session.

## Non-goals

Thai prompts (matching stays ASCII-only), the usage-based demotion loop (slice 3, R14/R15), the session limits (6 notes, 2,400 bytes), any LLM call at prompt time (I-039 slice 1 is "no LLM calls", hook p95 150 ms), the SessionStart `--cwd` block.

## Known limits

- The noise list is a fixed list taken from the owner's typed prompts on 2026-11-11. It ages as projects change. Re-run `precision_eval.sh`; regenerate the list with `precision_sim.py noise` when precision falls under 80%.
- The threshold 2.5 was chosen at 27 notes. Rarity weights shift as the vault grows (slice 2 adds notes nightly), so both eval scripts are the re-tuning gate.
- The replay covers typed prompts only. Task notifications, subagent briefs and pasted text stored as placeholders are not in `history.jsonl`.
- The labels come from one strict reviewer in one pass, with no second opinion.

## Appendix A: query noise list

Every term of 4 or more characters typed in at least 2% of 8,370 prompts, minus two personal names (77 words):

```
action agent already asset audits auto bash begin between branch build claim claude command conduct constraints context continue create data date decisions deploy design document dont echo epic execute file first focus full handoff help historical image immediate improve inline instructions lines local logs main next null objective original override owner past pasted picture plan quant read release repos review section ship spec steps stop studio task test text toward transitioning user users without work workspace worktree
```

## Appendix: audit trail

- 2026-11-11 self-grill-audit: verdict safe-with-fixes. Corrected: P3 replaced (the note-share rule could not reach the words it named and failed the recall floor at every share that helped; the "two title-or-tag terms" alternative scored 19/25); P4 given a script, labels frozen before any rule was tried, an unlabelled injected note counts as off topic; long prompts given a requirement (P3a); problem 2's cause corrected (headings then a rule, not a leading rule); fenced blocks spelled out; rollout steps and goal coverage added; replay script saved with what it does not cover. Open: none that blocks. The owner has not reviewed this spec; the coverage cost above is the point to look at.
