---
title: "vault-recall precision measure goes stale when the vault grows"
id: F-031
status: refined
from_idea: I-044
---

# vault-recall precision measure goes stale when the vault grows

Owner's goal, verbatim: "want it help auto save knowledge + auto retrieve knowledge to session", "make sure it is token efficient", "consider speed , session result, knowledge reusability , scale , robust, production grade", "visibility + readiness".

Follow-up to F-028 (slice 1 of I-039). Written by the agent on 2026-11-11; not owner-reviewed yet.

## Problem (measured 2026-11-11)

`tools/vault-engine/precision_eval.sh` replays 300 frozen prompts and counts an injected note as relevant only when its id is in that prompt's `relevant_ids`. A note that did not exist when the set was labelled can never be in `relevant_ids`, so every injection of a new note counts as off topic.

| Index | Engine | Script result |
|---|---|---|
| 27 active notes (11:55) | F-028 build | 15/17 = 88.2% PASS |
| 29 active notes (19:26) | same binary | 7/23 = 30.4% FAIL |

What the 23 injections at 29 notes are:

- 7 relevant, 2 off topic (both judged pairs).
- 14 are the two new notes (9 and 5 injections). None of these pairs had been judged.

What happened to the 8 relevant injections that disappeared:

- 7 are still above the threshold and were pushed out of the top 2 by a new note.
- 1 fell below the threshold (3.03 to 2.42) because the rarity weights moved.

Two checks on the scoring rule itself:

- With the 29-note weights and the two new notes skipped before the top-2 cut: 14/16 = 87.5%. The rule did not degrade on the notes it was tuned on.
- The 14 new pairs were then labelled by one reviewer with the F-028 rule, without scores or matched terms: 10 relevant, 4 not (all 4 from one note, on prompts that share its project words but not its task). With these labels the live result is **17/23 = 73.9%**.

So there are two findings:

1. **The measure is wrong as soon as a note is added.** It reported 30.4% when the judged figure is 73.9%. Slices 2 and 3 add notes without anyone watching, so the gate would fail every time and say nothing useful.
2. **Real precision is 73.9%, under the 80% gate**, on 23 injections. Two more relevant injections would pass it. All 4 new misses come from one note. This is too small a sample to re-tune on, and re-tuning needs a valid measure first.

Also found: the per-pair record of which pairs were judged lived only in `precision_candidates.json`, which the recall hook deletes after 7 days. It was copied on 2026-11-11 to `precision_judged.jsonl` (451 pairs, read-only, ids and row numbers only). The 14 new labels are in `precision_labels_extra.jsonl`. Both are private state files next to the frozen set. The frozen set was not changed.

## Why now

- F-029 (slice 2) is live in shadow mode and I-043 (slice 3) will publish notes nightly. Each published note breaks the gate under today's script.
- I-043's calibration needs a trustworthy "did recall get worse" signal before it can publish without a person.
- F-028's pass condition P5 is a check a person runs by hand; Gate 1, Gate 2 and CI do not run it (the labelled set is private). Today it reads FAIL for a reason that is not the engine's, so nobody can tick it honestly.
- F-028's known limits say to regenerate the noise list when precision falls under 80%. The judged figure is 73.9%, so that rule applies now; see open question 4.

## Sketch

Keep the frozen set. Change what the script counts, and add a cheap way to label new pairs.

1. **Three outcomes per injected pair, not two.** `precision_eval.sh` takes the judged-pairs file and the extra-labels file. A pair is *relevant*, *off topic*, or *not judged*. Precision = relevant / (relevant + off topic). Not-judged pairs are counted and printed, never scored.
2. **A stale measure fails loudly and differently.** When not-judged pairs are more than a set share of the injections (proposed: 20%), the script exits with a separate code and says how many pairs need labels. An engine crash gets a third code: today `check=True` makes a crash exit 1, the same as FAIL. Then FAIL means "the engine got worse", STALE means "label these", and ERROR means "the run did not happen".
3. **Labelling new pairs.** A small command lists the not-judged pairs and sends each (prompt head, note summary) to Jev with the F-028 rule, then appends the answers to the extra-labels file. Jev calls are cheap by the owner's ruling. The first run must agree with the 14 reviewer labels and a sample of the 451 judged pairs before its labels are trusted.
4. **Readiness.** `ps-skills-doctor` runs the script itself when the private set exists (measured: 1.7 s, no model call) and reports the figure and the not-judged count. No result file and no extra schedule are needed for visibility.
5. **Trigger and budget for labelling.** The nightly `vault-distill` run calls the labelling command after its own work, so labels exist before anyone looks. Only injected pairs are labelled (at most 2 per prompt; 23 pairs today), not every note against every prompt, and one run makes at most 50 Jev calls. With that order, STALE means the labelling step failed or hit its cap.

Not in this idea:

- Changing the scoring rule or the threshold. That is a separate decision once the measure is valid and has more than 23 injections behind it.
- Adding prompts to the frozen 300. The set stays as it is; only pair labels grow.

