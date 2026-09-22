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
#                       -- x -->); sequenceDiagram arrows carry text after
#                       the colon; flowchart node count <=7 per diagram.
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
    for fid, stmt, src in rows:
        fact_ids.add(f'F{fid}')
        src = src.strip()
        valid = src != '(...)' and (
            src.lower() == 'user said'
            or bool(re.fullmatch(r'\S+:\d+', src))
            or bool(re.fullmatch(r'\S+', src))
        )
        if not valid:
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
    missing_q = [n for n in (1, 2, 3) if n not in q_seen]
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
    def strip_shapes(block):
        return re.sub(
            r'([A-Za-z0-9_]+)(\[\[[^\]]*\]\]|\[[^\]]*\]|\(\([^)]*\)\)|\([^)]*\)|\{\{[^}]*\}\}|\{[^}]*\})',
            r'\1',
            block,
        )

    edge_re = re.compile(
        r'(?P<src>[A-Za-z0-9_]+)\s*(?P<op>--[^->\n]*-->|-->)\s*(?:\|(?P<label>[^|\n]*)\|)?\s*(?P<dst>[A-Za-z0-9_]+)'
    )
    seq_edge_re = re.compile(
        r'(?m)^\s*[\w".]+\s*(?:-{1,2}>{1,2}|-{1,2}[x)])\s*[\w".]+\s*:\s*(?P<text>.*)$'
    )

    for idx, block_m in enumerate(re.finditer(r'```mermaid\s*\n(.*?)```', content, re.S), start=1):
        block = block_m.group(1)
        first_line = ''
        for ln in block.splitlines():
            if ln.strip():
                first_line = ln.strip()
                break
        if re.match(r'(?i)^(flowchart|graph)\b', first_line):
            clean = strip_shapes(block)
            nodes = set()
            for em in edge_re.finditer(clean):
                op, label = em.group('op'), em.group('label')
                labeled = (op != '-->') or (label is not None and label.strip() != '')
                nodes.add(em.group('src'))
                nodes.add(em.group('dst'))
                if not labeled:
                    defects.append(
                        f"app/content.md: flowchart diagram #{idx} edge "
                        f"'{em.group('src')} --> {em.group('dst')}' has no label"
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

print('\n'.join(defects))
sys.exit(1 if defects else 0)
PY
