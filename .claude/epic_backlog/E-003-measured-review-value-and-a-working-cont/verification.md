---
title: "Measured review value and a working context loop"
id: E-003
---

# How we will know E-003 works

Prose for humans. `scripts/epic-check.sh` implements these assertions; the
toolkit never parses this file.

## Assertions

1. With `VAULT_ENGINE` pointing at a failing binary, the first prompt of a session writes exactly
   one line to `errors.jsonl` and prints one "recall is down" context line; a second prompt adds nothing.
   With a working engine it writes one line to `heartbeat.jsonl`.
2. `install.sh` refuses to install a `vault-engine` build whose `context` command exits non-zero.
3. `review-ledger collect` run twice over the same fixture tree reports `0 new, 0 updated` the second time,
   and a 60-day backfill writes a non-zero number of rows to `dispatches.jsonl`.
4. `review-ledger footer-hook` prints the result contract for a reviewer agent type and nothing for any other type.
5. `review-ledger join` writes a non-zero number of rows to `outcomes.jsonl`, and the scorecard prints the
   acted-on rate beside the random-line control.
6. The nightly run appends one line to the recall `metrics.jsonl` in which relevant + off-topic + not-judged
   equals the number of evaluated pairs.
7. The manual promote command publishes one candidate, refuses when the target note exists, and marks the
   draft ledger entry `published`.
8. Every lens name `jev-gate triage-diff` can return resolves to an agent file or a skill directory.
9. `python3 -m unittest discover -s tests` and the engine `pytest -q` both pass.
