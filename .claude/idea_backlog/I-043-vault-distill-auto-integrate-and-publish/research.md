# I-043 (I-039 slice 3) research notes

The spec in this folder is the owner-approved I-039 spec, unchanged. Slice 3 covers R10a, R10af, R10b, R10bf, R18 (calibration), R15 (used-rate), R20, R21, the rest of R17, the publish cap and the publish-then-recall end-to-end case. No plan yet (`writing-plans` next).

## Inputs from the slice 2 go-live (2026-11-11)

- First real run, classification only: 718 sessions, 718 Jev calls, 0 failed, 5.05 MB sent, 392 seconds.
- Jev `lesson_prob` is not selective yet. 339 sessions (47%) scored 0.85 or above, 362 (50%) landed between 0.15 and 0.85, and 17 (2%) were dropped. By tenth: 8, 10, 55, 63, 18, 17, 51, 81, 176, 239. The run exited 2 under R16 (more than half unsure). R18 calibration has to fix the cut-offs or the classify prompt before shadow mode can end by itself.
- At 20 extractions a night, the 339 waiting sessions are 17 nights of backlog.
- Extraction and review do not run yet (I-042): the nightly job has `VAULT_DISTILL_MAX=0`.
- Known needs from the slice 2 handoff: `commit --append-body`, a `publish-knowledge` existence check, the R14/R15 usage loop.
