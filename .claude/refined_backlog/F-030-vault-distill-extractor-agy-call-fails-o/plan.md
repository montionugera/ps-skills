# F-030 vault-distill extractor (route C) Implementation Plan

Spec: `spec.md` in this folder (audited 2026-11-11, owner chose route C). The spec's Design 1–8, requirements X1, X3–X11 and acceptance criteria are the task; this plan only fixes order and verification.

One task, one file plus tests, so one worker. The spec's design is already at code level and was audited, so this plan was not audited separately.

## Task 1: direct Gemini API extractor, failure reasons, retries, token count

Files: `bin/vault-distill`, `tests/test_vault_distill_drafts.py` (replace the fake-`agy` helper, one rename), new `tests/test_vault_distill_gemini_api.py`, `README.md` (vault-distill paragraph, X7).

The spec (route A, rewritten 2026-11-11 after the owner switched from route C) is the task: Design 1 to 10, X1 to X11, every acceptance criterion outside Go-live.

Order (test first):
1. Write every acceptance criterion as a test in the new file; the HTTP call is replaced in process or by a local stub server, never the network. Run them; they must fail for the right reason.
2. Implement Design 1 to 10.
3. Update the README paragraph.

An earlier worker (route C, stopped by the owner) left an uncommitted diff in this worktree in `bin/vault-distill`, `README.md` and `tests/test_vault_distill_drafts.py`. Read it with `git diff`; keep what matches design 5 to 9 and discard the rest.

Verify:

```bash
python3 -m unittest tests.test_vault_distill tests.test_vault_distill_drafts tests.test_vault_distill_audit tests.test_vault_distill_gemini_api tests.test_jev_gate_distill tests.test_ps_skills_doctor_distill -v
python3 -m py_compile bin/vault-distill
```

Constraints: tests make no network call and never read the real Keychain; no real note ids, prompts or `/Users/<name>/` paths in committed files; commit per logical unit, never amend.

## Go-live (controller, after ship)

Spec section "Go-live" L1–L3.
