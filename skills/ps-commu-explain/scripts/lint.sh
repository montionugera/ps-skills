#!/usr/bin/env bash
# lint.sh — authoring-chain lint gate for a ps-commu workspace.
# Usage: lint.sh <slug>
#   Checks the workspace's authoring docs and, if present, app/content.md.
#   HTML comments (<!-- ... -->) are stripped from every file before any
#   check runs, so the templates' own instructional comments (which mention
#   the literal "(...)" placeholder marker as documentation) don't trip the
#   placeholder check on themselves.
#     00-brief.md:      no unfilled "(...)" placeholders; exactly three
#                       numbered reader questions (Q1-Q3); a section budget
#                       line with an integer 4-7.
#     01-facts.md:      at least one row "F<n> | statement | source"; every
#                       source is path:line, a bare path, a commit hash, or
#                       the literal "user said".
#     02-storyboard.md: every brief question id (Q1-Q3) appears in at least
#                       one row; every row cites >=1 F<n> that exists in
#                       01-facts.md.
#     app/content.md (only checked if present): every F<n> mentioned exists
#                       in 01-facts.md; forbidden classes absent (stat-grid,
#                       stat-tile, meter, cat-*, metric-grid, card-grid);
#                       Mermaid flowchart edges carry a label (-->|x| or
#                       -- x -->, and the same for the ---/-.->/==>/--x/--o
#                       link families); sequenceDiagram arrows carry text
#                       after the colon; flowchart node count <=7 per
#                       diagram, counting every declared node id (edge
#                       endpoints AND standalone "ID[label]" declarations).
#   Output: one defect per line ("<file>: <reason>"). Exit 0 = clean;
#   1 = defects listed.
set -uo pipefail
source "$(dirname "$0")/common.sh"

usage() { grep '^#' "$0" | cut -c3-; exit "${1:-0}"; }
slug=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    *) slug="$1" ;;
  esac
  shift
done
[[ -n "$slug" ]] || usage 1
ws="$PS_COMMU_ROOT/$slug"
[[ -d "$ws" ]] || { echo "no workspace: $ws (run init.sh first)" >&2; exit 1; }

python3 - "$ws" <<'PY'
import os, re, sys

ws = sys.argv[1]
defects = []


def strip_comments(text):
    return re.sub(r'<!--.*?-->', '', text, flags=re.S)


def read(path):
    try:
        with open(path, encoding='utf-8') as f:
            return strip_comments(f.read())
    except FileNotFoundError:
        return None


brief_path = os.path.join(ws, '00-brief.md')
facts_path = os.path.join(ws, '01-facts.md')
story_path = os.path.join(ws, '02-storyboard.md')
content_path = os.path.join(ws, 'app', 'content.md')

brief = read(brief_path)
facts = read(facts_path)
story = read(story_path)
content = read(content_path)  # None if absent — content.md is optional (html/react tiers)

# --- 00-brief.md ---
q_ids = []  # the brief's actual parsed reader-question ids — reused below by
            # the storyboard's Q-coverage check instead of a hardcoded (1,2,3),
            # so the two checks can never silently diverge.
if brief is None:
    defects.append("00-brief.md: missing")
else:
    if '(...)' in brief:
        defects.append("00-brief.md: unfilled (...) placeholder")
    q_ids = sorted(int(n) for n in re.findall(r'(?m)^Q(\d+):', brief))
    if q_ids != [1, 2, 3]:
        found = ', '.join(f'Q{n}' for n in q_ids) or 'none'
        defects.append(
            f"00-brief.md: expected exactly three reader questions Q1-Q3, found: {found}"
        )
    m = re.search(r'(?mi)^Section budget:\s*(\S+)', brief)
    if not m:
        defects.append("00-brief.md: missing a 'Section budget:' line")
    else:
        val = m.group(1)
        if not re.fullmatch(r'[0-9]+', val) or not (4 <= int(val) <= 7):
            defects.append(f"00-brief.md: section budget '{val}' must be an integer 4-7")

# --- 01-facts.md ---
fact_ids = set()
if facts is None:
    defects.append("01-facts.md: missing")
