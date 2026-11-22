---
title: "Triage the vault sync fix-later review notes from release 1.11"
id: I-032
status: idea
---

# Triage the vault sync fix-later review notes from release 1.11

## Problem

The reviews of the vault sync leftovers build (F-021, release 1.11, code under
`tools/vault-engine/`) parked about 64 findings as "fix later": 34 from the final
code review and 30 from the final Go review. None of them blocked the release, and
none has been looked at since.

The notes lived only in an uncommitted folder inside the F-021 feature worktree
(`.superpowers/sdd/2026-10-11-agentic-vault-sync-leftovers/`). Release cleanup removed
that worktree and the notes with it. They were rebuilt on 2026-10-12 from saved
session records and are kept in `research.md` next to this file.

What is known about the rebuilt notes:

- The 34 code-review items are itemised in full (Part 1 of `research.md`).
- The 30 Go-review items were never itemised; that reviewer returned counts only.
  `research.md` Part 2 holds the 41 smaller Go findings they were drawn from, so the
  set to triage is 41, not a clean 30.
- Features F-022, F-023 and F-024 shipped in release 1.11 after these reviews. Some
  findings may already be closed by them. This has not been checked.

## Why now

No deadline. The cost of waiting is that the findings go stale as the code moves, and
line numbers in the notes stop matching.

## Sketch

1. Walk every finding in `research.md` Parts 1 and 2 against the code on `main` and
   mark each one: already fixed, still open, or no longer applies.
2. Group the still-open ones by area (sync engine, recovery and undo, build script,
   agent rules text, tests).
3. Turn each group worth doing into its own idea or feature; drop the rest with a
   one-line reason.

## Acceptance criteria

- [x] Every finding in `research.md` Parts 1 and 2 carries one of three marks (already fixed, still open, no longer applies), each with the file and line checked on `main`.
- [x] Every still-open finding is either linked to a new idea or feature id, or dropped with a written reason. (All 32 open findings, A1-A32, are fixed by F-025, shipped to release 1.12; leftovers found in review are I-036 and I-037.)
- [x] No review notes for this build exist only in an uncommitted folder.

## Progress (2026-10-13)

- Done: every finding marked and reviewed (`triage.md`); the 76 open rows merged into 32
  distinct open findings (`open-findings.md`).
- Decided by the owner's session default: the nine findings a review ruled "not a defect"
  stay closed (listed in `triage.md`).
- Left: the second box above. Group the 32 findings into planned features, or drop them
  with a reason.
