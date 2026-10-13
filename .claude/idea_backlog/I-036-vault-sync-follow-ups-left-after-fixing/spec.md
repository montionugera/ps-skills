---
title: "Vault sync follow-ups left after fixing the 32 review findings"
id: I-036
status: idea
---

# Vault sync follow-ups left after fixing the 32 review findings

## Problem

Reviewers of F-025 (fix the 32 open vault sync review findings) found these smaller items. None blocked the merge. All paths are under `tools/vault-engine/`.

Behaviour:
- An annotated tag sent as the new tip passes the hub's ancestor check. Git then refuses it, but the place's daily allowance is still charged (`pkg/vaultsync/hub.go`, near line 203). `README.md` line 82 words the refusal as unconditional.
- `Begin` refuses a save when only the folder sync failed after the file was already written (`pkg/vaultsync/recover.go`, near line 107).
- `chargeDaily` swallows the folder-sync error without logging it.
- The wider leak of git location variables (GIT_DIR and friends) outside the test fixture was left for later (finding A14 stayed as worded).

Tests:
- The build test allows itself 15 minutes, more than the harness quick round's 10-minute limit (`pkg/vaultsync/build_release_test.go`, near line 38). It should use `t.Deadline()`.
- The folder-sync branches of undo and `Begin` have no test.
- The hub type-check tests do not clear git location variables.
- A test helper discards stderr (`pkg/vaultsync/repo_test.go`, near line 148).
- Finding A9 has no regression test.
- `waitingForFolderLock` matches any goroutine; `cancelledAt` / `closedWhen` have clean-up gaps.

Wording:
- `README.md` line 61 and `pkg/vaultsync/syncer.go` lines 55-57 claim slightly more than the code does.

## Why now

The notes that list these live in the F-025 backlog folder (`.claude/refined_backlog/F-025-.../reviews/`). They are easy to forget once release 1.12 is promoted.

## Sketch

Triage each item: fix, or close with a written reason. The annotated-tag charge and the `Begin` refusal are the two that change behaviour; do those first.

## Acceptance criteria

- [ ] An annotated tag sent as the new tip is refused before the daily allowance is charged, with a test.
- [ ] A save is not refused when only the folder sync failed, or the refusal is documented as intended, with a test either way.
- [ ] The build test cannot outlive the test run's own time limit.
- [ ] Every other item above is fixed or closed with a written reason.
