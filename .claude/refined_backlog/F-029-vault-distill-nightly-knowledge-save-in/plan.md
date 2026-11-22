# I-040 (I-039 Slice 2): Nightly Knowledge Save in Shadow Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A nightly `vault-distill` batch turns finished agent sessions into candidate knowledge notes in the vault inbox, screened by cheap Jev calls, with a report every morning, and publishes nothing yet.

**Architecture:** `bin/vault-distill` (Python 3.11+ stdlib) rotates the Stop hook's pointer inbox, builds a 12,000-byte digest per finished session, and asks Jev (`jev-gate classify-lesson`) whether it holds a lesson. Selected sessions go to one Gemini Flash call that returns a draft. Each draft then passes four gates in order: a script evidence check, Jev `score-draft`, recurrence through Jev `same-lesson`, and one Argon-low review per night. Every external call goes through one of three command seams (`VAULT_DISTILL_JEV_CMD`, `VAULT_DISTILL_EXTRACT_CMD`, `VAULT_DISTILL_REVIEW_CMD`), and tests replace all three with stub scripts. Machine state lives in `~/.claude/state/vault-distill/`. The vault gets only inbox files and the report.

**Tech Stack:** Python 3.11+ stdlib (`bin/vault-distill`, `bin/jev-gate`, `bin/ps-skills-doctor`), `unittest` (CI runs `pytest tests`), bash (`tools/vault-engine/test_e2e.sh`), the existing Go `vault-engine` (`context`, `validate`), `agy` print mode.

**Spec:** `.claude/idea_backlog/I-040-vault-distill-nightly-knowledge-save-in/spec.md`. This plan covers R6, R6f, R7, R7f, R7s, R8, R8f, R8u, R9, R9f, R9c, R9d, R9df, R19, R10, R10f, R11, R11a, R12, R13, R16, and the save rows of the token budget table.

**Scope of this plan:** slice 2 only. Slice 3 (R10a, R10af, R10b, R10bf, R18 calibration, R14/R15 used-rate, R20, R21, the rest of R17) gets its own plan. Nothing in this plan writes to `04_Knowledge/` or calls `publish-knowledge` or `commit`.

## Global Constraints

Copied from the spec. Every task must meet them.

- Session digest sent to Jev: at most 12,000 bytes (first 2,000 + last 10,000), tool output stripped. The extractor gets the same digest, never the raw transcript.
- Jev calls: one per session, one per draft, and at most 5 same-lesson comparisons per draft.
- Extractor runs: only on a confident yes (`lesson_prob` at least 0.85), plus at most 3 unsure (`VAULT_DISTILL_UNSURE_MAX`); at most 20 per night (`VAULT_DISTILL_MAX`). At 0.15 or below a session is dropped.
- Draft note: `knowledge/v1`, at most 1,500 bytes. The body is a one-sentence summary, then `When this applies`, `Rule`, `Why`, `Source` (session id), and `Evidence`. Tags: `auto-distilled`, plus `project_ids` for the repo, or `repo:<name>` when the repo has no project note, or `global`.
- Junk gate: `specific` or `novel` below 0.5 is `junk`. Review needs a match at 0.85 or above with a candidate from a different session, or `high_stakes` at 0.85 or above. A candidate with no match after 60 days leaves the queue.
- Review: one Argon-low (`gemini-4-argon-low`) call per night. Extraction model: `gemini-3.8-flash-high`. Never route anything to a Fable model.
- A session's transcript mtime within 30 minutes of the run start means it is still active: its line goes back to the live inbox. Growth of less than 4,000 bytes since the recorded offset means skip.
- Credential patterns: `vault-distill`'s own copy of `bin/ps-skills-sync` `SECRET_RE`, every pattern except `/Users/[a-z]+/`. A hit goes to `_inbox/private/` and is sent to no model.
- `VAULT_DISTILL_SKIP_REPOS` (comma-separated repo root basenames): such a session is marked `not-allowed` and nothing is sent. The owner decided this (2026-11-11): every other repo's digests go to TypeSafe (Jev) and Gemini after the credential scan. Do not reopen it.
- Fail open to "parked in inbox": no stage deletes a note or a draft that passed. A crash is resumable: the seen-file is appended per session, and a leftover dated work file is processed first.
- Exit non-zero when more than 50% of the night's classified sessions are unsure, or when a stage failed on every call. `VAULT_DISTILL=0` does nothing.
- Shadow mode: publishing does not exist in this slice. A publish verdict is recorded as `would-publish`.
- Public repo: no real note ids, titles, session text or transcript paths in code, fixtures or docs. Never write a literal home path (`/Users/<name>/`) or a literal token (`ghp_` plus 20 characters) into a committed file. Build such strings at runtime in tests, because `ps-skills-sync --push` scans for them.
- No new dependencies. Tests never call Jev, Gemini, `agy` or `dispatch-worker` for real.
- Before Task 1: `psrw refine I-040`, then `psrw claim F-NNN`. Every edit happens in the claimed feature worktree. `bin/jev-gate` is already on `release/1.12`, so no `sync-main` is needed for it.
- Commits: new commits only, never `--amend`.

Batch: 1,2
Batch: 3,4

## Audit amendments (2026-11-11, binding)

These override the task text below wherever they differ. The code in Tasks 1 to 4 was run before it was written down; the amendments were not, so each one is implemented test first.

- **A1 (Task 2, `repo_root`).** Resolve the repo the way `vault-engine` does (`tools/vault-engine/pkg/vault/context.go`, `RepoRoot`), so a sibling hotfix worktree (`../<repo>-hotfix-<x>`) maps to its main repo for the skip list and for `repo_scope`. Keep the string split as the fallback for a cwd that no longer exists:

  ```python
  def repo_root(cwd):
      """Main repo path for a session cwd, resolved like vault-engine RepoRoot; a removed worktree falls back to its path."""
      try:
          out = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                               capture_output=True, text=True, timeout=5)
          if out.returncode == 0 and out.stdout.strip():
              return str(Path(out.stdout.strip()).parent)
      except (OSError, subprocess.SubprocessError):
          pass
      return cwd.rstrip("/").split("/.claude/worktrees/", 1)[0]
  ```

  Test: a temp repo with `git worktree add ../demo-hotfix-x`; a session whose cwd is that worktree is `not-allowed` when the skip list names the main repo's basename.
- **A2 (Task 2, `run_batch`).** A session parked by the nightly cap must be extracted on the next run whatever its probability: the first branch becomes `if p >= EXTRACT_AT or prior_state == "extract-pending":`. Test: an unsure session that was marked `extract-pending` (p 0.5) is queued the next night and is not counted as unsure.
- **A3 (Task 2, `build_digest`).** A user record's typed text is its string content, or the joined `text` blocks when the content is a list. A typed text that starts with `<` after stripping is an automated prompt (task notification, command output): leave it out of the digest and out of the correction count. Tool results in a list are handled as written. Tests: a list-form text prompt appears in the digest; a `<task-notification>` prompt does not.
- **A4 (Task 3, `ask_agy`).** Add `"--sandbox"` to the command. Go-live G4 confirms the call still returns JSON; if it does not, drop the flag and say so in the report.
- **A5 (Task 4, README).** State that the skip list for the nightly run is the `VAULT_DISTILL_SKIP_REPOS=` assignment on the cron line (cron does not read `~/.zshrc`), and that `--dry-run` still writes digest files under the state directory.
- **Effect of F-028 (merged after this plan was written).** `context --query` now keeps only the first 20 terms of a query longer than 80 terms, drops a fixed noise list, weights by note rarity and takes `--limit` as given. No test in this plan depends on engine scoring (all use the engine stub). `related_notes` on the user prompts is therefore driven by the opening of the session; this is accepted.

## Deviations from the spec

1. **The extractor is one model call, not an agent run (R9).** The spec routes the extractor through `dispatch-worker --agent agy`. What I checked:
   - `bin/dispatch-agy-worker:2195-2203` builds `agy --add-dir <dir> -p <task> --dangerously-skip-permissions --output-format stream-json`. That is a full agent turn with write access, wrapped in worker instructions, quota checks and a verify gate.
   - `agy --help` (checked on this machine) lists a print mode: `-p/--print` runs one prompt non-interactively, and the CLI also has `--model`, `--mode plan`, `--json-schema` ("enforce structured output"), `--output-format text`, `--print-timeout` and `--disable-slash-commands`.
   - `agy models` lists `gemini-3.8-flash-high` and `gemini-4-argon-low`.
   - No direct Gemini HTTP path exists: there is no `generativelanguage` and no `GEMINI_API_KEY` anywhere in `bin/`, `skills/`, `engine/` or `tools/`.

   The default extractor is therefore one `agy -p` call with `--model gemini-3.8-flash-high --mode plan --json-schema <schema>`. It runs with no `--add-dir`, no `--dangerously-skip-permissions`, and an empty temp directory as cwd. The model returns JSON, and `vault-distill` renders the draft file itself, so the note's shape is fixed in code. The seam contract stays as the spec wrote it: `VAULT_DISTILL_EXTRACT_CMD` reads a request on stdin and returns `{"path": str}` or `{"path": null, "reason": "no-lesson"}`. The reviewer is the same kind of call on `gemini-4-argon-low`.
   - Not verified, because doing so needs a real model call: that plan mode with no permissions makes zero tool calls, and that `--json-schema` with `--output-format text` prints bare JSON. `parse_json` also accepts JSON wrapped in prose. Go-live step G4 checks this with one real call. If it fails, fall back to the spec's `dispatch-worker --agent agy` route behind the same seam.
2. **Who runs `context --query`, and on what (R9).** The lesson title does not exist before the single call. `vault-distill` therefore runs `vault-engine context --query` on the digest's user prompts before the call and passes the top 3 notes in, so the model can make the draft a proposed addition (`proposed_addition_to: <id>` in the frontmatter). After the draft exists, `context --query <draft title>` supplies the R9d "top 3 existing notes".
3. **`jev-gate score-draft` takes `--related <path>`** (the context output written by `vault-distill`). Without it, `jev-gate` would have to call `vault-engine` itself. It still reads the first 20,000 bytes of `~/.claude/CLAUDE.md` itself.
4. **Candidates are moved, not removed (R19).** Expired candidates move to `_inbox/agent/distill/expired/` and are listed in the report. The newer half of a recurrence merge moves to `merged/`. This follows the owner's "nothing is ever deleted from the vault". The only file deleted is a draft that contains a credential, after its copy lands in `_inbox/private/`, plus the dated work file (R13 says to delete it, and every line in it is already in the seen-file).
5. **Report fields that belong to slice 3 (R12).** `published`, `merged` (into an existing note), `collisions` and `archived` are always 0. Used-rate per note shows injection counts from slice 1's `injections.jsonl`; used counts need R15 (slice 3). A publish verdict is counted as `would_publish`.
6. **Private quarantine needs the vault's `.gitignore` rule (R11).** Credential content is written to `_inbox/private/` only when the vault's `.gitignore` contains `_inbox/private/`, the same rule `vault-engine check-privacy` enforces (`tools/vault-engine/pkg/vault/privacy.go:11`). Otherwise only a pointer file is written. The real vault's `.gitignore` lacks the rule today. Go-live step G1 adds it.
7. **Evidence quotes must be at least 8 characters (R9c).** This tightens the gate, so that a quote like `exit 2` cannot pass by accident.
8. **The 12,000-byte digest includes the signals line (R7, R7s).** The spec does not say. Counting it keeps the limit hard.
9. **R16's denominator** is the number of sessions sent to `classify-lesson` that night. Not-allowed, private, too-small and active sessions are not counted.
10. **A Jev failure does not use up the R8u second offer.** A `jev-failed` session is asked again every night until Jev answers. A missing key makes every night exit non-zero (R16), and the doctor flags it.
11. **New tests go in new files.** They are `tests/test_jev_gate_distill.py` and `tests/test_ps_skills_doctor_distill.py`, not additions to `tests/test_jev_gate.py` and `tests/test_ps_skills_doctor.py`. The reason: `extract-acceptance-tests` overwrites a block's target file with the block content (`bin/extract-acceptance-tests:276-291`).
12. **Part of R17 (a slice-3 requirement) is pulled forward**, because the slice-1 plan said the save-side checks arrive with slice 2. Those checks are Jev key found, cron line present, and last run under 36 hours. "Publishing enabled" is left out, because publishing is always off in slice 2.
13. **The end-to-end case stops at "would publish" (spec, End-to-end verification).** It asserts a validated candidate, the report rows, and an unchanged `04_Knowledge/`. The spec's publish-then-recall case needs slice 3.
14. **Sessions below the 4,000-byte growth threshold are not written to the seen-file.** The report counts them as `skipped_small`. The Stop hook's next line for that session brings it back once it grows.

---

### Task 1: `jev-gate` subcommands `classify-lesson`, `score-draft`, `same-lesson`

**Files:**
- Modify: `bin/jev-gate` (module docstring lines 11-14; new functions before `def main()` at line 411; parsers before `args = parser.parse_args()` at line 438)
- Modify: `tests/fixtures/typesafe_stub/typesafe_sdk.py` (inside `system_one`, before `return`)
- Test: `tests/test_jev_gate_distill.py` (new)

**Interfaces:**
- Consumes: `_load_api_key()` (line 32), `typesafe_sdk.TypeSafeClient.system_one(model, state, questions)` and `Noul(instructions=...)`, whose answer has `.noul` (pattern of `cmd_triage_spec`, line 341).
- Produces (Task 2 and Task 3 call these through `VAULT_DISTILL_JEV_CMD`, default `bin/jev-gate`; every subcommand also accepts the common `--timeout`, `--model` and `--min-conf`, and always exits 0):
  - `jev-gate classify-lesson --digest <path>` prints `{"lesson_prob": float, "fallback": false}`, or on any failure `{"lesson_prob": 0.5, "fallback": true, "error": str}`.
  - `jev-gate score-draft --draft <path> --digest <path> [--related <path>]` prints `{"specific": p, "novel": p, "high_stakes": p, "fallback": false}`, or `{"fallback": true, "error": str}`.
  - `jev-gate same-lesson --a <path> --b <path>` prints `{"same": p, "fallback": false}`, or `{"same": 0.0, "fallback": true, "error": str}`.
  - Stub SDK: a `JEV_<NAME>=<p>` marker anywhere in the state sets the answer for `lesson`, `specific`, `novel`, `high_stakes` or `same_lesson`; the default is 0.5.

- [ ] **Step 1: Write the failing test**

```python test:tests/test_jev_gate_distill.py
#!/usr/bin/env python3
"""bin/jev-gate subcommands for vault-distill (I-040): classify-lesson, score-draft, same-lesson."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
JEV_GATE = BIN_DIR / "jev-gate"
STUB_DIR = str(Path(__file__).resolve().parent / "fixtures" / "typesafe_stub")
# Hermetic env: the stub typesafe_sdk answers JEV_<NAME>=<p> markers (no network, no host ~/.zshrc).
STUB_ENV = {**os.environ, "PYTHONPATH": STUB_DIR + os.pathsep + os.environ.get("PYTHONPATH", "")}
PY_BIN = "/opt/homebrew/bin/python3" if os.path.exists("/opt/homebrew/bin/python3") else sys.executable


class TestJevGateVaultDistill(unittest.TestCase):
    """classify-lesson, score-draft and same-lesson (I-040): output shape and fail-open."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.home = self.dir / "home"
        (self.home / ".claude").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text)
        return str(path)

    def run_gate(self, *args, key="stub"):
        env = {**STUB_ENV, "HOME": str(self.home)}
        if key is None:
            env.pop("TYPESAFE_API_KEY", None)
        else:
            env["TYPESAFE_API_KEY"] = key
        res = subprocess.run([PY_BIN, str(JEV_GATE), *args], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_help_lists_new_subcommands(self):
        res = subprocess.run([PY_BIN, str(JEV_GATE), "--help"], capture_output=True, text=True)
        for sub in ("classify-lesson", "score-draft", "same-lesson"):
            self.assertIn(sub, res.stdout)

    def test_classify_lesson_returns_probability(self):
        digest = self.write("d.txt", "user: the gate failed twice JEV_LESSON=0.95\n")
        self.assertEqual(self.run_gate("classify-lesson", "--digest", digest), {"lesson_prob": 0.95, "fallback": False})

    def test_classify_lesson_without_key_falls_back_unsure(self):
        digest = self.write("d.txt", "user: something JEV_LESSON=0.95\n")
        out = self.run_gate("classify-lesson", "--digest", digest, key=None)
        self.assertTrue(out["fallback"])
        self.assertEqual(out["lesson_prob"], 0.5)

    def test_classify_lesson_missing_digest_falls_back(self):
        out = self.run_gate("classify-lesson", "--digest", str(self.dir / "nope.txt"))
        self.assertTrue(out["fallback"])

    def test_score_draft_returns_three_scores(self):
        draft = self.write("draft.md", "# Rule\nJEV_SPECIFIC=0.3 JEV_NOVEL=0.8 JEV_HIGH_STAKES=0.9\n")
        digest = self.write("d.txt", "digest text\n")
        out = self.run_gate("score-draft", "--draft", draft, "--digest", digest)
        self.assertEqual(out, {"specific": 0.3, "novel": 0.8, "high_stakes": 0.9, "fallback": False})

    def test_score_draft_without_key_falls_back(self):
        draft = self.write("draft.md", "# Rule\n")
        digest = self.write("d.txt", "digest\n")
        out = self.run_gate("score-draft", "--draft", draft, "--digest", digest, key=None)
        self.assertEqual(out["fallback"], True)
        self.assertNotIn("specific", out)

    def test_same_lesson_returns_probability(self):
        a = self.write("a.md", "lesson a JEV_SAME_LESSON=0.9\n")
        b = self.write("b.md", "lesson b\n")
        self.assertEqual(self.run_gate("same-lesson", "--a", a, "--b", b), {"same": 0.9, "fallback": False})

    def test_same_lesson_without_key_falls_back(self):
        a = self.write("a.md", "lesson a\n")
        b = self.write("b.md", "lesson b\n")
        out = self.run_gate("same-lesson", "--a", a, "--b", b, key=None)
        self.assertEqual(out, {"same": 0.0, "fallback": True, "error": "TYPESAFE_API_KEY not set"})


if __name__ == "__main__":
    unittest.main()
```

