# EPIC Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an epic layer to ps-release-workflow that delivers multiple features under one epic and verifies the epic as a unit within its own workflow.

**Architecture:** A third catalog (`epic_backlog/_catalog.json`) holds `E-NNN` lifecycle; membership lives only on the child as an optional `epic` key on idea and feature entries. An epic fans out into ideas (never directly into features), so the existing `from_idea` invariant and the brainstorm-before-refine gate both survive untouched. Verification happens twice: a non-blocking gate at ship time that runs an outcome-level hook against an immutable detached-worktree snapshot chosen by compare-and-set, and a blocking gate at promote time that enforces completeness and re-runs the hook whenever the recorded `verified_sha` no longer matches release HEAD.

**Tech Stack:** Python 3.11+, stdlib only (no new dependencies). pytest 8 with `-v --strict-markers`. Bash for the `epic-check.sh` hook contract. Git worktrees for snapshot isolation.

**Spec:** `/Users/pasitnusso/workspace/tools/research/2026-09-18-psrw-epic-workflow-design.md`

**Target repo:** `/Users/pasitnusso/ps-skills/engine/ps-release-workflow` (engine) and `/Users/pasitnusso/ps-skills/skills/` (skill source of truth).

## Global Constraints

- **No new dependencies.** stdlib + git only. `pyproject.toml` dev extras stay `["pytest>=8", "pytest-mock>=3"]`.
- **Every catalog write goes through `lib/state.py:mutate_state`**, and every mutate+commit pair is wrapped in `file_lock(get_release_worktree(repo))`.
- **Never hold `file_lock` across a hook invocation.** That lock is shared by ship, claim, refine, unclaim and idea (`init_work_refined_backlog.py:157,285`, `unclaim.py:116`, `new_idea.py:73`).
- **Hook names must be registered** in `lib/hooks.py:DEFAULT_HOOKS`; `resolve_hook` hard-rejects unknown keys.
- **Absent `epic` key = legacy entry.** No migration is written, ever. Every new predicate must tolerate entries with no `epic` key.
- **A missing hook script warns loudly and skips** — never silently passes, never hard-fails. Mirrors Gate 1's behaviour.
- **SKILL.md bodies are ≤ 40 non-blank lines**, `Mechanics:` anchors come from exactly `d11-backlog-routing|gates|promote-sequence|state-layout|guard-guarantees`, and the `/ps-release-workflow:` slash form is forbidden (`verify.sh:189-205`).
- **Commit style:** one commit per task. Never `git commit --amend`.
- **Epic id prefix is `E`**, zero-padded to 3 (`E-001`), minted by the existing `catalog.next_id(entries, "E")`.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `lib/epic.py` | Epic catalog entry shape, the completeness predicate, and the CAS transition. All epic *state* logic, no git and no subprocess. |
| `lib/epic_gate.py` | Running `epic_check` against an immutable snapshot: create detached worktree, invoke hook, tear down. All epic *execution* logic. |
| `scripts/epic.py` | The `psrw epic` verb: `open`, `fanout`, `verify` subcommands. Thin argparse layer over `lib/epic.py`. |
| `tests/test_epic.py` | Predicate + CAS unit tests. |
| `tests/test_epic_gate.py` | Snapshot-worktree and hook-invocation tests. |
| `tests/test_epic_cli.py` | `psrw epic open` / `fanout` / `verify` behaviour tests. |
| `~/ps-skills/skills/ps-release-workflow-epic-open/SKILL.md` | Trigger surface for opening an epic. |
| `~/ps-skills/skills/ps-release-workflow-epic-fanout/SKILL.md` | Trigger surface for fanning out. |

**Modified:**

| File | Change |
|---|---|
| `lib/catalog.py:53,66` | Optional `epic` parameter on `add_idea_entry` and `add_refined_entry`. |
| `lib/backlog_paths.py:37-40` | Docstring only — `{idea, refined}` → `{idea, refined, epic}`. Code is already generic. |
| `lib/hooks.py` | Register `epic_check` in `DEFAULT_HOOKS`. |
| `scripts/promote_idea_to_refined.py:264` | Pass the idea's `epic` through to `add_refined_entry`. |
| `scripts/ship_current_work_to_release.py` | After the lock is released: CAS, then G-E2. |
| `scripts/promote_release.py:99-123, ~219` | `gh pr edit --body` on the adopt path; G-E3 before Gate 2; epic archiving in `cleanup()`. |
| `scripts/unclaim.py` | Demote a `verified` epic to `open`. |
| `scripts/status.py` | Epic rollup section. |
| `bin/psrw:37-48` | `"epic": Verb("epic.py", ..., True)`. |
| `verify.sh:81,89,187` | Verb count 10→11, verb loop, skill count 13→15. |
| `tests/test_scripts_runnable.py:20`, `tests/test_psrw_cli.py:43-50` | Register `epic.py`. |
| `docs/lifecycle.md`, `docs/known-issues.md` | Epic section; anything discovered. |

Split rationale: `lib/epic.py` is pure state (fast, trivially testable, no git); `lib/epic_gate.py` is the only place that shells out for verification. Keeping them apart means the predicate tests need no git fixtures at all, and the gate tests need no catalog scaffolding.

---

## Task 1: Epic data layer and tag propagation

**Files:**
- Create: `lib/epic.py`, `tests/test_epic.py`
- Modify: `lib/catalog.py:53,66`, `lib/backlog_paths.py:38`, `scripts/promote_idea_to_refined.py:264`
- Test: `tests/test_epic.py`, plus existing `tests/test_catalog.py` and `tests/test_promote_idea_to_refined.py` must stay green

**Interfaces:**
- Consumes: `lib.state.mutate_state`, `lib.catalog.next_id`, `lib.catalog.list_entries`, `lib.backlog_paths.get_backlog_catalog_path`
- Produces:
  - `lib.epic.add_epic_entry(catalog: Path, title: str) -> dict`
  - `lib.epic.epic_completeness(idea_cat: Path, refined_cat: Path, epic_id: str, release_version: str) -> tuple[bool, list[str]]` — `(is_complete, reasons_not_complete)`
  - `lib.epic.try_begin_verification(epic_cat: Path, epic_id: str, sha: str) -> bool` — the CAS
  - `lib.epic.mark_epic_verified(epic_cat, epic_id, sha, release_version) -> dict`
  - `lib.epic.mark_epic_failed(epic_cat, epic_id, release_version) -> dict`
  - `lib.epic.demote_epic(epic_cat, epic_id) -> dict`
  - `lib.epic.mark_epic_promoted(epic_cat, epic_id) -> dict`
  - `lib.epic.set_split_approved(epic_cat, epic_id, owner: str) -> dict` — the **only** producer of `split_approved_by`; called by Task 4's `--allow-split-epic`
  - `lib.epic.epic_folder_path(repo: Path, epic_id: str) -> Path | None` — resolves `E-NNN-<slug>/` by id prefix; supplies `PSRW_EPIC_DIR`
  - `lib.catalog.add_idea_entry(catalog, title, epic=None)` / `add_refined_entry(catalog, idea_id, title, epic=None)`

