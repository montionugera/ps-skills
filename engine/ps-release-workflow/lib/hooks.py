"""Resolve the optional `hooks` block in .release.json to a validated path.

The value is EXECUTED, so it is untrusted input: a committed .release.json on
any branch could otherwise point Gate 2 at an arbitrary binary. Only relative
paths that stay inside the tree are accepted.

Read from the tree that will EXECUTE the hook, never a fixed checkout: Gate 1
resolves precheck.sh from the feature worktree (audit A5) while Gate 2 and the
deploy resolve from _release, and .release.json is committed so it differs per
branch.
"""
import json
from pathlib import Path

DEFAULT_HOOKS = {
    "precheck": "scripts/precheck.sh",
    "integration": "scripts/integration.sh",
    "deploy_local": "scripts/deploy-local.sh",
}


class HookPathError(RuntimeError):
    """A hooks value is absolute, escapes the tree, or is otherwise unusable.

    Subclasses RuntimeError deliberately: promote_release.main() catches
    (NoReleaseInProgressError, Gate2FailedError, CatalogEntryNotFoundError,
    RuntimeError), and ship's main() also catches RuntimeError. A bare Exception
    here would escape both as a raw traceback instead of the `ERROR: ...` line
    every other verb guarantees. tests/test_hooks.py pins the subclassing.
    """


def _read_block(tree: Path) -> dict:
    rj = Path(tree) / ".release.json"
    if not rj.is_file():
        return {}
    try:
        data = json.loads(rj.read_text())
    except (ValueError, OSError):
        return {}
    block = data.get("hooks")
    return block if isinstance(block, dict) else {}


def resolve_hook(tree: Path, name: str) -> Path:
    """Absolute path to `name`'s script inside `tree`. Existence is NOT checked."""
    if name not in DEFAULT_HOOKS:
        raise KeyError(f"unknown hook {name!r}; known: {sorted(DEFAULT_HOOKS)}")

    tree = Path(tree).resolve()
    block = _read_block(tree)
    # Fall back ONLY when the key is absent. `or` would have let any falsy value
    # ("" , 0, null) fall back silently, while "   " raised — the module contract
    # is that a present-but-invalid value is always a hard error.
    raw = block[name] if name in block else DEFAULT_HOOKS[name]

    if not isinstance(raw, str) or not raw.strip():
        raise HookPathError(f"hooks.{name} must be a non-empty string, got {raw!r}")
    if "\x00" in raw:
        # Legal JSON ("\u0000"), but Path.resolve() raises ValueError on it —
        # NOT a RuntimeError, so it would escape every caller's except net and
        # leave ship's post-merge rollback unrun. Reject before we touch the fs.
        raise HookPathError(
            f"hooks.{name} must not contain a NUL byte, got {raw!r}"
        )

    candidate = Path(raw)
    if candidate.is_absolute() or raw.startswith("~"):
        raise HookPathError(
            f"hooks.{name} must be a relative path inside the tree, got {raw!r}"
        )
    if ".." in candidate.parts:
        raise HookPathError(f"hooks.{name} must not contain '..', got {raw!r}")

    try:
        resolved = (tree / candidate).resolve()
    except ValueError as e:
        # Belt and braces behind the NUL check above: resolve() raises ValueError
        # for platform-specific reasons too, and ValueError is not a RuntimeError.
        raise HookPathError(f"hooks.{name} is not a usable path ({raw!r}): {e}")
    # Catches symlinks pointing outside the tree, not just lexical escapes.
    if not resolved.is_relative_to(tree):
        raise HookPathError(
            f"hooks.{name} resolves outside the tree: {resolved} not under {tree}"
        )
    return resolved