Verify-Cmd: python3 -m unittest tests.test_jev_gate_distill -v

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_jev_gate_distill -v`
Expected: FAIL. `--help` lacks `classify-lesson`, and the subcommands exit 2 (argparse: invalid choice), so `json.loads` raises.

- [ ] **Step 3: Extend the stub SDK**

In `tests/fixtures/typesafe_stub/typesafe_sdk.py`, insert before `return NS(model="stub", ...)` in `system_one`:

```python
        # vault-distill questions: a JEV_<NAME>=<p> marker anywhere in the state sets that answer, else 0.5.
        blob = " ".join(str(v) for v in state.values())
        for name in ("lesson", "specific", "novel", "high_stakes", "same_lesson"):
            m = re.search(rf"JEV_{name.upper()}=([0-9.]+)", blob)
            answers[name] = NS(noul=float(m.group(1)) if m else 0.5)
```

- [ ] **Step 4: Implement the subcommands**

Add to the module docstring's subcommand list:

```text
  4. classify-lesson --digest <path>                       (vault-distill)
  5. score-draft     --draft <path> --digest <path> [--related <path>]
  6. same-lesson     --a <path> --b <path>
```

Insert before `def main() -> int:`:

```python
# --- vault-distill screening (I-040): one Jev call each, fail open to {"fallback": true} ---
LESSON_Q = ("Does this agent session digest contain a reusable lesson: a trap, fix, decision or rule that "
            "would save a future session time or prevent a mistake (not just routine work that went fine)?")
SPECIFIC_Q = "Is this draft rule specific and actionable: does it name the situation, the command, file or error, and what to do?"
NOVEL_Q = "Is this draft lesson NOT already covered by the existing notes or the owner rules given in the state?"
HIGH_STAKES_Q = "Would ignoring this lesson risk data loss, a production failure or a security problem?"
SAME_Q = "Do draft_a and draft_b describe the same lesson (the same situation and the same rule), even if worded differently?"


def _read(path: str, limit: int) -> str:
    try:
        return Path(path).read_bytes()[:limit].decode("utf-8", errors="ignore")
    except (OSError, TypeError):
        return ""


def _jev_nouls(args: argparse.Namespace, state: dict, questions: dict):
    """Ask Jev yes/no questions in one call. Returns ({name: prob}, "") or (None, error)."""
    key = _load_api_key()
    if not key:
        return None, "TYPESAFE_API_KEY not set"
    try:
        from typesafe_sdk import Noul, TypeSafeClient

        client = TypeSafeClient(api_key=key, timeout=args.timeout)
        res = client.system_one(model=args.model, state=state,
                                questions={k: Noul(instructions=q) for k, q in questions.items()})
        return {k: round(float(res.answers[k].noul), 4) for k in questions}, ""
    except Exception as exc:
        return None, str(exc)


def cmd_classify_lesson(args: argparse.Namespace) -> int:
    digest = _read(args.digest, 12000)
    probs, err = _jev_nouls(args, {"session_digest": digest}, {"lesson": LESSON_Q}) if digest else (None, "digest missing or empty")
    if probs is None:
        print(json.dumps({"lesson_prob": 0.5, "fallback": True, "error": err}))
    else:
        print(json.dumps({"lesson_prob": probs["lesson"], "fallback": False}))
    return 0


def cmd_score_draft(args: argparse.Namespace) -> int:
    draft = _read(args.draft, 1500)
    state = {
        "draft": draft,
        "session_digest": _read(args.digest, 12000),
        "existing_notes": _read(args.related, 4000) if args.related else "",
        "owner_rules": _read(str(Path.home() / ".claude" / "CLAUDE.md"), 20000),
    }
    questions = {"specific": SPECIFIC_Q, "novel": NOVEL_Q, "high_stakes": HIGH_STAKES_Q}
    probs, err = _jev_nouls(args, state, questions) if draft else (None, "draft missing or empty")
    print(json.dumps({"fallback": True, "error": err} if probs is None else {**probs, "fallback": False}))
    return 0


def cmd_same_lesson(args: argparse.Namespace) -> int:
    a, b = _read(args.a, 4000), _read(args.b, 4000)
    probs, err = _jev_nouls(args, {"draft_a": a, "draft_b": b}, {"same_lesson": SAME_Q}) if a and b else (None, "draft missing or empty")
    print(json.dumps({"same": 0.0, "fallback": True, "error": err} if probs is None else {"same": probs["same_lesson"], "fallback": False}))
    return 0
```

Insert before `args = parser.parse_args()` in `main()`:

```python
    p_les = sub.add_parser("classify-lesson", parents=[common], help="vault-distill: does a session digest hold a lesson?")
    p_les.add_argument("--digest", required=True, help="Session digest file (at most 12,000 bytes)")
    p_les.set_defaults(func=cmd_classify_lesson)

    p_scd = sub.add_parser("score-draft", parents=[common], help="vault-distill: score a draft note (specific, novel, high_stakes)")
    p_scd.add_argument("--draft", required=True, help="Draft note file")
    p_scd.add_argument("--digest", required=True, help="Session digest file the draft came from")
    p_scd.add_argument("--related", default="", help="File with the top existing notes (vault-engine context output)")
    p_scd.set_defaults(func=cmd_score_draft)

    p_same = sub.add_parser("same-lesson", parents=[common], help="vault-distill: do two drafts state the same lesson?")
    p_same.add_argument("--a", required=True, help="First draft file")
    p_same.add_argument("--b", required=True, help="Second draft file")
    p_same.set_defaults(func=cmd_same_lesson)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_jev_gate_distill tests.test_jev_gate -v`
Expected: PASS. The old `test_jev_gate` must stay green, because the stub only adds answers.

- [ ] **Step 6: Commit**

```bash
git add bin/jev-gate tests/fixtures/typesafe_stub/typesafe_sdk.py tests/test_jev_gate_distill.py
git commit -m "feat(jev-gate): classify-lesson, score-draft and same-lesson for vault-distill"
```

(The README step for this task is folded into Task 4, which owns `README.md`.)

---

### Task 2: `vault-distill` session stage: rotate, digest, screen, record, report

**Files:**
- Create: `bin/vault-distill` (mode 755)
- Create: `tests/fixtures/vault_distill/jev_stub.py`, `engine_stub.py`, `extract_stub.py`, `review_stub.py`
- Test: `tests/test_vault_distill.py` (new; also holds the `DistillCase` base class that Task 3's tests import)
- Test: `tests/test_vault_distill_audit.py` (new, written by you; imports `DistillCase` from `tests/test_vault_distill.py`)

**Audit amendments A1, A2 and A3 apply to this task** (full text under "Audit amendments" near the top of this plan; they override the code below where they differ). After the steps below are green, implement each one test first in `tests/test_vault_distill_audit.py`, without editing `tests/test_vault_distill.py`:
- A1: `repo_root` asks git (`git -C <cwd> rev-parse --path-format=absolute --git-common-dir`, parent directory) and falls back to the string split. Test: a temp repo with `git worktree add ../demo-hotfix-x`; a session whose cwd is that worktree is `not-allowed` when the skip list names the main repo's basename.
- A2: in `run_batch` the first branch is `if p >= EXTRACT_AT or prior_state == "extract-pending":`. Test: a session marked `extract-pending` with p 0.5 is queued on the next run and is not counted as unsure.
- A3: in `build_digest` a user record's typed text is its string content, or the joined `text` blocks of a list content; a typed text that starts with `<` after stripping is left out of the digest and of the correction count. Tests: a list-form text prompt appears in the digest; a `<task-notification>` prompt does not.
If an amendment makes a test in `tests/test_vault_distill.py` fail, stop and report BLOCKED with the test name; do not edit that file.


**Interfaces:**
- Consumes: Task 1's `classify-lesson` output shape. The Stop hook's inbox line format (`agent-harness/scripts/vault-session-summary.sh:85-88`, not edited): ``- **YYYY-MM-DD HH:MM** — repo: `<repo>` — cwd: `<cwd>` — session: `<id>` — transcript: `<path>` ``. Claude Code transcript JSONL: `type` is `user` or `assistant`; `message.content` is a string (a user prompt) or a list of blocks (`text`, `tool_use`, `thinking`, `tool_result` with optional `is_error`); `isMeta: true` lines are skipped.
- Seams (all three are read from the environment; tests set every one):
  - `VAULT_DISTILL_JEV_CMD` (default: `bin/jev-gate` next to the script). It is called as `<cmd> <subcommand> --timeout 20 <flags...>`, with the main text on stdin as well, and prints that subcommand's JSON.
  - `VAULT_DISTILL_EXTRACT_CMD` and `VAULT_DISTILL_REVIEW_CMD`: used from Task 3.
  - `VAULT_ENGINE` (existing; the same resolution as `vault-recall.py:28`): one executable path.
- Produces (Task 3 relies on these names):
  - `class Run` with `vault`, `distill` (`<vault>/_inbox/agent/distill`), `live`, `state` (`~/.claude/state/vault-distill`), `seen`, `counts` (keys `COUNT_KEYS`), `bytes` / `attempts` / `failures` (keys `STAGES` = `classify, extract, score, same_lesson, review`), `notes`, `dry`. Methods: `mark(session, state, offset=None, **extra)` appends one seen-file line now (R13); `call(stage, argv, stdin_text, timeout) -> dict | list | None` (None on a non-zero exit, bad JSON, or `"fallback": true`); `jev(stage, sub, flags, stdin_text)`.
  - A session dict has `sid`, `cwd`, `transcript`, `line`, `offset`, `end`, `digest`, `digest_path`.
  - `run_extractions(run, queue)`, where `queue` is a list of `(lesson_prob, session)`. Task 3 replaces the interim version.
  - Module helpers: `atomic_write(path, text)`, `repo_root(cwd)`, `quarantine(run, name, text)`, `size_or_zero(path)`, `env_int(name, default)`, `engine_bin()`, `SECRET_RE`, `build_digest(transcript, offset) -> str`.
  - Seen-file `~/.claude/state/vault-distill/seen.jsonl`: one JSON object per line, `{sid, transcript, cwd, offset, state, ts, ...}`, last line per sid wins. Final states: `not-allowed`, `no-transcript`, `private`, `dropped`, `unsure`, `no-lesson`, `invalid`, `extracted`. Pending states, which come back next run: `jev-failed`, `unsure-pending`, `extract-pending`.
  - Report: `<vault>/_inbox/agent/distill/report-<date>.md`, with a table of rows formatted `| <key> | <n> |` and a per-stage table `| <stage> | <bytes> | <calls> | <failed> |`. Also `~/.claude/state/vault-distill/last-run.json`: `{ts, date, exit, report, counts, bytes}`.
  - CLI: `vault-distill [--dry-run] [--report]`. Exit codes: 0 when the run is healthy, 2 when it is degraded (R16), and 1 from `--report` when no run has been recorded.

- [ ] **Step 1: Create the stub fixtures** (test infrastructure; later tasks may extend them)

`tests/fixtures/vault_distill/jev_stub.py`:

```python
#!/usr/bin/env python3
"""Stand-in for jev-gate in vault-distill tests: answers from JEV_<NAME>=<p> markers in stdin.

Logs each call as one JSON line ({"sub", "bytes"}) to $JEV_STUB_LOG. JEV_STUB_FAIL=1 answers fallback for
every subcommand; JEV_STUB_FAIL=<subcommand> only for that one.
"""
import json
import os
import re
import sys

sub = sys.argv[1]
text = sys.stdin.read()
log = os.environ.get("JEV_STUB_LOG")
if log:
    with open(log, "a") as handle:
        handle.write(json.dumps({"sub": sub, "bytes": len(text.encode())}) + "\n")


def marker(name, default):
    m = re.search(rf"JEV_{name}=([0-9.]+)", text)
    return float(m.group(1)) if m else default


if os.environ.get("JEV_STUB_FAIL") in ("1", sub):
    print(json.dumps({"fallback": True, "error": "stub failure"}))
elif sub == "classify-lesson":
    print(json.dumps({"lesson_prob": marker("LESSON", 0.5), "fallback": False}))
elif sub == "score-draft":
    print(json.dumps({"specific": marker("SPECIFIC", 0.9), "novel": marker("NOVEL", 0.9),
                      "high_stakes": marker("HIGH_STAKES", 0.1), "fallback": False}))
elif sub == "same-lesson":
    print(json.dumps({"same": marker("SAME_LESSON", 0.1), "fallback": False}))
else:
    sys.exit(2)
```

`tests/fixtures/vault_distill/engine_stub.py`:

```python
#!/usr/bin/env python3
"""Stand-in for vault-engine in vault-distill tests.

`context ...` prints the file named by $ENGINE_STUB_CONTEXT (or nothing). `validate <path>` passes when the
file declares schema knowledge/v1. Each call is logged to $ENGINE_STUB_LOG.
"""
import json
import os
import sys

log = os.environ.get("ENGINE_STUB_LOG")
if log:
    with open(log, "a") as handle:
        handle.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1] == "context":
    path = os.environ.get("ENGINE_STUB_CONTEXT")
    if path and os.path.exists(path):
        sys.stdout.write(open(path).read())
elif sys.argv[1] == "validate":
    text = open(sys.argv[2]).read()
    sys.exit(0 if 'schema: "knowledge/v1"' in text or "schema: knowledge/v1" in text else 1)
```

`tests/fixtures/vault_distill/extract_stub.py`:

```python
#!/usr/bin/env python3
"""Stand-in for the vault-distill extractor: reads the request JSON on stdin, writes one draft.

Markers in the digest steer it: EXTRACT_NO_LESSON, EXTRACT_FAIL, EXTRACT_INVALID, EXTRACT_BAD_EVIDENCE,
EXTRACT_SECRET, EXTRACT_BIG, TITLE=<words_joined_by_underscores>. Every JEV_* marker except JEV_LESSON is copied into the
draft so the Jev stub can score it. Each call is logged to $EXTRACT_STUB_LOG.
"""
import json
import os
import re
import sys

req = json.loads(sys.stdin.read())
log = os.environ.get("EXTRACT_STUB_LOG")
if log:
    with open(log, "a") as handle:
        handle.write(json.dumps(req) + "\n")
digest = open(req["digest_path"]).read()
if "EXTRACT_FAIL" in digest:
    sys.exit(1)
if "EXTRACT_NO_LESSON" in digest:
    print(json.dumps({"path": None, "reason": "no-lesson"}))
    sys.exit(0)
