"""Tests for the psrw verb dispatcher."""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PSRW = REPO_ROOT / "bin" / "psrw"
SCRIPTS_DIR = REPO_ROOT / "scripts"


def load_psrw():
    """Import bin/psrw as a module despite having no .py suffix.

    spec_from_file_location() returns None for an extension-less path (there is
    no registered loader for it), so module_from_spec(None) would raise. Name the
    loader explicitly instead.
    """
    import importlib.util
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("psrw_cli", str(PSRW))
    spec = importlib.util.spec_from_loader("psrw_cli", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_psrw_exists_and_is_executable():
    assert PSRW.is_file(), f"missing dispatcher: {PSRW}"
    assert PSRW.stat().st_mode & 0o111, "bin/psrw is not executable"


def test_every_verb_maps_to_a_real_script():
    psrw = load_psrw()
    for verb, entry in psrw.VERBS.items():
        assert (SCRIPTS_DIR / entry.script).is_file(), (
            f"verb {verb!r} points at missing script {entry.script}"
        )
        assert entry.summary, f"verb {verb!r} has no summary"


def test_every_script_is_a_verb_or_explicitly_excluded():
    """Bidirectional: no script may be silently unreachable through psrw."""
    psrw = load_psrw()
    mapped = {e.script for e in psrw.VERBS.values()}
    for script in sorted(p.name for p in SCRIPTS_DIR.glob("*.py")):
        assert script in mapped or script in psrw.NON_VERBS, (
            f"{script} is neither a psrw verb nor in NON_VERBS — add it to one"
        )


def test_unknown_verb_exits_2_and_lists_verbs():
    proc = subprocess.run([sys.executable, str(PSRW), "frobnicate"],
                          capture_output=True, text=True)
    assert proc.returncode == 2
    combined = proc.stdout + proc.stderr
    assert "frobnicate" in combined
    assert "status" in combined, "the verb list should be printed on an unknown verb"


def test_no_verb_exits_2_and_lists_verbs():
    proc = subprocess.run([sys.executable, str(PSRW)], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "status" in proc.stdout + proc.stderr


def test_status_verb_forwards_and_exits_0_outside_a_workflow_repo(tmp_path):
    """status.py prints 'not a ps-release-workflow repo' and exits 0."""
    proc = subprocess.run([sys.executable, str(PSRW), "status"], cwd=tmp_path,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def _snapshot(repo: Path, home: Path) -> dict:
    """Everything --help must not change.

    git treats `.claude/worktrees/_release` as an opaque nested worktree: `git
    rev-parse HEAD` / `git status` run against `repo` never descend into it (it
    collapses to a single untracked line), and commits made inside it land on
    release/<v> in the worktree's own history, never touching the outer repo's
    HEAD. Since every backlog mutation in this toolkit routes through that
    worktree (decision D11), the outer-repo fields below are blind to it — so
    we also snapshot the worktree's own HEAD/status and the two catalog files
    directly, guarded for the worktree/catalogs not existing yet (e.g. the
    `init` case, before any release has been opened).
    """
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    tracked = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                             cwd=repo, capture_output=True, text=True).stdout
    claude_md = home / ".claude" / "CLAUDE.md"

    release_wt = repo / ".claude" / "worktrees" / "_release"
    if release_wt.is_dir():
        wt_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=release_wt,
                                 capture_output=True, text=True).stdout.strip()
        wt_status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                                   cwd=release_wt, capture_output=True, text=True).stdout
    else:
        wt_head = None
        wt_status = None

    idea_catalog = release_wt / ".claude" / "idea_backlog" / "_catalog.json"
    refined_catalog = release_wt / ".claude" / "refined_backlog" / "_catalog.json"

    return {
        "head": head,
        "status": tracked,
        "release_json": (repo / ".release.json").read_bytes() if (repo / ".release.json").exists() else None,
        "claude_md": claude_md.read_bytes() if claude_md.exists() else None,
        "paths": sorted(str(p.relative_to(repo)) for p in repo.rglob("*") if ".git" not in p.parts),
        "release_wt_head": wt_head,
        "release_wt_status": wt_status,
        "idea_catalog": idea_catalog.read_bytes() if idea_catalog.exists() else None,
        "refined_catalog": refined_catalog.read_bytes() if refined_catalog.exists() else None,
    }


