#!/usr/bin/env python3
"""UserPromptSubmit hook: inject up to 3 agentic-vault notes relevant to the prompt.

Calls `vault-engine context --query <prompt>` (no LLM), injects each note at most once per
session, and stops at 6 notes / 2,400 bytes per session. Fails open: any problem means no
output and exit 0, so it can never block a prompt.
"""
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROMPT_NOTES, PROMPT_BYTES = 3, 1200
SESSION_NOTES, SESSION_BYTES = 6, 2400
STATE_MAX_AGE = 7 * 24 * 3600
OPT_OUT = ("VAULT_RECALL", "VAULT_CONTEXT_BOOTSTRAP", "CLAUDE_VAULT_SUMMARY")


def state_dir() -> Path:
    return Path(os.environ.get("VAULT_RECALL_STATE") or Path.home() / ".claude" / "state" / "vault-recall")


def run_engine(args: list[str]) -> str:
    binary = os.environ.get("VAULT_ENGINE") or shutil.which("vault-engine") or str(Path.home() / ".local/bin/vault-engine")
    proc = subprocess.run([binary, "context", *args], capture_output=True, text=True, timeout=2)
    return proc.stdout if proc.returncode == 0 else ""


def note_lines(block: str) -> list[str]:
    return [line for line in block.splitlines() if line.startswith("- ") and " | " in line]


def note_id(line: str) -> str:
    return line[2:].split(" | ", 1)[0]


def size(line: str) -> int:
    return len(line.encode()) + 1


def prune(directory: Path) -> None:
    cutoff = time.time() - STATE_MAX_AGE
    for path in directory.glob("*.json"):
        if path.name != "usage.json" and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


def main() -> int:
    if any(os.environ.get(key) == "0" for key in OPT_OUT):
        return 0
    data = json.load(sys.stdin)
    prompt = (data.get("prompt") or "").strip()
    session = "".join(c for c in str(data.get("session_id") or "") if c.isalnum() or c in "-_")
    if len(prompt) < 12 or prompt.startswith("/") or not session:
        return 0

    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    prune(directory)
    usage = directory / "usage.json"
    demoted = set(json.loads(usage.read_text()).get("demoted", [])) if usage.exists() else set()

    chosen: list[str] = []
    with open(directory / f"{session}.json", "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        raw = handle.read()
        try:
            state = json.loads(raw) if raw else None
        except ValueError:
            state = None  # corrupt state: start the session's budget again
        if state is None:
            # First prompt of the session: count what the SessionStart hook already injected.
            seed = note_lines(run_engine(["--cwd", data.get("cwd") or os.getcwd()]))
            state = {"ids": [note_id(line) for line in seed], "bytes": sum(size(line) for line in seed)}
        used = 0
        for line in note_lines(run_engine(["--query", prompt[:2000]])):
            nid = note_id(line)
            if nid in state["ids"] or nid in demoted:
                continue
            if len(chosen) >= PROMPT_NOTES or len(state["ids"]) >= SESSION_NOTES:
                break
            if used + size(line) > PROMPT_BYTES or state["bytes"] + size(line) > SESSION_BYTES:
                continue  # this note does not fit; a smaller one further down may
            chosen.append(line)
            used += size(line)
            state["ids"].append(nid)
            state["bytes"] += size(line)
        handle.seek(0)
        handle.truncate()
        json.dump(state, handle)

    if not chosen:
        return 0
    with open(directory / "injections.jsonl", "a") as log:
        for line in chosen:
            log.write(json.dumps({"ts": int(time.time()), "session_id": session, "note_id": note_id(line)}) + "\n")
    context = "<vault-context>\n" + "\n".join(chosen) + "\n</vault-context>"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
