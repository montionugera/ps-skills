# Facts

One row per fact, referenced by id (F1, F2, ...) from 02-storyboard.md and
app/content.md. `source` must be one of: a `path:line`, a bare `path`, a
commit hash, or the literal `user said`.

| id | statement | source |
| --- | --- | --- |
| F1 | ps-commu-explain must ALWAYS be served via scripts/serve.sh, never an ad-hoc server | SKILL.md:8 |
| F2 | infographic is the DEFAULT tier: init.sh runs infographic with no --tier flag | SKILL.md:18 |
| F3 | init.sh rejects a slug that is not kebab-case before creating any workspace | scripts/init.sh:39 |
| F4 | init.sh scaffolds the authoring-chain docs into the workspace root, sibling to app/, so they are never served | scripts/init.sh:82 |
| F5 | init.sh probes ports 7700-7799 with lsof for an advisory free port | scripts/init.sh:100 |
| F6 | serve.sh's own bind attempt is authoritative: on failure it walks forward to the next port, up to 7799 | scripts/serve.sh:14 |
| F7 | init.sh only sweeps a workspace idle more than 3 days that also has no live marker-verified server | scripts/init.sh:59 |
| F8 | serve.sh refuses to serve a workspace until its authoring chain passes scripts/lint.sh, unless --no-lint is passed | scripts/serve.sh:44 |
| F9 | every server serve.sh starts binds 127.0.0.1 only | scripts/serve.sh:12 |
| F10 | a live server is only ever killed if its own process command line contains the workspace path | scripts/common.sh:13 |
| F11 | serve.sh's watchdog self-destructs the server once its keep-alive TTL, default 24h, expires | scripts/serve.sh:136 |
| F12 | verify.sh loads the served page in headless Chrome with --dump-dom under a virtual-time budget | scripts/verify.sh:4 |
| F13 | verify.sh's assert 1 compares the rendered Mermaid svg count against the fenced mermaid block count in the doc | scripts/verify.sh:158 |
| F14 | verify.sh's assert 6 statically greps the served explainer.css for scroll-behavior, a permanent regression gate | scripts/verify.sh:198 |
| F15 | verify.sh exits 2, SKIP and never a pass, when Chrome is missing or no live server exists | scripts/verify.sh:54 |
| F16 | lint.sh rejects 5 exact forbidden classes plus any class prefixed cat- in app/content.md | scripts/lint.sh:186 |
| F17 | lint.sh reports every unlabeled flowchart edge in app/content.md as its own defect | scripts/lint.sh:597 |
| F18 | lint.sh caps flowchart node count at 7 per diagram | scripts/lint.sh:604 |
| F19 | the old python -m http.server habit exposes all of /tmp on all interfaces, forever | SKILL.md:54 |
