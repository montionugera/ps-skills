# Vault and release current-work view implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add JSON release status, a validated vault project-to-feature link, and a combined read-only current-work view.

**Architecture:** `psrw status --json` exposes a small versioned delivery snapshot. A standalone Python `ps-work` command calls `vault-engine` and `psrw` through subprocess argument arrays; `link` writes link metadata through vault OCC, while `show` only reads and joins by feature ID.

**Tech Stack:** Python 3 standard library, pytest, existing Go vault-engine CLI and project JSON schema, shell installer.

**Spec:** `docs/superpowers/specs/2026-09-29-vault-release-view-design.md`

## Global constraints

- Commit this plan on the release branch, then run `psrw claim F-016` before editing implementation files. Keep F-015 and the main checkout untouched.
- Preserve `psrw status` and `--brief` text output and their zero-exit SessionStart behavior.
- `psrw-status/v1` contains only opted-in flag, release version/in-progress, and ID/title/status/release-version fields for features plus ID/title/status for epics.
- Link fields are optional scalars: `release_repo` is the absolute main checkout root; `release_feature_id` is one `F-NNN`.
- `show` never invokes a mutating command or displays cached delivery status as live.
- Each phase ends: implement → focused verify → independent adversarial review → resolve findings/refactor → re-verify → commit.
- The top-level installer points at main; after shipping, run the command from the `_release` worktree. Global installed commands update only when release 1.8 is promoted. Do not relink global binaries to an unfinished release.

---

### Preparation: Claim the isolated worktree

- [ ] Commit the reviewed spec/plan files on the release branch, leaving rendered HTML untracked.
- [ ] Run `psrw claim F-016`; verify its owner marker and clean starting diff. Workers read the reviewed spec and plan by absolute path in the _release worktree; claim branches from main and does not copy these documents.
- [ ] Before shipping, record exact explicit test commands because this repo has no `scripts/precheck.sh`.

### Task 1: Versioned release status JSON

**Files:** modify `engine/ps-release-workflow/scripts/status.py`; test `engine/ps-release-workflow/tests/test_status.py` and, if useful, `test_psrw_cli.py`.

**Interface:** `psrw status --json [--repo PATH]` emits one JSON object with `schema: "psrw-status/v1"`. Success includes `opted_in: true`, `release: {version, in_progress}`, `features: [{id,title,status,release_version}]`, `epics: [{id,title,status}]`. Failure includes `opted_in: false`, `error: {code,message}`, using `not_opted_in` or `status_unavailable`. Existing text modes remain byte-for-byte compatible; `--json` conflicts with `--brief`.

- [ ] Add failing tests for success shape, missing repo, collection error, text compatibility, and no identity-state write.
- [ ] Run focused tests and observe expected failure.
- [ ] Implement explicit JSON projection from `collect_status()` and JSON error output; do not dump the internal dict.
- [ ] Re-run focused tests; inspect representative CLI output.
- [ ] Independent code and Python review; fix findings, re-run tests, commit Task 1.

### Task 2: Vault link and read-only view

**Files:** create `bin/ps-work`; test `tests/test_ps_work.py`; modify `tools/vault-engine/schemas/project-v1.json` and `skills/agentic-vault/SKILL.md`.

**Interface:** `ps-work link PROJECT_ID --vault-root PATH --repo MAIN_ROOT --feature F-NNN [--actor NAME]`; `ps-work show PROJECT_ID --vault-root PATH [--json]`. Both accept optional `--vault-engine` and `--psrw` paths. When `--psrw` is omitted, the command prefers the dispatcher in its own checkout, so the `_release` copy works before global promotion; otherwise it uses PATH. Set `VAULT_ROOT` for the vault child. `link` validates main checkout and live feature existence, reads the project SHA, then invokes vault commit with only the two link fields. `show` reads the project and release status, presents title/outcome (title fallback) plus feature and release state, and emits the spec's distinct unavailable states.

- [ ] Write failing tests with fake CLI executables for valid link/show, missing or malformed link, worktree path rejection, absent feature, unavailable release, malformed child JSON, and OCC conflict. Assert `show` calls no write verb.
- [ ] Run tests and observe expected failure.
- [ ] Implement the CLI, optional project schema fields, and short skill instructions for link/show ownership.
- [ ] Re-run focused tests and a temporary-vault/repo integration fixture; verify `show` leaves both sources unchanged.
- [ ] Independent code, Python, and security review; fix findings, re-run tests, commit Task 2.

### Task 3: Install, document, and integrate

**Files:** modify `install.sh` and its tests; update relevant command documentation only where needed.

- [ ] Add a failing installer test for linking `bin/ps-work` and replacing it under `--force`.
- [ ] Add the command to the install link and replace allowlist; run installer tests.
- [ ] Run focused tests from Tasks 1–2 together, top-level installer tests, and `go test ./...` in `tools/vault-engine`. There is no `scripts/precheck.sh` in this repo, so preserve explicit test output as the ship evidence.
- [ ] Independent adversarial review of the combined diff; fix findings, rerun focused and gate tests, commit Task 3.
- [ ] Ship F-016 into release 1.8 only after explicit tests pass and the worktree is clean. Ship syncs main by default; diagnose any conflict rather than bypassing sync. Smoke-test `_release/bin/ps-work` with the sibling release dispatcher, and state that the globally installed command remains on main until promotion.

## Appendix — audit trail

- 2026-09-29 self-grill-audit: initial verdict no. Corrected missing claim step, committed-plan prerequisite, release-versus-global command availability, absent precheck assumption, command-name drift, and the mistaken expectation that claim copies release-branch docs. Open: none.