- [ ] **Step 1: Write the failing completeness tests**

```python
# tests/test_epic.py
import json
from pathlib import Path

import pytest

from lib.epic import add_epic_entry, epic_completeness, try_begin_verification


def _write(p: Path, data) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    return p


def test_unfanned_epic_is_not_vacuously_complete(tmp_path):
    ideas = _write(tmp_path / "idea.json", [])
    refined = _write(tmp_path / "ref.json", [])
    ok, reasons = epic_completeness(ideas, refined, "E-001", "1.1")
    assert ok is False
    assert any("no ideas" in r for r in reasons)


def test_unrefined_slice_blocks_completeness(tmp_path):
    """The blocker the first audit found: a slice still sitting as an idea."""
    ideas = _write(tmp_path / "idea.json", [
        {"id": "I-001", "title": "a", "promoted_to": "F-001", "epic": "E-001"},
        {"id": "I-002", "title": "b", "promoted_to": None, "epic": "E-001"},
    ])
    refined = _write(tmp_path / "ref.json", [
        {"id": "F-001", "from_idea": "I-001", "epic": "E-001",
         "status": "shipped", "release_version": "1.1"},
    ])
    ok, reasons = epic_completeness(ideas, refined, "E-001", "1.1")
    assert ok is False
    assert any("I-002" in r for r in reasons)


def test_unclaimed_sibling_with_stale_release_version_is_not_shipped(tmp_path):
    """unclaim.py:112-118 leaves release_version set; status must also be checked."""
    ideas = _write(tmp_path / "idea.json", [
        {"id": "I-001", "title": "a", "promoted_to": "F-001", "epic": "E-001"},
    ])
    refined = _write(tmp_path / "ref.json", [
        {"id": "F-001", "from_idea": "I-001", "epic": "E-001",
         "status": "open", "release_version": "1.1"},
    ])
    ok, reasons = epic_completeness(ideas, refined, "E-001", "1.1")
    assert ok is False
    assert any("F-001" in r for r in reasons)


def test_complete_epic(tmp_path):
    ideas = _write(tmp_path / "idea.json", [
        {"id": "I-001", "title": "a", "promoted_to": "F-001", "epic": "E-001"},
        {"id": "I-002", "title": "b", "promoted_to": "F-002", "epic": "E-001"},
    ])
    refined = _write(tmp_path / "ref.json", [
        {"id": "F-001", "from_idea": "I-001", "epic": "E-001",
         "status": "shipped", "release_version": "1.1"},
        {"id": "F-002", "from_idea": "I-002", "epic": "E-001",
         "status": "promoted", "release_version": "1.1"},
    ])
    ok, reasons = epic_completeness(ideas, refined, "E-001", "1.1")
    assert ok is True
    assert reasons == []


def test_legacy_entries_without_epic_key_are_ignored(tmp_path):
    """No migration is ever written, so the predicate must tolerate absent keys."""
    ideas = _write(tmp_path / "idea.json", [
        {"id": "I-009", "title": "legacy", "promoted_to": None},
        {"id": "I-001", "title": "a", "promoted_to": "F-001", "epic": "E-001"},
    ])
    refined = _write(tmp_path / "ref.json", [
        {"id": "F-009", "from_idea": "I-009", "status": "open", "release_version": None},
        {"id": "F-001", "from_idea": "I-001", "epic": "E-001",
         "status": "shipped", "release_version": "1.1"},
    ])
    ok, _ = epic_completeness(ideas, refined, "E-001", "1.1")
    assert ok is True


def test_cas_lets_exactly_one_caller_begin(tmp_path):
    cat = _write(tmp_path / "epic.json", [])
    add_epic_entry(cat, "Multi-account risk limits")
    assert try_begin_verification(cat, "E-001", "deadbeef") is True
    assert try_begin_verification(cat, "E-001", "deadbeef") is False
    entry = json.loads(cat.read_text())[0]
    assert entry["status"] == "verifying"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/ps-skills/engine/ps-release-workflow && python -m pytest tests/test_epic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.epic'`

- [ ] **Step 3: Write `lib/epic.py`**

```python
"""Epic-layer state: the third catalog, the completeness predicate, and the CAS.

Pure state only — no git, no subprocess. lib/epic_gate.py owns execution.
"""
from datetime import datetime, timezone
from pathlib import Path

from lib.catalog import list_entries, next_id
from lib.state import mutate_state


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_epic_entry(catalog: Path, title: str) -> dict:
    new_entry: dict = {}

    def add(entries: list) -> list:
        new_entry.update({
            "id": next_id(entries, "E"),
            "title": title,
            "created_at": _now(),
            "status": "open",
            "release_version": None,
            "verified_sha": None,
            "verified_at": None,
            "split_approved_by": None,
        })
        return entries + [new_entry]

    mutate_state(catalog, add, default=[])
    return new_entry


def epic_children(idea_cat: Path, epic_id: str) -> list[dict]:
    """Ideas tagged to this epic. Legacy entries have no 'epic' key — .get() tolerates that."""
    return [e for e in list_entries(idea_cat) if e.get("epic") == epic_id]


def epic_completeness(
    idea_cat: Path, refined_cat: Path, epic_id: str, release_version: str
) -> tuple[bool, list[str]]:
    """Spec 5.1. Returns (is_complete, reasons_not_complete).

    Condition 3 checks status AND release_version: unclaim.py:112-118 clears
    claimed_by but LEAVES release_version set, so release_version alone would
    misread a reclaimed-then-unclaimed sibling as shipped.
    """
    reasons: list[str] = []
    ideas = epic_children(idea_cat, epic_id)

    if not ideas:
        return False, [f"{epic_id} has no ideas — it has not been fanned out"]

    unrefined = [i["id"] for i in ideas if not i.get("promoted_to")]
    if unrefined:
        reasons.append(f"not yet refined into a feature: {', '.join(sorted(unrefined))}")

    wanted = {i["promoted_to"] for i in ideas if i.get("promoted_to")}
    by_id = {f["id"]: f for f in list_entries(refined_cat)}
    for feature_id in sorted(wanted):
        feature = by_id.get(feature_id)
        if feature is None:
            reasons.append(f"{feature_id} is missing from the refined catalog")
        elif feature.get("status") not in ("shipped", "promoted"):
            reasons.append(f"{feature_id} is {feature.get('status')}, not shipped")
        elif feature.get("release_version") != release_version:
            reasons.append(
                f"{feature_id} shipped on {feature.get('release_version')}, not {release_version}"
            )

    return (not reasons), reasons


class _NoTransition(Exception):
    """Raised inside the mutate_state callback to leave the file untouched."""


def try_begin_verification(epic_cat: Path, epic_id: str, sha: str) -> bool:
    """Compare-and-set: open|failed_verification -> verifying. True == this caller won.

    No timestamp and no timeout: 'recently verifying' is not implementable without
    inventing a threshold nobody can defend. A crashed run is cleared by
    `psrw epic verify --force`.
    """
    won = False

    def cas(entries: list) -> list:
        nonlocal won
        for e in entries:
            if e["id"] != epic_id:
                continue
            if e.get("status") not in ("open", "failed_verification"):
                raise _NoTransition()
            e["status"] = "verifying"
            e["verifying_sha"] = sha
            won = True
            return entries
        raise _NoTransition()

    try:
        mutate_state(epic_cat, cas, default=[])
    except _NoTransition:
        return False
    return won


def _set_fields(epic_cat: Path, epic_id: str, **fields) -> dict:
    updated: dict = {}

    def apply(entries: list) -> list:
        for e in entries:
            if e["id"] == epic_id:
                e.update(fields)
                updated.update(e)
                return entries
        raise _NoTransition()

    try:
        mutate_state(epic_cat, apply, default=[])
    except _NoTransition:
        raise KeyError(f"epic {epic_id} not found in {epic_cat}")
    return updated


def mark_epic_verified(epic_cat: Path, epic_id: str, sha: str, release_version: str) -> dict:
    return _set_fields(
        epic_cat, epic_id, status="verified", verified_sha=sha,
        verified_at=_now(), release_version=release_version,
    )


def mark_epic_failed(epic_cat: Path, epic_id: str, release_version: str) -> dict:
    return _set_fields(
        epic_cat, epic_id, status="failed_verification",
        verified_sha=None, release_version=release_version,
    )


def demote_epic(epic_cat: Path, epic_id: str) -> dict:
    """Back to 'open' — never to 'verifying', which would collide with the CAS
    and strand the epic forever."""
    return _set_fields(epic_cat, epic_id, status="open", verified_sha=None, verified_at=None)


def mark_epic_promoted(epic_cat: Path, epic_id: str) -> dict:
    return _set_fields(epic_cat, epic_id, status="promoted")


def set_split_approved(epic_cat: Path, epic_id: str, owner: str) -> dict:
    """Permanent: once set, G-E3 exempts this epic in every later release too.
    Otherwise the operator re-approves the same split each release and the
    override decays into a rubber stamp."""
    return _set_fields(epic_cat, epic_id, split_approved_by=owner)


def epic_folder_path(repo: Path, epic_id: str):
    """`E-NNN-<slug>/` inside the _release worktree, or None if absent."""
    from lib.backlog_paths import get_release_worktree
    root = get_release_worktree(repo) / ".claude" / "epic_backlog"
    for child in sorted(root.glob(f"{epic_id}-*")):
        if child.is_dir():
            return child
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/ps-skills/engine/ps-release-workflow && python -m pytest tests/test_epic.py -v`
Expected: PASS, 6 passed

