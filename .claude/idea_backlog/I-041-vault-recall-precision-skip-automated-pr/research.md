# I-041 research notes: how the precision rule was chosen (2026-11-11)

All runs are local. Private inputs stay in `~/.claude/state/vault-recall/`; nothing here quotes a prompt or a note.

## Method

1. `precision_sim.py freeze` took the last 300 typed prompts from `~/.claude/history.jsonl` (the hook's own filters: 12+ characters, not starting with `/`) and listed every note that passes today's threshold for each prompt, in shuffled order: 70 prompts, 451 pairs.
2. One in-session reviewer labelled each pair relevant or not from a digest of the 27 notes, without seeing scores or matched terms. Rule given: relevant only when the note bears on the specific task of the prompt; a shared project name or generic word does not count; when in doubt, not relevant. Result: 48 relevant pairs, 32 prompts with at least one.
3. The labels were written to `precision_set.jsonl` (300 lines, `{"prompt", "relevant_ids"}`, read-only) before any rule was tried. A prompt that injects nothing today has an empty list, so any note a new rule injects there counts as off topic.
4. Rules were then scored against that file and the pre-registered 25-prompt recall set.

## What was tried

| Rule | Recall | Injected | Relevant | Precision |
|---|---|---|---|---|
| Today (threshold 4) | 23/25 | 164 | 39 | 23.8% |
| Threshold 6 | 23/25 | 115 | 33 | 28.7% |
| Threshold 8 | 18/25 | 98 | 25 | 25.5% |
| Two title-or-tag terms | 19/25 | 98 | 31 | 31.6% |
| Note-share cut (the first P3) at 30%, the lowest share that keeps 21/25 | 21/25 | 145 | 40 | 27.6% |
| Flat weights, threshold 6, top 2, noise list, long prompts cut | 21/25 | 24 | 14 | 58.3% |
| Flat weights, top 1, long prompts skipped, threshold 6 | 22/25 | 21 | 12 | 57.1% |
| Rarity weights, threshold 2.5, top 2, no noise list | 21/25 | 32 | 19 | 59.4% |
| Rarity weights, threshold 2.5, top 2, noise list, long prompts skipped | 21/25 | 13 | 11 | 84.6% |
| **Rarity weights, threshold 2.5, top 2, noise list, long prompts cut to first 20 terms** | 21/25 | 17 | 15 | 88.2% |

Three things were each needed: weighting by note rarity, dropping words the owner types in 2% or more of prompts, and not scoring the body of a long prompt. Any two without the third stay under 60%.

A trap found on the way: applying the noise list before the long-prompt count drops the result to 38.5%, because handoff boilerplate is mostly noise words and the prompt then no longer counts as long. The count must be taken on the raw terms (P3a before P3b).

## Not done

- No rule that calls a model at prompt time was tried. I-039 fixes slice 1 as "no LLM calls" with a 150 ms hook budget.
- The labels were not double-checked by a second reviewer.
