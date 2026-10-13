# Handoff: F-025 vault sync review findings

**Goal (verbatim):** fix the 32 open findings from the vault sync review notes, as a feature in release 1.12, tested and reviewed, without changing anything on the main branch.

**Plan:** `.claude/refined_backlog/F-025-fix-the-32-open-vault-sync-review-findin/plan.md` (six tasks, items A1 to A32, each task has a worker brief with a verify command).

**Worktree:** `/Users/pasitnusso/ps-skills/.claude/worktrees/F-025-fix-the-32-open-vault-sync-review-findin` (branch `feat/F-025`).

**Current state:** plan written. No code changed, no commits made. Every code block in the plan was compiled and run against a scratch copy of the module; the five behaviour tests were seen to fail before their fix and pass after.

**Next step:** execute Task 1 (Recovery and undo: A4, A5, A6, A7, A15, A16, A17, A18). Its first step is a grep that must STOP the task if a production caller reaches `Undo` with no marker on disk.

**Open problems:** none. Decided and written into the plan: A5 is narrowed (only a stop is "unknown"; any other failed compare still moves the file aside); A14 stays as worded (the wider `GIT_DIR` fix is listed under "Follow-ups not in this plan"); A8's exit code change from 1 to 6 is accepted, tested in Task 2 and written into the README in Task 6.

**Limits:** never touch `/Users/pasitnusso/workspace/agentic-vault`; do not run `test_e2e.sh`; do not redirect `HOME`; no `git commit --amend`; always `go test -timeout 40m`.