- [ ] **Step 5: Add the `epic` parameter to both entry constructors**

In `lib/catalog.py`, change the two signatures and include the key only when set, so legacy rows stay byte-identical:

```python
def add_idea_entry(catalog: Path, title: str, epic: str | None = None) -> dict:
    new_entry: dict = {}
    def add(entries: list) -> list:
        nid = next_id(entries, "I")
        new_entry.update({
            "id": nid, "title": title,
            "created_at": _now(), "promoted_to": None,
        })
        if epic:
            new_entry["epic"] = epic
        return entries + [new_entry]
    mutate_state(catalog, add, default=[])
    return new_entry
```

Apply the same `if epic: new_entry["epic"] = epic` line to `add_refined_entry`.

- [ ] **Step 6: Propagate the tag at refine time**

`scripts/promote_idea_to_refined.py:264` currently drops anything not in the signature:

```python
        feat = add_refined_entry(
            ref_cat, idea_id=idea_id, title=idea["title"], epic=idea.get("epic")
        )
```

Add to `tests/test_promote_idea_to_refined.py`:

```python
def test_refine_carries_the_epic_tag_forward(tmp_repo_in_release, fixed_owner):
    repo = tmp_repo_in_release
    idea_cat = get_backlog_catalog_path(repo, "idea")
    add_idea_entry(idea_cat, "slice a", epic="E-001")
    result = promote_idea_to_refined(repo, "I-001")
    refined = json.loads(get_backlog_catalog_path(repo, "refined").read_text())
    assert refined[0]["epic"] == "E-001"
    assert refined[0]["id"] == result["feature"]["id"]
```

- [ ] **Step 7: Update the `backlog_paths` docstring**

`lib/backlog_paths.py:38`: `"""kind in {idea, refined, epic}. Returns ..."""` — the code is already generic, so this is the whole change.

- [ ] **Step 8: Run the full suite**

Run: `cd ~/ps-skills/engine/ps-release-workflow && python -m pytest -q 2>&1 | tail -n 15`
Expected: all green. `test_catalog.py` and `test_promote_idea_to_refined.py` must be unaffected — the `epic` parameter defaults to `None` and adds no key when unset.

- [ ] **Step 9: Commit**

```bash
git add lib/epic.py lib/catalog.py lib/backlog_paths.py \
        scripts/promote_idea_to_refined.py tests/test_epic.py tests/test_promote_idea_to_refined.py
git commit -m "feat(epic): epic catalog, completeness predicate, CAS, tag propagation"
```

- [ ] **Step 10: Phase gate** — verify (Step 8 output) → independent review (`code-reviewer` + `python-reviewer`, `model: sonnet`) → `/simplify` → re-run Step 8.

---

## Task 2: `psrw epic open` and `psrw epic fanout`, fully registered

**Files:**
- Create: `scripts/epic.py`, `tests/test_epic_cli.py`
- Modify: `bin/psrw:37-48`, `verify.sh:81,89`, `tests/test_scripts_runnable.py:20`, `tests/test_psrw_cli.py:43-50`

**Interfaces:**
- Consumes: `lib.epic.add_epic_entry`, `lib.catalog.add_idea_entry`, `lib.backlog_paths.get_backlog_catalog_path`, `lib.backlog_paths.get_release_worktree`, `lib.state.file_lock`, `lib.git_ops.commit_all`, `lib.slug.slugify`
- Produces: `scripts.epic.epic_open(repo, title) -> dict`, `scripts.epic.epic_fanout(repo, epic_id, titles) -> dict`

<div class="callout warn">Registration lives in THIS task, not a later one. v2 of the spec deferred it to a final surface phase, which would have left this task's own quality gate red — <code>tests/test_psrw_cli.py</code> asserts bidirectionally that every file in <code>scripts/</code> is either a verb or in <code>NON_VERBS</code>.</div>

- [ ] **Step 1: Write the failing CLI tests**

