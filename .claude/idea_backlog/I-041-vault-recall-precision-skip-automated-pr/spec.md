---
title: "vault recall precision: skip automated prompts, fix rule-only summaries, down-weight generic terms"
id: I-041
status: idea
---

# Vault recall precision (follow-up to F-027, slice 1 of I-039)

Owner's goal, verbatim: "want it help auto save knowledge + auto retrieve knowledge to session", "make sure it is token efficient".

## Problem (measured 2026-11-11, the day slice 1 went live)

Automatic retrieval works on focused prompts (private recall set: 23/25, 18 of 20 recall prompts, 5 of 5 silent prompts). On real traffic it injects too much that is off topic:

1. **Automated prompts trigger the hook.** A background-task notification (prompt text starting with `<task-notification>`) made the hook inject 2 unrelated notes into a live session. Long machine-written prompts (handoff documents) behave the same way. Not yet verified: that the hook payload's `prompt` field carries this exact text; the session transcript does.
2. **11 of the 27 index summaries are `---`.** Notes whose body starts with a horizontal rule get that rule as their summary, so the injected line says nothing about the note.
3. **Generic words score.** Replaying the last 300 typed prompts from `~/.claude/history.jsonl` through `vault-engine context --query` (local only): 70 prompts (23%) would inject at least one note, 41 of them the full 3. The most frequent matched terms include `build`, `2026`, `owner`, `work`, `decisions`, `release`, `already`, `full`, `main`, `spec`, `context`, `local`, `repo`, `auto`. A title made of common development words (for example "… Build Pipeline Design Spec") gives 3 points per word, so two everyday words pass the threshold of 4. Of the first 5 live injections, 4 were off topic.

Cost today is bounded by the session limits (6 notes, 2,400 bytes), but early off-topic notes use up the session budget, so later relevant prompts get nothing.

## Requirements

- P1. When the prompt starts with `<` (after leading whitespace), the hook shall emit nothing and exit 0 without calling the engine or creating session state.
- P2. When the engine derives a note summary, it shall skip blank lines, horizontal rules (`---`, `***`, `___`), headings and code-fence lines, and use the first remaining line. After `rebuild-index` on the real vault, no summary is a rule.
- P3. When scoring a query, a term that occurs (title, tags or body terms) in more than a set share of the indexed notes shall score 0. The share is chosen on the labelled set below and written as one constant; it applies only when the index holds at least 20 notes, so small test vaults keep today's behaviour.
- P4. Precision is measured before and after on a private labelled set at `~/.claude/state/vault-recall/precision_set.jsonl`: the prompts from the 300-prompt replay that inject today, each labelled relevant or not by an in-session reviewer (no external send), plus the existing 25-prompt recall set. Pass: the recall set still scores at least 21/25, and at least 80% of the injected notes on the labelled set are relevant. If both cannot hold, report the numbers; do not edit the sets to fit.

## Non-goals

Thai prompts (matching stays ASCII-only), the usage-based demotion loop (slice 3, R14/R15), any change to the byte and note limits.

## Open

- Whether P3 should instead require two distinct title-or-tag terms. Decide on the labelled set, pick the simpler rule that passes P4.
