# F-028 vault recall precision: implementation plan

Goal (owner, verbatim): "want it help auto save knowledge + auto retrieve knowledge to session", "make sure it is token efficient".

Spec: `spec.md` in this folder (requirements P1 to P5). One task, one worker, one commit per logical unit. All paths are relative to the feature worktree.

## Rules for the worker

- Do not read `~/.claude/state/vault-recall/`, `~/.claude/history.jsonl` or `~/workspace/agentic-vault/`. They are private. Tests use synthetic notes only. P5 is run by the controller after the merge.
- Do not run `precision_sim.py`.
- Touch only the files listed below. No other cleanup.
- Never `git commit --amend`. No real note ids, titles or prompts in any committed file.

## Task 1: hook, engine scoring, summary, eval script

### 1. `skills/agentic-vault/hooks/vault-recall.py` (P1, P3h)

- In `main()`, extend the early return so a prompt that starts with `<` is skipped before the state directory is touched:
  `if len(prompt) < 12 or prompt.startswith(("/", "<")) or not session: return 0` (`prompt` is already stripped).
- `PROMPT_NOTES` becomes 2 and the engine call passes `"--limit", "2"`. Update the module docstring ("up to 2").
- `tests/test_vault_recall.py`: add a test that a `<task-notification>…` prompt prints nothing and creates no file in the state directory; update `test_at_most_three_notes_per_prompt` and `test_query_passes_limit_12` (names and numbers) to 2. Fix any other test whose fixture relied on 3 notes per prompt.

### 2. `tools/vault-engine/pkg/vault/context.go` (P2, P3)

`SummaryLine`: also skip horizontal rules (a trimmed line that is 3 or more of the same character out of `-`, `*`, `_`) and fenced code blocks (a line starting with three backticks or `~~~` toggles "inside a fence"; skip the fence lines and everything inside).

Query terms, a new unexported function used by `ContextByQuery` only (index terms keep using `Terms`). Order matters: the long check counts the raw terms, before the noise words are dropped.

```go
const (
	contextThreshold = 4   // flat score, used while the index is small
	rarityThreshold  = 2.5 // rarity-weighted score, chosen on a labelled prompt set (F-028)
	rarityMinNotes   = 20  // below this, note rarity says nothing
	longQueryTerms   = 80
	longQueryHead    = 20
)

// queryTerms is Terms for a prompt: a long prompt keeps only its opening terms (a long text matches some
// title word of almost every note), then numbers and words typed in most prompts are dropped.
func queryTerms(query string) []string {
	terms := Terms(query)
	if len(terms) > longQueryTerms {
		terms = terms[:longQueryHead]
	}
	var out []string
	for _, t := range terms {
		if !queryNoise[t] && strings.Trim(t, "0123456789") != "" {
			out = append(out, t)
		}
	}
	return out
}
```

`queryNoise` is a `map[string]bool` built from the 77 words of spec Appendix A (copy them exactly), with this comment above it:
`// shortcut: fixed list from the owner's prompt history on 2026-11-11, regenerate when precision_eval.sh drops under 80%.`

`ContextHit.Score` becomes `float64`. `ContextByQuery`:

1. `qTerms := queryTerms(query)`; return nil when empty.
2. Load the index, keep `Status == "active"` entries, build the title, tag and body sets once per entry.
3. `n := len(active)`. When `n >= rarityMinNotes`, count `df[q]` for each query term: the number of active entries where the term is in the title, tag or body set.
4. Per entry and term, the field weight is 3 (title), 2 (tag) or 1 (body), first match wins, as today. When `n >= rarityMinNotes` multiply it by `math.Log(float64(n+1)/(float64(df[q])+0.5)) / math.Log(float64(n+1)/0.5)`.
5. Keep a hit when its score is at least the threshold (`rarityThreshold` when `n >= rarityMinNotes`, else `contextThreshold`) and at least one title or tag term matched.
6. Sort and limit exactly as today (score descending, then `Updated` descending, then `ID` ascending).

Check every reader of `ContextHit.Score` (`graft callers ContextHit` or grep `\.Score`) and fix what the type change breaks.

### 3. `tools/vault-engine/pkg/vault/context_test.go`

Add table tests for the spec's acceptance list (use the helpers already in this file):
- summary: headings, then `---`, then prose gives the prose; a body that opens with a fenced block gives the first line after it;
- a 20-note index where one title word is in every title and another in one title: a query with both returns only the note with the rare word;
- a 100-term query whose only matching term is the 50th returns nothing on a 20-note index; the same term placed first is returned;
- a query whose only matching terms are `2026` and one noise word (for example `build`) returns nothing;
- an index of fewer than 20 notes still uses weights 3/2/1 and threshold 4 (the existing tests cover this: keep them green, changing a query only where it relied on a noise word).