def test_snapshot_handles_missing_release_worktree(tmp_repo_with_release, tmp_path):
    """_snapshot() must not raise when no _release worktree exists yet (e.g. before
    `psrw new-release` has run), and its worktree-only fields must come back None."""
    home = tmp_path / "_home"
    home.mkdir(exist_ok=True)
    snap = _snapshot(tmp_repo_with_release, home)
    assert snap["release_wt_head"] is None
    assert snap["release_wt_status"] is None
    assert snap["idea_catalog"] is None
    assert snap["refined_catalog"] is None


@pytest.mark.parametrize("verb", ["init", "idea", "refine", "ship"])
def test_help_never_mutates_state(verb, tmp_repo_in_release, tmp_path):
    """psrw <verb> --help must exit 0 and change absolutely nothing, for the
    four verbs whose scripts used to sniff sys.argv directly (before each
    gained its own argparse parser).

    All four now call parse_args() before any side effect, so --help exits
    via argparse's own SystemExit(0) and never reaches the mutating code —
    the guarantee no longer depends on bin/psrw's --help interception (that
    interception is now unreachable belt-and-braces, since argparse_safe is
    True for all 9 verbs). This test guards the *structural* fact that
    parse_args() runs first: a future change that reordered a side effect
    ahead of parse_args() in any of these four scripts would slip past a
    narrower assertion (e.g. checking only one field) but is caught here by
    a full-repo snapshot diff. This replaces the deleted
    test_help_is_not_destructive_for_argparse_less_verbs, which asserted the
    same zero-mutation guarantee back when bin/psrw's interception was the
    only thing providing it.
    """
    home = tmp_path / "_home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "CLAUDE.md").write_text("# global rules\nkeep me byte-identical\n")

    before = _snapshot(tmp_repo_in_release, home)

    proc = subprocess.run(
        [sys.executable, str(PSRW), verb, "--help"],
        cwd=tmp_repo_in_release,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/local/bin"},
        input="", capture_output=True, text=True,
    )

    assert proc.returncode == 0, f"psrw {verb} --help exited {proc.returncode}:\n{proc.stderr}"
    assert _snapshot(tmp_repo_in_release, home) == before, (
        f"psrw {verb} --help mutated state"
    )


@pytest.mark.parametrize("verb", ["init", "new-release", "idea", "refine", "claim",
                                   "ship", "promote", "unclaim", "status", "hotfix",
                                   "epic"])
def test_help_is_forwarded_for_argparse_safe_verbs(verb, tmp_path):
    """Safe verbs get the script's real argparse usage, so flags stay discoverable.

    All 11 verbs are now argparse_safe — `hotfix` was missing from this list even
    though the docstring claimed full coverage. This test now overlaps with
    test_help_never_mutates_state for init/idea/refine/ship (same claim
    of a clean, forwarded --help) — kept separately because this one checks
    usage-text forwarding for every verb including the 5 that were always
    argparse_safe, while the other does the deeper state-snapshot proof for
    the four that only became safe once their scripts gained argparse.
    """
    psrw = load_psrw()
    assert psrw.VERBS[verb].argparse_safe is True
    proc = subprocess.run([sys.executable, str(PSRW), verb, "--help"], cwd=tmp_path,
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert "usage:" in (proc.stdout + proc.stderr).lower()


def test_every_verb_script_calls_parse_args():
    """The one residual gap in the --help safety property.

    Both safety layers key off `argparse_safe`: the dispatcher refuses to forward
    --help to a script marked False, and a script marked True is trusted to let
    argparse reject/handle the flag BEFORE any side effect. Nothing else forces a
    verb's script to actually parse — a future verb wrongly marked True while
    reading sys.argv directly (or doing work in module scope) would sail past
    both. Assert the call is at least present.
    """
    psrw = load_psrw()
    for verb, entry in psrw.VERBS.items():
        src = (SCRIPTS_DIR / entry.script).read_text()
        assert "parse_args(" in src, (
            f"scripts/{entry.script} (verb {verb!r}) never calls parse_args(); "
            f"argparse_safe={entry.argparse_safe} is then unenforceable"
        )


def test_every_verb_script_sets_prog_to_its_verb():
    """bin/psrw's docstring claims all ten scripts pass prog="psrw <verb>".

    Without it, `psrw promote --help` prints `usage: promote_release.py`, naming a
    file the user never types. This pins the claim so it cannot rot again.
    """
    psrw = load_psrw()
    for verb, entry in psrw.VERBS.items():
        src = (SCRIPTS_DIR / entry.script).read_text()
        assert f'prog="psrw {verb}"' in src, (
            f'scripts/{entry.script} (verb {verb!r}) does not set prog="psrw {verb}"'
        )