```python
# tests/test_epic_cli.py
import json

import pytest

from lib.backlog_paths import get_backlog_catalog_path
from scripts.epic import epic_open, epic_fanout


def test_open_mints_epic_with_spec_and_verification(tmp_repo_in_release, fixed_owner):
    repo = tmp_repo_in_release
    result = epic_open(repo, "Multi-account risk limits")
    assert result["epic"]["id"] == "E-001"
    folder = result["folder"]
    assert (folder / "spec.md").exists()
    assert (folder / "verification.md").exists()
    assert "status: epic" in (folder / "spec.md").read_text()


def test_fanout_mints_one_idea_per_slice_all_tagged(tmp_repo_in_release, fixed_owner):
    repo = tmp_repo_in_release
    epic_open(repo, "Multi-account risk limits")
    result = epic_fanout(repo, "E-001", ["per-account cap", "aggregate cap", "breach alert"])
    ideas = json.loads(get_backlog_catalog_path(repo, "idea").read_text())
    assert [i["id"] for i in ideas] == ["I-001", "I-002", "I-003"]
    assert {i["epic"] for i in ideas} == {"E-001"}
    assert len(result["ideas"]) == 3


def test_fanout_is_all_or_nothing(tmp_repo_in_release, fixed_owner, monkeypatch):
    """A failure partway must mint nothing — the FileExistsError-on-retry bug in
    docs/known-issues.md multiplies by N here."""
    repo = tmp_repo_in_release
    epic_open(repo, "Multi-account risk limits")

    # Patch the NARROW call, not Path.mkdir globally: file_lock's lockdir.mkdir
    # (state.py:28) and mutate_state's parent.mkdir (state.py:69) both fire first,
    # so a global patch raises before a single id is minted and the rollback this
    # test exists for is never exercised.
    import scripts.epic as epic_mod
    real_write = epic_mod.Path.write_text
    calls = {"n": 0}

    def exploding_write(self, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 3:          # partway through slice 2
            raise OSError("disk full")
        return real_write(self, *a, **kw)

    monkeypatch.setattr(epic_mod.Path, "write_text", exploding_write)
    with pytest.raises(OSError):
        epic_fanout(repo, "E-001", ["a", "b", "c"])

    ideas = json.loads(get_backlog_catalog_path(repo, "idea").read_text())
    assert ideas == [], "a partial fan-out must mint nothing"
    assert not list((repo / ".claude" / "worktrees" / "_release"
                     / ".claude" / "idea_backlog").glob("I-*"))


def test_fanout_twice_appends_slices(tmp_repo_in_release, fixed_owner):
    """No stored slice_count, so a later fanout simply adds more tagged ideas."""
    repo = tmp_repo_in_release
    epic_open(repo, "E")
    epic_fanout(repo, "E-001", ["a"])
    epic_fanout(repo, "E-001", ["b"])
    ideas = json.loads(get_backlog_catalog_path(repo, "idea").read_text())
    assert len(ideas) == 2


def test_title_with_double_quotes_is_sanitized(tmp_repo_in_release, fixed_owner):
    """known-issues.md: quotes in titles produce broken YAML in skeletons."""
    repo = tmp_repo_in_release
    result = epic_open(repo, 'Cap the "risk" number')
    spec = (result["folder"] / "spec.md").read_text()
    assert '"risk"' not in spec.split("---")[1]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_epic_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.epic'`

- [ ] **Step 3: Write `scripts/epic.py`**

```python
"""psrw epic — open an epic, fan it out into ideas, verify it."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import shutil
import sys
from pathlib import Path

from lib.backlog_paths import (
    NoReleaseInProgressError, get_backlog_catalog_path, get_release_worktree,
)
from lib.catalog import CatalogEntryNotFoundError, add_idea_entry, find_entry
from lib.epic import add_epic_entry
from lib.git_ops import GitError, commit_all
from lib.repo import find_repo_root
from lib.slug import slugify
from lib.state import file_lock

_SPEC_SKELETON = """---
title: {title}
id: {epic_id}
status: epic
---

# {title}

## Outcome

<!-- What is true once every slice has shipped? -->

## Slices

<!-- One line per slice. `psrw epic fanout` turns these into ideas. -->
"""

_VERIFICATION_SKELETON = """---
title: {title}
id: {epic_id}
---

# How we will know {epic_id} works

Prose for humans. `scripts/epic-check.sh` implements these assertions; the
toolkit never parses this file.

## Assertions

1. <!-- end-to-end assertion -->
"""


def _sanitize(title: str) -> str:
    """Double quotes break the YAML in skeletons and in the identity rewrite
    (docs/known-issues.md). Strip them on the way in rather than inherit the bug."""
    return title.replace('"', "'").strip()


def epic_open(repo: Path, title: str) -> dict:
    title = _sanitize(title)
    wt = get_release_worktree(repo)
    epic_cat = get_backlog_catalog_path(repo, "epic")
    with file_lock(wt):
        epic = add_epic_entry(epic_cat, title)
        folder = wt / ".claude" / "epic_backlog" / f"{epic['id']}-{slugify(title)}"
        try:
            folder.mkdir(parents=True)
            (folder / "spec.md").write_text(
                _SPEC_SKELETON.format(title=title, epic_id=epic["id"])
            )
            (folder / "verification.md").write_text(
                _VERIFICATION_SKELETON.format(title=title, epic_id=epic["id"])
            )
        except Exception:
            _rollback_epic(epic_cat, epic["id"], folder)
            raise
        commit_all(wt, f"chore(epic): open {epic['id']} {title}")
    return {"epic": epic, "folder": folder}


def epic_fanout(repo: Path, epic_id: str, titles: list[str]) -> dict:
    """Mint one IDEA per slice — never a feature. Minting F-NNN directly would
    break the from_idea invariant and auto-chain idea -> refine."""
    titles = [_sanitize(t) for t in titles]
    wt = get_release_worktree(repo)
    # A typo'd id must not silently mint N ideas tagged to an epic that does not
    # exist — nothing would ever complete them. This is the same silent-drift
    # class CatalogEntryNotFoundError was introduced to kill (lib/catalog.py:10-22).
    epic_cat = get_backlog_catalog_path(repo, "epic")
    if find_entry(epic_cat, epic_id) is None:
        raise CatalogEntryNotFoundError(epic_id, epic_cat)
    idea_cat = get_backlog_catalog_path(repo, "idea")
    minted: list[dict] = []
    folders: list[Path] = []
    with file_lock(wt):
        try:
            for title in titles:
                idea = add_idea_entry(idea_cat, title, epic=epic_id)
                minted.append(idea)
                folder = wt / ".claude" / "idea_backlog" / f"{idea['id']}-{slugify(title)}"
                folder.mkdir(parents=True)
                folders.append(folder)
                (folder / "spec.md").write_text(
                    f"---\ntitle: {title}\nid: {idea['id']}\nstatus: idea\n---\n\n# {title}\n"
                )
                (folder / "research.md").write_text(f"# Research — {title}\n")
        except Exception:
            _rollback_ideas(idea_cat, minted, folders)
            raise
        commit_all(wt, f"chore(epic): fan out {epic_id} into {len(minted)} ideas")
    return {"epic_id": epic_id, "ideas": minted}
```

- [ ] **Step 3b: Write `main()` — `verify.sh` fails without it**

`verify.sh:90-94` runs every listed verb's `--help` and requires exit 0 **and** the word "usage" in the output; `bin/psrw:94-104` forwards `--help` to the script for `argparse_safe` verbs. Without this block Task 2's own phase gate goes red.

