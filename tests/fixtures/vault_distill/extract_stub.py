#!/usr/bin/env python3
"""Stand-in for the vault-distill extractor: reads the request JSON on stdin, writes one draft.

Markers in the digest steer it: EXTRACT_NO_LESSON, EXTRACT_FAIL, EXTRACT_INVALID, EXTRACT_BAD_EVIDENCE,
EXTRACT_SECRET, EXTRACT_BIG, TITLE=<words_joined_by_underscores>. Every JEV_* marker except JEV_LESSON is copied into the
draft so the Jev stub can score it. Each call is logged to $EXTRACT_STUB_LOG.
"""
import json
import os
import re
import sys

req = json.loads(sys.stdin.read())
log = os.environ.get("EXTRACT_STUB_LOG")
if log:
    with open(log, "a") as handle:
        handle.write(json.dumps(req) + "\n")
digest = open(req["digest_path"]).read()
if "EXTRACT_FAIL" in digest:
    sys.exit(1)
if "EXTRACT_NO_LESSON" in digest:
    print(json.dumps({"path": None, "reason": "no-lesson"}))
    sys.exit(0)
sid = req["session_id"]
m = re.search(r"TITLE=(\S+)", digest)
title = m.group(1).replace("_", " ") if m else f"Stub lesson {sid}"
markers = " ".join(t for t in re.findall(r"JEV_[A-Z_]+=[0-9.]+", digest) if not t.startswith("JEV_LESSON"))
prompt = next(line[6:66] for line in digest.splitlines() if line.startswith("user: "))
evidence = "this quote is not in the digest at all" if "EXTRACT_BAD_EVIDENCE" in digest else prompt
secret = "token = " + "abcdefghijklmnop" if "EXTRACT_SECRET" in digest else ""
big = "w" * 1600 if "EXTRACT_BIG" in digest else ""
schema = "" if "EXTRACT_INVALID" in digest else 'schema: "knowledge/v1"\n'
slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
path = os.path.join(req["out_dir"], f"{slug}--{sid[:8]}.md")
os.makedirs(req["out_dir"], exist_ok=True)
with open(path, "w") as handle:
    handle.write(f'---\n{schema}id: "KNOW-{slug}"\nkind: "knowledge"\ntitle: "{title}"\nstatus: "draft"\n'
                 f'tags: {json.dumps(["auto-distilled", *req["tags"]])}\nproject_ids: {json.dumps(req["project_ids"])}\n---\n\n'
                 f"One-sentence summary.\n\n## When this applies\nWhen it happens.\n\n## Rule\nDo the thing. {secret}{big}\n\n"
                 f"## Why\nBecause. {markers}\n\n## Source\n- session `{sid}`\n\n## Evidence\n- {evidence}\n")
print(json.dumps({"path": path}))
