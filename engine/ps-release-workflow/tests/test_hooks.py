"""The hooks block is executed, so its value is untrusted input."""
import json
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.hooks import DEFAULT_HOOKS, HookPathError, resolve_hook


def _tree(tmp_path: Path, hooks=None) -> Path:
    tree = tmp_path / "tree"
    (tree / "scripts").mkdir(parents=True)
    payload = {"version": "1.1", "in_progress": True}
    if hooks is not None:
        payload["hooks"] = hooks
    (tree / ".release.json").write_text(json.dumps(payload))
    return tree


def test_defaults_when_no_hooks_block(tmp_path):
    """Absence must reproduce today's hardcoded behavior byte for byte."""
    tree = _tree(tmp_path)
    assert resolve_hook(tree, "precheck") == tree / "scripts" / "precheck.sh"
    assert resolve_hook(tree, "integration") == tree / "scripts" / "integration.sh"
    assert resolve_hook(tree, "deploy_local") == tree / "scripts" / "deploy-local.sh"


def test_defaults_when_release_json_absent(tmp_path):
    tree = tmp_path / "bare"
    tree.mkdir()
    assert resolve_hook(tree, "precheck") == tree / "scripts" / "precheck.sh"


def test_custom_relative_path_is_honoured(tmp_path):
    tree = _tree(tmp_path, {"integration": "ci/integration.sh"})
    assert resolve_hook(tree, "integration") == tree / "ci" / "integration.sh"


def test_partial_block_falls_back_per_key(tmp_path):
    tree = _tree(tmp_path, {"integration": "ci/integration.sh"})
    assert resolve_hook(tree, "precheck") == tree / "scripts" / "precheck.sh"


@pytest.mark.parametrize("bad", [
    "/etc/passwd",                 # absolute
    "../../evil.sh",               # parent escape
    "scripts/../../evil.sh",       # escape after a valid segment
    "~/evil.sh",                   # home expansion attempt
])
def test_rejects_paths_that_escape_the_tree(tmp_path, bad):
    tree = _tree(tmp_path, {"precheck": bad})
    with pytest.raises(HookPathError) as e:
        resolve_hook(tree, "precheck")
    assert "precheck" in str(e.value), "the error must name the offending key"


def test_rejects_a_symlink_that_escapes_the_tree(tmp_path):
    tree = _tree(tmp_path, {"precheck": "scripts/escape.sh"})
    outside = tmp_path / "outside.sh"
    outside.write_text("#!/bin/sh\necho pwned\n")
    (tree / "scripts" / "escape.sh").symlink_to(outside)
    with pytest.raises(HookPathError):
        resolve_hook(tree, "precheck")


def test_unknown_hook_name_is_a_programming_error(tmp_path):
    tree = _tree(tmp_path)
    with pytest.raises(KeyError):
        resolve_hook(tree, "nope")


def test_rejects_an_embedded_nul_byte(tmp_path):
    """A NUL is legal JSON but makes Path.resolve() raise ValueError — which is
    NOT a RuntimeError, so it escaped every caller's except net and skipped
    ship's post-merge rollback, leaving the feature merge standing on release/<v>.
    """
    tree = _tree(tmp_path, {"precheck": "scripts/pre\x00check.sh"})
    # Precondition: the value really did survive the JSON round-trip.
    assert "\x00" in json.loads((tree / ".release.json").read_text())["hooks"]["precheck"]
    with pytest.raises(HookPathError) as e:
        resolve_hook(tree, "precheck")
    assert "precheck" in str(e.value), "the error must name the offending key"


def test_hook_path_error_is_a_runtime_error():
    """promote's and ship's main() except-tuples catch RuntimeError, not
    HookPathError by name. Break this and every hooks failure becomes a raw
    traceback instead of the `ERROR: ...` line every verb guarantees."""
    assert issubclass(HookPathError, RuntimeError)


@pytest.mark.parametrize("bad", ["", "   ", 0, None, [], {}])
def test_present_but_invalid_value_never_silently_falls_back(tmp_path, bad):
    """`or DEFAULT_HOOKS[name]` used to swallow every falsy value, so a repo with
    `"precheck": ""` ran the default while `"   "` errored. Presence decides now."""
    tree = _tree(tmp_path, {"precheck": bad})
    with pytest.raises(HookPathError) as e:
        resolve_hook(tree, "precheck")
    assert "precheck" in str(e.value)
