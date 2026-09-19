# G-E3 promote-time gate — review-fix spec, plan, and outcome

**Goal:** Close every CONFIRMED finding from the independent adversarial review
of Task 4 (G-E3, the promote-time epic completeness/freshness gate) in
`engine/ps-release-workflow`, with the minimal correct fix per finding, no
unrelated refactors, and the full `pytest` suite green afterward.

**Scope:** 17 findings from two independent opus reviewers (3-vote refutation
per finding) against commit `933732c`, deduped to **9 distinct defects**.

**Files touched:** `scripts/promote_release.py` (all 8 code defects),
`lib/epic.py` (the CAS source-state set), `tests/test_promote_release.py`
(+6 tests). `scripts/ship_current_work_to_release.py` and `lib/epic_gate.py`
were read but did **not** need changing — see defect 1.

**Spec:** `.claude/refined_backlog/F-001-epic-layer-deliver-and-verify-multiple-f/spec.md`
§5.3 (canonical, in the `_release` worktree). This doc is a review-response
addendum to Task 4 of that feature's plan, not a new spec.

---

## 1. HIGH — the freshness fast path was dead code

**Defect.** `if epic["verified_sha"] == head: continue` can never be true.
Ship-time G-E2 captures `cas_sha = HEAD`, then psrw itself adds **two** commits
to `release/<v>`: the CAS-claim commit (`ship_current_work_to_release.py`) and
`run_and_record`'s outcome commit (`lib/epic_gate.py`). `verified_sha` is
therefore permanently ≥2 commits behind release HEAD by the time promote reads
it. Spec 5.3's "Pass" row never fired: **every** promote re-ran the full
multi-minute `epic_check` for **every** epic — precisely the cost blowup spec
5.4 warns gets a gate disabled.

**Fix.** `promote_release._verification_is_fresh()`. The comparison is now
content-based, faithful to spec 5.3's own justification ("the answer is always
about the tree actually being promoted"): a verification is fresh while nothing
**but psrw's own epic bookkeeping** has changed between `verified_sha` and
release HEAD —

```
git diff --quiet <verified_sha> <head> -- ':(exclude).claude/epic_backlog'
```

Everything psrw writes as bookkeeping (the epic catalog and the `E-NNN-<slug>/`
folder the outcome check copies into) lives under that one directory. Any real
change — a ship's merge, a doc, another catalog's status flip — makes it stale
and the check re-runs. `--quiet` exits 0 for "identical", 1 for "differs" and
128 for anything git cannot answer (missing/garbage sha), and **only 0** is
treated as fresh, so every unknown fails safe.

**Why not re-anchor `verified_sha` to the post-bookkeeping HEAD instead** (the
other candidate root-cause fix, which would have touched ship + epic_gate):
it makes an epic's freshness depend on *other* epics' bookkeeping commits — in
a multi-epic release, epic A would go stale the moment epic B recorded its own
outcome, re-introducing the redundant re-runs this defect is about. Comparing
content is both narrower and more honest.

## 2. HIGH — unlocked catalog write in the `--allow-split-epic` branch

`set_split_approved()` + `commit_all()` ran outside `file_lock(rel_wt)` — the
only catalog-write-plus-commit in the codebase not serialized by that lock.
Now wrapped in `with file_lock(rel_wt):` (pass 3 of `_check_epics`), matching
every other catalog-mutation site.

## 3. HIGH — `force=True` stole an in-flight verification

`try_begin_verification(..., force=True)` accepts `verifying` as a source
state, so G-E3 could steal a concurrent ship-time G-E2 (or a running
`psrw epic verify`) mid-flight — two `epic_check` runs executing concurrently
against the same epic, both writing the same `epic_dir`.

**Fix.** New `reclaim_settled=True` keyword on `lib.epic.try_begin_verification`,
used by G-E3 instead of `force`. It widens the accepted source states to the
**settled** ones (`verified`, `promoted` — a finished verdict that is merely no
longer fresh) and deliberately **not** `verifying`. `force` is untouched, so
`psrw epic verify --force` keeps its stale-claim-clearing job.

## 4. MEDIUM — the refusal message described an impossible state

The old "is currently being verified elsewhere — retry promote once that
finishes" could not be reached for that reason (`force=True` stole `verifying`
rather than losing to it) and gave no way out for the state that *could* lose.
The message now names the actual status, explains that G-E3 never steals an
in-flight check, and offers both exits: wait and re-run promote, or clear a
dead claim with `psrw epic verify --force <epic>`.

## 5. MEDIUM — `--allow-split-epic` did nothing for a failed outcome check

