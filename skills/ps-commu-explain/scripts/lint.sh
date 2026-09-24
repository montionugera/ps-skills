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
#                       -- x -->, for every link family Mermaid has:
#                       ---/-->/-.->/==>/--x/--o/x--x/o--o/<-->/... ; the
#                       invisible ~~~ link is exempt); flowchart node count
#                       <=7 per diagram, counting every declared node id
#                       (edge endpoints AND standalone "ID[label]"
#                       declarations); sequenceDiagram arrows carry text
#                       after the colon. Flowcharts are read by a scanner
#                       that mirrors Mermaid's own case-sensitive grammar:
#                       anything it cannot classify, a mis-cased keyword
#                       ("Graph", "classdef", "End" closing a subgraph), a
#                       trailing "%% comment", an unbalanced subgraph, a
#                       link operator inside style arguments, or a block
#                       whose header is not a known diagram type is REPORTED
#                       (fail closed) — never silently skipped.
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
    if not q_ids:
        # q_ids is only ever [] when 00-brief.md is missing or had no
        # parseable Q<n> lines (both already their own defect above) — an
        # empty q_ids must not make Q-coverage trivially "pass" here; say
        # outright that it couldn't be checked.
        defects.append("02-storyboard.md: cannot verify Q-coverage — 00-brief.md has no parsed reader questions")
    else:
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

    # ------------------------------------------------------------------
    # Mermaid flowchart checking (fix round 4: single-pass scanner).
    #
    # The block is read ONCE, left to right, by a scanner modelled on
    # Mermaid's own flowchart lexer (packages/mermaid/src/diagrams/flowchart/
    # parser/flow.jison) and checked against Mermaid 11.15's real parser for
    # every syntax form named below. At every position the scanner knows
    # whether it is inside a quoted string, a node-shape label ("[...]",
    # "(...)", "{...}" and the double/stadium/cylinder/trapezoid/odd forms),
    # an inline edge label ("-- text -->") or a "|text|" label, and only
    # treats ';', '%%', a link operator or a directive keyword as meaningful
    # OUTSIDE all of those. Earlier rounds split each line with a sequence
    # of independent regexes; every fix moved the ambiguity to a different
    # form (a silent skip each time). Facts this scanner relies on, all
    # verified against the real parser rather than assumed:
    #   * Keywords are CASE-SENSITIVE: "Graph TD" is not a diagram at all,
    #     "classdef" is a parse error, "End" is an ordinary node id and does
    #     not close a subgraph, lowercase "end"/"style"/... cannot be ids.
    #   * ';' and '%%' are literal inside every label form, and quoted
    #     labels, edge text and |labels| may span lines.
    #   * '%%' comments are only legal on their own line.
    #   * "style"/"classDef"/"linkStyle" arguments run to END OF LINE (';'
    #     is a style token), so "style A fill:#f00; B --> C" is an error;
    #     "class"/"click"/"subgraph"/"end" statements end at ';'.
    #   * Link vocabulary: [xo<]?--+[-xo>], [xo<]?==+[=xo>],
    #     [xo<]?-?.+-[xo>]?, ~~~ (invisible), each bare, with "-- text -->"
    #     inline text, or with a trailing |text| label — never both.
    # ------------------------------------------------------------------
    FLOW_RESERVED = {  # exact-case whole tokens that can never be a node id
        'graph', 'flowchart', 'flowchart-elk', 'subgraph', 'end', 'style',
        'linkStyle', 'classDef', 'class', 'click', 'interpolate', 'href', 'call',
    }
    # Node id: word chars, '.', '#', a single ':' (not the ':::' class
    # separator) and Mermaid's own dash rule (a '-' not followed by '>', '-'
    # or '.'), so "a.b", "c-d", "node#1", "ก" are ids while "A-->B" is not.
    ID_RE = re.compile(r'(?:[\w.#]|:(?!::)|-(?=[^>\-.\s]))+')
    LINK_RE = re.compile(r'[xo<]?-{2,}[-xo>]|[xo<]?={2,}[=xo>]|[xo<]?-?\.+-[xo>]?|~{2,}')
    START_LINK_RE = re.compile(r'[xo<]?(?:--|==|-\.)')      # opens "-- text -->"
    LINK_CLOSER = {                                          # keyed by family char
        '-': re.compile(r'[xo<]?-{2,}[-xo>]'),
        '=': re.compile(r'[xo<]?={2,}[=xo>]'),
        '.': re.compile(r'[xo<]?-?\.+-[xo>]?'),
    }
    EDGE_ID_RE = re.compile(r'[\w-]+@(?=[xo<]?[-=.~])')     # "A e1@--> B"
    CLASS_TAG_RE = re.compile(r':::[\w-]+')
    HEADER_RE = re.compile(
        r'(?:flowchart-elk|flowchart|graph)(?:[ \t]+(?:TB|TD|BT|RL|LR|BR|[<>^v]))?[ \t\r]*(?=;|\n|$)'
    )
    DIRECTION_RE = re.compile(r'direction[ \t]+(?:TB|TD|BT|RL|LR)\b')
    ACC_RE = re.compile(r'acc(?:Title|Descr)[ \t]*[:{]')
    SHAPE_OPENERS = [  # longest opener first; each maps to its legal closer(s)
        ('(((', (')))',)), ('([', ('])',)), ('[(', (')]',)), ('[[', (']]',)),
        ('[/', ('/]', '\\]')), ('[\\', ('\\]', '/]')), ('((', ('))',)),
        ('{{', ('}}',)), ('(-', ('-)',)), ('[', (']',)), ('(', (')',)),
        ('{', ('}',)), ('>', (']',)),
    ]
    seq_edge_re = re.compile(
        r'(?m)^\s*[\w".]+\s*(?:-{1,2}>{1,2}|-{1,2}[x)])\s*[\w".]+\s*:\s*(?P<text>.*)$'
    )

    class Bad(Exception):
        """A statement this lint cannot classify. Carries the offending
        position and the reason; the caller turns it into a defect."""
        def __init__(self, pos, why):
            super().__init__(why)
            self.pos, self.why = pos, why

    def has_link(text, strip_brackets=False):
        text = re.sub(r'"[^"]*"', '', text)
        if strip_brackets:
            text = re.sub(r'\[[^\]]*\]', '', text)
        return bool(LINK_RE.search(text) or START_LINK_RE.search(text))

    def parse_flowchart(block, idx):
        """Return (node_ids, unlabeled_edges) for one flowchart/graph block.

        Guarantee: every statement is either understood and checked (node
        ids counted, every link's label checked, subgraph nesting balanced)
        or reported as a defect with its line number. Nothing is dropped
        from validation without a defect saying so.

        Deliberate, documented limits (each is a VISIBLE outcome, never a
        silent skip):
          * The lint is stricter than Mermaid on labels: a whitespace-only
            "|  |" label counts as unlabeled; the invisible link "~~~" is
            exempt because it carries no information.
          * Arguments of style/classDef/linkStyle/class/click/accTitle/
            accDescr and subgraph titles are not validated beyond their
            shape and the absence of a link operator; a CSS-level mistake
            there surfaces at render time (verify.sh), not here.
          * Node ids outside [\\w.#:-] (e.g. containing '&', '/', '"'), ids
            ending in '-' ("A- --> B" is legal Mermaid) and the "[|...|]"
            props form are reported as not understood rather than parsed.
          * A block headed by a diagram type this lint has no rules for
            (classDiagram, pie, ...) passes without any check, by design;
            any other unrecognised first line is reported.
          * Trailing "%% comments" (illegal in Mermaid) are reported, but the
            statement in front of them is still checked so a real defect
            there is not masked.
          * The lint does not track whether an id used by class/click/style
            was declared, or whether a "[quoted]" label form renders."""
        n = len(block)
        nodes, unlabeled, open_subgraphs = set(), [], []

        def line_of(p):
            return block.count('\n', 0, min(p, n)) + 1

        def eol(p):
            e = block.find('\n', p)
            return n if e < 0 else e

        def at_line_start(p):
            return block[block.rfind('\n', 0, p) + 1:p].strip() == ''

        def skip_ws(p):  # inline whitespace only: a newline ends a statement
            while p < n and block[p] in ' \t\r':
                p += 1
            return p

        def report(p, msg):
            defects.append(f"app/content.md: flowchart diagram #{idx} line {line_of(p)} {msg}")

        def stmt_text(start, err_pos):
            text = block[start:eol(max(start, err_pos))]
            return re.sub(r'\s+', ' ', text).strip()[:120]

        def expect_terminator(p, what):
            p = skip_ws(p)
            if p < n and block[p] not in ';\n' and not block.startswith('%%', p):
                raise Bad(p, f"unexpected text after {what}")
            return p

        def skip_quoted(p, what):  # p is on the opening '"'
            e = block.find('"', p + 1)
            if e < 0:
                raise Bad(p, f"unterminated quote in {what}")
            return e + 1

        def scan_to_stmt_end(p, brackets):
            """Advance to the first top-level ';' or newline, skipping quoted
            strings and (optionally) bracketed text."""
            depth = 0
            while p < n:
                ch = block[p]
                if ch == '"':
                    p = skip_quoted(p, 'statement')
                    continue
                if brackets and ch in '[({':
                    depth += 1
                elif brackets and ch in '])}':
                    depth = max(0, depth - 1)
                elif depth == 0 and ch in ';\n':
                    return p
                p += 1
            return p

        def scan_label(p, closers, what):
            """p is just past a shape opener; returns the position just past
            its closer. Mirrors Mermaid's text state: quotes protect
            anything, unquoted brackets and '|' are errors."""
            while p < n:
                ch = block[p]
                if ch == '"':
                    p = skip_quoted(p, what)
                    continue
                for c in closers:
                    if block.startswith(c, p):
                        return p + len(c)
                if ch in '[](){}|':
                    raise Bad(p, f"unquoted '{ch}' inside {what} (wrap the label in double quotes)")
                p += 1
            raise Bad(p, f"unterminated {what}")

        def scan_shape_data(p, nid):  # p is just past '@{'
            while p < n:
                ch = block[p]
                if ch == '"':
                    p = skip_quoted(p, f"the @{{...}} data of node '{nid}'")
                    continue
                if ch == '}':
                    return p + 1
                p += 1
            raise Bad(p, f"unterminated @{{...}} data on node '{nid}'")

        def parse_node(p):
            m = ID_RE.match(block, p)
            if not m:
                found = f" (found '{block[p]}')" if p < n else ''
                raise Bad(p, 'expected a node id' + found)
            nid, p = m.group(), m.end()
            if nid in FLOW_RESERVED:
                raise Bad(m.start(), f"reserved word '{nid}' used as a node id — Mermaid keywords "
                                     f"are case-sensitive, so 'End'/'Style' are node ids but '{nid}' is not")
            for opener, closers in SHAPE_OPENERS:
                if block.startswith(opener, p):
                    p = scan_label(p + len(opener), closers, f"the '{opener}' label of node '{nid}'")
                    break
            tagged = False
            while True:
                if block.startswith(':::', p):
                    if tagged:
                        raise Bad(p, f"node '{nid}' has two ':::' class tags")
                    c = CLASS_TAG_RE.match(block, p)
                    if not c:
                        raise Bad(p, "':::' must be followed by a class name")
                    p, tagged = c.end(), True
                elif block.startswith('@{', p):
                    p = scan_shape_data(p + 2, nid)
                else:
                    return nid, p

        def parse_node_group(p):  # "A", or "A & B & C" (spaces around '&')
            ids = []
            while True:
                nid, p = parse_node(p)
                ids.append(nid)
                q = skip_ws(p)
                if q > p and q < n and block[q] == '&' and (q + 1 >= n or block[q + 1] in ' \t\r\n'):
                    p = skip_ws(q + 1)
                    continue
                return ids, p

        def parse_link(p):
            """Returns (operator text, labeled, position past the link and
            any |label|)."""
            m = LINK_RE.match(block, p)
            if m:
                op, p, inline = m.group(), m.end(), ''
            else:
                s = START_LINK_RE.match(block, p)
                if not s:
                    raise Bad(p, f"expected a link operator or end of statement (found '{block[p]}')")
                closer = LINK_CLOSER[s.group()[-1]].search(block, s.end())
                if not closer:
                    raise Bad(p, f"inline edge label opened by '{s.group()}' is never closed by a link operator")
                inline = block[s.end():closer.start()]
                op = re.sub(r'\s+', ' ', block[p:closer.end()]).strip()
                p = closer.end()
            pipe = None
            q = skip_ws(p)
            if q < n and block[q] == '|':
                if inline.strip():
                    raise Bad(q, "a link cannot carry both an inline '-- text -->' label and a '|text|' label")
                r = q + 1
                while True:
                    if r >= n:
                        raise Bad(q, "'|' label is never closed")
                    if block[r] == '"':
                        r = skip_quoted(r, '|label|')
                        continue
                    if block[r] == '|':
                        break
                    r += 1
                pipe, p = block[q + 1:r], r + 1
            labeled = bool(inline.replace('"', '').strip()) or bool(pipe is not None and pipe.replace('"', '').strip())
            return op, labeled, p

        def parse_vertex_statement(p):
            groups, links = [], []
            while True:
                ids, p = parse_node_group(p)
                groups.append(ids)
                p = skip_ws(p)
                if p >= n or block[p] in ';\n' or block.startswith('%%', p):
                    break
                e = EDGE_ID_RE.match(block, p)
                if e:
                    p = e.end()
                op, labeled, p = parse_link(p)
                links.append((op, labeled))
                p = skip_ws(p)
                if p >= n or block[p] in ';\n':
                    raise Bad(p, f"link '{op}' has no target node")
            for ids in groups:
                nodes.update(ids)
            for i, (op, labeled) in enumerate(links):
                if labeled or op.startswith('~'):
                    continue
                for src in groups[i]:
                    for dst in groups[i + 1]:
                        unlabeled.append((src, op, dst))
            return p

        def parse_statement(p):
            m = ID_RE.match(block, p)
            word = m.group() if m else ''
            if word in ('graph', 'flowchart', 'flowchart-elk'):
                h = HEADER_RE.match(block, p)
                if not h:
                    raise Bad(p, f"'{word}' header must be followed by an optional direction, then ';' or end of line")
                return h.end()
            if word == 'subgraph':
                end = scan_to_stmt_end(m.end(), brackets=True)
                title = block[m.end():end].strip()
                if has_link(title, strip_brackets=True):
                    raise Bad(m.end(), 'link operator inside a subgraph title')
                name = re.split(r'[\[\s]', title.strip('"'), maxsplit=1)[0]
                open_subgraphs.append((p, name or title))
                return end
            if word == 'end':
                if open_subgraphs:
                    open_subgraphs.pop()
                else:
                    report(p, "has an 'end' that closes no open subgraph")
                return expect_terminator(m.end(), "'end'")
            if word in ('style', 'classDef', 'linkStyle'):
                end = eol(p)
                args = block[m.end():end]
                if not re.match(r'[ \t]+\S', args):
                    raise Bad(p, f"'{word}' needs arguments")
                if has_link(args):
                    report(p, f"has a link operator inside a '{word}' statement — Mermaid reads the rest of "
                              f"the line as style arguments and rejects '--'/'=='/'-.' there "
                              f"(so CSS var(--x) cannot be used; put any edge on its own line)")
                return end
            if word in ('class', 'click'):
                end = scan_to_stmt_end(m.end(), brackets=False)
                args = block[m.end():end]
                if not re.match(r'[ \t]+\S+[ \t]+\S', args):
                    raise Bad(p, f"'{word}' needs a node id followed by a "
                                 f"{'class name' if word == 'class' else 'link or callback'}")
                if has_link(args):
                    report(p, f"has a link operator inside a '{word}' statement")
                return end
            d = DIRECTION_RE.match(block, p)
            if d:  # otherwise "direction" is an ordinary node id (legal Mermaid)
                end = eol(p)
                if block[d.end():end].strip():
                    # Mermaid's lexer takes the WHOLE line as the direction
                    # token, so anything after it (an edge, a ';'-joined
                    # statement, a comment) silently never exists.
                    report(p, f"has text after '{d.group()}' that Mermaid silently ignores — "
                              f"put it on its own line")
                return end
            a = ACC_RE.match(block, p)
            if a:
                if block[a.end() - 1] == '{':
                    close = block.find('}', a.end())
                    if close < 0:
                        raise Bad(p, 'unterminated accDescr { ... }')
                    return close + 1
                return eol(p)
            return parse_vertex_statement(p)

        pos = 0
        while pos < n:
            ch = block[pos]
            if ch in ' \t\r\n;':
                pos += 1
                continue
            if block.startswith('%%', pos):
                if not at_line_start(pos):
                    report(pos, "has a trailing '%%' comment — Mermaid only accepts comments on their own line")
                pos = eol(pos)
                continue
            start = pos
            try:
                pos = parse_statement(pos)
            except Bad as bad:
                report(start, f"not understood by lint: '{stmt_text(start, bad.pos)}' ({bad.why})")
                pos = eol(bad.pos)  # resync at the end of the offending line
        for p, name in open_subgraphs:
            report(p, f"opens subgraph '{name}' that is never closed — only lowercase 'end' closes a "
                      f"subgraph ('End' is a node id; keywords are case-sensitive)")
        return nodes, unlabeled

    FLOWCHART_HEADS = {'flowchart', 'graph', 'flowchart-elk'}
    CHECKED_HEADS = FLOWCHART_HEADS | {'sequenceDiagram'}
    # Mermaid diagram types this lint has no rules for. A block headed by
    # one of these passes silently BY DESIGN (the brief names flowchart and
    # sequenceDiagram only). Any other first line is reported, so a typo
    # ("flowchat"), a body line before the header, or an unknown type can
    # never leave a block silently unchecked.
    OTHER_DIAGRAM_HEADS = {
        # Some of these have a plain form alongside (or instead of) their
        # '-beta' form — verified against mermaid-js/mermaid's own detector
        # regexes (each diagram's detector.ts), not guessed:
        # classDiagram-v2 (classDetector-V2.ts: /^\s*classDiagram/, comment says
        # "Both classDiagram and classDiagram-v2 render with the unified class
        # diagram"), sankey/sankey-beta and packet/packet-beta (both detectors:
        # /^\s*<name>(-beta)?/), block/block-beta and xychart/xychart-beta
        # (same (-beta)? pattern), architecture/architecture-beta (detector:
        # /^\s*architecture/, a bare prefix match), treemap/treemap-beta
        # (detector: /^\s*treemap/, also a bare prefix match). radar has NO
        # plain form — its detector requires the literal 'radar-beta'.
        'classDiagram', 'classDiagram-v2', 'stateDiagram', 'stateDiagram-v2', 'erDiagram',
        'journey', 'gantt', 'pie', 'quadrantChart', 'requirementDiagram', 'gitGraph',
        'mindmap', 'timeline', 'zenuml', 'sankey', 'sankey-beta', 'xychart-beta', 'xychart',
        'block-beta', 'block', 'packet-beta', 'packet', 'kanban', 'architecture-beta',
        'architecture', 'radar-beta', 'treemap-beta', 'treemap', 'C4Context', 'C4Container',
        'C4Component', 'C4Dynamic', 'C4Deployment', 'info', 'agentflow-beta', 'swimlane-beta',
    }

    def split_front_matter(block):
        """Returns (block with any leading '---' YAML front-matter blanked
        out so line numbers are preserved, the first real line's keyword).
        The header search skips blank lines, the front-matter and %% lines."""
        lines = block.splitlines()
        i = 0
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i < len(lines) and lines[i].strip() == '---':
            j = i + 1
            while j < len(lines) and lines[j].strip() != '---':
                j += 1
            for k in range(i, min(j + 1, len(lines))):
                lines[k] = ''
            i = j + 1
        while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith('%%')):
            i += 1
        head = re.split(r'[\s;]', lines[i].strip(), maxsplit=1)[0] if i < len(lines) else ''
        return '\n'.join(lines), head

    for idx, block_m in enumerate(re.finditer(r'```mermaid\s*\n(.*?)```', content, re.S), start=1):
        block, head = split_front_matter(block_m.group(1))
        if head in FLOWCHART_HEADS:
            nodes, unlabeled = parse_flowchart(block, idx)
            for src, op_text, dst in unlabeled:
                defects.append(
                    f"app/content.md: flowchart diagram #{idx} edge "
                    f"'{src} {op_text} {dst}' has no label"
                )
            if len(nodes) > 7:
                defects.append(
                    f"app/content.md: flowchart diagram #{idx} has {len(nodes)} nodes (max 7)"
                )
        elif head == 'sequenceDiagram':
            for em in seq_edge_re.finditer(block):
                if not em.group('text').strip():
                    defects.append(
                        f"app/content.md: sequenceDiagram diagram #{idx} arrow has no text after the colon"
                    )
        elif head.lower() in {h.lower() for h in CHECKED_HEADS}:
            defects.append(
                f"app/content.md: diagram #{idx} header '{head}' is not a Mermaid diagram type — "
                f"diagram keywords are case-sensitive (use 'flowchart', 'graph' or 'sequenceDiagram')"
            )
        elif head not in OTHER_DIAGRAM_HEADS:
            defects.append(
                f"app/content.md: diagram #{idx} header '{head}' is not a Mermaid diagram type this "
                f"lint knows, so the block was NOT checked — the diagram keyword must be the first "
                f"line after any '---' front-matter or '%%' lines"
            )

if defects:
    seen = set()
    print('\n'.join(d for d in defects if not (d in seen or seen.add(d))))
sys.exit(1 if defects else 0)
PY