```python
def main() -> int:
    import argparse
    p = argparse.ArgumentParser(prog="psrw epic", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    p_open = sub.add_parser("open", help="mint an epic and its spec skeletons")
    p_open.add_argument("title")

    p_fan = sub.add_parser("fanout", help="mint one idea per slice, tagged to the epic")
    p_fan.add_argument("epic_id", metavar="E-NNN")
    p_fan.add_argument("titles", nargs="+", metavar="SLICE")

    p_ver = sub.add_parser("verify", help="re-run the epic gate")
    p_ver.add_argument("epic_id", metavar="E-NNN")
    p_ver.add_argument("--force", action="store_true",
                       help="clear a stale 'verifying' left by a crashed run")

    args = p.parse_args()
    repo = find_repo_root(Path.cwd())
    try:
        if args.cmd == "open":
            result = epic_open(repo, args.title)
        elif args.cmd == "fanout":
            result = epic_fanout(repo, args.epic_id, args.titles)
        else:
            result = epic_verify(repo, args.epic_id, force=args.force)
    except (NoReleaseInProgressError, CatalogEntryNotFoundError, GitError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Write `_rollback_epic` and `_rollback_ideas` as mirror images of the rollback in `promote_idea_to_refined.py` (remove the catalog entry, then `shutil.rmtree` the folder if present) so a retry re-mints the *same* id.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_epic_cli.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Register the verb**

`bin/psrw`, in `VERBS`: `"epic": Verb("epic.py", "Open an epic, fan it out into ideas, verify it", True)`

`argparse_safe=True` is required or the dispatcher swallows `--help`. It is safe despite `fanout` mutating, because argparse handles `--help` and exits during parsing, before any handler runs.

`tests/test_scripts_runnable.py:20`: add `"epic.py"` to `RUNNABLE_SCRIPTS`.

`verify.sh:81`: `check "verb table has 11 verbs" "11"`; add `epic` to the hardcoded verb loop at `:89`; and update the adjacent literal message at `:94`, which still says "all 10 verbs".

- [ ] **Step 6: Run the registration tests**

Run: `python -m pytest tests/test_psrw_cli.py tests/test_scripts_runnable.py -v && ./verify.sh 2>&1 | tail -n 20`
Expected: PASS, and `verify.sh` green. **The skill-count check at `:187` still expects 13 and is correct at this point** — skills land in Task 5.

- [ ] **Step 7: Commit**

```bash
git add scripts/epic.py tests/test_epic_cli.py bin/psrw verify.sh \
        tests/test_scripts_runnable.py tests/test_psrw_cli.py
git commit -m "feat(epic): psrw epic open + fanout, verb registered"
```

- [ ] **Step 8: Phase gate** — verify (Step 6) → independent review → `/simplify` → re-verify.

---

## Task 3: G-E2 — the ship-time verification gate

**Files:**
- Create: `lib/epic_gate.py`, `tests/test_epic_gate.py`
- Modify: `lib/hooks.py`, `scripts/ship_current_work_to_release.py`, `scripts/epic.py` (adds the `verify` subcommand)

**Interfaces:**
- Consumes: `lib.hooks.resolve_hook`, `lib.epic.try_begin_verification`, `lib.epic.mark_epic_verified`, `lib.epic.mark_epic_failed`, `lib.epic.epic_completeness`, `lib.git_ops.git_run`
- Produces: `lib.epic_gate.run_epic_check(repo, rel_wt, epic_id, features, sha) -> int | None` — returns the hook's exit code, or `None` when the script is absent

- [ ] **Step 1: Write the failing gate tests**

```python
# tests/test_epic_gate.py
import subprocess

from lib.epic_gate import run_epic_check


def _scaffold_epic_check(repo, body="#!/bin/sh\nexit 0\n"):
    """Commit scripts/epic-check.sh on main BEFORE branches are cut, so the
    release tree carries it — same pattern as _scaffold_precheck."""
    d = repo / "scripts"
    d.mkdir(exist_ok=True)
    f = d / "epic-check.sh"
    f.write_text(body)
    f.chmod(0o755)
    subprocess.run(["git", "add", "scripts/epic-check.sh"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "scaffold epic-check"], cwd=repo,
                   check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True, capture_output=True)


def test_missing_script_returns_none_and_does_not_fail(tmp_repo_in_release, capsys):
    repo = tmp_repo_in_release
    rel_wt = repo / ".claude" / "worktrees" / "_release"
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rel_wt,
                         capture_output=True, text=True, check=True).stdout.strip()
    rc = run_epic_check(repo, rel_wt, "E-001", ["F-001"], sha)
    assert rc is None
    assert "epic_check" in capsys.readouterr().err


def test_hook_runs_in_a_detached_snapshot_not_the_shared_tree(tmp_repo_in_release):
    """The suite must not run in _release, which concurrent ships mutate."""
    repo = tmp_repo_in_release
    _scaffold_epic_check(repo, "#!/bin/sh\npwd > \"$PSRW_EPIC_DIR/where\"\nexit 0\n")
    rel_wt = repo / ".claude" / "worktrees" / "_release"
    subprocess.run(["git", "merge", "origin/main", "--no-edit"], cwd=rel_wt,
                   check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rel_wt,
                         capture_output=True, text=True, check=True).stdout.strip()
    epic_dir = repo / ".claude" / "epic_tmp"
    epic_dir.mkdir()
    rc = run_epic_check(repo, rel_wt, "E-001", ["F-001"], sha, epic_dir=epic_dir)
    assert rc == 0
    where = (epic_dir / "where").read_text().strip()
    assert str(rel_wt) not in where


def test_snapshot_worktree_is_removed_afterwards(tmp_repo_in_release):
    repo = tmp_repo_in_release
    _scaffold_epic_check(repo)
    rel_wt = repo / ".claude" / "worktrees" / "_release"
    subprocess.run(["git", "merge", "origin/main", "--no-edit"], cwd=rel_wt,
                   check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rel_wt,
                         capture_output=True, text=True, check=True).stdout.strip()
    before = subprocess.run(["git", "worktree", "list"], cwd=repo,
                            capture_output=True, text=True).stdout
    run_epic_check(repo, rel_wt, "E-001", ["F-001"], sha)
    after = subprocess.run(["git", "worktree", "list"], cwd=repo,
                           capture_output=True, text=True).stdout
    assert before.count("\n") == after.count("\n")


