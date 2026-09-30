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
