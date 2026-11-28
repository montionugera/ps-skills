---
title: "Measured review value and a working context loop"
id: E-003
status: epic
---

# Measured review value and a working context loop

Approved by the owner on 2026-11-28. The full design, the measured baseline and the
review record are kept outside this public repo, in the local folder
`~/.local/state/review-ledger/baseline-2026-11-28/` (`spec.md`, section numbers below refer to it).

## Outcome

1. Every Claude subagent dispatch leaves one durable row, and a reviewer's result is
   machine-readable down to the finding (verdict, severity, file and line) without a classifier.
2. For each review seat there is a measured answer to "does it find defects that are known
   to be there", and a nightly join from a report to the fix that followed, printed beside a
   random-line control.
3. Vault recall is alive in interactive sessions, a recall failure is visible in the session
   it happens in, and recall has three nightly numbers: alive, relevant, used.
4. Distilled lessons can reach the vault through a manual promote step.
5. No agent or lens is removed before a rule in section 7.3 fires on measured data.

Not in this epic: automatic publishing of distilled notes, a bridge from auto-memory to
recall, and any measure of external workers (agy, codex).

## Slices

- Recall failure is visible: install guard for `vault-engine`, heartbeat and error record in the `vault-recall` hook, doctor accepts the launchd distill job (plan phase 0, items 2, 3, 5)
- Review ledger and result contract: `bin/review-ledger` with `collect`, `report`, `footer-hook`, `alarm`, tests, install link, README (plan phase 1)
- Context loop measured and closed by hand: F-031 as specified, used-rate check, manual promote command in `vault-distill`, nightly recall metrics line (plan phase 2; reuses F-031 and I-043)
- Reviews joined to fixes: `review-ledger join`, scorecard with controls, hand-audit sampler, `jev-gate` lens record and lens-name resolve test (plan phase 4)

Outside the repo, tracked in the local plan only: the replay benchmark (phase 3) and the
decision rounds every 4 weeks (phase 5).
