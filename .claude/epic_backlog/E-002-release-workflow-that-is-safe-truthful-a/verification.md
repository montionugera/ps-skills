---
title: "Release workflow that is safe, truthful and cheap to run"
id: E-002
---

# How we will know E-002 works

Prose for humans. `scripts/epic-check.sh` implements these assertions; the
toolkit never parses this file.

## Assertions

1. Two sessions with different `CLAUDE_CODE_SESSION_ID` values: session B is blocked from editing a worktree claimed by session A, and `claim --resume` hands it over.
2. A claim made with the legacy shared owner id is accepted with a warning and is listed by `psrw status` as a legacy-owner claim.
3. Cleanup of a promoted release leaves a worktree that has uncommitted edits or commits after its shipped commit in place, reports it, and exits non-zero.
4. An untracked file placed in the main checkout or in the `_release` worktree is not included in any commit made by claim, ship, unclaim or cleanup.
5. Cleanup refuses when local main has commits that are not on origin, and discards nothing.
6. After install, no lock files exist under the temp directory; all state locks are under `~/.cache/psrw/locks`.
7. During a promote, `psrw idea`, `refine`, `claim` and `epic` refuse with a hint to retry after cleanup.
8. With `--babysit`, the commit that is merged is the commit the checks ran on.
9. A release that is finalized but not merged can still take main in through `psrw sync-main`.
10. A second Gate 1 run on an identical tree is skipped with a visible "cached pass" line; `PSRW_GATE_CACHE=0` forces a real run.
11. For a finalized release whose pull request is open, `psrw status` names that version and says to merge the pull request; it never suggests cleaning up an older version.
12. `psrw full-promote` takes a release from promote to an open next release in one invocation.
13. No user-facing message names `promote_release.py`; every hint uses a `psrw` verb.
