# F-018 verification notes

## Baseline (before), 2026-09-30, live skill (main checkout @ e5be894)

Topic: How ps-commu-explain's `stop.sh` decides whether it may kill a server. Slug: f018-bench-before.
Timed by hand with `time`; timings.log does not exist yet. Tier: infographic (default). Wall clock 20:41:04 to 20:46:22 local.

| step | real (s) | runs |
| --- | --- | --- |
| init.sh | 0.80 | 1 |
| lint.sh | 0.35 | 1 (exit 0, first try) |
| serve.sh | 1.09 | 1 (includes its own lint pass) |
| verify.sh (asserts) | 64.31 | 1 (7 PASS, 1 SKIP: assert 5 nav click, permanent SKIP) |
| verify.sh --dump-text | 55.00 | 1 |
| list.sh (handoff) | 0.51 | 1 |
| fix cycles | 0 | 1 verify cycle total, no fixes needed |
| **total wall clock (end - start)** | **318** | |
| Chrome launches (chrome-launches.log lines) | 2 | per cycle: 2 (one per verify.sh call) |

Scripts total about 122 s of the 318 s; the two verify.sh Chrome runs alone are 119.3 s (about 37% of wall clock).
The remaining ~196 s is model and subagent time: 2 parallel facts subagents (about 10 s and 13 s),
writing 00-brief/01-facts/02-storyboard/content.md in the main thread, and the reader-gate subagent (about 16 s).
The end timestamp also includes the idle gap between the reader-gate result arriving and the handoff step.

Subagents dispatched (as SKILL.md prescribes, default model, no overrides): 2 facts (stop.sh, common.sh), 1 reader gate.
Render gate: verify.sh was run directly in the main thread with `time`, per the Task 0 brief, not inside a check subagent.

Reader gate (cycle 1): **PASS**. Q1, Q2 and Q3 all answered with page-cited facts (F2, F3, F9-F14; F6, F7, F13; F9, F10). Unexplained terms: none.
Verify/fix cycles: 1 of the 5-cycle cap.

## After, 2026-09-30, feature worktree @ 1288526

Topic: same as the baseline (stop.sh kill decision). Slug: f018-bench-after. Wall clock measured with `date +%s` start/end (71 s).

timings.log:
```
2026-09-30T16:26:06Z init.sh 1
2026-09-30T16:26:16Z skeleton.sh 1
2026-09-30T16:26:23Z serve.sh 1
2026-09-30T16:26:23Z verify.sh 0
2026-09-30T16:26:28Z serve.sh 2
2026-09-30T16:27:09Z verify.sh 41
2026-09-30T16:27:12Z verify.sh 0
2026-09-30T16:27:16Z handoff.sh 1
```
(The first serve.sh/verify.sh pair was a lint refusal: my facts used a `path:6-7` range, which lint rejects. One fix, then re-served. The 0 s verify.sh at 16:27:12 is the `--reader-prompt` call.)

| metric | before | after | delta |
| --- | --- | --- | --- |
| total wall clock (s) | 318 | 71 | -247 (NOT like-for-like, see caveats) |
| verify cycles (with a Chrome load) | 1 | 1 | 0 |
| Chrome launches | 2 | 1 | -1 |
| Chrome launches per cycle | 2 | 1 | -1 |
| verify.sh time per cycle (s) | 119.3 (64.31 + 55.00) | 41 | -78.3 |

## Comparison

Script time was 47 s of 71 s (timings.log sum), of which 41 s is the single verify.sh Chrome load; the rest of the wall clock is model time between timings.log entries (writing brief/facts/storyboard 16:26:06 to 16:26:16, filling TODO lines 16:26:16 to 16:26:23). One Chrome launch per verify cycle held (chrome-launches.log: 1 line). The per-cycle verify saving (119.3 s to 41 s) is the like-for-like result.

Caveats, stated honestly: the wall-clock delta is inflated because this run did NOT include the baseline's 2 facts subagents (I authored facts directly from source I had already read in this session) and did NOT run the reader gate as an independent subagent (none may be dispatched in this task). `verify.sh --reader-prompt` ran and produced the prompt, but no sonnet reader verdict exists, so the reader gate is unverified for this run. The baseline's ~196 s model time included those subagents. The short model gaps (10 s for the chain docs, 7 s for all TODO lines) also mean the content was pre-written in context before the timed run started, so model time is understated beyond the facts point above. Only the Chrome/verify figures and launch count are directly comparable.

## Full test suite

`----- 111 passed, 0 failed, 0 skipped`
