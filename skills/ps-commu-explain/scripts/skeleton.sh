#!/usr/bin/env bash
# skeleton.sh — draft app/content.md from the authoring chain (infographic tier).
# Usage: skeleton.sh <slug> [--force]
#   Reads 00-brief.md (Q1-Q3), 01-facts.md (F<n> rows) and 02-storyboard.md
#   (one row per section) and writes app/content.md:
#     - the reader-questions block (the brief's Q1-Q3)
#     - per storyboard row: a section-head block, then ONE placeholder line
#         TODO(<questions>; <facts>): <storyboard section text>
#       Plain Markdown, never an HTML comment (Cherry renders `<!--` as literal
#       page text). lint.sh rejects any remaining TODO( line on the
#       infographic tier, so an unfilled skeleton cannot be served. Replace
#       each one with prose that cites its facts.
#     - a Receipts footer: every fact the storyboard cites, with its source.
#   --force  overwrite an existing app/content.md (default: refuse, so authored
#            work is never destroyed).
# Exit 0 = written; 1 = refused (content.md exists) or no filled storyboard
# rows; 2 = cannot run (no workspace, not the infographic tier, a chain file
# missing).
set -uo pipefail
source "$(dirname "$0")/common.sh"

usage() { grep '^#' "$0" | cut -c3-; exit "${1:-0}"; }
slug="" force=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) force=1 ;;
    -h|--help) usage ;;
    *) slug="$1" ;;
  esac
  shift
done
[[ -n "$slug" ]] || usage 1
ws="$PS_COMMU_ROOT/$slug"
[[ -d "$ws/app" ]] || { echo "no workspace app dir: $ws/app (run init.sh first)" >&2; exit 2; }
trap 'log_timing skeleton.sh "$SECONDS"' EXIT
tier="$(meta_get "$slug" tier)"
[[ "$tier" == "infographic" ]] || { echo "skeleton.sh is infographic-tier only (tier='$tier')" >&2; exit 2; }
for f in 00-brief.md 01-facts.md 02-storyboard.md; do
  [[ -f "$ws/$f" ]] || { echo "missing $ws/$f (run init.sh, then fill it)" >&2; exit 2; }
done
if [[ -e "$ws/app/content.md" && "$force" != 1 ]]; then
  echo "refusing to overwrite $ws/app/content.md (pass --force to replace it)" >&2
  exit 1
fi

python3 - "$ws" <<'PY'
import html, os, re, sys, tempfile

ws = sys.argv[1]


def read(name):
    try:
        with open(os.path.join(ws, name), encoding="utf-8") as f:
            return re.sub(r"<!--.*?-->", "", f.read(), flags=re.S)
    except UnicodeDecodeError:
        sys.stderr.write(f"{name}: not valid UTF-8 (re-save it as UTF-8)\n")
        sys.exit(2)


def esc(s):
    return html.escape(s, quote=False)


brief, facts, story = read("00-brief.md"), read("01-facts.md"), read("02-storyboard.md")
qs = dict(re.findall(r"(?m)^Q([1-3]):[ \t]*(\S.*)$", brief))
fact_rows = {
    f"F{n}": (stmt.strip(), src.strip())
    for n, stmt, src in re.findall(r"(?m)^\s*\|?\s*F(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|?\s*$", facts)
}
rows = []
for sec, q, fc in re.findall(r"(?m)^\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$", story):
    if re.fullmatch(r"-{2,}", sec) or sec.lower() == "section" or "(...)" in sec + q + fc:
        continue
    rows.append((sec, re.sub(r"\s+", "", q), re.sub(r"\s+", "", fc)))
if not rows:
    sys.stderr.write("02-storyboard.md: no filled rows (fill it and run lint.sh first)\n")
    sys.exit(1)

out = ['<div class="reader-questions">',
       '  <div class="rq-kicker"><i data-lucide="help-circle"></i> This explainer answers</div>',
       '  <div class="rq-list">']
for n in ("1", "2", "3"):
    out.append(f'    <div class="rq-q"><span class="rq-num">{n}</span>'
               f'<span class="rq-text">{esc(qs.get(n, "").strip())}</span></div>')
out += ["  </div>", "</div>", ""]

ids, cited = set(), []
for i, (sec, q, fc) in enumerate(rows, 1):
    title = re.sub(r"^\d+[.)]?\s*", "", sec) or f"Section {i}"
    sid = re.sub(r"[^a-z0-9]", "", title.lower()) or f"s{i}"
    while sid in ids:
        sid += "x"
    ids.add(sid)
    out += [f'<div class="section-head" data-nav="{html.escape(title)}" data-nav-icon="hash" id="{sid}">',
            '  <span class="icon-chip lg"><i data-lucide="hash"></i></span>',
            '  <div class="sh-text">',
            f'    <span class="sh-kicker">{i}</span>',
            f'    <div class="sh-title">{esc(title)}</div>',
            "  </div>", "</div>", "",
            f"TODO({q}; {fc}): {sec}", ""]
    for fid in re.findall(r"F\d+", fc):
        if fid not in cited:
            cited.append(fid)

out += ['<div class="receipts">',
        '  <div class="receipts-label"><i data-lucide="receipt"></i> Receipts</div>',
        '  <ul class="receipts-list">']
for fid in sorted(cited, key=lambda f: int(f[1:])):
    stmt, src = fact_rows.get(fid, ("(missing from 01-facts.md)", "?"))
    out.append(f'    <li><span class="receipts-fact">{fid}</span> {esc(src)} — {esc(stmt)}</li>')
out += ["  </ul>", "</div>", ""]

path = os.path.join(ws, "app", "content.md")
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".content.")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    os.replace(tmp, path)
except BaseException:
    try: os.unlink(tmp)
    except OSError: pass
    raise
print(f"wrote {path}: {len(rows)} sections, {len(cited)} receipts. "
      "Replace every TODO( line with cited prose, then serve.sh.")
PY
