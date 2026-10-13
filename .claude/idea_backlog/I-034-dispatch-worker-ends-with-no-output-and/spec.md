---
title: "dispatch-worker ends with no output and no reason on a read-only task"
id: I-034
status: idea
---

# dispatch-worker ends with no output and no reason on a read-only task

## Problem

On 2026-10-13 four `dispatch-worker --agent agy` runs were asked to read review notes
and code, then write one markdown table. All four ended `Status: VERIFY_FAILED (exit
13)` with `Files Modified: 0`. The result file did not exist, and the report held no
worker text at all: nothing about what the worker did, tried, or refused.

The four runs (cwd was the `_release` worktree each time, `--timeout 3600`):

- Runs 1 and 2: asked to write the result to a path outside the cwd. No file.
- Runs 3 and 4: same task, result path inside the cwd and passed as `--output-file`.
  No file.

Quota was not the cause: the report line showed about 97% of the 5-hour allowance and
95% of the weekly allowance left. The same two tasks then finished in about two
minutes each as Claude subagents.

Two separate faults are possible and neither was investigated:

1. The worker did nothing, or failed early, on this kind of task.
2. Whatever the worker did, the report dropped it: `Last Output` only repeated the
   verify command's own error, so the caller had nothing to act on.

## Why now

The global rules send bulk mechanical work to this tool first. A failure that gives no
reason costs a full retry each time and pushes the work back onto Claude quota.

## Sketch

Reproduce with a tiny read-only task (read one file, write a one-line result). Keep
the worker's own final message and exit code in the report, apart from the verify
output. Find out whether the worker can write outside its cwd, and say so in the help.

## Acceptance criteria

- [ ] A read-only task with `--output-file` inside the cwd produces that file, or the report states the worker's own error.
- [ ] When the worker produces nothing, the report shows the worker's exit code and its last lines of output, separate from the verify command's output.
- [ ] `dispatch-worker --help` states whether a worker may write outside `--cwd`.

## Update (2026-10-13)

A fix to this tool landed on main the same day, after the four failed runs: "wait blocks
until the job ends; zero-change unverified runs are not SUCCESS" (pull request 39). It was
not re-tested against this problem. Check first whether it already covers any of the
criteria above.