else:
    rows = re.findall(
        r'(?m)^\s*\|?\s*F(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|?\s*$', facts
    )
    if not rows:
        defects.append("01-facts.md: no valid fact rows found (expected 'F<n> | statement | source')")
    def valid_source(src):
        # "path:line", a commit hash (7-40 hex chars), or a bare path that
        # actually looks like one (contains "/" or ".") — NOT any
        # whitespace-free token (that fallback made this check near-vacuous:
        # "garbage"/"???"/"TBD" all fullmatch \S+ and would have passed).
        if src == '(...)':
            return False
        if src.lower() == 'user said':
            return True
        if re.fullmatch(r'\S+:\d+', src):
            return True
        if re.fullmatch(r'[0-9a-fA-F]{7,40}', src):
            return True
        if re.fullmatch(r'[\w./-]+', src) and ('/' in src or '.' in src):
            return True
        return False

    for fid, stmt, src in rows:
        fact_ids.add(f'F{fid}')
        src = src.strip()
        if not valid_source(src):
            defects.append(
                f"01-facts.md: fact F{fid} has invalid source '{src}' "
                "(expected path:line, path, commit hash, or 'user said')"
            )

# --- 02-storyboard.md ---
if story is None:
    defects.append("02-storyboard.md: missing")
else:
    raw_rows = re.findall(
        r'(?m)^\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$', story
    )
    data_rows = []
    for sec, q, facts_cell in raw_rows:
        sec_s = sec.strip()
        if re.fullmatch(r'-{2,}', sec_s) or sec_s.lower() == 'section':
            continue  # separator / header row
        data_rows.append((sec_s, q.strip(), facts_cell.strip()))
    q_seen = set()
    for sec_s, q, facts_cell in data_rows:
        q_seen.update(int(n) for n in re.findall(r'Q(\d+)', q))
        row_fact_ids = re.findall(r'F(\d+)', facts_cell)
        if not row_fact_ids:
            defects.append(f"02-storyboard.md: row '{sec_s}' cites no existing F<n>")
        else:
            for n in row_fact_ids:
                if f'F{n}' not in fact_ids:
                    defects.append(
                        f"02-storyboard.md: row '{sec_s}' cites F{n} which does not exist in 01-facts.md"
                    )
    missing_q = [n for n in q_ids if n not in q_seen]
    if missing_q:
        missing = ', '.join(f'Q{n}' for n in missing_q)
        defects.append(f"02-storyboard.md: missing coverage for {missing} (every brief question must appear in at least one row)")

