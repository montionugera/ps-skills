# ps-commu-explain diagram DSL with auto-layout that emits drawio XML — research notes

(prior art, related issues, open questions)

## Findings (2026-09-30 pipeline map)

- **The model writes drawio mxGraph XML by hand**: ~50+ lines per diagram, invented x/y/width/height values, and 26 mxCells in one exemplar diagram (skills/ps-commu-explain/assets/template-infographic/content.md:32-85).
- **Lint rejects overlaps, out-of-bounds boxes, missing labels and bad escaping** (lint.sh drawio checks), which starts fix loops of up to 5 cycles (SKILL.md:65). This is the biggest source of output tokens and retries.
- **F-013 already noted there is no auto-layout** and proposed a manual coordinate recipe (.claude/refined_backlog/_archive/1.6/F-013-*/spec.md:115-126).
- **Proposal:** a small text format (`A[label] -> B: edge label`) plus a layout script that writes the XML. Candidate engines: graphviz `dot -Tjson`, elkjs, or a simple rank/grid. Output that passes lint by construction.
- **Related:** docs/superpowers/specs/2026-07-16-ps-commu-explain-component-system-design.md (approved but never started: declarative input rendered to the page by a script).
- **Open questions:** Is a layout dependency like graphviz or node acceptable? Is manual XML still allowed for unusual diagrams? How does the html tier (Mermaid) fit in?
