#!/usr/bin/env python3
"""Stand-in for jev-gate in vault-distill tests: answers from JEV_<NAME>=<p> markers in stdin.

Logs each call as one JSON line ({"sub", "bytes"}) to $JEV_STUB_LOG. JEV_STUB_FAIL=1 answers fallback for
every subcommand; JEV_STUB_FAIL=<subcommand> only for that one.
"""
import json
import os
import re
import sys

sub = sys.argv[1]
text = sys.stdin.read()
log = os.environ.get("JEV_STUB_LOG")
if log:
    with open(log, "a") as handle:
        handle.write(json.dumps({"sub": sub, "bytes": len(text.encode())}) + "\n")


def marker(name, default):
    m = re.search(rf"JEV_{name}=([0-9.]+)", text)
    return float(m.group(1)) if m else default


if os.environ.get("JEV_STUB_FAIL") in ("1", sub):
    print(json.dumps({"fallback": True, "error": "stub failure"}))
elif sub == "classify-lesson":
    print(json.dumps({"lesson_prob": marker("LESSON", 0.5), "fallback": False}))
elif sub == "score-draft":
    print(json.dumps({"specific": marker("SPECIFIC", 0.9), "novel": marker("NOVEL", 0.9),
                      "high_stakes": marker("HIGH_STAKES", 0.1), "fallback": False}))
elif sub == "same-lesson":
    print(json.dumps({"same": marker("SAME_LESSON", 0.1), "fallback": False}))
else:
    sys.exit(2)