def test_failing_hook_returns_nonzero(tmp_repo_in_release):
    repo = tmp_repo_in_release
    _scaffold_epic_check(repo, "#!/bin/sh\nexit 3\n")
    rel_wt = repo / ".claude" / "worktrees" / "_release"
    subprocess.run(["git", "merge", "origin/main", "--no-edit"], cwd=rel_wt,
                   check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rel_wt,
                         capture_output=True, text=True, check=True).stdout.strip()
    assert run_epic_check(repo, rel_wt, "E-001", ["F-001"], sha) == 3
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_epic_gate.py -v`
Expected: FAIL — `No module named 'lib.epic_gate'`

- [ ] **Step 3: Register the hook**

`lib/hooks.py`, in `DEFAULT_HOOKS`: `"epic_check": "scripts/epic-check.sh"`. Mandatory — `resolve_hook` hard-rejects unknown keys.

- [ ] **Step 4: Write `lib/epic_gate.py`**

```python
"""Run the epic_check hook against an immutable snapshot of the release tree.

The shared _release worktree is mutated by every concurrent ship (merge --no-ff,
reset --hard HEAD~1, commit_all — ship_current_work_to_release.py:112-145).
Running a multi-minute outcome suite there yields false failures, or a pass
against a tree that is then reset. So the hook runs in a throwaway worktree
detached at a captured sha, which nothing can move underneath it.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from lib.git_ops import _run as git_run          # NOTE: the public name is `_run`;
from lib.hooks import HookPathError, resolve_hook  # every caller aliases it this way


def run_epic_check(
    repo: Path, rel_wt: Path, epic_id: str, features: list[str], sha: str,
    epic_dir: Path | None = None, release_version: str = "",
) -> int | None:
    """Returns the hook's exit code, or None when the script is absent or unusable.

    Absent -> warn loudly and skip, mirroring Gate 1
    (ship_current_work_to_release.py:52-59). Never silently green.
    """
    with tempfile.TemporaryDirectory(prefix="psrw-epic-") as tmp:
        snapshot = Path(tmp) / "snapshot"
        git_run(repo, "worktree", "add", "--detach", str(snapshot), sha)
        try:
            # resolve_hook returns an ABSOLUTE path inside the tree it is given
            # (lib/hooks.py:74-86) and does NOT check existence. Resolving against
            # `snapshot` is load-bearing: resolving against rel_wt and then doing
            # `snapshot / hook` is a no-op, because pathlib drops the left side
            # when the right is absolute — the hook would run in the SHARED tree
            # and the immutable-snapshot guarantee would be silently void.
            try:
                hook = resolve_hook(snapshot, "epic_check")
            except HookPathError as e:
                print(f"WARNING: hooks.epic_check unusable ({e}) — {epic_id} "
                      f"outcome check SKIPPED. Completeness is still enforced at "
                      f"promote.", file=sys.stderr)
                return None
            if not hook.exists():
                print(f"WARNING: hooks.epic_check not found at {hook} — {epic_id} "
                      f"outcome check SKIPPED. Completeness is still enforced at "
                      f"promote.", file=sys.stderr)
                return None

            env = {
                "PSRW_EPIC_ID": epic_id,
                "PSRW_EPIC_FEATURES": ",".join(sorted(features)),
                "PSRW_EPIC_DIR": str(epic_dir) if epic_dir else "",
                "PSRW_EPIC_SHA": sha,
                "PSRW_RELEASE_VERSION": release_version,
            }
            proc = subprocess.run([str(hook)], cwd=snapshot, env={**os.environ, **env})
            return proc.returncode
        finally:
            git_run(repo, "worktree", "remove", "--force", str(snapshot))
```

<div class="callout danger">
Three real API contracts this block depends on, each verified against source and each one a crash if assumed wrong:
<strong>(1)</strong> <code>lib/git_ops.py:10</code> exports <code>_run</code>, not <code>git_run</code> — every caller aliases it (<code>ship_current_work_to_release.py:23</code>, <code>promote_release.py:17</code>).
<strong>(2)</strong> <code>_run</code> returns a <code>CompletedProcess</code>, so reading output is <code>.stdout.strip()</code>, never <code>.strip()</code>.
<strong>(3)</strong> <code>resolve_hook</code> (<code>lib/hooks.py:46,74-86</code>) states "Existence is NOT checked" and raises only <code>KeyError</code> or <code>HookPathError</code> — never <code>FileNotFoundError</code>. Catching the wrong exception would leave the documented warn-and-skip path dead, and the missing-script case would crash instead.
</div>

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest tests/test_epic_gate.py -v`
Expected: PASS, 4 passed

- [ ] **Step 6: Wire G-E2 into ship, outside the lock**

In `ship_current_work()`, after the `with file_lock(rel_wt):` block ends. The CAS itself runs inside the lock (HEAD is stable there); the hook runs after it is released.

```python
    # --- inside the existing lock, after commit_all ---
    # ship currently imports only CatalogEntryNotFoundError and mark_shipped
    # (ship_current_work_to_release.py:22) — add find_entry and the epic helpers,
    # and `from lib.git_ops import _run as git_run` if not already aliased.
    epic_id = (find_entry(refined_cat, feature_id) or {}).get("epic")
    cas_sha = None
    if epic_id:
        idea_cat = get_backlog_catalog_path(repo, "idea")
        epic_cat = get_backlog_catalog_path(repo, "epic")
        complete, _ = epic_completeness(idea_cat, refined_cat, epic_id, release_version)
        if complete:
            head = git_run(rel_wt, "rev-parse", "HEAD").stdout.strip()
            if try_begin_verification(epic_cat, epic_id, head):
                cas_sha = head

    # --- lock released; only the CAS winner gets here ---
    if cas_sha:
        features = [i["promoted_to"] for i in epic_children(idea_cat, epic_id)]
        epic_folder = epic_folder_path(repo, epic_id)   # spec 5.4: PSRW_EPIC_DIR
        rc = run_epic_check(repo, rel_wt, epic_id, features, cas_sha,
                            epic_dir=epic_folder, release_version=release_version)
        with file_lock(rel_wt):
            if rc is None or rc == 0:
                mark_epic_verified(epic_cat, epic_id, cas_sha, release_version)
            else:
                mark_epic_failed(epic_cat, epic_id, release_version)
            commit_all(rel_wt, f"chore(epic): {epic_id} verification result")
```

**Nothing is rolled back on failure.** The epic catalog is a tracked file in this tree, so a `reset --hard` would erase the very write recording the failure — and ship's only other `commit_all` is on the success path. A failing epic stays on `release/<v>`; that is safe because `release/<v>` is not production, and G-E3 (Task 4) guards the way to main.

- [ ] **Step 7: Add the ship-integration tests**

```python
# append to tests/test_ship_current_work_to_release.py
def test_failing_epic_check_leaves_the_merge_standing(tmp_repo_in_release, fixed_owner):
    """v1 rolled the merge back here; that erased the failure record and made the
    re-run test an emptied tree."""
    # ... scaffold epic + 1 slice, ship it with a failing epic-check.sh ...
    assert epic_entry["status"] == "failed_verification"
    assert feature_entry["status"] == "shipped"          # merge still standing
    log = git_run(rel_wt, "log", "--oneline", "-5")
    assert feature_id in log


def test_second_concurrent_ship_does_not_run_a_second_check(tmp_repo_in_release, fixed_owner):
    """The CAS must let exactly one caller through."""
    # ... two siblings; assert epic-check.sh ran exactly once (count marker file lines) ...
```

- [ ] **Step 8: Add `psrw epic verify [--force]` to `scripts/epic.py`**

`--force` clears a stale `verifying` left by a crashed run — the only way out, since there is deliberately no timeout.

- [ ] **Step 9: Run the full suite**

Run: `python -m pytest -q 2>&1 | tail -n 15 && git -C . worktree list`
Expected: all green, and the worktree list shows no leftover `psrw-epic-*` snapshots.

- [ ] **Step 10: Commit**

```bash
git add lib/epic_gate.py lib/hooks.py scripts/epic.py \
        scripts/ship_current_work_to_release.py tests/test_epic_gate.py \
        tests/test_ship_current_work_to_release.py
git commit -m "feat(epic): G-E2 ship-time gate on an immutable snapshot"
```

- [ ] **Step 11: Phase gate** — verify (Step 9) → independent review → `/simplify` → re-verify.

---

## Task 4: G-E3, unclaim demotion, cleanup archiving

**This is the riskiest task — the only one that modifies existing release behaviour. Review it hardest.**

**Files:**
- Modify: `scripts/promote_release.py:99-123` (PR adopt), `~219` (G-E3), `~400-410` (cleanup), `scripts/unclaim.py`
- Test: `tests/test_promote_release.py`, `tests/test_unclaim.py`

**Interfaces:**
- Consumes: everything from Tasks 1 and 3
- Produces:
  - `promote_release.EpicGateError(RuntimeError)` — **must** subclass `RuntimeError`: `main()` catches `(NoReleaseInProgressError, Gate2FailedError, CatalogEntryNotFoundError, RuntimeError)` at `promote_release.py:560-562`, so a plain-`Exception` subclass escapes as a raw traceback instead of the `ERROR:` line the toolkit guarantees. `HookPathError` (`lib/hooks.py:22-30`) exists for exactly this reason and is pinned by tests.
  - `promote_release.check_epics(repo, rel_wt, version, allow_split: bool) -> None` — raises `EpicGateError` on refusal
  - a new `--allow-split-epic` flag on promote's argparse (mirror the existing flag pattern at `promote_release.py:526,558`), which calls `lib.epic.set_split_approved` — without it Task 4's tests cannot pass `allow_split_epic=True` and nothing ever writes the field

- [ ] **Step 1: Write the failing G-E3 tests**

```python
def test_promote_refuses_when_a_slice_is_unrefined(tmp_repo_in_release, fixed_owner):
    """F1, the failure this whole design exists to kill."""
    with pytest.raises(EpicGateError) as exc:
        promote_release(repo, version="1.1")
    assert "I-002" in str(exc.value)


def test_promote_reruns_the_check_when_verified_sha_is_stale(tmp_repo_in_release, fixed_owner):
    """An unrelated ship after verification must re-trigger the check —
    otherwise 'verified' is a stale label at the only moment it matters."""
    # ... verify epic, then ship an unrelated feature, then promote ...
    assert epic_check_invocations == 2


def test_split_approval_is_permanent(tmp_repo_in_release, fixed_owner):
    """Otherwise the operator re-approves the same split every release and the
    override decays into a rubber stamp."""
    promote_release(repo, version="1.1", allow_split_epic=True)
    # ... open 1.2, ship the remainder ...
    promote_release(repo, version="1.2")          # must NOT raise
    assert epic["split_approved_by"] is not None


def test_split_disclosure_survives_pr_adoption(tmp_repo_in_release, fixed_owner):
    """_create_or_adopt_pr passes pr_body only to `gh pr create`; the adopt path
    never updated an existing PR's body, so a second promote dropped the
    disclosure entirely."""
    promote_release(repo, version="1.1", allow_split_epic=True)
    promote_release(repo, version="1.1", allow_split_epic=True)   # adopts the PR
    assert "gh pr edit" in recorded_gh_calls
    assert "split epic" in last_pr_body.lower()


def test_missing_epic_check_script_warns_but_does_not_block(tmp_repo_in_release, fixed_owner):
    promote_release(repo, version="1.1")          # must NOT raise
    assert "epic_check" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_promote_release.py -k epic -v`
Expected: FAIL — `EpicGateError` not defined

- [ ] **Step 3: Implement `check_epics`, called before Gate 2**

Read the catalog via `get_backlog_catalog_path(repo, "epic")`, which resolves inside `_release` where the populated catalogs live; hard-error if `_release` is absent. Then, per spec §5.3, for each epic with ≥1 feature shipped into this release:

| Epic state | Behaviour |
|---|---|
| `split_approved_by` set | exempt, permanently |
| not complete | raise `EpicGateError`, naming the unrefined ideas / unshipped features |
| complete, `verified`, `verified_sha == release HEAD` | pass |
| complete, but never verified / failed / stale sha | re-run `run_epic_check` at release HEAD, then pass or raise |
| hook script absent | warn loudly, pass |

- [ ] **Step 4: Fix the PR adopt path**

`promote_release.py:115-122` — on the adopt branch, call `gh pr edit <n> --body <body>`. Without this a second promote silently drops the split-epic disclosure.

- [ ] **Step 5: Demote the epic in `unclaim.py`**

After `reopen()`, if the feature carries an `epic` tag and that epic is `verified`, call `demote_epic` — to `open`, **never** to `verifying`, which would collide with the CAS and strand the epic forever.

- [ ] **Step 6: Archive epics in `cleanup()`**

`cleanup()` reads `<repo>/.claude/refined_backlog/_catalog.json` in the **main checkout** and archives under `_archive/<version>/` (`promote_release.py:400-403`), because the `_release` worktree is removed later in the same call. Mirror that exactly for `epic_backlog`: `mark_epic_promoted`, move `E-NNN-<slug>/` into `<repo>/.claude/epic_backlog/_archive/<version>/`, and refuse to archive an incomplete epic unless `split_approved_by` is set.

- [ ] **Step 7: Run the suite**

Run: `python -m pytest tests/test_promote_release.py tests/test_unclaim.py -v 2>&1 | tail -n 20`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add scripts/promote_release.py scripts/unclaim.py \
        tests/test_promote_release.py tests/test_unclaim.py
git commit -m "feat(epic): G-E3 completeness gate, unclaim demotion, epic archiving"
```

- [ ] **Step 9: Phase gate** — verify (Step 7) → independent review (`code-reviewer` + `python-reviewer`; this task touches release behaviour, so do **not** batch its gate with a neighbour) → `/simplify` → re-verify.

---

## Task 5: Skills

**Files:**
- Create: `~/ps-skills/skills/ps-release-workflow-epic-open/SKILL.md`, `~/ps-skills/skills/ps-release-workflow-epic-fanout/SKILL.md`
- Modify: `verify.sh:187`

- [ ] **Step 1: Write `ps-release-workflow-epic-open/SKILL.md`**

```markdown
---
name: ps-release-workflow-epic-open
description: |
  Use BEFORE capturing work that is bigger than one feature in a
  ps-release-workflow repo — an outcome that will take several features to
  deliver. Creates E-NNN-<slug> with spec + verification skeletons and commits
  the epic entry on the release branch via the _release worktree.
  After this skill: brainstorm the epic spec into a SOLID outcome statement
  FIRST, then fan it out with ps-release-workflow-epic-fanout.
---

# ps-release-workflow:epic-open

Open an epic: one outcome, delivered by several features, verified as a unit.

## Precondition

A release must be in progress (`psrw new-release` first) — epic metadata commits
route through the `_release` worktree.

## Run

`psrw epic open "<title>"`

## Then

Brainstorm `E-NNN/spec.md` until the outcome and its slices are solid. Write
`E-NNN/verification.md` — what must be true once every slice has shipped.
Only then fan out. Never auto-chain open -> fanout -> refine -> claim.

## Refuses if

- no release is in progress
- the title is empty

Mechanics: ~/.claude/ps-release-workflow/docs/lifecycle.md#state-layout
Flags: psrw epic --help
```

- [ ] **Step 2: Write `ps-release-workflow-epic-fanout/SKILL.md`**

Same shape. Key body content: it mints **one idea per slice, never a feature** — each slice still needs its own brainstorm before `psrw refine`. Anchor `#state-layout`.

- [ ] **Step 3: Bump the skill count**

`verify.sh:187`: `check "15 ps-release-workflow skills present" "15"`

- [ ] **Step 4: Install and verify**

Run:
```bash
~/ps-skills/install.sh && ./verify.sh 2>&1 | tail -n 20
ls ~/.claude/skills/ | grep epic
for c in "" "open" "fanout" "verify"; do psrw epic $c --help >/dev/null || echo "FAIL: psrw epic $c --help"; done
```
Expected: `verify.sh` green; both epic skills symlinked; every `--help` exits 0 (spec §8 Phase 5 requires the subcommand help checks, not just the skill count).

- [ ] **Step 5: Commit** (in `~/ps-skills`)

```bash
git add skills/ps-release-workflow-epic-open skills/ps-release-workflow-epic-fanout \
        engine/ps-release-workflow/verify.sh
git commit -m "feat(epic): epic-open and epic-fanout skills"
```

- [ ] **Step 6: Phase gate** — verify (Step 4) → independent review → `/simplify` → re-verify. This task's diff is < 50 lines and is documentation-shaped; batching its gate with Task 6 is acceptable.

---

## Task 6: `status.py` epic rollup

**Files:**
- Modify: `scripts/status.py`
- Test: `tests/test_status.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_status_groups_features_under_their_epic(tmp_repo_in_release, fixed_owner):
    out = status_report(repo)
    assert "E-001" in out
    assert "2/3 slices shipped" in out


def test_status_warns_when_two_siblings_are_claimed_at_once(tmp_repo_in_release, fixed_owner):
    """Mitigation for F2: epic branches are cut off main, so siblings are
    developed blind to each other."""
    out = status_report(repo)
    assert "two siblings of E-001 are claimed" in out.lower()


def test_rollup_does_not_assume_plan_md_exists(tmp_repo_in_release, fixed_owner):
    """'All three files always exist' is explicitly NOT an invariant (F-015)."""
    (feature_folder / "plan.md").unlink()
    status_report(repo)          # must not raise
```

- [ ] **Step 2: Run to verify failure, implement, re-run**

Run: `python -m pytest tests/test_status.py -v`

Existing status counts must not change — the rollup is an added section, and `status.py` already ignores unknown keys on idea entries.

- [ ] **Step 3: Commit**

```bash
git add scripts/status.py tests/test_status.py
git commit -m "feat(epic): epic rollup and concurrent-sibling warning in status"
```

- [ ] **Step 4: Phase gate** — verify → independent review → `/simplify` → re-verify.

---

## Task 7: Documentation

**Files:**
- Modify: `docs/lifecycle.md`, `docs/known-issues.md`

- [ ] **Step 1: Add the epic section to `docs/lifecycle.md`**

Place it under an existing permitted anchor (`#state-layout` for the catalog and folder layout, `#gates` for G-E2 and G-E3). `verify.sh` checks that every SKILL.md anchor resolves, so a new anchor would break the build.

- [ ] **Step 2: Record anything discovered in `docs/known-issues.md`**

At minimum: no schema version exists on any artifact, so the `epic` key has no versioned contract.

- [ ] **Step 3: Run `verify.sh`**

Run: `./verify.sh 2>&1 | tail -n 20`
Expected: green, including the docs-single-source and anchor checks.

- [ ] **Step 4: Commit**

```bash
git add docs/lifecycle.md docs/known-issues.md
git commit -m "docs(epic): lifecycle section and known issues"
```

- [ ] **Step 5: Final phase gate** — full suite (`python -m pytest -q`), `./verify.sh`, `git status` clean.

---

## Audit trail

| Round | Applied |
|---|---|
| Spec v1 → v2 (adversarial audit, 3 blockers) | Gate moved out of the lock; rollback removed; completeness anchored so unrefined slices count |
| Spec v2 → v3 (quality/efficiency review, "needs rework") | Snapshot worktree; `verified_sha` anchor; CAS instead of a timestamp; `slice_count`, `fanned_out` and one skill cut; registration moved into Task 2 |
| Plan self-review | See below |
| Plan audit round 1 (3 blockers) | `git_run` does not exist (it is `_run`) · `_run` returns `CompletedProcess`, so `.stdout.strip()` · `resolve_hook` never raises `FileNotFoundError` and returns an **absolute** path, so `snapshot / hook` discarded the snapshot and would have run the hook in the shared tree — silently voiding the v3 immutable-snapshot fix · Task 2 had no `main()`/argparse, failing its own `verify.sh` gate · `split_approved_by` had no producer · the all-or-nothing test passed vacuously · `fanout` accepted a nonexistent epic id · `EpicGateError` base class unspecified |

**Self-review results:**

1. **Spec coverage** — §3 → Task 1; §4 → Tasks 1-2; §5.1 → Task 1; §5.2 → Task 3; §5.3 → Task 4; §5.4 → Task 3 (hook registration) + Task 2 (`verification.md` skeleton); §6 → Tasks 2 and 5; §7 edge cases → Tasks 1 (legacy keys, stale `release_version`), 2 (quotes, all-or-nothing, re-fanout), 3 (CAS, `--force`), 4 (unclaim, split permanence), 6 (`plan.md`, sibling warning); §8 → Tasks 1-7. No gaps.
2. **Placeholder scan** — Tasks 4 and 6 carry test *skeletons* with elided setup (`# ... scaffold ...`). Their assertions are exact and their names state the behaviour; the setup follows the `_scaffold_precheck` pattern already in `tests/test_ship_current_work_to_release.py:18-30`. Flagged here rather than hidden: an executor must expand them, and the reference pattern is named.
3. **Type consistency** — `epic_completeness` returns `(bool, list[str])` everywhere; `run_epic_check` returns `int | None` everywhere; `try_begin_verification` returns `bool`; the epic id parameter is `epic_id` in every signature; `demote_epic` (not `unverify_epic`) is the single demotion entry point.
