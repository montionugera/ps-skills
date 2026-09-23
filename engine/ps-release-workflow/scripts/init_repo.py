"""ps-release-workflow:init — opt a repo into the workflow + install global routing rule."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import os
import sys
from pathlib import Path

from lib.git_ops import commit_all
from lib.repo import is_ps_release_workflow_repo


ROUTING_MARKER = "<!-- ps-release-workflow:routing-convention -->"

ROUTING_BLOCK = f"""\

{ROUTING_MARKER}
## ps-release-workflow routing convention

When you are inside a repo that has adopted ps-release-workflow
(i.e., `.release.json` exists at repo root):

**Spec/plan output routing:**
- If invoking `superpowers:brainstorming` or `superpowers:writing-plans`
  from inside a claimed worktree (`.git/worktrees/<id>/working-feature.json`
  exists), route the output to:
  - spec → `.claude/refined_backlog/<F-NNN>/spec.md`
    (instead of `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`)
  - plan → `.claude/refined_backlog/<F-NNN>/plan.md`
    (instead of `docs/superpowers/plans/YYYY-MM-DD-<feature>.md`)
- Read F-NNN from the `working-feature.json` marker.

**Always confirm before writing:**
"I'll write the spec to: .claude/refined_backlog/F-001-fee-cap/spec.md — proceed?"

**Escape hatches:**
- If user explicitly provides a path in their prompt → that overrides auto-route.
- If not inside a claimed worktree → defer to the skill's own default path.
- If `.release.json` doesn't exist → convention doesn't apply, skill defaults stand.
"""


# Gate-script templates stamped into <repo>/scripts/ (never over an existing file).
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
GATE_TEMPLATES = {
    "precheck.sh": _TEMPLATES_DIR / "precheck.sh",        # Gate 1, run by `psrw ship`
    "integration.sh": _TEMPLATES_DIR / "integration.sh",  # Gate 2, run by `psrw promote`
}


def _stamp_gate_templates(repo: Path) -> list[str]:
    """Create scripts/precheck.sh and scripts/integration.sh from the templates
    when absent. An existing script is the repo's own gate and is left untouched."""
    stamped = []
    for name, template in GATE_TEMPLATES.items():
        target = repo / "scripts" / name
        if target.exists() or target.is_symlink():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template.read_text())
        target.chmod(0o755)
        stamped.append(f"scripts/{name}")
    return stamped


class AlreadyInitializedError(Exception):
    pass


def init_repo(repo: Path) -> None:
    if is_ps_release_workflow_repo(repo):
        raise AlreadyInitializedError(f"{repo} already has .release.json")

    # 1. Create .release.json
    (repo / ".release.json").write_text(json.dumps({
        "version": "1.0", "in_progress": False,
        "started_at": None, "started_by": None,
    }, indent=2) + "\n")

    # 2. Create backlog folders + catalogs
    (repo / ".claude" / "idea_backlog").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "idea_backlog" / "_catalog.json").write_text("[]\n")
    (repo / ".claude" / "refined_backlog").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "refined_backlog" / "_catalog.json").write_text("[]\n")
    (repo / ".claude" / "epic_backlog").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "epic_backlog" / "_catalog.json").write_text("[]\n")

    # 3. Extend .gitignore
    gi = repo / ".gitignore"
    existing = gi.read_text() if gi.exists() else ""
    additions = []
    for pat in [".claude/state/", ".claude/worktrees/"]:
        if pat not in existing:
            additions.append(pat)
    if additions:
        gi.write_text(existing + ("\n" if existing and not existing.endswith("\n") else "") +
                     "# ps-release-workflow (gitignored state)\n" + "\n".join(additions) + "\n")

    # 4. Stamp gate-script templates (unfilled Gate 2 slots fail until filled or n/a)
    _stamp_gate_templates(repo)

    # 5. Install routing convention to ~/.claude/CLAUDE.md (idempotent)
    home = Path(os.environ.get("HOME", str(Path.home())))
    claude_md = home / ".claude" / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text()
        if ROUTING_MARKER not in content:
            claude_md.write_text(content + ROUTING_BLOCK)

    # 6. Commit the opt-in
    commit_all(repo, "chore: adopt ps-release-workflow")


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="psrw init",
        description="Opt this repo into ps-release-workflow. Run once per repo.",
    )
    p.parse_args()
    repo = Path.cwd()
    try:
        init_repo(repo)
    except AlreadyInitializedError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"✅ Initialized ps-release-workflow in {repo}")
    print("   Gate templates: scripts/precheck.sh (Gate 1), scripts/integration.sh (Gate 2).")
    print("   Fill each slot or mark it `# n/a: <reason>` — unfilled Gate 2 slots fail promote.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
