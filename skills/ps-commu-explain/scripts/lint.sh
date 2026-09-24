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
    # draw.io / mxGraph XML checking (replaces the retired Mermaid-grammar
    # scanner as of F-013's Mermaid -> draw.io migration; fix round 1 closed
    # 5 Important findings from independent code-reviewer + python-reviewer
    # passes -- see task-2-review-general.md / task-2-review-python.md).
    #
    # xml.etree.ElementTree is a real parser -- not hand-rolled regex-based
    # tokenization the way the retired Mermaid scanner had to be, since
    # Mermaid has no formal machine-readable grammar to lean on. A
    # malformed ```drawio fence is caught by ET.fromstring() itself, not by
    # lint code trying to reimplement XML's own well-formedness rules.
    #
    # Empirically verified (live python3 xml.etree.ElementTree, not
    # assumed -- this is exactly the kind of distinction that burned 4 fix
    # rounds on the retired Mermaid scanner, so it is checked here rather
    # than guessed, and independently re-verified by both reviewers):
    #   * A literal, unescaped '<' OR a bare '&' (one not starting amp;/
    #     lt;/gt;/quot;/apos;/a numeric character ref) inside an mxCell
    #     attribute value is REJECTED BY xml.etree.ElementTree ITSELF as
    #     not-well-formed (raises ParseError) -- it never reaches the
    #     per-cell checks below, so this lint does not need its own regex
    #     for either half of that case; the try/except on ET.fromstring()
    #     below already reports it as malformed XML (pinned by
    #     test_lint_fails_drawio_bare_ampersand).
    #   * What DOES survive parsing -- and is exactly the case this lint
    #     must catch itself -- is a value that is valid XML but decodes to
    #     a literal '<', e.g. value="F&lt;n&gt; cites this" (or a numeric
    #     ref like &#60;/&#x3C;). ET happily decodes any of those to the
    #     Python string "F<n> cites this". draw.io's viewer renders
    #     html=1 labels via innerHTML, and a *raw* '<' character reaching
    #     the browser's HTML tokenizer there opens a bogus tag and
    #     corrupts the label -- so any literal '<' surviving in a decoded
    #     value is rejected below.
    #   * A literal '&' surviving decode (e.g. value="Q&amp;A" decoding to
    #     "Q&A") is, by contrast, SAFE for that same innerHTML render path:
    #     the WHATWG HTML tokenizer's "ambiguous ampersand" rule treats a
    #     '&' that does not complete a recognised named/numeric character
    #     reference as literal text, and even a fully entity-shaped
    #     substring surviving decode (e.g. a doubly-escaped value that
    #     decodes to literal text "&lt;") is consumed as ordinary text by
    #     a second HTML-entity pass, not re-opened as a tag, because HTML
    #     entity decoding of a text node never re-triggers tag-boundary
    #     detection. Flagging a plain decoded '&' here would therefore be
    #     a FALSE POSITIVE against completely ordinary, safe label text
    #     ("Sales & Marketing"). This lint deliberately does NOT flag a
    #     bare '&' post-decode -- a design choice, not an oversight.
    # ------------------------------------------------------------------
    import xml.etree.ElementTree as ET
    import math

    DRAWIO_HEX_RE = re.compile(r'(fill|stroke)Color=#[0-9a-fA-F]{3,6}')
    DRAWIO_HEAD_RE = re.compile(r'^<mxGraphModel\b')
    DRAWIO_MAX_VERTICES = 7

    def parse_drawio_xml(block, idx):
        """Validate one draw.io diagram block's mxGraph XML. Every defect
        found is appended to `defects`; nothing is silently accepted. A
        block that fails to parse at all is reported once and no further
        checks run against it -- there is no tree left to walk."""

        def report(msg):
            defects.append(f"app/content.md: drawio diagram #{idx} {msg}")

        try:
            model = ET.fromstring(block)
        except ET.ParseError as e:
            report(f"has unparseable/malformed XML: {e}")
            return

        seen_ids = set()
        has_root0 = has_root1 = False
        vertex_ids = []
        geom_by_id = {}    # cid -> (x, y, w, h), OWN (parent-relative) geometry
        parent_by_id = {}  # cid -> parent id, vertices only

        for cell in model.findall('.//mxCell'):
            cid = cell.get('id')
            if cid is None:
                report("has an <mxCell> with no id attribute")
                continue
            if cid in seen_ids:
                report(f"has a duplicate mxCell id '{cid}'")
            seen_ids.add(cid)

            if cid == '0':
                has_root0 = True
                continue
            if cid == '1':
                if cell.get('parent') == '0':
                    has_root1 = True
                continue

            is_vertex = cell.get('vertex') == '1'
            is_edge = cell.get('edge') == '1'
            if is_vertex == is_edge:
                report(
                    f"cell '{cid}' has "
                    + ("both vertex=\"1\" and edge=\"1\"" if is_vertex
                       else "neither vertex=\"1\" nor edge=\"1\"")
                    + " set — every non-root mxCell must be exactly one"
                )
                continue

            value = cell.get('value')
            if value and '<' in value:
                report(
                    f"cell '{cid}' value contains a literal '<' after XML-decoding "
                    "(from &lt; or a numeric character ref) — this corrupts the html=1 "
                    "label once the browser re-parses it as HTML"
                )

            style = cell.get('style') or ''
            hexm = DRAWIO_HEX_RE.search(style)
            if hexm:
                report(
                    f"cell '{cid}' style uses a raw hex color '{hexm.group()}' — use a "
                    "role=accent/pitfall/check token instead (substituted for real theme "
                    "hex at render time)"
                )

            if is_edge:
                if not (value and value.strip()):
                    report(f"edge '{cid}' has no label")
                continue

            # vertex
            vertex_ids.append(cid)
            geom = cell.find('mxGeometry')
            if geom is None:
                report(f"vertex '{cid}' has no <mxGeometry> child")
                continue
            try:
                # mxCodec (draw.io's own export codec) omits x/y entirely when
                # they equal mxGeometry's template default of 0 -- a real,
                # valid export of an origin-positioned shape has no x=/y=
                # attribute at all. width/height are never legitimately
                # omitted (a vertex must have a size), so only x/y get the
                # "absent means 0" leniency; present-but-garbage (e.g. x="abc")
                # still fails below, same as width/height always do.
                x = float(geom.get('x') or 0)
                y = float(geom.get('y') or 0)
                w = float(geom.get('width'))
                h = float(geom.get('height'))
            except (TypeError, ValueError):
                report(
                    f"vertex '{cid}' geometry has a missing or non-numeric width/height, "
                    "or a non-numeric x/y (x/y default to 0 only when the attribute is "
                    "absent, not when it is present but invalid)"
                )
                continue
            if not all(math.isfinite(v) for v in (x, y, w, h)):
                report(f"vertex '{cid}' geometry has a non-finite x/y/width/height (nan/inf)")
                continue
            if w <= 0 or h <= 0:
                report(
                    f"vertex '{cid}' has non-positive geometry (width={w:g}, height={h:g}) "
                    "— a vertex must have positive size"
                )
                continue
            geom_by_id[cid] = (x, y, w, h)
            parent_by_id[cid] = cell.get('parent')

        if not has_root0:
            report('is missing the required root mxCell id="0"')
        if not has_root1:
            report('is missing the required root mxCell id="1" parent="0"')

        if len(vertex_ids) > DRAWIO_MAX_VERTICES:
            report(f"has {len(vertex_ids)} vertex cells (max {DRAWIO_MAX_VERTICES})")

        # mxGraph child geometry is PARENT-RELATIVE, not absolute: a vertex
        # whose parent is not the default layer ("1") has x/y measured from
        # its parent's own origin (e.g. a group/container's children), so
        # overlap/bounds must run on ABSOLUTE position -- resolved by walking
        # the parent chain and summing each ancestor's own (parent-relative)
        # offset until reaching the default layer. A chain that cycles, or
        # passes through a cell with no geometry of its own to resolve,
        # cannot be verified: fail closed (report a defect, exclude from
        # overlap/bounds) rather than silently trusting the cell's own x/y
        # as though it were already absolute.
        def resolve_absolute(cid, chain):
            if cid in chain or cid not in geom_by_id:
                return None
            chain = chain | {cid}
            x, y, w, h = geom_by_id[cid]
            parent = parent_by_id.get(cid)
            if parent in (None, '0', '1'):
                return (x, y, w, h)
            base = resolve_absolute(parent, chain)
            if base is None:
                return None
            return (base[0] + x, base[1] + y, w, h)

        vertex_boxes = []  # (id, x1, y1, x2, y2) -- ABSOLUTE page coordinates
        for cid in geom_by_id:
            resolved = resolve_absolute(cid, frozenset())
            if resolved is None:
                report(
                    f"vertex '{cid}' position cannot be resolved (its parent chain is "
                    "cyclic, or passes through a cell with no geometry of its own) — "
                    "overlap/bounds cannot be verified for it"
                )
                continue
            ax, ay, aw, ah = resolved
            vertex_boxes.append((cid, ax, ay, ax + aw, ay + ah))

        # A group/container vertex is EXPECTED to geometrically contain its own
        # descendants (that is the entire point of nesting) -- their absolute
        # boxes overlapping is correct, not a defect. Only pairs with no
        # ancestor/descendant relationship are genuine candidates for the
        # overlap check; walk each vertex's own parent chain (bounded, since
        # every id here already resolved successfully above -- a cycle or an
        # unresolvable ancestor already excluded it from vertex_boxes) to
        # find its ancestor ids and skip any pair related that way.
        def ancestor_ids(cid):
            ids, cur, seen = set(), parent_by_id.get(cid), set()
            while cur not in (None, '0', '1') and cur not in seen:
                seen.add(cur)
                ids.add(cur)
                cur = parent_by_id.get(cur)
            return ids

        ancestors = {cid: ancestor_ids(cid) for cid, *_ in vertex_boxes}

        for i, (aid, ax1, ay1, ax2, ay2) in enumerate(vertex_boxes):
            for bid, bx1, by1, bx2, by2 in vertex_boxes[i + 1:]:
                if bid in ancestors[aid] or aid in ancestors[bid]:
                    continue
                if not (ax2 <= bx1 or bx2 <= ax1 or ay2 <= by1 or by2 <= ay1):
                    report(f"vertex '{aid}' overlaps vertex '{bid}'")

        # <mxGraphModel> is the bare root the spec's authoring convention asks
        # for, but draw.io's own export codec sometimes wraps it in
        # <mxfile><diagram><mxGraphModel>...</mxGraphModel></diagram></mxfile>
        # -- unwrap to find the real model either way, rather than reading
        # pageWidth/pageHeight off the wrong (<mxfile>) element and finding
        # nothing.
        graph_model = model if model.tag == 'mxGraphModel' else model.find('.//mxGraphModel')
        page_w = page_h = None
        if graph_model is not None:
            raw_w, raw_h = graph_model.get('pageWidth'), graph_model.get('pageHeight')
            if raw_w is not None and raw_h is not None:
                try:
                    cand_w, cand_h = float(raw_w), float(raw_h)
                except ValueError:
                    cand_w = cand_h = None
                if (
                    cand_w is not None
                    and math.isfinite(cand_w)
                    and math.isfinite(cand_h)
                ):
                    page_w, page_h = cand_w, cand_h

        if page_w is None or page_h is None:
            # A bounds check that cannot positively confirm correctness must
            # not stay silent -- the same fail-closed discipline as every
            # other rule here. Covers all of: pageWidth/pageHeight missing,
            # non-numeric, only one of the two present, non-finite, or no
            # <mxGraphModel> found at all (e.g. an <mxfile> wrapper with
            # nothing nested inside it).
            report(
                "declares no usable pageWidth/pageHeight (missing, non-numeric, or no "
                "<mxGraphModel> element found), so vertex bounds cannot be verified"
            )
        else:
            for cid, x1, y1, x2, y2 in vertex_boxes:
                if x1 < 0 or y1 < 0 or x2 > page_w or y2 > page_h:
                    report(
                        f"vertex '{cid}' extends beyond the declared page bounds "
                        f"(0,0)-({page_w:g},{page_h:g})"
                    )

    # cherry-setup.js's frameAndRunDrawio() renders a fenced code block as a
    # diagram when EITHER it is explicitly labelled ```drawio (the
    # "isLabelled" branch there, which renders unconditionally regardless of
    # content -- e.g. an <mxfile>-wrapped export) OR -- mirroring its
    # content-sniff fallback over its "pre code" candidate scan, which
    # inspects every code block regardless of language tag -- the block's
    # trimmed body starts with "<mxGraphModel" (cherry-setup.js's own
    # DRAWIO_HEAD = /^<mxGraphModel\b/, deliberately NOT <mxfile> or <?xml --
    # see that file's own comment on why those two are excluded from content-
    # sniffing there). Matching only ```drawio here would leave a real, live-
    # rendered diagram (e.g. a ```xml fence, or an untagged fence, whose body
    # happens to start with <mxGraphModel) with zero lint coverage; widened
    # to genuinely mirror the renderer, not just approximate it.
    drawio_idx = 0
    for block_m in re.finditer(r'```([^\n`]*)\n(.*?)```', content, re.S):
        lang = block_m.group(1).strip()
        body = block_m.group(2)
        is_labelled = lang == 'drawio'
        if not is_labelled and not DRAWIO_HEAD_RE.match(body.strip()):
            continue
        drawio_idx += 1
        parse_drawio_xml(body, drawio_idx)

if defects:
    seen = set()
    print('\n'.join(d for d in defects if not (d in seen or seen.add(d))))
sys.exit(1 if defects else 0)
PY
