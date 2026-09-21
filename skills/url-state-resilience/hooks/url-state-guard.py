#!/usr/bin/env python3
"""
url-state-guard.py — PreToolUse / Verification reminder hook for URL-as-State compliance.
Zero-overhead, non-blocking reminder hook for UI filtering and refresh resilience.
"""

import json
import os
import re
import sys


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return

    try:
        data = json.loads(raw)
    except Exception:
        return

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Check if tool is modifying frontend files or running git commit
    command = tool_input.get("command", "") or tool_input.get("CommandLine", "")
    target_file = tool_input.get("TargetFile", "") or tool_input.get("path", "")

    reminder = (
        "URL-as-State Reminder (url-state-resilience): "
        "Any parameter determining data selection, filtering, sorting, or pagination "
        "MUST be serialized to the URL and hydrated on page refresh. "
        "Ensure an E2E test asserts 'page.reload()' with filter retention."
    )

    should_remind = False

    if command and re.search(r"\b(git\s+commit|gh\s+pr\s+create)\b", command):
        # Look for staged UI files
        should_remind = True

    if target_file and re.search(r"(app\.js|router|filter|screener|\.vue|\.svelte)", target_file, re.IGNORECASE):
        should_remind = True

    if should_remind:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": reminder,
            }
        }
        print(json.dumps(out))


if __name__ == "__main__":
    main()
