# F-030 vault-distill extractor (route C) Implementation Plan

Spec: `spec.md` in this folder (audited 2026-11-11, owner chose route C). The spec's Design 1–8, requirements X1, X3–X11 and acceptance criteria are the task; this plan only fixes order and verification.

One task, one file plus tests, so one worker. The spec's design is already at code level and was audited, so this plan was not audited separately.

## Task 1: extractor envelope, failure reasons, retries, token count

Files: `bin/vault-distill`, `tests/test_vault_distill_drafts.py` (`FAKE_AGY` and one rename only), new `tests/test_vault_distill_agy_envelope.py`, `README.md` (vault-distill paragraph, X7).

Order (test first):
1. Extend `FAKE_AGY` so it can print a reply file, exit with a given code and write stderr (env vars, defaults keep old behaviour). Rename `test_extract_default_is_one_tool_free_flash_call_that_renders_the_draft`.
2. Write every acceptance criterion of the spec as a test in the new file. Run them; they must fail for the right reason.
3. Implement Design 1–8 in `bin/vault-distill`:
   - `ask_agy`: flags `--mode plan --disable-slash-commands --sandbox --json-schema <schema> --output-format json`; envelope = JSON object with a `status` key; returns the answer, or a failure reason, plus `usage.total_tokens`.
   - `extract_default` / `review_default`: tool failure → stdout `{"fallback": true, "error": "<reason>"}`, exit 0; bad answer (unparsable, or extractor answer without `lesson`) → reason on stderr, exit 1. Extractor output adds `"tokens"`.
   - `Run.call`: on failure append `"<stage> failed: <text>"` to `run.notes`; text = fallback `error`, else last stderr line, else exception class name; `SECRET_RE` on the full text first → "error text withheld"; then one line, ≤200 chars; dedupe per run; ≤5 distinct lines per stage. `Run.call` must let the caller tell a tool failure (fallback / non-zero / timeout) from a bad answer.
   - `extract_session` / `run_extractions`: tool failure → `extract-pending` with try count +1 (stored on the session's seen record), third tool failure → `invalid`; bad answer → `invalid` at once; two tool failures in a row → no more extract calls tonight, untried sessions stay `extract-pending`. Sum `tokens` into a new report count `extract_tokens`.
   - Comments and docstring stop claiming "no tools"; keep the "Use no tools." prompt lines.
4. README vault-distill paragraph: default extractor and reviewer are `agy` agent calls that can read and write under the home directory; owner accepted this on 2026-11-11 (route C); `extract_tokens` in the report.

Verify:

```bash
python3 -m unittest tests.test_vault_distill tests.test_vault_distill_drafts tests.test_vault_distill_audit tests.test_vault_distill_agy_envelope tests.test_jev_gate_distill tests.test_ps_skills_doctor_distill -v
python3 -m py_compile bin/vault-distill
```

Constraints: never run the real `agy -p` (tests use the fake on PATH); no real note ids, prompts or `/Users/<name>/` paths in committed files; commit per logical unit, never amend.

## Go-live (controller, after ship)

Spec section "Go-live" L1–L3.