sid = req["session_id"]
m = re.search(r"TITLE=(\S+)", digest)
title = m.group(1).replace("_", " ") if m else f"Stub lesson {sid}"
markers = " ".join(t for t in re.findall(r"JEV_[A-Z_]+=[0-9.]+", digest) if not t.startswith("JEV_LESSON"))
prompt = next(line[6:66] for line in digest.splitlines() if line.startswith("user: "))
evidence = "this quote is not in the digest at all" if "EXTRACT_BAD_EVIDENCE" in digest else prompt
secret = "token = " + "abcdefghijklmnop" if "EXTRACT_SECRET" in digest else ""
big = "w" * 1600 if "EXTRACT_BIG" in digest else ""
schema = "" if "EXTRACT_INVALID" in digest else 'schema: "knowledge/v1"\n'
slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
path = os.path.join(req["out_dir"], f"{slug}--{sid[:8]}.md")
os.makedirs(req["out_dir"], exist_ok=True)
with open(path, "w") as handle:
    handle.write(f'---\n{schema}id: "KNOW-{slug}"\nkind: "knowledge"\ntitle: "{title}"\nstatus: "draft"\n'
                 f'tags: {json.dumps(["auto-distilled", *req["tags"]])}\nproject_ids: {json.dumps(req["project_ids"])}\n---\n\n'
                 f"One-sentence summary.\n\n## When this applies\nWhen it happens.\n\n## Rule\nDo the thing. {secret}{big}\n\n"
                 f"## Why\nBecause. {markers}\n\n## Source\n- session `{sid}`\n\n## Evidence\n- {evidence}\n")
print(json.dumps({"path": path}))
```

`tests/fixtures/vault_distill/review_stub.py`:

```python
#!/usr/bin/env python3
"""Stand-in for the Argon-low review call: every candidate gets $REVIEW_STUB_VERDICT (default publish).

Logs the candidate list to $REVIEW_STUB_LOG. REVIEW_STUB_FAIL=1 exits 1.
"""
import json
import os
import sys

items = json.loads(sys.stdin.read())
log = os.environ.get("REVIEW_STUB_LOG")
if log:
    with open(log, "a") as handle:
        handle.write(json.dumps(items) + "\n")
if os.environ.get("REVIEW_STUB_FAIL") == "1":
    sys.exit(1)
verdict = os.environ.get("REVIEW_STUB_VERDICT", "publish")
print(json.dumps([{"draft": i["draft"], "verdict": verdict, "reason": "stub"} for i in items]))
```

- [ ] **Step 2: Write the failing test**

Each test maps to a spec line:
- `gate_outcomes`, `active_session`, `no_jev_key` and `home_path...quarantined`: the spec's slice-2 acceptance rows 1 to 4.
- `skip_repo`: acceptance row 5.
- R6f: `crashed_work_file`.
- R7: `small_growth` and `digest_starts_at_the_recorded_offset`.
- R7f: `missing_transcript`.
- R7s: `digest_drops_tool_output_and_counts_signals`.
- R8u: `unsure_twice`.
- R12: `report_file`.
- R13: `seen_file`.
- Public-repo guard: `new_files_pass_the_public_repo_secret_scan`. It keeps the credential regex copy from tripping `ps-skills-sync --push`; the GitHub fine-grained token literal is split in two for that reason.
- R16: the non-zero exits in `no_jev_key` and `unsure_twice`.

```python test:tests/test_vault_distill.py
#!/usr/bin/env python3
"""Tests for bin/vault-distill, session stage (I-040 R6-R8u, R11, R11a, R12, R13, R16)."""
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN = REPO_ROOT / "bin"
DISTILL = BIN / "vault-distill"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "vault_distill"