# --- app/content.md (optional) ---
if content is not None:
    used_facts = set(re.findall(r'\bF(\d+)\b', content))
    for n in sorted(used_facts, key=int):
        if f'F{n}' not in fact_ids:
            defects.append(f"app/content.md: cites F{n} which does not exist in 01-facts.md")

    forbidden_exact = {'stat-grid', 'stat-tile', 'meter', 'metric-grid', 'card-grid'}
    for m in re.finditer(r'class=["\']([^"\']*)["\']', content):
        for c in m.group(1).split():
            if c in forbidden_exact or c.startswith('cat-'):
                defects.append(f"app/content.md: forbidden class '{c}' used")

    # Strip node-shape text ("A[label]", "A(label)", "A{label}", "A((label))",
    # "A{{label}}") so edge matching below only sees bare node ids.
    def strip_shapes(text):
        return re.sub(
            r'([A-Za-z0-9_]+)(\[\[[^\]]*\]\]|\[[^\]]*\]|\(\([^)]*\)\)|\([^)]*\)|\{\{[^}]*\}\}|\{[^}]*\})',
            r'\1',
            text,
        )

    # Link (edge) operators, covering the dashed/dotted/thick families Mermaid
    # flowcharts support, each as a bare token or with inline "-- text -->"
    # style label text. A trailing "|label|" (the other Mermaid label form) is
    # matched separately below so it also applies to non-dashed link styles.
    # IMPORTANT: this only matches the OPERATOR text, never the surrounding
    # node ids — an earlier version matched "src op dst" as one combined,
    # non-overlapping regex, which silently skipped the tail edge of a chain
    # like "A --> B --> C" (the first match consumed "B" as its dst, leaving
    # nothing for the second arrow to anchor a src on). Node ids are now
    # recovered separately, from the text BETWEEN operator matches.
    BARE_OPS = {'-->', '---', '--x', '--o', '-.->', '==>'}
    op_re = re.compile(
        r'(?P<op>'
        r'--[^->\n]*-->'      # dashed, inline label, arrowhead
        r'|--[^->\n]*---'     # dashed, inline label, open link
        r'|--[^->\n]*--x'     # dashed, inline label, x-end
        r'|--[^->\n]*--o'     # dashed, inline label, o-end
        r'|-\.[^.>\n]*\.->'   # dotted, inline label, arrowhead
        r'|==[^=>\n]*==>'     # thick, inline label, arrowhead
        r'|-->|---|--x|--o|-\.->|==>'  # bare forms of all of the above
        r')'
        r'(?:\|(?P<pipelabel>[^|\n]*)\|)?'  # optional trailing |label| (any style)
    )
    seq_edge_re = re.compile(
        r'(?m)^\s*[\w".]+\s*(?:-{1,2}>{1,2}|-{1,2}[x)])\s*[\w".]+\s*:\s*(?P<text>.*)$'
    )
    # Statement-level keywords that are never node ids, so lines starting with
    # one of them are skipped entirely for node/edge extraction (the diagram
    # header itself, subgraph boundaries, style/click directives, comments).
    FLOW_KEYWORDS = {
        'flowchart', 'graph', 'subgraph', 'end', 'direction',
        'classdef', 'class', 'style', 'linkstyle', 'click',
    }

    def parse_flowchart(block):
        """Return (node_ids, unlabeled_edges) for one flowchart/graph block,
        walking every line so chained edges and standalone node declarations
        are both counted."""
        node_ids = set()
        unlabeled = []  # list of (src, op_text, dst)
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line.startswith('%%'):
                continue
            first_word = re.split(r'[\s;]', line, maxsplit=1)[0].lower()
            if first_word in FLOW_KEYWORDS:
                continue
            clean = strip_shapes(line)
            ops = list(op_re.finditer(clean))
            if not ops:
                # No link on this line: a standalone node declaration (or
                # several). Every id token here is a real node.
                node_ids.update(re.findall(r'[A-Za-z0-9_]+', clean))
                continue
            segments, prev_end = [], 0
            for m in ops:
                segments.append(clean[prev_end:m.start()].strip())
                prev_end = m.end()
            segments.append(clean[prev_end:].strip())
            # Only trust this line's node ids if every segment between/around
            # the operators reduces to a single bare identifier — anything
            # else (fan-out "B & C", inline attrs, ...) is a shape this
            # lightweight lint doesn't parse, so skip rather than guess.
            if not all(re.fullmatch(r'[A-Za-z0-9_]+', s) for s in segments):
                continue
            node_ids.update(segments)
            for i, m in enumerate(ops):
                src, dst = segments[i], segments[i + 1]
                op_text, pipe_label = m.group('op'), m.group('pipelabel')
                labeled = (op_text not in BARE_OPS) or bool(pipe_label and pipe_label.strip())
                if not labeled:
                    unlabeled.append((src, op_text, dst))
        return node_ids, unlabeled

    for idx, block_m in enumerate(re.finditer(r'```mermaid\s*\n(.*?)```', content, re.S), start=1):
        block = block_m.group(1)
        first_line = ''
        for ln in block.splitlines():
            if ln.strip():
                first_line = ln.strip()
                break
        if re.match(r'(?i)^(flowchart|graph)\b', first_line):
            nodes, unlabeled = parse_flowchart(block)
            for src, op_text, dst in unlabeled:
                defects.append(
                    f"app/content.md: flowchart diagram #{idx} edge "
                    f"'{src} {op_text} {dst}' has no label"
                )
            if len(nodes) > 7:
                defects.append(
                    f"app/content.md: flowchart diagram #{idx} has {len(nodes)} nodes (max 7)"
                )
        elif re.match(r'(?i)^sequenceDiagram\b', first_line):
            for em in seq_edge_re.finditer(block):
                if not em.group('text').strip():
                    defects.append(
                        f"app/content.md: sequenceDiagram diagram #{idx} arrow has no text after the colon"
                    )

if defects:
    print('\n'.join(defects))
sys.exit(1 if defects else 0)
PY