## Requirements

- M1. When an injected pair has no label, the script shall count it as not judged and shall leave it out of the precision figure.
- M2. When not-judged pairs exceed the stale share, the script shall exit with a code different from the FAIL code and print the count.
- M3. The script shall print relevant, off topic, not judged and the precision figure on one line.
- M4. The labelling command shall append labels to the extra-labels file and shall not write to `precision_set.jsonl`, `precision_judged.jsonl` or `recall_set.jsonl`.
- M5. The labelling command shall send a prompt to Jev only after the same credential scan that `vault-distill` applies to digests.
- M6. Before its labels are used, the labelling command shall be compared with the existing reviewer labels, and the agreement figure shall be recorded in research.md.
- M7. No committed file shall contain a note id, a note title or prompt text.
- M8. When the engine exits non-zero, the script shall exit with a third code and print the engine's error text.
- M9. One labelling run shall make at most 50 Jev calls and shall report how many pairs it left not judged.
- M10. The labelling command shall write `.jsonl` files only (the recall hook deletes `*.json` older than 7 days in that directory).
- M11. `ps-skills-doctor` shall run the script when the private set exists and report FAIL, STALE or ERROR as a warning with the counts.

## Open questions for the owner

1. Is Jev the labeller (cheap, automatic, quality not yet measured), or should an in-session Opus reviewer label new pairs on demand (what was done on 2026-11-11: 14 pairs, 66,000 tokens)?
2. The stale share: 20% proposed.
3. Sending prompt heads to Jev: the standing ruling covers session digests from all repos. This spec assumes prompts fall under the same ruling.
4. Order of work: F-028 says to regenerate the noise list now (73.9% is under 80%). Proposed: fix the measure first, then regenerate and compare on it. Reason: all 4 new misses come from one note matched on its project words, and nobody has tested whether a new noise list removes them.

## Acceptance criteria

- [ ] Given the frozen set, the judged-pairs file and no extra labels, when the script runs against a 29-note index with 14 not-judged pairs out of 23, then it exits with the stale code and prints 14 not judged.
- [ ] Given the same inputs plus the 14 extra labels, when the script runs, then it prints 17 relevant, 6 off topic, 0 not judged, 73.9%.
- [ ] Given a synthetic set where every pair is judged and precision is under the minimum, when the script runs, then it exits with the FAIL code, not the stale code.
- [ ] Given the labelling command and a stubbed Jev reply, when it runs, then only the extra-labels file changes (checked by checksum of the other three files).
- [ ] Given a prompt that fails the credential scan, when the labelling command runs, then no call is made for that pair and it stays not judged.
- [ ] Given the labelling command run on pairs that already have reviewer labels, then the agreement figure is written to research.md.
- [ ] Given a stub engine that exits non-zero, when the script runs, then it exits with the ERROR code and prints the engine's error text.
- [ ] Given 60 not-judged pairs and a stubbed Jev, when the labelling command runs once, then it makes 50 calls and reports 10 left.
- [ ] Given `ps-skills-doctor --strict` with a private set that produces a stale result, then it reports the not-judged count.

## What this change touches

- `tools/vault-engine/precision_eval.sh`: new arguments, three exit codes, new output line.
- `tests/test_vault_recall.py` lines 215 and 219 match today's output string exactly and must change with it.
- `bin/jev-gate`: no labelling subcommand exists; one is added.
- `bin/vault-distill`: one call to the labelling command at the end of the nightly run.
- `bin/ps-skills-doctor`: `check_vault_recall` gains the precision report.
- `README.md` line 222 and `tools/vault-engine/README.md` line 32 describe the old usage.
- Undo: revert the commit. The private label files are append-only and are not touched by a revert.

## Known gaps left open

- `recall_eval.sh` reads 21/25 against a minimum of 21, so it has no margin, and a new note can push an expected note out of the top results in the same way. It is not changed here; it needs the same owner decision as question 4.
- Judged pairs cover 70 of the 300 prompts. A pair that was never injected before is not judged until the labelling command reaches it.
- Labels come from one reviewer (or one Jev call) per pair.

## Appendix: audit trail

- 2026-11-11 self-grill-audit: verdict safe-with-fixes. Headline numbers reproduced by the auditor (7/23 live; 17/6/0 with the extra labels; 14/16 with the new notes skipped; 451 judged pairs). Corrected: an engine crash shared the FAIL exit code (M8 added); readiness had nothing behind it (doctor now runs the script, M11); the "cannot be promoted" claim was wrong, P5 is a manual check (reworded); F-028's re-tune rule applies at 73.9% (stated, open question 4); files touched listed; labelling budget and trigger added (M9, sketch 5); `.jsonl`-only rule added (M10). Not re-checked by the auditor: the 15/17 figure at 27 notes and the 3.03 to 2.42 score change (the 27-note index no longer exists; both come from a re-implementation of the scoring that matched the live engine on the 29-note index). Open: questions 1 to 4.