`allow_split` is consulted only in the incompleteness branch, yet the
failed-outcome message told the operator to "pass --allow-split-epic to promote
anyway" — following that advice burned another full `epic_check` run and
changed nothing. Spec 5.3's table is explicit: split approval covers an
**incomplete** epic; the failed-outcome row says "pass or refuse on the
result", with no override. So the **message** was the bug. It now names the
real exits (fix the epic / its `hooks.epic_check`, re-run just the check with
`psrw epic verify --force`) and states that `--allow-split-epic` does not cover
this case.

## 6. MEDIUM — a permanent split approval survived an aborted promote

`set_split_approved` is permanent by design (there is no un-approve verb), yet
it was committed for an earlier epic inside a loop that could still refuse the
promote over a later one — leaving a real operator decision on `release/<v>` as
the side effect of an attempt that never succeeded.

**Fix.** `_check_epics` is now three passes: **(1)** classify every epic,
writing nothing (incompleteness refusals raise here, before any write);
**(2)** freshness + outcome check for every complete epic; **(3)** only once
the whole sweep has passed, commit the split approvals. A refusal anywhere
leaves no split approval behind.

## 7. MEDIUM — uncaught exception types escaped `main()`'s guaranteed ERROR line

`check_epics` could raise `lib.backlog_paths.NoReleaseInProgressError` (a
*different* class from `promote_release`'s own same-named one, which is what
`main()` catches) and `lib.git_ops.GitError` (a plain `Exception`, not a
`RuntimeError`) — neither in `main()`'s catch tuple, defeating the whole point
of `EpicGateError(RuntimeError)`.

**Fix.** `check_epics` is now a thin boundary that delegates to `_check_epics`
and normalises both classes into `EpicGateError` (intended refusals —
`EpicGateError`, `CatalogEntryNotFoundError` — pass through untouched).
Additionally, the window between the CAS win and `run_and_record`'s own
try/except (`epic_children`, `epic_folder_path`) is wrapped so a raise records
`failed_verification` on the way out instead of pinning the epic in
`verifying` forever — the same pattern Task 3 added to `run_and_record`.

## 8. MEDIUM — silent skip on a drifted/missing epic id

`if epic is None: continue` disabled the entire gate for that epic with zero
output — exactly F1 (a half-epic reaching main), silently.

**Decision: warn unmissably, do not refuse.** A hard refusal would brick
promote with no way out: no override in this toolkit can repair a missing
catalog entry (`--allow-split-epic` would itself raise
`CatalogEntryNotFoundError`, and `psrw epic verify` needs the entry too), so
the gate would be refusing on the *absence* of information with no operator
exit. The warning goes to stderr, names the epic id and the catalog path, says
plainly that completeness could NOT be checked and that the release may be
carrying a half-epic, and states the repair. This is the same call `cleanup()`
already makes for the identical condition 380 lines below.

## 9. MEDIUM (test) — the staleness test did not test staleness

`test_promote_reruns_the_check_when_verified_sha_is_stale` asserted
`invocations == 2` while the gate re-ran unconditionally (defect 1), so it
could not catch a regression in either direction.

**Six tests added** to `tests/test_promote_release.py`:

| Test | Guards |
|---|---|
| `test_promote_skips_the_check_when_nothing_shipped_since_verification` | defect 1 — the negative case: verify at ship, promote immediately, assert **1** invocation |
| `test_promote_refuses_instead_of_stealing_an_in_flight_verification` | defects 3 + 4 — refuses a `verifying` epic, names `epic verify --force`, check is NOT re-run |
| `test_promote_warns_loudly_when_a_shipped_features_epic_is_missing` | defect 8 |
| `test_promote_does_not_leave_a_split_approval_behind_when_a_later_epic_fails` | defects 5 + 6 |
| `test_promote_records_failed_verification_when_the_gate_itself_crashes` | defect 7 — `GitError` → `EpicGateError`, epic not pinned in `verifying` |
| `test_pr_body_refresh_failure_warns_but_does_not_fail_promote` | the `gh pr edit` failure branch (warn, never raise) |

---

## Outcome

- **Full suite:** `python3 -m pytest -q` → **402 passed, 2 skipped** (396 + 2
  at `933732c`; +6 new tests).
- **Regression-value probe:** the five behavioural new tests were re-run
  against the pre-fix `scripts/promote_release.py` + `lib/epic.py` restored
  from `933732c` — **all five fail** there. (The `gh pr edit` test passes on
  both: that branch already existed and was merely uncovered.)
- **Lint:** `ruff check scripts/promote_release.py lib/epic.py` reports 4
  findings, all pre-existing on untouched lines (`F401`/`F811` on the
  `push` import, two `E701`s on the exception one-liners). No new finding.
- **Locking discipline preserved:** the multi-minute `epic_check` still runs
  entirely outside `file_lock(rel_wt)`; only the HEAD read + freshness diff +
  CAS + its commit, the split-approval writes, and `run_and_record`'s outcome
  write take the lock.
