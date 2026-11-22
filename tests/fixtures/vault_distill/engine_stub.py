#!/usr/bin/env python3
"""Stand-in for vault-engine in vault-distill tests.

`context ...` prints the file named by $ENGINE_STUB_CONTEXT (or nothing). `validate <path>` passes when the
file declares schema knowledge/v1. Each call is logged to $ENGINE_STUB_LOG.
"""
import json
import os
import sys

log = os.environ.get("ENGINE_STUB_LOG")
if log:
    with open(log, "a") as handle:
        handle.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1] == "context":
    path = os.environ.get("ENGINE_STUB_CONTEXT")
    if path and os.path.exists(path):
        sys.stdout.write(open(path).read())
elif sys.argv[1] == "validate":
    text = open(sys.argv[2]).read()
    sys.exit(0 if 'schema: "knowledge/v1"' in text or "schema: knowledge/v1" in text else 1)
