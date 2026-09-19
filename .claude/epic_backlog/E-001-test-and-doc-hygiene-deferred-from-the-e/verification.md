---
title: "Test and doc hygiene deferred from the epic-run review"
id: E-001
---

# How we will know E-001 works

Prose for humans. There is NO `scripts/epic-check.sh` in ps-skills, so nothing runs automatically; the toolkit never parses
this file and the human ticks these by hand after the chain. Trust `rc: null` in the ship result, not the epic catalog status
(`run_and_record` marks the epic `verified` even when the check was skipped).

## Assertions

1. `git -C <_release worktree> log release/1.1` shows exactly three new slice commits after the epic/idea commits, and nothing was pushed.
2. `cd <_release worktree>/engine/ps-release-workflow && python3 -m pytest tests -q` reports `468 passed, 2 skipped`.
3. `grep -rn "def _git" engine/ps-release-workflow/tests/` prints nothing; the refine SKILL grep in S3 criterion 1 prints nothing.
4. `git diff --stat <release head before the pilot> release/1.1` touches no path under `engine/ps-release-workflow/scripts/`
   or `engine/ps-release-workflow/lib/`.
