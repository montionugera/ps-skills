#!/usr/bin/env python3
"""Stand-in for the Argon-low review call: every candidate gets $REVIEW_STUB_VERDICT (default publish).

Logs the candidate list to $REVIEW_STUB_LOG. REVIEW_STUB_FAIL=1 exits 1.
"""
import json
import os
import sys

items = json.loads(sys.stdin.read())
log = os.environ.get("REVIEW_STUB_LOG")
if log:
    with open(log, "a") as handle:
        handle.write(json.dumps(items) + "\n")
if os.environ.get("REVIEW_STUB_FAIL") == "1":
    sys.exit(1)
verdict = os.environ.get("REVIEW_STUB_VERDICT", "publish")
print(json.dumps([{"draft": i["draft"], "verdict": verdict, "reason": "stub"} for i in items]))
