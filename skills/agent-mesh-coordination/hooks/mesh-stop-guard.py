#!/usr/bin/env python3
"""
mesh-stop-guard.py — Stop hook for Claude Code
Checks if the current session holds active in-progress tasks or unreleased claims in mesh.db.
If so, blocks premature stopping and prompts the agent to complete verification or release the claim.
"""

import json
import os
import subprocess
import sys


def main():
    agent_id = os.environ.get("MESH_AGENT_ID")
    if not agent_id:
        # If no explicit MESH_AGENT_ID, check by session or exit gracefully
        return

    try:
        res = subprocess.run(["mesh", "status", "--json"], capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            return
        data = json.loads(res.stdout)
    except Exception:
        return

    # Check for held claims by this agent
    now = data.get("now_ms", 0)
    my_claims = [
        c for c in data.get("claims", [])
        if c.get("owner_id") == agent_id and c.get("state") == "held" and c.get("expires_at", 0) > now
    ]

    my_tasks = [
        t for t in data.get("tasks", [])
        if t.get("owner_id") == agent_id and t.get("status") == "in_progress"
    ]

    if my_tasks:
        t = my_tasks[0]
        reason = (
            f"AGENT MESH STOP GUARD: You are currently working on task [{t['id']}]: '{t['title']}'. "
            "You cannot stop while this task is in-progress. Complete verification and mark it done with `mesh task-done`, or release it."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        return

    if my_claims:
        c = my_claims[0]
        reason = (
            f"AGENT MESH STOP GUARD: You hold an active claim on '{c['resource']}'. "
            "Complete your side-effecting operation or run `mesh release` before stopping."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        return


if __name__ == "__main__":
    main()
