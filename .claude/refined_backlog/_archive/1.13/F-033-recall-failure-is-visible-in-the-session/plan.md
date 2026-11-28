# F-033 Implementation Plan

Spec: `spec.md` in this folder (the authority). Tests first, then code, per task. Batch: 1,2,3

## Task 1: hook heartbeat and error record (`skills/agentic-vault/hooks/vault-recall.py`)
- `run_engine` raises `EngineError(kind, detail)` for non-zero exit (`exit`), `TimeoutExpired` (`timeout`), `FileNotFoundError` (`missing`); any other exception from the seed call becomes `exception`.
- Seed call failure: append `{ts, session_id, kind, detail}` to `errors.jsonl`, print one `additionalContext` line saying recall is down, skip the query call, save state with `reported: true`.
- Seed success: append `{ts, session_id, ok: true}` to `heartbeat.jsonl`, state `reported: true`.
- The query call's failure stays silent (no output, no record). Later prompts and old state files with no seed write nothing.
- Tests (`tests/test_vault_recall.py`): false -> 1 error `exit` + one-line output + second run still 1; sleeping engine -> `timeout`; `/nonexistent` -> `missing`; good stub -> 1 heartbeat, 0 errors, second prompt adds nothing. Update the two existing tests that assumed silence on missing/slow engine.
- Verify: `python3 -m unittest tests.test_vault_recall -v`

## Task 2: doctor accepts launchd (`bin/ps-skills-doctor`, `check_vault_distill`)
- Add `launchd=None` param (injectable like `crontab`); default runs `launchctl list` and looks for `local.vault-distill`. Warn "no cron line" only when neither crontab nor launchd has it.
- Tests (`tests/test_ps_skills_doctor_distill.py`): launchd present + empty crontab -> no warning; both absent -> warns. Existing tests pass `launchd=""` through `run_check`.
- Verify: `python3 -m unittest tests.test_ps_skills_doctor_distill -v`

## Task 3: install guard (`install.sh` vault-engine block) and README
- Build to `mktemp -d`, run `<tmp>/vault-engine context --cwd "$REPO"`, install to `$BIN_HOME` (and the AGY copy) only on exit 0; otherwise print one reason line and continue.
- Tests (`tests/test_install.py`): `run_install` gains an optional PATH prefix; fake `go` writes a failing/passing binary. Failing build leaves a pre-seeded `vault-engine` byte-identical and prints the reason; good build installs it.
- README: document `heartbeat.jsonl` / `errors.jsonl`, the install guard, doctor launchd acceptance.
- Existing tests there are pytest functions, so `unittest tests.test_install` runs 0 tests today; the new tests are a `unittest.TestCase` so the spec's unittest command runs them.
- Verify: `python3 -m unittest tests.test_install -v` (must show the new tests, not 0); `python3 -m pytest tests/test_install.py -q`; `bash -n install.sh`

## Final gate
`python3 -m unittest tests.test_vault_recall tests.test_ps_skills_doctor_distill tests.test_install -v`; `python3 -m unittest discover -s tests 2>&1 | tail -5`; hand probes of the hook with a temp `VAULT_RECALL_STATE`.