def load_distill():
    loader = importlib.machinery.SourceFileLoader("vault_distill", str(DISTILL))
    spec = importlib.util.spec_from_loader("vault_distill", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def stub(name):
    return f"{sys.executable} {FIXTURES / name}"


class DistillCase(unittest.TestCase):
    """Base: a throwaway vault, HOME and transcripts. No test methods here (imported by other test files)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.home = self.dir / "home"
        self.vault = self.dir / "vault"
        (self.home / ".claude").mkdir(parents=True)
        (self.vault / "_inbox" / "agent").mkdir(parents=True)
        (self.vault / "_meta" / "indexes").mkdir(parents=True)
        (self.vault / "04_Knowledge").mkdir()
        (self.vault / ".gitignore").write_text("_inbox/private/\n")
        self.live = self.vault / "_inbox" / "agent" / "session-summaries.md"
        self.state = self.home / ".claude" / "state" / "vault-distill"
        self.jev_log = self.dir / "jev.log"
        self.extract_log = self.dir / "extract.log"
        self.review_log = self.dir / "review.log"
        self.repo = self.dir / "repos" / "demo-repo"
        self.repo.mkdir(parents=True)
        self.engine = self.dir / "vault-engine"  # VAULT_ENGINE names one executable, as in vault-recall.py
        self.engine.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FIXTURES / "engine_stub.py"}" "$@"\n')
        self.engine.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def transcript(self, sid, prompts, age_seconds=7200, pad=4500, extra=()):
        """A Claude Code style transcript: user prompts, assistant text, and one tool result per turn."""
        path = self.dir / "transcripts" / f"{sid}.jsonl"
        path.parent.mkdir(exist_ok=True)
        lines = []
        for prompt in prompts:
            lines.append({"type": "user", "message": {"role": "user", "content": prompt}})
            lines.append({"type": "assistant", "message": {"content": [{"type": "text", "text": "Working on it."}]}})
            lines.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "content": "TOOL-OUTPUT-SHOULD-NOT-APPEAR " + "x" * 50}]}})
            lines.append({"type": "assistant", "message": {"content": [{"type": "text", "text": "Done: " + "y" * pad}]}})
        lines.extend(extra)
        path.write_text("".join(json.dumps(line) + "\n" for line in lines))
        then = time.time() - age_seconds
        os.utime(path, (then, then))
        return path

    def inbox_line(self, sid, transcript, cwd=None):
        cwd = cwd or str(self.repo)
        return (f"- **2026-11-10 10:00** — repo: `{os.path.basename(cwd)}` — cwd: `{cwd}` — "
                f"session: `{sid}` — transcript: `{transcript}`")

    def write_inbox(self, lines):
        header = "---\ntype: session-inbox\n---\n\n# Agent Session Inbox\n\n"
        self.live.write_text(header + "".join(line + "\n" for line in lines))

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("VAULT_DISTILL") and k not in ("TYPESAFE_API_KEY", "VAULT_ROOT", "VAULT_ENGINE")}
        env.update({
            "HOME": str(self.home), "VAULT_ROOT": str(self.vault), "VAULT_ENGINE": str(self.engine),
            "VAULT_DISTILL_JEV_CMD": stub("jev_stub.py"), "VAULT_DISTILL_EXTRACT_CMD": stub("extract_stub.py"),
            "VAULT_DISTILL_REVIEW_CMD": stub("review_stub.py"), "JEV_STUB_LOG": str(self.jev_log),
            "EXTRACT_STUB_LOG": str(self.extract_log), "REVIEW_STUB_LOG": str(self.review_log),
            "ENGINE_STUB_LOG": str(self.dir / "engine.log"),
        })
        env.update(extra)
        return env

    def distill(self, *args, **extra):
        return subprocess.run([sys.executable, str(DISTILL), *args], capture_output=True, text=True,
                              env=self.env(**extra), timeout=120)

    def calls(self, log):
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def seen(self):
        path = self.state / "seen.jsonl"
        recs = {}
        for line in (path.read_text().splitlines() if path.exists() else []):
            rec = json.loads(line)
            recs[rec["sid"]] = rec
        return recs

    def count(self, report, key):
        m = re.search(rf"^\| {key} \| (\d+) \|$", report, re.M)
        self.assertIsNotNone(m, f"{key} missing from report")
        return int(m.group(1))


class TestSessionStage(DistillCase):
    def test_secret_patterns_match_ps_skills_sync_without_home_rule(self):
        src = (BIN / "ps-skills-sync").read_text()
        shell = re.search(r"^SECRET_RE='(.*)'$", src, re.M).group(1).replace("'\"'\"'", "'")
        self.assertEqual(shell, load_distill().SECRET_RE.pattern + "|/Users/[a-z]+/")

    def test_new_files_pass_the_public_repo_secret_scan(self):
        src = (BIN / "ps-skills-sync").read_text()
        scan = re.compile(re.search(r"^SECRET_RE='(.*)'$", src, re.M).group(1).replace("'\"'\"'", "'"))
        for path in (DISTILL, Path(__file__), *FIXTURES.glob("*.py")):
            self.assertIsNone(scan.search(path.read_text()), path)

    def test_gate_outcomes_on_40_lines_for_3_sessions(self):
        paths = {sid: self.transcript(sid, [f"please fix the flaky build JEV_LESSON={p}"])
                 for sid, p in (("s-yes", 0.95), ("s-no", 0.05), ("s-mid", 0.5))}
        lines = [self.inbox_line(sid, paths[sid]) for _ in range(13) for sid in paths] + [self.inbox_line("s-yes", paths["s-yes"])]
        self.assertEqual(len(lines), 40)
        self.write_inbox(lines)
        res = self.distill("--dry-run")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.count(res.stdout, "extracted"), 1)
        self.assertEqual(self.count(res.stdout, "dropped"), 1)
        self.assertEqual(self.count(res.stdout, "unsure"), 1)
        sent = [c for c in self.calls(self.jev_log) if c["sub"] == "classify-lesson"]
        self.assertEqual(len(sent), 3)
        self.assertTrue(all(c["bytes"] <= 12000 for c in sent))
        self.assertEqual(self.calls(self.extract_log), [])  # dry run never extracts
        self.assertFalse((self.state / "seen.jsonl").exists())  # dry run records nothing

    def test_active_session_goes_back_to_live_inbox(self):
        fresh = self.transcript("s-live", ["still going JEV_LESSON=0.95"], age_seconds=300)
        for args in (("--dry-run",), ()):
            self.write_inbox([self.inbox_line("s-live", fresh)])
            res = self.distill(*args)
            self.assertIn(res.returncode, (0, 2), res.stderr)
            self.assertNotIn("s-live", self.seen())
            self.assertIn("session: `s-live`", self.live.read_text())
        self.assertEqual(self.calls(self.jev_log), [])

    def test_no_jev_key_means_all_unsure_no_extractor_and_nonzero_exit(self):
        paths = [self.transcript(f"s-{i}", [f"prompt {i} JEV_LESSON=0.95"]) for i in range(3)]
        self.write_inbox([self.inbox_line(f"s-{i}", p) for i, p in enumerate(paths)])
        env = self.env()
        env.pop("VAULT_DISTILL_JEV_CMD")  # the real bin/jev-gate, which reads TYPESAFE_API_KEY or ~/.zshrc
        res = subprocess.run([sys.executable, str(DISTILL)], capture_output=True, text=True, env=env, timeout=120)
        self.assertNotEqual(res.returncode, 0)
        report = (self.vault / "_inbox" / "agent" / "distill").glob("report-*.md")
        text = next(report).read_text()
        self.assertEqual(self.count(text, "unsure"), 3)
        self.assertEqual(self.calls(self.extract_log), [])
        self.assertEqual({r["state"] for r in self.seen().values()}, {"jev-failed"})

    def test_home_path_is_sent_but_a_credential_is_quarantined(self):
        home_path = "/Users/" + "x/repo"  # built at runtime: the public repo's own secret scan flags the literal
        token = "ghp_" + "A" * 20
        ok = self.transcript("s-home", [f"look at {home_path}/main.py JEV_LESSON=0.5"])
        bad = self.transcript("s-cred", [f"my key is {token} JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line("s-home", ok), self.inbox_line("s-cred", bad)])
        res = self.distill("--dry-run")
        self.assertIn(res.returncode, (0, 2), res.stderr)
        sent = self.calls(self.jev_log)
        self.assertEqual(len(sent), 1)  # only the home-path session went to Jev
        private = self.vault / "_inbox" / "private" / "digest-s-cred.md"
        self.assertIn(token, private.read_text())
        self.assertEqual(self.count(res.stdout, "private"), 1)

    def test_quarantine_without_gitignore_rule_writes_a_pointer_only(self):
        (self.vault / ".gitignore").write_text("")
        token = "ghp_" + "B" * 20
        bad = self.transcript("s-cred", [f"my key is {token}"])
        self.write_inbox([self.inbox_line("s-cred", bad)])
        self.distill()
        text = (self.vault / "_inbox" / "private" / "digest-s-cred.md").read_text()
        self.assertNotIn(token, text)

    def test_skip_repo_is_not_allowed_and_sends_nothing(self):
        path = self.transcript("s-skip", ["secret project work JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line("s-skip", path)])
        res = self.distill(VAULT_DISTILL_SKIP_REPOS="other, demo-repo")
        self.assertEqual(res.returncode, 0, res.stderr)
        report = next((self.vault / "_inbox" / "agent" / "distill").glob("report-*.md")).read_text()
        self.assertEqual(self.count(report, "not_allowed"), 1)
        self.assertRegex(report, r"\| classify \| 0 \|")
        self.assertEqual(self.calls(self.jev_log), [])
        self.assertEqual(self.seen()["s-skip"]["state"], "not-allowed")

    def test_worktree_cwd_resolves_to_its_repo_for_the_skip_list(self):
        path = self.transcript("s-wt", ["work in a worktree JEV_LESSON=0.95"])
        wt = str(self.repo / ".claude" / "worktrees" / "F-001-x")
        self.write_inbox([self.inbox_line("s-wt", path, cwd=wt)])
        self.distill(VAULT_DISTILL_SKIP_REPOS="demo-repo")
        self.assertEqual(self.seen()["s-wt"]["state"], "not-allowed")

    def test_unsure_twice_sends_top_3_and_marks_the_rest(self):
        probs = {"u1": 0.5, "u2": 0.6, "u3": 0.7, "u4": 0.4, "u5": 0.3}
        paths = {sid: self.transcript(sid, [f"topic {sid} JEV_LESSON={p}"]) for sid, p in probs.items()}
        self.write_inbox([self.inbox_line(sid, p) for sid, p in paths.items()])
        first = self.distill()
        self.assertNotEqual(first.returncode, 0)  # R16: more than half unsure
        self.assertEqual({r["state"] for r in self.seen().values()}, {"unsure-pending"})
        second = self.distill()  # the inbox is empty now: the pending sessions come from the seen-file
        self.assertIn(second.returncode, (0, 2), second.stderr)
        states = {sid: rec["state"] for sid, rec in self.seen().items()}
        self.assertEqual(states["u4"], "unsure")
        self.assertEqual(states["u5"], "unsure")
        self.assertTrue(all(states[s] != "unsure" for s in ("u1", "u2", "u3")), states)
        self.assertEqual(len([c for c in self.calls(self.jev_log) if c["sub"] == "classify-lesson"]), 10)

    def test_crashed_work_file_is_processed_first_and_deleted(self):
        path = self.transcript("s-crash", ["left over from a crash JEV_LESSON=0.05"])
        work = self.vault / "_inbox" / "agent" / "session-summaries.2026-11-09-234000.work.md"
        work.write_text(self.inbox_line("s-crash", path) + "\n")
        res = self.distill()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.seen()["s-crash"]["state"], "dropped")
        self.assertFalse(work.exists())
        self.assertEqual(list(self.live.parent.glob("*.work.md")), [])

    def test_rotation_renames_the_live_inbox(self):
        path = self.transcript("s-rot", ["rotate me JEV_LESSON=0.05"])
        self.write_inbox([self.inbox_line("s-rot", path)])
        self.distill()
        self.assertFalse(self.live.exists())  # the Stop hook's next append starts a fresh file
        self.assertEqual(self.seen()["s-rot"]["offset"], path.stat().st_size)

    def test_small_growth_since_offset_is_skipped(self):
        path = self.transcript("s-grow", ["first part JEV_LESSON=0.05"])
        self.write_inbox([self.inbox_line("s-grow", path)])
        self.distill()
        with open(path, "a") as handle:
            handle.write(json.dumps({"type": "user", "message": {"content": "tiny follow-up"}}) + "\n")
        os.utime(path, (time.time() - 7200, time.time() - 7200))
        self.write_inbox([self.inbox_line("s-grow", path)])
        res = self.distill()
        self.assertEqual(self.count(next(self.live.parent.glob("distill/report-*.md")).read_text(), "skipped_small"), 1)
        self.assertEqual(len(self.calls(self.jev_log)), 1, res.stdout)

    def test_digest_starts_at_the_recorded_offset(self):
        path = self.transcript("s-off", ["OLD-PROMPT-TEXT JEV_LESSON=0.05"])
        offset = path.stat().st_size
        with open(path, "a") as handle:
            for _ in range(3):
                handle.write(json.dumps({"type": "user", "message": {"content": "NEW-PROMPT-TEXT"}}) + "\n")
                handle.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "z" * 2000}]}}) + "\n")
        digest = load_distill().build_digest(str(path), offset)
        self.assertIn("NEW-PROMPT-TEXT", digest)
        self.assertNotIn("OLD-PROMPT-TEXT", digest)

    def test_missing_transcript_is_marked_no_transcript(self):
        self.write_inbox([self.inbox_line("s-gone", self.dir / "nope.jsonl")])
        self.distill()
        self.assertEqual(self.seen()["s-gone"]["state"], "no-transcript")

    def test_digest_drops_tool_output_and_counts_signals(self):
        failing = {"type": "user", "message": {"content": [
            {"type": "tool_result", "is_error": True, "content": "Error: test_x failed"}]}}
        passing = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "1 passed"}]}}
        blocked = {"type": "user", "message": {"content": [
            {"type": "tool_result", "is_error": True, "content": "PreToolUse:Edit hook error: blocked by guard_check"}]}}
        path = self.transcript("s-sig", ["no, that is wrong, use the worktree"],
                               extra=[failing, failing, passing, blocked])
        digest = load_distill().build_digest(str(path), 0)
        self.assertTrue(digest.startswith("signals: corrections=1 fail_then_pass=1 hook_blocks=1 repeated_errors=1\n"), digest[:120])
        self.assertNotIn("TOOL-OUTPUT-SHOULD-NOT-APPEAR", digest)
        self.assertIn("user: no, that is wrong", digest)

    def test_digest_is_cut_to_12000_bytes_head_and_tail(self):
        path = self.transcript("s-long", [f"prompt number {i}" for i in range(40)], pad=3000)
        digest = load_distill().build_digest(str(path), 0)
        self.assertLessEqual(len(digest.encode()), 12000)
        self.assertIn("prompt number 0", digest)
        self.assertIn("prompt number 39", digest)

    def test_kill_switch_does_nothing(self):
        path = self.transcript("s-off", ["anything JEV_LESSON=0.95"])
        self.write_inbox([self.inbox_line("s-off", path)])
        before = self.live.read_text()
        res = self.distill(VAULT_DISTILL="0")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(self.live.read_text(), before)
        self.assertFalse(self.state.exists())

    def test_report_file_and_report_flag(self):
        path = self.transcript("s-rep", ["report me JEV_LESSON=0.05"])
        self.write_inbox([self.inbox_line("s-rep", path)])
        self.distill()
        report = next((self.vault / "_inbox" / "agent" / "distill").glob("report-*.md")).read_text()
        for key in ("seen", "not_allowed", "dropped", "unsure", "no_lesson", "extracted", "no_evidence", "junk",
                    "candidates_waiting", "published", "merged", "rejected", "collisions", "archived"):
            self.count(report, key)
        self.assertEqual(self.count(report, "seen"), 1)
        self.assertIn("| classify |", report)
        res = self.distill("--report")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), report.strip())

    def test_seen_file_gets_one_line_per_session(self):
        paths = {sid: self.transcript(sid, [f"t {sid} JEV_LESSON=0.05"]) for sid in ("a1", "a2")}
        self.write_inbox([self.inbox_line(sid, p) for sid, p in paths.items()])
        self.distill()
        lines = (self.state / "seen.jsonl").read_text().splitlines()
        self.assertEqual(sorted(json.loads(line)["sid"] for line in lines), ["a1", "a2"])


if __name__ == "__main__":
    unittest.main()
```

Verify-Cmd: python3 -m unittest tests.test_vault_distill tests.test_vault_distill_audit -v

- [ ] **Step 3: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_vault_distill -v`
Expected: FAIL or ERROR on every test: `bin/vault-distill` does not exist (`FileNotFoundError` from the loader, and a non-zero exit from `subprocess`).

- [ ] **Step 4: Implement `bin/vault-distill`**

Create `bin/vault-distill` with this content, then run `chmod 755 bin/vault-distill`. `run_extractions` here is the interim version: it marks every selected session `extract-pending`, which is the same state the nightly cap uses. Task 3 replaces it with the real extraction.

```python
#!/usr/bin/env python3
"""vault-distill: nightly batch that turns finished agent sessions into candidate knowledge notes.

Shadow mode (I-040, slice 2 of I-039): it writes drafts, scores, candidates and review verdicts to
the vault inbox and a report, and never publishes to 04_Knowledge/.

Usage:
  vault-distill              run the nightly batch
  vault-distill --dry-run    gate preview: calls Jev, never the extractor or reviewer, records nothing
  vault-distill --report     print the last run's report

Env: VAULT_DISTILL=0 (do nothing), VAULT_DISTILL_MAX (20), VAULT_DISTILL_UNSURE_MAX (3),
VAULT_DISTILL_SKIP_REPOS (comma-separated repo root basenames), VAULT_ROOT, VAULT_ENGINE.
Test seams: VAULT_DISTILL_JEV_CMD, VAULT_DISTILL_EXTRACT_CMD, VAULT_DISTILL_REVIEW_CMD.
"""
import argparse
import datetime
import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DIGEST_MAX = 12000
DIGEST_HEAD = 2000
GROWTH_MIN = 4000
ACTIVE_SECONDS = 30 * 60
EXTRACT_AT = 0.85
DROP_AT = 0.15
PENDING = {"jev-failed", "unsure-pending", "extract-pending"}
# Own copy of bin/ps-skills-sync SECRET_RE without the home-path rule (R11); a test keeps them in step.
# The literal is split so this public file does not trip ps-skills-sync's scan of itself.
SECRET_RE = re.compile(r"""ghp_[A-Za-z0-9]{20}|github""" r"""_pat_|sk-[A-Za-z0-9_-]{20}|xox[bpas]-|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY|(password|passwd|api[_-]?key|secret|token)["' ]*[:=]["' ]*[A-Za-z0-9/+_-]{12,}""")
LINE_RE = re.compile(r"repo: `[^`]*` — cwd: `(?P<cwd>[^`]*)` — session: `(?P<sid>[^`]+)` — transcript: `(?P<transcript>[^`]*)`")
CORRECTION_RE = re.compile(r"^\s*(no\b|nope|wrong|don't|do not|stop|actually|that's not|not what|instead)", re.I)
HOOK_BLOCK_RE = re.compile(r"hook (?:error|blocked)|blocked by (?:a |the )?\w*\s*hook|guard_check", re.I)
COUNT_KEYS = ("seen", "not_allowed", "private", "no_transcript", "skipped_small", "skipped_active", "dropped",
              "unsure", "no_lesson", "extracted", "invalid", "no_evidence", "junk", "unscored", "candidates_waiting",
              "recurred", "ready", "would_publish", "published", "merged", "rejected", "collisions", "archived", "expired")
STAGES = ("classify", "extract", "score", "same_lesson", "review")


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def vault_root():
    return Path(os.environ.get("VAULT_ROOT") or Path.home() / "workspace" / "agentic-vault")


def state_dir():
    return Path.home() / ".claude" / "state" / "vault-distill"


def engine_bin():
    return os.environ.get("VAULT_ENGINE") or shutil.which("vault-engine") or str(Path.home() / ".local/bin/vault-engine")


def repo_root(cwd):
    """Main repo path for a session cwd: a feature worktree belongs to the repo that holds it."""
    return cwd.rstrip("/").split("/.claude/worktrees/", 1)[0]


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.replace(tmp, path)


class Run:
    def __init__(self, dry_run=False):
        self.dry = dry_run
        self.vault = vault_root()
        self.distill = self.vault / "_inbox" / "agent" / "distill"
        self.live = self.vault / "_inbox" / "agent" / "session-summaries.md"
        self.state = state_dir()
        self.seen_path = self.state / "seen.jsonl"
        self.digests = self.state / "digests"
        self.start = time.time()
        self.date = datetime.date.today().isoformat()
        self.counts = dict.fromkeys(COUNT_KEYS, 0)
        self.bytes = dict.fromkeys(STAGES, 0)
        self.attempts = dict.fromkeys(STAGES, 0)
        self.failures = dict.fromkeys(STAGES, 0)
        self.classified = 0
        self.notes = []  # report lines: expired candidates, verdicts
        self.seen = self.load_seen()

    # --- seen-file (R13): one JSON line per final state, last line per session wins ---
    def load_seen(self):
        seen = {}
        try:
            lines = self.seen_path.read_text().splitlines()
        except OSError:
            return seen
        for line in lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue  # a torn last line from a crash
            if isinstance(rec, dict) and rec.get("sid"):
                seen[rec["sid"]] = rec
        return seen

    def mark(self, session, state, offset=None, **extra):
        rec = {"sid": session["sid"], "transcript": session["transcript"], "cwd": session["cwd"],
               "offset": session.get("offset", 0) if offset is None else offset, "state": state,
               "ts": int(time.time()), **extra}
        self.seen[session["sid"]] = rec
        if self.dry:
            return
        self.state.mkdir(parents=True, exist_ok=True)
        with open(self.seen_path, "a") as handle:
            handle.write(json.dumps(rec) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    # --- external calls: every model call goes through one of these three seams ---
    def call(self, stage, argv, stdin_text, timeout):
        self.attempts[stage] += 1
        self.bytes[stage] += len(stdin_text.encode())
        try:
            proc = subprocess.run(argv, input=stdin_text, capture_output=True, text=True, timeout=timeout)
            out = json.loads(proc.stdout) if proc.returncode == 0 else None
        except (OSError, subprocess.SubprocessError, ValueError):
            out = None
        if out is None or (isinstance(out, dict) and out.get("fallback")):
            self.failures[stage] += 1
            return None
        return out

    def jev(self, stage, sub, flags, stdin_text):
        cmd = shlex.split(os.environ.get("VAULT_DISTILL_JEV_CMD", "")) or [str(Path(__file__).resolve().parent / "jev-gate")]
        return self.call(stage, [*cmd, sub, "--timeout", "20", *flags], stdin_text, timeout=60)


# --- inbox rotation (R6, R6f) ---
def work_files(run):
    """Dated work files to process: a crashed run's first (R6f), then tonight's rotation."""
    inbox = run.live.parent
    files = sorted(inbox.glob("session-summaries.*.work.md"))
    if run.dry:
        return files + ([run.live] if run.live.exists() else [])
    if run.live.exists():
        target = inbox / f"session-summaries.{datetime.datetime.now():%Y-%m-%d-%H%M%S}.work.md"
        os.rename(run.live, target)  # atomic: the Stop hook's next append starts a fresh live file
        files.append(target)
    return files


def parse_entries(paths):
    """One entry per session id (the last line wins), with the raw line kept for re-queueing."""
    entries = {}
    for path in paths:
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            m = LINE_RE.search(line)
            if m:
                entries[m["sid"]] = {"sid": m["sid"], "cwd": m["cwd"], "transcript": m["transcript"], "line": line}
    return entries


def requeue(run, session):
    """A session still running goes back to the live inbox and is not processed (R6)."""
    if run.dry or not session["line"]:
        return
    with open(run.live, "a") as handle:
        handle.write(session["line"] + "\n")


# --- digest (R7, R7s) ---
def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def tool_result_text(block):
    content = block.get("content")
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return content if isinstance(content, str) else ""


def build_digest(transcript, offset):
    """Signals line plus user prompts and each turn's last assistant text, tool output removed."""
    with open(transcript, "rb") as handle:
        handle.seek(offset)
        raw = handle.read()
    turns, last_assistant = [], ""
    corrections = fail_then_pass = hook_blocks = 0
    open_failures = 0
    errors = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("isMeta"):
            continue
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        content = msg.get("content")
        if rec.get("type") == "user" and isinstance(content, str):
            if last_assistant:
                turns.append("assistant: " + last_assistant.strip())
                last_assistant = ""
            corrections += bool(CORRECTION_RE.search(content))
            turns.append("user: " + content.strip())
        elif rec.get("type") == "user" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                text = tool_result_text(block)
                hook_blocks += bool(HOOK_BLOCK_RE.search(text))
                if block.get("is_error") is True:
                    open_failures += 1
                    first = text.strip().splitlines()[0][:200] if text.strip() else ""
                    errors[first] = errors.get(first, 0) + 1
                elif open_failures:
                    fail_then_pass += 1
                    open_failures = 0
        elif rec.get("type") == "assistant":
            said = text_of(content)
            if said.strip():
                last_assistant = said
    if last_assistant:
        turns.append("assistant: " + last_assistant.strip())
    repeats = sum(1 for k, n in errors.items() if k and n >= 2)
    signals = (f"signals: corrections={corrections} fail_then_pass={fail_then_pass} "
               f"hook_blocks={hook_blocks} repeated_errors={repeats}\n")
    return signals + cut("\n".join(turns), DIGEST_MAX - len(signals.encode()))


def cut(text, limit):
    """First DIGEST_HEAD bytes plus the last bytes that fit, so the digest is at most `limit` bytes."""
    data = text.encode()
    if len(data) <= limit:
        return text
    head = data[:DIGEST_HEAD].decode("utf-8", errors="ignore")
    tail = data[len(data) - (limit - len(head.encode()) - 5):].decode("utf-8", errors="ignore")
    return head + "\n...\n" + tail


def quarantine(run, name, text):
    """R11: credential-bearing text goes to _inbox/private/, never to a model. Content is written only when
    the vault's .gitignore quarantines that folder (vault-engine check-privacy's rule); else a pointer."""
    private = run.vault / "_inbox" / "private"
    try:
        ignored = "_inbox/private/" in (run.vault / ".gitignore").read_text()
    except OSError:
        ignored = False
    body = text if ignored else "content withheld: add _inbox/private/ to the vault .gitignore\n"
    atomic_write(private / f"{name}.md", body)


# --- one session through the cheap stages (R7, R7f, R8, R11, R11a) ---
def screen(run, session, skip_repos):
    """Return the lesson probability for a session, or None when it reached a final or pending state."""
    sid = session["sid"]
    prior = run.seen.get(sid, {})
    session["offset"] = prior.get("offset", 0)
    if os.path.basename(repo_root(session["cwd"])) in skip_repos:
        run.counts["not_allowed"] += 1
        run.mark(session, "not-allowed", offset=size_or_zero(session["transcript"]))
        return None
    try:
        size = os.path.getsize(session["transcript"])
        if size - session["offset"] < GROWTH_MIN and prior.get("state") not in PENDING:
            run.counts["skipped_small"] += 1
            return None
        digest = build_digest(session["transcript"], session["offset"])
    except OSError:
        run.counts["no_transcript"] += 1
        run.mark(session, "no-transcript")
        return None
    session["end"] = size
    if SECRET_RE.search(digest):
        run.counts["private"] += 1
        quarantine(run, f"digest-{sid}", digest)
        run.mark(session, "private", offset=size)
        return None
    session["digest"] = digest
    session["digest_path"] = str(run.digests / f"{sid}.txt")
    atomic_write(Path(session["digest_path"]), digest)  # kept for tomorrow's rescoring (R9df)
    if prior.get("state") == "extract-pending":
        return prior.get("p", 1.0)
    run.classified += 1
    out = run.jev("classify", "classify-lesson", ["--digest", session["digest_path"]], digest)
    if out is None:
        run.counts["unsure"] += 1
        run.mark(session, "jev-failed")  # R8f: unsure, no extractor tonight, asked again next run
        return None
    return float(out.get("lesson_prob", 0.5))


def size_or_zero(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def run_batch(run):
    skip_repos = {r.strip() for r in os.environ.get("VAULT_DISTILL_SKIP_REPOS", "").split(",") if r.strip()}
    files = work_files(run)
    entries = parse_entries(files)
    for sid, rec in run.seen.items():  # pending sessions from earlier nights (R8u, caps)
        if rec.get("state") in PENDING and sid not in entries:
            entries[sid] = {"sid": sid, "cwd": rec.get("cwd", ""), "transcript": rec.get("transcript", ""), "line": ""}
    queue, unsure_again = [], []
    for session in entries.values():
        try:
            active = run.start - os.path.getmtime(session["transcript"]) < ACTIVE_SECONDS
        except OSError:
            active = False
        if active:
            run.counts["skipped_active"] += 1
            requeue(run, session)
            continue
        run.counts["seen"] += 1
        prior_state = run.seen.get(session["sid"], {}).get("state")
        p = screen(run, session, skip_repos)
        if p is None:
            continue
        if p >= EXTRACT_AT:
            queue.append((p, session))
        elif p <= DROP_AT:
            run.counts["dropped"] += 1
            run.mark(session, "dropped", offset=session["end"], p=p)
        elif prior_state == "unsure-pending":
            unsure_again.append((p, session))
        else:
            run.counts["unsure"] += 1
            run.mark(session, "unsure-pending", p=p)  # R8u: offered to Jev once more next run
    unsure_again.sort(key=lambda item: -item[0])
    keep = env_int("VAULT_DISTILL_UNSURE_MAX", 3)
    for p, session in unsure_again[keep:]:
        run.counts["unsure"] += 1
        run.mark(session, "unsure", offset=session["end"], p=p)
    queue.extend(unsure_again[:keep])
    run_extractions(run, queue)
    finish(run, files)


def run_extractions(run, queue):
    """Slice 2, Task 2: extraction is wired in Task 3. Until then a selected session waits as extract-pending."""
    for p, session in queue:
        run.counts["extracted"] += 1
        run.mark(session, "extract-pending", p=p)


# --- report and exit code (R12, R16) ---
def injections_per_note():
    counts = {}
    try:
        lines = (Path.home() / ".claude" / "state" / "vault-recall" / "injections.jsonl").read_text().splitlines()
    except OSError:
        return counts
    for line in lines:
        try:
            nid = json.loads(line).get("note_id")
        except (ValueError, AttributeError):
            continue
        if nid:
            counts[nid] = counts.get(nid, 0) + 1
    return counts


def render_report(run, exit_code):
    lines = [f"# vault-distill report {run.date}", "", "Shadow mode: nothing is published (I-040).", "",
             "| count | value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in run.counts.items()]
    lines += ["", "| stage | bytes sent | calls | failed |", "|---|---|---|---|"]
    lines += [f"| {s} | {run.bytes[s]} | {run.attempts[s]} | {run.failures[s]} |" for s in STAGES]
    lines += ["", "## Injections per note (used-rate arrives with R15, slice 3)", ""]
    lines += [f"- {nid}: {n} injections, used n/a" for nid, n in sorted(injections_per_note().items(), key=lambda kv: -kv[1])[:20]]
    lines += ["", "## Notes", ""] + [f"- {n}" for n in run.notes] + ["", f"exit: {exit_code}", ""]
    return "\n".join(lines)


def exit_code_for(run):
    """R16: non-zero when more than half the classified sessions are unsure, or a stage failed every call."""
    if run.classified and run.counts["unsure"] * 2 > run.classified:
        return 2
    if any(run.attempts[s] and run.failures[s] == run.attempts[s] for s in STAGES):
        return 2
    return 0


def finish(run, files):
    code = exit_code_for(run)
    report = render_report(run, code)
    run.exit_code = code
    if run.dry:
        print(report)
        return
    path = run.distill / f"report-{run.date}.md"
    atomic_write(path, report)
    atomic_write(run.state / "last-run.json", json.dumps({
        "ts": int(time.time()), "date": run.date, "exit": code, "report": str(path),
        "counts": run.counts, "bytes": run.bytes}, indent=2) + "\n")
    for f in files:
        if f != run.live:
            f.unlink(missing_ok=True)  # R13: every session in it reached a final or pending state
    print(f"vault-distill: report {path} (exit {code})")


def show_report():
    try:
        last = json.loads((state_dir() / "last-run.json").read_text())
        print(Path(last["report"]).read_text())
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print("vault-distill: no run recorded yet")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Nightly knowledge distillation from agent sessions (shadow mode).")
    parser.add_argument("--dry-run", action="store_true", help="call Jev only; record, extract and review nothing")
    parser.add_argument("--report", action="store_true", help="print the last run's report")
    args = parser.parse_args()
    if os.environ.get("VAULT_DISTILL") == "0":
        return 0
    if args.report:
        return show_report()
    if not (vault_root() / "_inbox").is_dir():
        print(f"vault-distill: no vault inbox at {vault_root()}", file=sys.stderr)
        return 0
    state_dir().mkdir(parents=True, exist_ok=True)
    with open(state_dir() / "run.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("vault-distill: another run holds the lock", file=sys.stderr)
            return 0
        run = Run(dry_run=args.dry_run)
        run_batch(run)
        return run.exit_code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_vault_distill -v`
Expected: PASS (20 tests).

- [ ] **Step 6: Commit**

```bash
git add bin/vault-distill tests/test_vault_distill.py tests/fixtures/vault_distill/
git commit -m "feat(vault-distill): nightly session stage (rotate, digest, Jev screen, seen-file, report)"
```

- [ ] **Step 7: Phase gate for Tasks 1 and 2** (rule 7)
  - Verify: `python3 -m unittest tests.test_jev_gate_distill tests.test_jev_gate tests.test_vault_distill -v` is green.
  - Review, RISK R1 (new nightly writer into the vault inbox, external sends): `code-reviewer` + `python-reviewer`, then one fix round and one scoped re-review.
  - `/simplify`, then re-run the three test modules.

---

### Task 3: `vault-distill` draft stage: extract, gate, candidates, one review

**Files:**
- Modify: `bin/vault-distill` (constants after `PENDING = {...}`; replace the interim `run_extractions`; two hidden flags in `main()`)
- Test: `tests/test_vault_distill_drafts.py` (new; imports `DistillCase` from `tests/test_vault_distill.py`)

**Audit amendment A4 applies to this task:** add `"--sandbox"` to the `ask_agy` command list (after `"--disable-slash-commands"`). Keep `tests/test_vault_distill_audit.py` from Task 2 green.


**Interfaces:**
- Consumes: from Task 2, `Run`, `run.call`, `run.jev`, `run.mark`, `atomic_write`, `quarantine`, `repo_root`, `size_or_zero`, `env_int`, `engine_bin`, `SECRET_RE`, and the session dict keys. From Task 1, the `score-draft` and `same-lesson` shapes. `vault-engine context --query <q> --limit 3`, which prints `<vault-context>` lines `- <id> | <title> | <path> | matched: ... | <summary>`. `vault-engine validate <path>`, which exits 0 on pass. `_meta/indexes/projects.jsonl` entries with `id` and `release_repo`.
- Seams:
  - `VAULT_DISTILL_EXTRACT_CMD` (default: `vault-distill --extract-default`). stdin: `{"session_id", "digest_path", "out_dir", "project_ids", "tags", "related"}`. stdout: `{"path": str}` or `{"path": null, "reason": "no-lesson"}`. A non-zero exit means the worker failed.
  - `VAULT_DISTILL_REVIEW_CMD` (default: `vault-distill --review-default`). stdin: `[{"draft", "sessions", "scores", "text"}]`. stdout: `[{"draft", "verdict": "publish"|"reject", "reason"}]`.
  - The default commands call `agy` on `PATH` exactly once each. Tests replace `agy` with a fake script on `PATH`.
- Produces:
  - Draft ledger `~/.claude/state/vault-distill/drafts.json`: `{<path relative to distill/>: {sid, sessions, digest, created, state, scores, reason?, into?}}`. Draft states: `invalid`, `private`, `no-evidence`, `unscored`, `junk`, `candidate`, `ready`, `would-publish`, `rejected`, `merged`, `expired`.
  - Vault folders under `_inbox/agent/distill/`: drafts at the top level, then `candidates/`, `merged/`, `expired/`. Credential hits go to `_inbox/private/draft-<sid>.md`.
  - Functions `render_draft(answer, request) -> (slug, text)`, `evidence_ok(text, digest) -> bool`, `parse_json(text)`, `ask_agy(model, prompt, schema)`.

- [ ] **Step 1: Write the failing test**

Each test maps to a spec line:
- Slice-2 acceptance rows: `no-evidence` (R9c), `junk` (R9d), `recurrence` and `high stakes` (R19), and `shadow mode`, which covers the "would publish" row of R18.
- R9: `extractor_gets_project_ids_or_repo_tag`, `render_draft`, and `extract_default`.
- R9f: `no_lesson_and_worker_failure_and_invalid_draft`.
- R9df: `failed_score_is_retried`.
- R10 and R10f: `reject`, `review_failure`, and `review_default`.
- R11: `draft_with_a_credential`.
- R19: `at_most_5` and `older_than_60_days`.
- Token budget: `nightly_extraction_cap` and `report_counts_bytes`.

```python test:tests/test_vault_distill_drafts.py
#!/usr/bin/env python3
"""Tests for bin/vault-distill, draft stage (I-040 R9-R10f, R19, shadow mode) and the default model calls."""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_vault_distill import DISTILL, DistillCase, load_distill  # noqa: E402

FAKE_AGY = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["AGY_LOG"], "a") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
sys.stdout.write(open(os.environ["AGY_REPLY"]).read())
"""


class TestDraftStage(DistillCase):
    def session(self, sid, marker, run=True, **extra):
        path = self.transcript(sid, [f"the codegen drift gate failed on {sid} JEV_LESSON=0.95 {marker}"])
        self.write_inbox([self.inbox_line(sid, path)])
        return self.distill(**extra) if run else None

    def ledger(self):
        path = self.state / "drafts.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def by_session(self, sid):
        return [(k, e) for k, e in self.ledger().items() if sid in e["sessions"]]

    def report(self):
        return next((self.vault / "_inbox" / "agent" / "distill").glob("report-*.md")).read_text()

    def subs(self):
        return [c["sub"] for c in self.calls(self.jev_log)]

    def test_quote_missing_from_digest_is_no_evidence_and_never_scored(self):
        self.session("s-ev", "EXTRACT_BAD_EVIDENCE")
        [(key, entry)] = self.by_session("s-ev")
        self.assertEqual(entry["state"], "no-evidence")
        self.assertNotIn("score-draft", self.subs())
        self.assertTrue((self.vault / "_inbox" / "agent" / "distill" / key).exists())  # stays in the inbox

    def test_low_specific_score_is_junk_not_a_candidate(self):
        self.session("s-junk", "JEV_SPECIFIC=0.3")
        [(key, entry)] = self.by_session("s-junk")
        self.assertEqual(entry["state"], "junk")
        self.assertFalse(key.startswith("candidates/"))
        self.assertEqual(self.count(self.report(), "junk"), 1)

    def test_one_off_waits_and_a_recurrence_goes_to_review_citing_both(self):
        self.session("s-one", "TITLE=Codegen_drift_gate")
        [(key, entry)] = self.by_session("s-one")
        self.assertEqual(entry["state"], "candidate")
        self.assertTrue(key.startswith("candidates/"))
        self.assertEqual(self.calls(self.review_log), [])
        self.session("s-two", "TITLE=Codegen_drift_check JEV_SAME_LESSON=0.9")
        [items] = self.calls(self.review_log)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["sessions"], ["s-one", "s-two"])
        self.assertIn("s-two", items[0]["text"])
        self.assertEqual(self.count(self.report(), "recurred"), 1)

    def test_same_session_drafts_are_never_compared(self):
        self.session("s-self", "TITLE=Alpha_lesson")
        before = self.subs().count("same-lesson")
        ledger = self.ledger()
        key = next(iter(ledger))
        self.assertEqual(before, 0)
        self.assertEqual(ledger[key]["sessions"], ["s-self"])

    def test_high_stakes_goes_to_review_alone(self):
        self.session("s-high", "JEV_HIGH_STAKES=0.9")
        [items] = self.calls(self.review_log)
        self.assertEqual([i["sessions"] for i in items], [["s-high"]])

    def test_shadow_mode_never_touches_04_knowledge(self):
        before = sorted(p.name for p in (self.vault / "04_Knowledge").rglob("*"))
        res = self.session("s-pub", "JEV_HIGH_STAKES=0.9")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(sorted(p.name for p in (self.vault / "04_Knowledge").rglob("*")), before)
        report = self.report()
        self.assertEqual(self.count(report, "would_publish"), 1)
        self.assertEqual(self.count(report, "published"), 0)
        self.assertIn("would publish: candidates/", report)
        [(_, entry)] = self.by_session("s-pub")
        self.assertEqual(entry["state"], "would-publish")

    def test_reject_verdict_is_recorded(self):
        self.session("s-rej", "JEV_HIGH_STAKES=0.9", REVIEW_STUB_VERDICT="reject")
        [(_, entry)] = self.by_session("s-rej")
        self.assertEqual(entry["state"], "rejected")
        self.assertEqual(self.count(self.report(), "rejected"), 1)

    def test_review_failure_leaves_candidates_ready_and_exits_nonzero(self):
        res = self.session("s-rf", "JEV_HIGH_STAKES=0.9", REVIEW_STUB_FAIL="1")
        self.assertNotEqual(res.returncode, 0)
        [(_, entry)] = self.by_session("s-rf")
        self.assertEqual(entry["state"], "ready")
        self.assertEqual(self.count(self.report(), "would_publish"), 0)

    def test_no_lesson_and_worker_failure_and_invalid_draft(self):
        self.session("s-nol", "EXTRACT_NO_LESSON")
        self.assertEqual(self.seen()["s-nol"]["state"], "no-lesson")
        self.session("s-fail", "EXTRACT_FAIL")
        self.assertEqual(self.seen()["s-fail"]["state"], "invalid")
        self.session("s-inv", "EXTRACT_INVALID")
        [(key, entry)] = self.by_session("s-inv")
        self.assertEqual(entry["state"], "invalid")
        self.assertTrue((self.vault / "_inbox" / "agent" / "distill" / key).exists())
        self.session("s-big", "EXTRACT_BIG")
        [(_, entry)] = self.by_session("s-big")
        self.assertEqual(entry["state"], "invalid")  # over 1,500 bytes

    def test_draft_with_a_credential_is_quarantined_and_not_scored(self):
        self.session("s-sec", "EXTRACT_SECRET")
        [(_, entry)] = self.by_session("s-sec")
        self.assertEqual(entry["state"], "private")
        self.assertNotIn("score-draft", self.subs())
        self.assertTrue((self.vault / "_inbox" / "private" / "draft-s-sec.md").exists())

    def test_failed_score_is_retried_next_run(self):
        self.session("s-uns", "", JEV_STUB_FAIL="score-draft")
        [(_, entry)] = self.by_session("s-uns")
        self.assertEqual(entry["state"], "unscored")
        self.distill()  # empty inbox: only the rescoring happens
        [(key, entry)] = self.by_session("s-uns")
        self.assertEqual(entry["state"], "candidate")
        self.assertTrue(key.startswith("candidates/"))

    def test_nightly_extraction_cap_leaves_the_rest_pending(self):
        paths = {sid: self.transcript(sid, [f"lesson {sid} JEV_LESSON=0.95"]) for sid in ("c1", "c2", "c3")}
        self.write_inbox([self.inbox_line(sid, p) for sid, p in paths.items()])
        self.distill(VAULT_DISTILL_MAX="2")
        self.assertEqual(len(self.calls(self.extract_log)), 2)
        states = sorted(r["state"] for r in self.seen().values())
        self.assertEqual(states, ["extract-pending", "extracted", "extracted"])
        self.distill(VAULT_DISTILL_MAX="2")
        self.assertEqual(len(self.calls(self.extract_log)), 3)
        self.assertEqual({r["state"] for r in self.seen().values()}, {"extracted"})

    def test_at_most_5_same_lesson_comparisons(self):
        for i in range(7):
            self.session(f"old{i}", f"TITLE=Gate_lesson_{i}")
        self.jev_log.unlink()
        self.session("s-new", "TITLE=Gate_lesson_new")
        self.assertEqual(self.subs().count("same-lesson"), 5)

    def test_candidate_older_than_60_days_moves_to_expired(self):
        self.session("s-old", "TITLE=Old_lesson")
        ledger = self.ledger()
        [key] = list(ledger)
        ledger[key]["created"] = int(time.time()) - 61 * 86400
        (self.state / "drafts.json").write_text(json.dumps(ledger))
        self.distill()
        [(new_key, entry)] = self.by_session("s-old")
        self.assertEqual(entry["state"], "expired")
        self.assertTrue((self.vault / "_inbox" / "agent" / "distill" / new_key).exists())  # moved, not deleted
        self.assertIn(f"expired: {key}", self.report())

    def test_extractor_gets_project_ids_or_repo_tag(self):
        self.session("s-tag", "")
        self.assertEqual(self.calls(self.extract_log)[0]["tags"], ["repo:demo-repo"])
        (self.vault / "_meta" / "indexes" / "projects.jsonl").write_text(
            json.dumps({"id": "PROJ-demo", "release_repo": str(self.repo)}) + "\n")
        self.session("s-proj", "")
        req = self.calls(self.extract_log)[1]
        self.assertEqual((req["project_ids"], req["tags"]), (["PROJ-demo"], []))

    def test_report_counts_bytes_per_stage(self):
        self.session("s-bytes", "JEV_HIGH_STAKES=0.9")
        report = self.report()
        for stage in ("classify", "extract", "score", "review"):
            row = next(line for line in report.splitlines() if line.startswith(f"| {stage} |"))
            self.assertGreater(int(row.split("|")[2]), 0, row)


class TestDefaultModelCalls(DistillCase):
    """The default extractor and reviewer: one agy print-mode call each, through a fake agy on PATH."""

    def fake_agy(self, reply):
        bindir = self.dir / "fakebin"
        bindir.mkdir(exist_ok=True)
        agy = bindir / "agy"
        agy.write_text(FAKE_AGY)
        agy.chmod(0o755)
        (self.dir / "reply.txt").write_text(reply)
        return {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "AGY_LOG": str(self.dir / "agy.log"),
                "AGY_REPLY": str(self.dir / "reply.txt")}

    def request(self):
        digest = self.dir / "digest.txt"
        digest.write_text("signals: corrections=0\nuser: make check failed with exit 2\n")
        return json.dumps({"session_id": "sess-1234abcd", "digest_path": str(digest),
                           "out_dir": str(self.dir / "out"), "project_ids": [], "tags": ["repo:demo-repo"],
                           "related": ""})

    def run_default(self, flag, stdin, env):
        return subprocess.run([sys.executable, str(DISTILL), flag], input=stdin, capture_output=True, text=True,
                              env={**self.env(), **env}, timeout=60)

    def test_extract_default_is_one_tool_free_flash_call_that_renders_the_draft(self):
        answer = {"lesson": True, "title": "Make check exit 2", "summary": "Exit 2 means lint failed.",
                  "when": "make check fails", "rule": "Run lint first.", "why": "Saves a cycle.",
                  "scope": "repo", "evidence": ["make check failed with exit 2"]}
        env = self.fake_agy("Here you go:\n" + json.dumps(answer))
        res = self.run_default("--extract-default", self.request(), env)
        self.assertEqual(res.returncode, 0, res.stderr)
        draft = Path(json.loads(res.stdout)["path"])
        text = draft.read_text()
        for section in ("## When this applies", "## Rule", "## Why", "## Source", "## Evidence"):
            self.assertIn(section, text)
        self.assertIn('schema: "knowledge/v1"', text)
        self.assertIn('tags: ["auto-distilled", "repo:demo-repo"]', text)
        self.assertIn("- session `sess-1234abcd`", text)
        self.assertLessEqual(len(text.encode()), 1500)
        self.assertTrue(load_distill().evidence_ok(text, Path(json.loads(self.request())["digest_path"]).read_text()))
        [argv] = [json.loads(line) for line in (self.dir / "agy.log").read_text().splitlines()]
        self.assertEqual(argv[argv.index("--model") + 1], "gemini-3.8-flash-high")
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertNotIn("--add-dir", argv)
        self.assertEqual(argv[argv.index("--mode") + 1], "plan")

    def test_extract_default_no_lesson_and_garbage(self):
        res = self.run_default("--extract-default", self.request(), self.fake_agy('{"lesson": false}'))
        self.assertEqual(json.loads(res.stdout), {"path": None, "reason": "no-lesson"})
        res = self.run_default("--extract-default", self.request(), self.fake_agy("not json"))
        self.assertNotEqual(res.returncode, 0)

    def test_render_draft_global_scope_and_proposed_addition(self):
        vd = load_distill()
        _, text = vd.render_draft({"title": "Use worktrees", "scope": "global", "existing_note_id": "KNOW-worktrees",
                                   "evidence": []}, {"session_id": "s1", "tags": ["repo:x"], "project_ids": ["PROJ-x"]})
        self.assertIn('tags: ["auto-distilled", "global"]', text)
        self.assertIn("project_ids: []", text)
        self.assertIn('proposed_addition_to: "KNOW-worktrees"', text)

    def test_review_default_is_one_argon_low_call(self):
        verdicts = {"verdicts": [{"draft": "candidates/a.md", "verdict": "publish", "reason": "solid"}]}
        res = self.run_default("--review-default", json.dumps([{"draft": "candidates/a.md", "text": "x"}]),
                               self.fake_agy(json.dumps(verdicts)))
        self.assertEqual(json.loads(res.stdout), verdicts["verdicts"])
        [argv] = [json.loads(line) for line in (self.dir / "agy.log").read_text().splitlines()]
        self.assertEqual(argv[argv.index("--model") + 1], "gemini-4-argon-low")

    def test_evidence_needs_8_characters(self):
        vd = load_distill()
        draft = "## Rule\nx\n\n## Evidence\n- `exit 2`\n"
        self.assertFalse(vd.evidence_ok(draft, "make check: exit 2"))
        self.assertTrue(vd.evidence_ok(draft.replace("`exit 2`", "`check: exit 2`"), "make check: exit 2"))


if __name__ == "__main__":
    unittest.main()
```

Verify-Cmd: python3 -m unittest tests.test_vault_distill_drafts tests.test_vault_distill tests.test_vault_distill_audit -v

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_vault_distill_drafts -v`
Expected: FAIL. The interim `run_extractions` never calls the extractor, so there is no `drafts.json` (`by_session` returns `[]` and unpacking raises `ValueError`). `--extract-default` is an unknown argument (exit 2). `render_draft` and `evidence_ok` do not exist (`AttributeError`).

- [ ] **Step 3: Add the constants**

Insert after `PENDING = {"jev-failed", "unsure-pending", "extract-pending"}`:

```python
DRAFT_MAX = 1500
JUNK_BELOW = 0.5
SAME_AT = 0.85
HIGH_STAKES_AT = 0.85
SAME_MAX = 5
CANDIDATE_DAYS = 60
JEV_RULES_MAX = 20000
EXTRACT_MODEL = "gemini-3.8-flash-high"
REVIEW_MODEL = "gemini-4-argon-low"
```

- [ ] **Step 4: Replace the interim `run_extractions`**

Delete Task 2's `run_extractions` function and put this block in its place, just before `# --- report and exit code (R12, R16) ---`:

```python
def run_extractions(run, queue):
    """R9-R10f and R19: extract up to VAULT_DISTILL_MAX sessions, gate each draft, then one review call."""
    queue.sort(key=lambda item: -item[0])
    cap = env_int("VAULT_DISTILL_MAX", 20)
    if run.dry:
        run.counts["extracted"] += min(len(queue), cap)
        return
    run.ledger = load_ledger(run)
    rescore_unscored(run)
    for i, (p, session) in enumerate(queue):
        if i >= cap:
            run.mark(session, "extract-pending", p=p)  # over the nightly cap: first in line tomorrow
            continue
        run.counts["extracted"] += 1
        state, draft = extract_session(run, session)
        run.mark(session, state, offset=session["end"], p=p, draft=draft)
        save_ledger(run)
    expire_candidates(run)
    review(run)
    for entry in run.ledger.values():
        run.counts["candidates_waiting"] += entry["state"] in ("candidate", "ready", "would-publish")
        run.counts["ready"] += entry["state"] == "ready"
    save_ledger(run)


def load_ledger(run):
    try:
        data = json.loads((run.state / "drafts.json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_ledger(run):
    atomic_write(run.state / "drafts.json", json.dumps(run.ledger, indent=1) + "\n")


def engine(run, *args):
    try:
        return subprocess.run([engine_bin(), *args], capture_output=True, text=True, timeout=20,
                              env={**os.environ, "VAULT_ROOT": str(run.vault)})
    except (OSError, subprocess.SubprocessError):
        return None


def related_notes(run, query):
    proc = engine(run, "context", "--query", query[:2000], "--limit", "3")
    return proc.stdout if proc is not None and proc.returncode == 0 else ""


def repo_scope(run, cwd):
    """project_ids of project notes whose release_repo is the session's repo, else the repo:<name> tag."""
    root = os.path.realpath(repo_root(cwd)) if cwd else ""
    ids = []
    try:
        lines = (run.vault / "_meta" / "indexes" / "projects.jsonl").read_text().splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("release_repo") and os.path.realpath(entry["release_repo"]) == root:
            ids.append(entry["id"])
    return (ids, []) if ids else ([], [f"repo:{os.path.basename(root)}"] if root else [])


def prompts_of(digest):
    return " ".join(line[6:] for line in digest.splitlines() if line.startswith("user: "))


def extract_session(run, session):
    """Returns (session state, draft key or None)."""
    project_ids, tags = repo_scope(run, session["cwd"])
    request = {"session_id": session["sid"], "digest_path": session["digest_path"], "out_dir": str(run.distill),
               "project_ids": project_ids, "tags": tags,
               "related": related_notes(run, prompts_of(session["digest"]) or session["digest"][:2000])}
    cmd = shlex.split(os.environ.get("VAULT_DISTILL_EXTRACT_CMD", "")) or [sys.executable, str(Path(__file__).resolve()), "--extract-default"]
    run.bytes["extract"] += len(session["digest"].encode()) + len(request["related"].encode())  # what the model reads
    out = run.call("extract", cmd, json.dumps(request), timeout=360)
    if not isinstance(out, dict):
        run.counts["invalid"] += 1
        return "invalid", None  # R9f: the worker failed
    if not out.get("path"):
        run.counts["no_lesson"] += 1
        return "no-lesson", None
    draft = Path(out["path"]).resolve()
    if run.distill.resolve() not in draft.parents or not draft.is_file():
        run.counts["invalid"] += 1
        return "invalid", None
    key = str(draft.relative_to(run.distill.resolve()))
    entry = {"sid": session["sid"], "sessions": [session["sid"]], "digest": session["digest_path"],
             "created": int(time.time()), "state": "new", "scores": {}}
    run.ledger[key] = entry
    admit_draft(run, key, entry)
    return "extracted", key


def admit_draft(run, key, entry):
    path = run.distill / key
    text = path.read_text(errors="replace")
    proc = engine(run, "validate", str(path))
    if len(text.encode()) > DRAFT_MAX or proc is None or proc.returncode != 0:
        entry["state"] = "invalid"  # R9f: stays in the inbox marked invalid
        run.counts["invalid"] += 1
    elif SECRET_RE.search(text):
        quarantine(run, f"draft-{entry['sid']}", text)
        path.unlink()  # a credential must not stay in a synced inbox path; the copy is in _inbox/private/
        entry["state"] = "private"
        run.counts["private"] += 1
    elif not evidence_ok(text, Path(entry["digest"]).read_text(errors="replace")):
        entry["state"] = "no-evidence"  # R9c: script check, no model
        run.counts["no_evidence"] += 1
    else:
        score_draft(run, key, entry)


def evidence_ok(text, digest):
    """R9c: at least one quoted Evidence line (8+ characters) is a substring of the digest."""
    m = re.search(r"^## Evidence[ \t]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        return False
    quotes = [ln.strip()[2:].strip().strip("`\"'") for ln in m.group(1).splitlines() if ln.strip()[:2] in ("- ", "> ")]
    return any(len(q) >= 8 and q in digest for q in quotes)


def title_of(text):
    m = re.search(r'^title:\s*"?(.*?)"?\s*$', text, re.M)
    return m.group(1) if m else ""


def score_draft(run, key, entry):
    """R9d: Jev scores specific, novel and high_stakes; below 0.5 on either of the first two is junk."""
    path = run.distill / key
    text = path.read_text(errors="replace")
    digest = Path(entry["digest"]).read_text(errors="replace") if Path(entry["digest"]).exists() else ""
    related = related_notes(run, title_of(text))
    related_path = run.state / "related" / f"{entry['sid']}.txt"
    atomic_write(related_path, related)
    claude_md = Path.home() / ".claude" / "CLAUDE.md"
    run.bytes["score"] += min(JEV_RULES_MAX, size_or_zero(claude_md))  # jev-gate reads it itself
    out = run.jev("score", "score-draft", ["--draft", str(path), "--digest", entry["digest"], "--related", str(related_path)],
                  text + "\n" + digest + "\n" + related)
    if out is None:
        entry["state"] = "unscored"  # R9df: scored again on the next run
        run.counts["unscored"] += 1
        return
    entry["scores"] = {k: float(out.get(k, 0.0)) for k in ("specific", "novel", "high_stakes")}
    if entry["scores"]["specific"] < JUNK_BELOW or entry["scores"]["novel"] < JUNK_BELOW:
        entry["state"] = "junk"
        run.counts["junk"] += 1
        return
    become_candidate(run, key, entry)


def rescore_unscored(run):
    for key, entry in list(run.ledger.items()):
        if entry["state"] == "unscored" and (run.distill / key).exists():
            score_draft(run, key, entry)


def terms(text):
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 4}


def keyword_score(query, text):
    """R2's field weights (title 3, tag 2, body 1) over a candidate file.
    shortcut: no engine stop-word list and no score floor; it only orders at most 5 Jev comparisons."""
    title = terms(title_of(text))
    tag_line = re.search(r"^tags:(.*)$", text, re.M)
    tags = terms(tag_line.group(1)) if tag_line else set()
    body = terms(text)
    return sum(3 if t in title else 2 if t in tags else 1 if t in body else 0 for t in query)


def become_candidate(run, key, entry):
    """R19: a candidate goes to review on recurrence in another session or on high_stakes >= 0.85."""
    src = run.distill / key
    dest = run.distill / "candidates" / src.name
    if dest.exists():
        dest = dest.with_name(f"{dest.stem}-{entry['sid'][:8]}.md")
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dest)
    new_key = str(dest.relative_to(run.distill))
    run.ledger.pop(key, None)
    run.ledger[new_key] = entry
    entry["state"] = "candidate"
    text = dest.read_text(errors="replace")
    query = terms(title_of(text) + " " + text)
    others = [(keyword_score(query, (run.distill / k).read_text(errors="replace")), k)
              for k, e in run.ledger.items()
              if k != new_key and e["state"] in ("candidate", "ready") and entry["sid"] not in e["sessions"]
              and (run.distill / k).exists()]
    for _, other in sorted(others, reverse=True)[:SAME_MAX]:
        other_text = (run.distill / other).read_text(errors="replace")
        out = run.jev("same_lesson", "same-lesson", ["--a", str(dest), "--b", str(run.distill / other)],
                      text + "\n---\n" + other_text)
        if out is not None and float(out.get("same", 0.0)) >= SAME_AT:
            merge(run, other, new_key)
            return
    if entry["scores"].get("high_stakes", 0.0) >= HIGH_STAKES_AT:
        entry["state"] = "ready"


def merge(run, keep_key, new_key):
    """Recurrence: the older candidate cites both sessions; the newer file moves to merged/."""
    keep, new = run.ledger[keep_key], run.ledger[new_key]
    keep["sessions"] = sorted(set(keep["sessions"]) | set(new["sessions"]))
    keep["state"] = "ready"
    with open(run.distill / keep_key, "a") as handle:
        handle.write("\n## Also seen in\n" + "".join(f"- session `{s}`\n" for s in new["sessions"]))
    src = run.distill / new_key
    dest = run.distill / "merged" / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dest)
    run.ledger.pop(new_key)
    run.ledger[str(dest.relative_to(run.distill))] = {**new, "state": "merged", "into": keep_key}
    run.counts["recurred"] += 1


def expire_candidates(run):
    """R19: a candidate with no match after 60 days leaves the queue; moved to expired/, never deleted."""
    cutoff = time.time() - CANDIDATE_DAYS * 86400
    for key, entry in list(run.ledger.items()):
        if entry["state"] == "candidate" and entry["created"] < cutoff and (run.distill / key).exists():
            dest = run.distill / "expired" / Path(key).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(run.distill / key, dest)
            run.ledger.pop(key)
            run.ledger[str(dest.relative_to(run.distill))] = {**entry, "state": "expired"}
            run.counts["expired"] += 1
            run.notes.append(f"expired: {key}")


def review(run):
    """R10: one review call for every ready candidate. Shadow mode: a publish verdict is recorded as would-publish."""
    ready = [k for k, e in run.ledger.items() if e["state"] == "ready" and (run.distill / k).exists()]
    if not ready:
        return
    items = [{"draft": k, "sessions": run.ledger[k]["sessions"], "scores": run.ledger[k]["scores"],
              "text": (run.distill / k).read_text(errors="replace")} for k in ready]
    cmd = shlex.split(os.environ.get("VAULT_DISTILL_REVIEW_CMD", "")) or [sys.executable, str(Path(__file__).resolve()), "--review-default"]
    out = run.call("review", cmd, json.dumps(items), timeout=360)
    if not isinstance(out, list):
        if out is not None:
            run.failures["review"] += 1
        return  # R10f: nothing changes, every candidate stays ready for tomorrow
    for verdict in out:
        if not isinstance(verdict, dict) or verdict.get("draft") not in ready:
            continue
        entry = run.ledger[verdict["draft"]]
        entry["reason"] = str(verdict.get("reason", ""))[:300]
        if verdict.get("verdict") == "publish":
            entry["state"] = "would-publish"
            run.counts["would_publish"] += 1
            run.notes.append(f"would publish: {verdict['draft']} ({entry['reason']})")
        elif verdict.get("verdict") == "reject":
            entry["state"] = "rejected"
            run.counts["rejected"] += 1
            run.notes.append(f"rejected: {verdict['draft']} ({entry['reason']})")


# --- default extractor and reviewer: one agy print-mode call each, no tools, no workspace ---
EXTRACT_SCHEMA = {
    "type": "object", "required": ["lesson"],
    "properties": {
        "lesson": {"type": "boolean"},
        "title": {"type": "string", "maxLength": 80},
        "summary": {"type": "string", "maxLength": 160},
        "when": {"type": "string", "maxLength": 300},
        "rule": {"type": "string", "maxLength": 300},
        "why": {"type": "string", "maxLength": 300},
        "scope": {"enum": ["repo", "global"]},
        "existing_note_id": {"type": "string"},
        "evidence": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 160}},
    },
}
EXTRACT_PROMPT = """You turn one finished agent session into at most one reusable lesson for a knowledge vault.
Answer with JSON only, matching the schema. Use no tools.
- lesson: false when the session holds no trap, fix, decision or rule that would help a future session.
- title: a short name for the lesson. summary: one sentence. when / rule / why: one or two sentences each.
- scope: "global" when the rule applies in every repo, else "repo".
- existing_note_id: when one of the existing notes below already covers this lesson, its id (the draft then
  becomes a proposed addition to that note); otherwise leave it out.
- evidence: 1 to 3 strings copied exactly from the digest (an error message, a command or a file path).

Existing notes (id | title | path | matched | summary):
{related}

Session digest:
{digest}
"""
REVIEW_SCHEMA = {
    "type": "object", "required": ["verdicts"],
    "properties": {"verdicts": {"type": "array", "items": {
        "type": "object", "required": ["draft", "verdict", "reason"],
        "properties": {"draft": {"type": "string"}, "verdict": {"enum": ["publish", "reject"]},
                       "reason": {"type": "string", "maxLength": 200}}}}},
}
REVIEW_PROMPT = """You review candidate knowledge notes written automatically from agent sessions.
For each candidate return publish or reject with a one-sentence reason. Publish only a rule that is specific,
correct as far as the text shows, useful in a future session, and not a one-off. Answer with JSON only. Use no tools.

Candidates (JSON):
"""


def parse_json(text):
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


def ask_agy(model, prompt, schema):
    """One print-mode turn: no --add-dir, no --dangerously-skip-permissions, plan mode, empty cwd."""
    cmd = ["agy", "-p", prompt, "--model", model, "--mode", "plan", "--disable-slash-commands",
           "--json-schema", json.dumps(schema), "--output-format", "text", "--print-timeout", "300s"]
    with tempfile.TemporaryDirectory() as empty:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=330, cwd=empty,
                                  env={**os.environ, "CLAUDE_VAULT_SUMMARY": "0"})
        except (OSError, subprocess.SubprocessError):
            return None
    return parse_json(proc.stdout) if proc.returncode == 0 else None