`TestContext_QueryStaysFastAt2000Notes` and `BenchmarkContextByQuery` must still pass at 50 ms.

### 4. `tools/vault-engine/precision_eval.sh` (new, executable) and `recall_eval.sh` (P4)

`recall_eval.sh`: `--limit 3` becomes `--limit 2`.

`precision_eval.sh`, exactly:

```bash
#!/usr/bin/env bash
# Scores injection precision against a private labelled set. Each line: {"prompt": "...", "relevant_ids": ["..."]}
# An injected note counts as relevant only when its id is in relevant_ids, so a note nobody labelled is off topic.
# Usage: precision_eval.sh <set.jsonl> [min_percent]   (VAULT_ENGINE overrides the binary)
set -euo pipefail
SET="${1:?usage: precision_eval.sh <set.jsonl> [min_percent]}"
exec python3 - "$SET" "${2:-80}" "${VAULT_ENGINE:-vault-engine}" <<'PY'
import json, subprocess, sys

path, minimum, engine = sys.argv[1], float(sys.argv[2]), sys.argv[3]
injected = relevant = 0
for line in open(path):
    if not line.strip():
        continue
    row = json.loads(line)
    # The hook sends the first 2,000 characters and injects at most 2 notes.
    out = subprocess.run([engine, "context", "--query", row["prompt"][:2000], "--limit", "2"],
                         capture_output=True, text=True, check=True).stdout
    ids = [l[2:].split(" | ", 1)[0] for l in out.splitlines() if l.startswith("- ") and " | " in l]
    injected += len(ids)
    relevant += sum(i in row["relevant_ids"] for i in ids)
pct = 100 * relevant / injected if injected else 0
print(f"precision: {relevant}/{injected} = {pct:.1f}% (min {minimum:g}%)")
sys.exit(0 if injected and pct >= minimum else 1)
PY
```

One unittest in `tests/test_vault_recall.py` (or a new `tests/test_precision_eval.py`): a stub engine script that always prints two note lines, a two-line set where one id is labelled relevant, expect `precision: 2/4 = 50.0%`, exit 1 at min 80 and exit 0 at min 50.

### 5. Docs

- `README.md` line about `vault-recall.py`: 2 notes per prompt, skips prompts that start with `<`; add `precision_eval.sh` next to where `recall_eval.sh` is described.
- `tools/vault-engine/README.md` `context --query` paragraph: rarity weights from 20 notes up, the noise list, the long-prompt cut.
- `skills/agentic-vault/SKILL.md` only if it states a number that changed.

### Verify (run all, paste the tails)

```bash
cd tools/vault-engine && gofmt -l pkg/vault/ && go vet ./pkg/vault/ && go test ./pkg/vault/ -run 'Context' -count=1 && go test ./pkg/vault/ -run XXX -bench ContextByQuery -benchtime 20x
cd ../.. && python3 -m unittest tests.test_vault_recall -v 2>&1 | tail -5
bash -n tools/vault-engine/precision_eval.sh && test -x tools/vault-engine/precision_eval.sh
python3 -m unittest tests.test_ps_skills_doctor 2>&1 | tail -3   # only if this module exists; the doctor probes `context --query`
```

## Controller only, after review

`psrw ship`, then build the engine, replace the three copies by copy-then-rename (keep `*.bak-pre-precision-20261111`), `vault-engine rebuild-index`, then P5:

```bash
tools/vault-engine/recall_eval.sh ~/.claude/state/vault-recall/recall_set.jsonl 21
tools/vault-engine/precision_eval.sh ~/.claude/state/vault-recall/precision_set.jsonl 80
ps-skills-doctor --strict
```

Expected from the simulation: recall 21/25, precision 15/17 = 88.2%.

## Audit trail

- 2026-11-11 implementation: one worker (`88c1b22`..`9c99580`). The built engine on the private sets: recall 21/25, precision 15/17 = 88.2%, the same as the simulation.
- 2026-11-11 whole-branch review (code-reviewer, Opus): SHIP, no Critical or High. No fix round.
  - Parked (Medium, backlog): `TestContext_RarityWeightsOn20Notes` also passes on the old scorer, because its other 19 notes score 3 there. Put two shared words in every title so the old scorer would return all 20.
  - Parked (Low, backlog):
    - `--limit 2` has no fallback: when the top 2 notes are already injected or demoted, a third qualifying note is not offered (P3h as written; no hook test covers it);
    - an unclosed code fence gives an empty summary, and a prose line that starts with three backticks opens a fence;
    - rules written with spaces (`- - -`, `* * *`) are still taken as the summary.
