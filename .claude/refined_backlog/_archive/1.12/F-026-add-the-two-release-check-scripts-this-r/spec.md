---
title: "Add the two release check scripts this repo is missing"
id: F-026
status: refined
from_idea: I-038
---

# Add the two release check scripts this repo is missing

## Problem

This repo uses the release workflow but has neither of the two check scripts it looks for.

- `scripts/precheck.sh` (the quick check run when a feature is merged into the release) is missing, so every merge prints "Gate 1 SKIPPED".
- `scripts/integration.sh` (the check run before a release is promoted to main) is missing, so a promote needs the `--allow-missing-gate2` flag and the release notes say "UNVERIFIED".

Seen while shipping F-025 (fix the 32 open vault sync review findings) to release 1.12.

## Why now

Release 1.12 is waiting to be promoted. The owner chose (2026-10-13) to add the scripts with the fast test suites, and to keep the hour-long vault sync harness as a manual step because it failed twice on a busy Mac for reasons unrelated to the code (see I-037).

## Sketch

Copy the two templates from `engine/ps-release-workflow/templates/` into `scripts/` and fill their slots.

- Quick check: `go vet` and a `gofmt` check for `tools/vault-engine`; the release tool's Python tests without the slow ones. No user interface in this repo, so that slot is marked not applicable.
- Promote check: the release tool's full Python tests, the root `tests/` suite, and the vault sync Go tests with the race detector and a 40-minute limit. This repo has no database and no browser pages, so those slots are marked not applicable with the reason.
- Not included: the hour-long harness and `test_e2e.sh`.
- Update `README.md` to say what each check runs.

## Acceptance criteria

- [ ] `bash scripts/precheck.sh` exits 0 on release 1.12 and prints "Gate 1: ok".
- [ ] `bash scripts/integration.sh` exits 0 on release 1.12 and prints "Gate 2: ok".
- [ ] Each script exits non-zero when one of its commands fails.
- [ ] Neither script runs the vault sync harness or `test_e2e.sh`, and neither redirects `HOME`.
- [ ] `README.md` says what each check runs and what is left as a manual step.