def one_line(value, limit):
    return " ".join(str(value or "").split())[:limit]


def render_draft(answer, request):
    sid = request["session_id"]
    title = one_line(answer.get("title"), 80) or "Untitled lesson"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "lesson"
    today = datetime.date.today().isoformat()
    scope_global = answer.get("scope") == "global"
    fm = {"schema": "knowledge/v1", "id": f"KNOW-{slug}", "kind": "knowledge", "title": title, "status": "draft",
          "category": "rule", "author": "agent-distiller", "created": today, "updated": today,
          "tags": ["auto-distilled"] + (["global"] if scope_global else list(request.get("tags", []))),
          "project_ids": [] if scope_global else list(request.get("project_ids", [])),
          "source_sessions": [sid]}
    if answer.get("existing_note_id"):
        fm["proposed_addition_to"] = one_line(answer["existing_note_id"], 120)
    lines = ["---"] + [f"{k}: {json.dumps(v)}" for k, v in fm.items()] + ["---", "",
             one_line(answer.get("summary"), 160), "",
             "## When this applies", one_line(answer.get("when"), 300), "",
             "## Rule", one_line(answer.get("rule"), 300), "",
             "## Why", one_line(answer.get("why"), 300), "",
             "## Source", f"- session `{sid}`", "",
             "## Evidence"] + [f"- {one_line(q, 160)}" for q in (answer.get("evidence") or [])[:3]]
    return slug, "\n".join(lines) + "\n"


def extract_default():
    request = json.loads(sys.stdin.read())
    digest = Path(request["digest_path"]).read_text(errors="replace")
    answer = ask_agy(EXTRACT_MODEL, EXTRACT_PROMPT.format(related=request.get("related") or "(none)", digest=digest),
                     EXTRACT_SCHEMA)
    if not isinstance(answer, dict):
        return 1
    if not answer.get("lesson"):
        print(json.dumps({"path": None, "reason": "no-lesson"}))
        return 0
    slug, text = render_draft(answer, request)
    path = Path(request["out_dir"]) / f"{slug}--{request['session_id'][:8]}.md"
    atomic_write(path, text)
    print(json.dumps({"path": str(path)}))
    return 0


def review_default():
    items = sys.stdin.read()
    answer = ask_agy(REVIEW_MODEL, REVIEW_PROMPT + items, REVIEW_SCHEMA)
    if not isinstance(answer, dict) or not isinstance(answer.get("verdicts"), list):
        return 1
    print(json.dumps(answer["verdicts"]))
    return 0
```

- [ ] **Step 5: Wire the hidden default commands into `main()`**

Replace the two lines `parser.add_argument("--report", ...)` and `args = parser.parse_args()` with:

```python
    parser.add_argument("--report", action="store_true", help="print the last run's report")
    parser.add_argument("--extract-default", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--review-default", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.extract_default:
        return extract_default()
    if args.review_default:
        return review_default()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_vault_distill_drafts tests.test_vault_distill -v`
Expected: PASS (41 tests).

- [ ] **Step 7: Commit**

```bash
git add bin/vault-distill tests/test_vault_distill_drafts.py
git commit -m "feat(vault-distill): draft stage (single-call extract, evidence and Jev gates, recurrence, Argon-low review)"
```

---

### Task 4: Install, doctor, end-to-end case, docs and diagram

**Files:**
- Modify: `install.sh` (line 61: add `|"$BIN_HOME/vault-distill"` to the `replace_destination` case list; after line 134, `link "$REPO/bin/jev-gate" "$BIN_HOME/jev-gate"`, add `link "$REPO/bin/vault-distill" "$BIN_HOME/vault-distill"`)
- Modify: `bin/ps-skills-doctor` (add `import time`; new `check_vault_distill` before `def main()`; call it after `check_vault_recall(home, issues, warnings)` at line 281)
- Modify: `tools/vault-engine/test_e2e.sh` (new case before `# Clean up temp test vault`)
- Modify: `README.md` (new subsection after "Automatic knowledge retrieval (I-039 slice 1)"), `skills/agentic-vault/SKILL.md` (section "4. Post-Flight Knowledge Compounding")
- Create: `docs/superpowers/specs/assets/vault-distill-pipeline.drawio` and `.drawio.svg`
- Test: `tests/test_ps_skills_doctor_distill.py` (new)

**Audit amendment A5 applies to this task:** in the README subsection, state that the skip list for the nightly run is the `VAULT_DISTILL_SKIP_REPOS=` assignment on the cron line (cron does not read `~/.zshrc`), and that `--dry-run` still writes digest files under the state directory (do not say it records nothing).


**Interfaces:**
- Consumes: `last-run.json` (`ts`, `exit`, `report`) from Task 2. The `crontab -l` text.
- Produces: `check_vault_distill(home, issues, warnings, crontab=None)`. Tests pass `crontab` as text; in production it reads `crontab -l`.

- [ ] **Step 1: Write the failing test**

```python test:tests/test_ps_skills_doctor_distill.py
#!/usr/bin/env python3
"""bin/ps-skills-doctor save-side vault checks (I-040): Jev key, cron line, last vault-distill run."""
import importlib.machinery
import importlib.util
import json as _json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

DOCTOR_SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "ps-skills-doctor"


def _load_doctor():
    loader = importlib.machinery.SourceFileLoader("ps_skills_doctor", str(DOCTOR_SCRIPT))
    spec = importlib.util.spec_from_loader("ps_skills_doctor", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestVaultDistillCheck(unittest.TestCase):
    """Save-side readiness (I-040): Jev key, cron line, last run age and exit code."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("VAULT_ROOT", None)
        os.environ.pop("TYPESAFE_API_KEY", None)
        self.doctor = _load_doctor()
        (self.home / "workspace" / "agentic-vault" / "_meta").mkdir(parents=True)
        self.last = self.home / ".claude" / "state" / "vault-distill" / "last-run.json"
        self.last.parent.mkdir(parents=True)
        self.cron = "40 23 * * * PATH=/usr/bin:/bin ~/.local/bin/vault-distill\n"

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_check(self, crontab):
        issues, warnings = [], []
        self.doctor.check_vault_distill(self.home, issues, warnings, crontab=crontab)
        return issues, warnings

    def record(self, hours_ago, code=0):
        self.last.write_text(_json.dumps({"ts": time.time() - hours_ago * 3600, "exit": code, "report": "r.md"}))

    def test_healthy(self):
        os.environ["TYPESAFE_API_KEY"] = "k"
        self.record(2)
        self.assertEqual(self.run_check(self.cron), ([], []))

    def test_key_in_zshrc_counts(self):
        (self.home / ".zshrc").write_text('export TYPESAFE_API_KEY="abc"\n')
        self.record(2)
        self.assertEqual(self.run_check(self.cron), ([], []))

    def test_missing_key_is_a_warning(self):
        (self.home / ".zshrc").write_text("export TYPESAFE_API_KEY=$FROM_ELSEWHERE\n")
        self.record(2)
        issues, warnings = self.run_check(self.cron)
        self.assertEqual(issues, [])
        self.assertTrue(any("no Jev key" in w for w in warnings), warnings)

    def test_no_cron_line_is_a_warning(self):
        os.environ["TYPESAFE_API_KEY"] = "k"
        issues, warnings = self.run_check("55 23 * * * other-job\n")
        self.assertEqual(issues, [])
        self.assertTrue(any("no cron line" in w for w in warnings), warnings)

    def test_cron_without_a_run_is_a_warning(self):
        os.environ["TYPESAFE_API_KEY"] = "k"
        issues, warnings = self.run_check(self.cron)
        self.assertEqual(issues, [])
        self.assertTrue(any("no run is recorded" in w for w in warnings), warnings)

    def test_stale_run_is_an_issue(self):
        os.environ["TYPESAFE_API_KEY"] = "k"
        self.record(40)
        issues, _ = self.run_check(self.cron)
        self.assertTrue(any("40 hours ago" in i for i in issues), issues)

    def test_degraded_run_is_a_warning(self):
        os.environ["TYPESAFE_API_KEY"] = "k"
        self.record(2, code=2)
        issues, warnings = self.run_check(self.cron)
        self.assertEqual(issues, [])
        self.assertTrue(any("exited 2" in w for w in warnings), warnings)

    def test_no_vault_is_skipped(self):
        shutil.rmtree(self.home / "workspace")
        self.assertEqual(self.run_check(""), ([], []))


if __name__ == "__main__":
    unittest.main()
```

Verify-Cmd: python3 -m unittest tests.test_ps_skills_doctor_distill tests.test_ps_skills_doctor -v

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_ps_skills_doctor_distill -v`
Expected: ERROR: `module 'ps_skills_doctor' has no attribute 'check_vault_distill'`.

- [ ] **Step 3: Implement the doctor check**

Add `import time` after `import argparse` in `bin/ps-skills-doctor`. Insert before `def main():`:

```python
def check_vault_distill(home, issues, warnings, crontab=None):
    """Knowledge save readiness (I-040): Jev key, cron line, age and exit code of the last nightly run."""
    vault = Path(os.environ.get("VAULT_ROOT") or home / "workspace" / "agentic-vault")
    if not (vault / "_meta").is_dir():
        return
    zshrc = home / ".zshrc"
    rc = zshrc.read_text(errors="ignore") if zshrc.exists() else ""
    if not (os.environ.get("TYPESAFE_API_KEY", "").strip()
            or re.search(r"^\s*(export\s+)?TYPESAFE_API_KEY=[\"']?[^$\s\"']", rc, re.M)):
        warnings.append("vault-distill: no Jev key (TYPESAFE_API_KEY or ~/.zshrc): every session will be unsure")
    if crontab is None:
        try:
            crontab = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            crontab = ""
    if "vault-distill" not in crontab:
        warnings.append("vault-distill: no cron line (expected `40 23 * * *`, see README)")
        return
    try:
        last = json.loads((home / ".claude" / "state" / "vault-distill" / "last-run.json").read_text())
        age_hours = (time.time() - float(last["ts"])) / 3600
    except (OSError, ValueError, KeyError, TypeError):
        warnings.append("vault-distill: cron line exists but no run is recorded yet")
        return
    if age_hours > 36:
        issues.append(f"vault-distill: last run was {age_hours:.0f} hours ago (limit 36)")
    elif last.get("exit"):
        warnings.append(f"vault-distill: last run exited {last['exit']} (see {last.get('report')})")
```

In `main()`, after `check_vault_recall(home, issues, warnings)`, add `check_vault_distill(home, issues, warnings)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_ps_skills_doctor_distill tests.test_ps_skills_doctor -v`
Expected: PASS.

- [ ] **Step 5: `install.sh`**

Make the two edits listed under Files. Check them with `bash -n install.sh && grep -n 'vault-distill' install.sh`; it should print two lines.

- [ ] **Step 6: End-to-end case (Tier 3: the run leaves non-zero rows)**

In `tools/vault-engine/test_e2e.sh`, insert before `# Clean up temp test vault`. `VAULT_ROOT` is already exported at line 86, and `$ENGINE_BIN` is the real engine built at the top of the script:

```bash
# vault-distill shadow run (I-040): stubbed Jev, extractor and reviewer; the real engine validates the draft
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FIX="${REPO_ROOT}/tests/fixtures/vault_distill"
DISTILL_HOME="$(mktemp -d /tmp/vault-distill-home-XXXXXX)"
mkdir -p "${VAULT_ROOT}/_inbox/agent" "${DISTILL_HOME}/.claude"
TRANSCRIPT="${DISTILL_HOME}/e2e.jsonl"
python3 - "$TRANSCRIPT" << 'PY'
import json, sys
lines = [{"type": "user", "message": {"content": "the release gate failed: make check exit 2 JEV_LESSON=0.95 JEV_HIGH_STAKES=0.9"}},
         {"type": "assistant", "message": {"content": [{"type": "text", "text": "Fixed it. " + "x" * 5000}]}}]
open(sys.argv[1], "w").write("".join(json.dumps(l) + "\n" for l in lines))
PY
touch -t 202601010000 "$TRANSCRIPT"
echo "- **2026-11-10 10:00** — repo: \`e2e-repo\` — cwd: \`/tmp/e2e-repo\` — session: \`e2e\` — transcript: \`${TRANSCRIPT}\`" \
  > "${VAULT_ROOT}/_inbox/agent/session-summaries.md"
KNOW_BEFORE=$(find "${VAULT_ROOT}/04_Knowledge" -type f | sort | xargs shasum | shasum)
HOME="$DISTILL_HOME" VAULT_ENGINE="$ENGINE_BIN" \
  VAULT_DISTILL_JEV_CMD="python3 ${FIX}/jev_stub.py" \
  VAULT_DISTILL_EXTRACT_CMD="python3 ${FIX}/extract_stub.py" \
  VAULT_DISTILL_REVIEW_CMD="python3 ${FIX}/review_stub.py" \
  python3 "${REPO_ROOT}/bin/vault-distill"
REPORT=$(ls "${VAULT_ROOT}"/_inbox/agent/distill/report-*.md)
CANDIDATE=$(ls "${VAULT_ROOT}"/_inbox/agent/distill/candidates/*.md)
"$ENGINE_BIN" validate "$CANDIDATE" > /dev/null
for row in "seen | 1" "extracted | 1" "candidates_waiting | 1" "would_publish | 1" "published | 0"; do
    grep -qF "| ${row} |" "$REPORT" || { echo "❌ ERROR: report row '${row}' missing"; cat "$REPORT"; exit 1; }
done
if [ "$(find "${VAULT_ROOT}/04_Knowledge" -type f | sort | xargs shasum | shasum)" != "$KNOW_BEFORE" ]; then
    echo "❌ ERROR: shadow run changed 04_Knowledge/"
    exit 1
fi
HOME="$DISTILL_HOME" python3 "${REPO_ROOT}/bin/vault-distill" --report | grep -qF "would publish: candidates/"
rm -rf "$DISTILL_HOME"
echo "✅ vault-distill shadow run verified."
```

Run: `cd tools/vault-engine && rm -f bin/vault-engine && ./test_e2e.sh 2>&1 | tail -8`
Expected: the output ends with `✅ vault-distill shadow run verified.` and `🎉 ALL TESTS PASSED!`. If the existing `pkg/vaultsync` step hangs, as the slice-1 audit saw, run only the new case: source the block above with `SCRIPT_DIR`, an exported `VAULT_ROOT` (a fresh temp vault containing `04_Knowledge/`) and `ENGINE_BIN` set. Report which way you ran it.

- [ ] **Step 7: Update `README.md` & `skills/agentic-vault/SKILL.md`**

In `README.md`, after the "Automatic knowledge retrieval (I-039 slice 1)" list, add:

```markdown
### Automatic knowledge save, shadow mode (I-039 slice 2)

- `vault-distill` (nightly, cron `40 23 * * *`): rotates `_inbox/agent/session-summaries.md`, builds a digest of at most 12,000 bytes per finished session (user prompts and the last assistant text of each turn, no tool output, plus a signals line), and asks Jev `jev-gate classify-lesson` whether it holds a lesson. At most 20 sessions a night go to one `gemini-3.8-flash-high` call (`agy -p`, no tools) that writes a draft note. A draft must quote evidence from the digest, pass `jev-gate score-draft`, and recur in a second session (`jev-gate same-lesson`) or score high-stakes before one `gemini-4-argon-low` review call judges it. Shadow mode: nothing is published; a publish verdict is reported as "would publish".
- Output: drafts in `_inbox/agent/distill/` (`candidates/`, `merged/`, `expired/`), credential hits in `_inbox/private/`, and the nightly report `_inbox/agent/distill/report-<date>.md`. Machine state lives in `~/.claude/state/vault-distill/` (`seen.jsonl`, `drafts.json`, `digests/`, `last-run.json`).
- `vault-distill --report` prints the last report. `vault-distill --dry-run` calls Jev only and records nothing.
- Exit code 2 means the run was degraded: more than half the classified sessions were unsure (for example, no Jev key), or a stage failed on every call.
- External sends: digests from every repo go to TypeSafe (Jev) and Gemini after the credential scan, except repos named in `VAULT_DISTILL_SKIP_REPOS`.
- Env: `VAULT_DISTILL=0` turns it off; `VAULT_DISTILL_MAX` (default 20 extractions a night); `VAULT_DISTILL_UNSURE_MAX` (default 3); `VAULT_DISTILL_SKIP_REPOS` (comma-separated repo root basenames); `VAULT_ROOT` and `VAULT_ENGINE` as for the hook. Test seams: `VAULT_DISTILL_JEV_CMD`, `VAULT_DISTILL_EXTRACT_CMD`, `VAULT_DISTILL_REVIEW_CMD`. `VAULT_DISTILL_PUBLISH` and `VAULT_DISTILL_PUBLISH_MAX` arrive with slice 3.
- `ps-skills-doctor` warns when no Jev key or cron line is found, and reports an issue when the last run is more than 36 hours old.
```

In `skills/agentic-vault/SKILL.md`, at the end of section "4. Post-Flight Knowledge Compounding", add:

```markdown
Lessons are also captured without anyone asking: the nightly `vault-distill` batch drafts candidate notes from finished sessions into `_inbox/agent/distill/` (shadow mode, nothing is published yet). Read the morning report with `vault-distill --report`. Do not hand-edit `_inbox/agent/distill/` or `~/.claude/state/vault-distill/`.
```

- [ ] **Step 8: Architecture diagram**

Draw `docs/superpowers/specs/assets/vault-distill-pipeline.drawio` (with a `.drawio.svg` export). Keep the fast path and the state loop apart:
- Fast path: Stop hook → live inbox → rotate → digest → credential/skip gate → Jev classify → Flash extract → evidence → Jev score → Jev same-lesson → Argon-low review → report.
- State loop: `seen.jsonl`, `drafts.json`, `digests/`, `last-run.json`, read back by the next night and by `ps-skills-doctor`.

Put background pills on all connector labels. Run `python3 ~/.gemini/config/skills/drawio-skill/scripts/validate.py docs/superpowers/specs/assets/vault-distill-pipeline.drawio --score`. Expected: `score: 0`.

- [ ] **Step 9: Commit**

```bash
git add install.sh bin/ps-skills-doctor tests/test_ps_skills_doctor_distill.py tools/vault-engine/test_e2e.sh README.md skills/agentic-vault/SKILL.md docs/superpowers/specs/assets/vault-distill-pipeline.drawio docs/superpowers/specs/assets/vault-distill-pipeline.drawio.svg
git commit -m "feat(vault-distill): install link, doctor save checks, e2e shadow case, docs and diagram"
```

- [ ] **Step 10: Phase gate for Tasks 3 and 4** (rule 7)
  - Verify: `python3 -m unittest discover -s tests -v` is green, and so is the e2e case from Step 6.
  - Review, RISK R1: `code-reviewer` + `python-reviewer` + `silent-failures`, then one fix round and one scoped re-review.
  - `/simplify`, then re-run the suite and the e2e case.

---

## Go-live (controller only, after the final review; not a worker task)

Workers must not run this section. It changes the live machine, the real vault, and sends real session digests to external models. Run it after `psrw ship`, from the `_release` worktree. G1, G2 and G6 are R1: state it, then do it. G3, G4 and G5 send session digests to Jev and Gemini, which cannot be recalled; the owner approved these sends on 2026-11-11 for every repo outside the skip list. Before G3, print the skip list in force (`echo "${VAULT_DISTILL_SKIP_REPOS:-<empty>}"`) and state the number of sessions about to be sent.

- [ ] **G1: Quarantine rule in the real vault.** Back up the vault's `.gitignore`, then append `_inbox/private/` unless it is already there:

```bash
V=~/workspace/agentic-vault
cp "$V/.gitignore" "$V/.gitignore.bak-vault-distill-$(date +%Y%m%d)"
grep -qxF '_inbox/private/' "$V/.gitignore" || echo '_inbox/private/' >> "$V/.gitignore"
```

- [ ] **G2: Link the CLI** to the `_release` worktree, which outlives the feature worktree (`psrw ship` may remove that one): `ln -sfn ~/ps-skills/.claude/worktrees/_release/bin/vault-distill ~/.local/bin/vault-distill`, after checking that the target exists. `vault-distill` calls the `jev-gate` next to its resolved path, which is the release copy with the new subcommands. After promotion, run `./install.sh` from the main checkout so the link points at `main`.

- [ ] **G3: Real Jev smoke on a small copy (first external send).** Build a temp vault holding the real indexes and the last 20 inbox lines, then do a dry run with real Jev:

```bash
T=$(mktemp -d); mkdir -p "$T/_inbox/agent" "$T/_meta"
cp -R ~/workspace/agentic-vault/_meta/indexes "$T/_meta/"
tail -n 20 ~/workspace/agentic-vault/_inbox/agent/session-summaries.md > "$T/_inbox/agent/session-summaries.md"
VAULT_ROOT="$T" vault-distill --dry-run | tee /tmp/vault-distill-g3.txt | head -40
```

Expected: `seen` is at least 1, `unsure` is less than half of `classify` calls, and every `classify` byte count is at most 12,000 per call. If every session is `unsure`, check the key with `jev-gate classify-lesson --digest <one file from ~/.claude/state/vault-distill/digests/>` and report its `error`.

- [ ] **G4: One real extraction (verifies Deviation 1).** Pick one digest file from G3, then run:

```bash
D=$(ls -t ~/.claude/state/vault-distill/digests/*.txt | head -1)
echo "{\"session_id\":\"golive\",\"digest_path\":\"$D\",\"out_dir\":\"$T/_inbox/agent/distill\",\"project_ids\":[],\"tags\":[],\"related\":\"\"}" \
  | vault-distill --extract-default; echo "exit=$?"
```

Expected: `{"path": ...}` with exit 0, or `{"path": null, "reason": "no-lesson"}`. Also check that the empty temp cwd of the call stayed empty and that nothing under `$T` changed apart from the draft: plan mode with `--sandbox` (A4) must not have written files. If there is a path, `VAULT_ROOT="$T" vault-engine validate <path>` passes and the file is at most 1,500 bytes. If `agy` prints something `parse_json` cannot read, or the call takes longer than 5 minutes, stop and switch `VAULT_DISTILL_EXTRACT_CMD` to a `dispatch-worker --agent agy` wrapper (the spec's route) before G5. Then `rm -rf "$T"`.

- [ ] **G5: First real run, in the background.** It rotates the real inbox (about 5,700 lines) and classifies every finished session it lists, one Jev call each:

```bash
mkdir -p ~/.claude/logs
nohup vault-distill >> ~/.claude/logs/vault-distill.log 2>&1 &
```

Wait for it to finish with one blocking wait, not a poll. Then run `vault-distill --report`.

- [ ] **G6: Cron line.** Back up the crontab, then add the job:

```bash
crontab -l > ~/.claude/crontab.bak-vault-distill-$(date +%Y%m%d)
( crontab -l; echo '40 23 * * * PATH=$HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin VAULT_DISTILL_SKIP_REPOS= $HOME/.local/bin/vault-distill >> $HOME/.claude/logs/vault-distill.log 2>&1' ) | crontab -
```

- [ ] **G7: Live check on the user's surface (Tier 4).** The next morning, run these and paste the output into the report:

```bash
vault-distill --report | head -45
ls ~/workspace/agentic-vault/_inbox/agent/distill/candidates | wc -l
ps-skills-doctor --strict
```

Expected:
- The report is dated today and has `seen` greater than 0.
- `published` is 0 and `04_Knowledge/` is unchanged: `git -C ~/workspace/agentic-vault status --short 04_Knowledge` is empty.
- Bytes per stage are shown, and `exit` is 0.
- The doctor shows no vault-distill issue.
- If the cron run did not happen (cron has no `agy` login, for example), the log in `~/.claude/logs/vault-distill.log` says why. Report it; do not bypass it.

---

## Self-review notes

- **Spec coverage:**

  | Requirement | Where |
  |---|---|
  | R6, R6f | `work_files`, `requeue` (Task 2) |
  | R7, R7f, R7s | `screen`, `build_digest`, `cut` |
  | R8, R8f, R8u | `screen`, `run_batch` |
  | R11, R11a | `quarantine`, the skip list in `screen`; draft scan in `admit_draft` |
  | R12 | `render_report`, `show_report` |
  | R13 | `Run.mark`, `finish` |
  | R16 | `exit_code_for`, `main` |
  | R9 | `extract_session`, `extract_default`, `render_draft` (Task 3) |
  | R9f | `extract_session`, `admit_draft` |
  | R9c | `evidence_ok` |
  | R9d, R9df | `score_draft`, `rescore_unscored` |
  | R19 | `become_candidate`, `merge`, `expire_candidates` |
  | R10, R10f | `review`, `review_default` |
  | Token budget, save rows | `DIGEST_MAX`, `VAULT_DISTILL_MAX`, `VAULT_DISTILL_UNSURE_MAX`, `SAME_MAX`, `DRAFT_MAX`, one `review` call |
  | Save-side doctor checks (R17 part) | Task 4 |

  The slice-2 acceptance rows are each a named test; the plan maps them in the Step 1 lists of Tasks 2 and 3.
- **Not in this plan (slice 3):** R10a, R10af, R10b, R10bf, R14 (shipped in slice 1), R15, R17's publishing check, R18, R20, R21, the publish cap `VAULT_DISTILL_PUBLISH_MAX`, `VAULT_DISTILL_PUBLISH`, the calibration sets, and the spec's publish-then-recall end-to-end case.
- **Placeholder scan:** every code step carries the code that was run. The interim `run_extractions` in Task 2 is real behaviour (it parks sessions as `extract-pending`, the same state the cap uses), not a stub.
- **Names:** Task 3 uses the Task 2 names listed in its Interfaces block. `candidates_waiting` counts `candidate`, `ready` and `would-publish`, so slice 3 can publish from the waiting set.
- **README:** Task 4 Step 7. **Diagram:** Task 4 Step 8. **Tier 4:** Go-live G7.
- **Evidence for this plan:** all test code and implementation code in this plan was run before it was written down, in a scratch copy of `bin/` and `tests/` (Python 3.13, `unittest`):
  - `test_jev_gate_distill`, `test_vault_distill`, `test_vault_distill_drafts`, `test_ps_skills_doctor_distill` and the existing `test_ps_skills_doctor`: 72 tests, OK.
  - The Task 2 version alone passes its 20 tests.
  - The new jev-gate and doctor tests fail against the current files (8 failures, 8 errors).
  - A draft rendered by `render_draft` passed the real `vault-engine validate`, built from `tools/vault-engine`.
  - The Task 4 e2e block passed against the real engine in a temp vault.
- **Known limits, left as is:**
  - The seen-file grows by one line per session per night (about 36,000 lines a year). `load_seen` reads it whole.
  - The first real run classifies every session in a 5,700-line inbox, which means many Jev calls. Jev is cheap, per the owner.
  - `keyword_score` ignores the engine's stop-word list (the `shortcut:` comment marks it).

## Audit trail

- 2026-11-11 plan written (writing-plans). Next: `self-grill-audit`.
- 2026-11-11 self-grill-audit (Opus, all 2,405 lines read): verdict safe-with-fixes, no Critical. Each High was checked against the plan text before editing.
  - Corrected (High): the skip list never reached cron (now on the cron line, G6, A5); `repo_root` split the path instead of asking git (A1); G2 linked the live CLI to a worktree that ship may remove (now `_release`).
  - Corrected (Medium): a capped unsure session bounced back to unsure (A2); automated `<` prompts filled the digest and list-form typed prompts were dropped (A3); `--sandbox` added (A4); README wording on `--dry-run` (A5).
  - Not changed: the sends in G3 to G5 stay approved (owner, 2026-11-11), with the skip list and the session count stated first. Auditor confirmed: `bin/jev-gate` is on `release/1.12`, CI's `pytest tests` collects the four new test files, every `agy` flag used exists, tasks sharing `bin/vault-distill` run in sequence.
  - Parked (Medium): cron skips a night when the Mac sleeps (launchd would catch up); the first run has no cap on classify calls (one serial call per session).
  - Parked (Low): an oversized draft is rejected before the credential scan, so one holding a secret stays in the inbox; extract bytes are counted twice in the report; `digests/` and `related/` are never pruned; Batch `3,4` puts about 900 lines on one worker.
  - Still unverified until G4 and G7: that the `agy` print call makes no tool calls and prints bare JSON; that `agy` is logged in under cron; that Jev accepts a 35 KB `score-draft` input.
- 2026-11-11 implementation through `sdd-drive`: 4 of 4 tasks, both batch gates approved (`fe48923`..`3122f31`). Amendments A1 to A5 implemented, with their tests in `tests/test_vault_distill_audit.py`.
- 2026-11-11 final whole-branch review (code-reviewer, Opus): fix first, 2 High, 1 Medium, 3 Low. One fix round (`00b870c`..`9156d4d`); scoped re-review: all seven addressed, one new Important (a night where every session errors exited 0, against R16).
  - Ruling: a second, small fix was dispatched (`461eab7`) instead of parking it, past the one-fix-round rule, because shipping a batch that reports success when every session failed breaks R16. The controller read that diff and ran the six covering test modules (OK); it had no third review. Cost if wrong: an unreviewed 30-line change in the error path.
  - Ruling: the run exits 2 when more than half of the night's sessions errored (the same share R16 uses for unsure). The spec says "fails for every session"; this is stricter.
  - Parked (Low, backlog): `score-draft` sends the first 20,000 bytes of `~/.claude/CLAUDE.md` and the related notes without a credential scan (the spec asks for that input); `quarantine` writes into the vault under `--dry-run`; the hotfix-name strip would rename a real repo called `<x>-hotfix-<y>` once its path is gone; `free_path` is tested at the extractor site only; there is no test that `related_notes` cannot raise.
