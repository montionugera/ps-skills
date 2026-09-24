#!/usr/bin/env bash
# verify.sh — render gate for a ps-commu workspace (infographic tier).
# Usage: verify.sh <slug> [--url URL]
#   Loads the served page in headless Google Chrome (--dump-dom under a virtual
#   time budget, so the client-side fetch() + Markdown + draw.io render has
#   completed before the DOM is dumped; console output is captured from Chrome's
#   stderr log) and prints one PASS/FAIL/SKIP line per assert:
#     1  rendered draw.io diagram count == fenced ```drawio count in the doc.
#        COUNT-based, not id-based: draw.io's static viewer has no id link
#        between a rendered shape and its source mxCell (confirmed in
#        task-0-report.md). FAILs on either of two failure modes, both
#        confirmed empirically against the pinned viewer build (never
#        assumed): (a) fewer rendered `<div class="mxgraph">` than fences —
#        the viewer script never loaded (CDN miss), so cherry-setup.js's
#        frameAndRunDrawio() bails out at its `typeof GraphViewer ===
#        "undefined"` guard before creating any div at all; (b) a
#        `.mxgraph` div whose `<svg>` is present but holds no shape content
#        (no `<rect>`/`<path>`/`<foreignObject>`) — the spec's documented
#        "malformed-but-JSON-valid XML renders an empty graph, zero console
#        errors" failure mode (reproduced with a well-formed-XML,
#        zero-vertex `<mxGraphModel>`: it renders `<svg><g><g/><g/><g/><g/>
#        </g></svg>` and nothing else, no console output whatsoever — a
#        naive "a nested <svg> exists" check would false-PASS this).
#     2  body text has no `~~CODE` placeholder leak
#     3  body text has no raw `data-nav` attribute text
#     4  zero page-origin console errors (chrome-extension:// ignored)
#     5  clicking the first sidebar nav item changes window.scrollY — SKIP:
#        a DOM dump cannot dispatch clicks, and the DevTools-protocol route
#        (Runtime.evaluate) hangs on this Chrome build once the page has loaded.
#     6  served explainer.css does NOT declare `scroll-behavior` (static proxy
#        for the click-to-jump root cause: `scroll-behavior: smooth` on <html>
#        turns window.scrollTo into a compositor animation that silently
#        no-ops in a hidden/headless tab — this is a real PASS/FAIL, not a
#        SKIP, so defect 1 keeps a scripted gate even while assert 5 can't run.
#        Assert 6 needs neither Chrome nor a live server, so it still runs —
#        and can still FAIL — even when Chrome is missing; see below)
#     7  draw.io pan/zoom interactivity actually initialized. A static DOM
#        proxy check, never a permanent SKIP the way assert 5's click check
#        is (per the spec's explicit "not deferred" requirement for
#        interactivity). FAILs (whenever Chrome is available, i.e. whenever
#        this assert runs at all) if either: no `.mxgraph` div rendered at
#        all for >=1 ```drawio fence (same GraphViewer-never-loaded signal
#        as assert 1's failure mode (a), checked here as its own named
#        assertion); or FEWER than ALL rendered `.mxgraph` divs show the
#        `margin-top` inline-style side effect that GraphViewer's
#        addToolbar() sets unconditionally the instant a div's `toolbar`
#        config key is honored — per-diagram, all-or-nothing, mirroring
#        assert 1's own rule, so a PARTIAL regression (e.g. 1 of 3 diagrams
#        losing pan/zoom) still FAILs instead of hiding behind "at least one
#        worked". Confirmed empirically (render the same diagram with and
#        without `"toolbar":"zoom"` in data-mxgraph) that `margin-top`
#        appears ONLY when the key is set. The zoom-in/out/fit BUTTONS
#        themselves are NOT usable evidence here: confirmed empirically that
#        GraphViewer only appends them to the DOM on a live `mouseenter`
#        over the graph container, which a --dump-dom capture can never
#        trigger — the same hover/click limitation that makes assert 5 a
#        permanent SKIP.
#   --url  page URL to load (default: http://127.0.0.1:<port> from meta.json;
#          requires a live marker-verified server). A ?doc=X query selects
#          which app/X markdown file the fence count is taken from.
#   --dump-text  skip the PASS/FAIL asserts; instead print the clean,
#          reader-visible page text to stdout and exit 0 (reuses the same
#          .cherry-previewer extractor the asserts use internally — this is
#          the reader gate's input, NOT a raw --dump-dom: that would return
#          duplicated toolbar/source-pane/preview copies plus raw data-nav
#          markup and unrendered ```drawio fences). Exit 1 if the page never
#          rendered a .cherry-previewer subtree; 2 if Chrome/server is
#          unavailable, same as the normal run.
#   Chrome: $CHROME_BIN, else google-chrome/chromium on PATH, else the macOS app.
# Exit 0 = every non-skipped assert passed; 1 = defects listed; 2 = cannot run
# (no Chrome / no server) — callers treat 2 as SKIP, never as pass. Exception:
# with no Chrome, assert 6 (no Chrome/server dependency) still runs, and a
# FAIL there is exit 1, not 2 — a real, actionable defect is never masked as
# "cannot run".
set -uo pipefail
source "$(dirname "$0")/common.sh"

usage() { grep '^#' "$0" | cut -c3-; exit "${1:-0}"; }
slug="" url="" dump_text=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) [[ $# -ge 2 ]] || { echo "--url requires a value" >&2; exit 1; }
           url="$2"; shift ;;
    --dump-text) dump_text=1 ;;
    -h|--help) usage ;;
    *) slug="$1" ;;
  esac
  shift
done
[[ -n "$slug" ]] || usage 1
ws="$PS_COMMU_ROOT/$slug"
[[ -d "$ws/app" ]] || { echo "no workspace app dir: $ws/app (run init.sh first)" >&2; exit 1; }

# Assert 6 (defined here, run at its usual point below AND from the
# no-Chrome branch just below): a static grep of a file already on disk, not
# a Chrome check, so it must not be silently skipped on a Chrome-less box —
# see the assert 6 comment further down for the full rationale.
assert6() {
  local explainer_css="$ws/app/explainer.css"
  if [[ ! -f "$explainer_css" ]]; then
    echo "FAIL: 6 explainer.css not found at $explainer_css"
    return 1
  elif python3 -c "
import re, sys
css = open(sys.argv[1]).read()
css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
sys.exit(0 if 'scroll-behavior' in css else 1)
" "$explainer_css"; then
    echo "FAIL: 6 explainer.css declares scroll-behavior (reintroduces the nav click-to-jump root cause)"
    return 1
  else
    echo "PASS: 6 explainer.css does not declare scroll-behavior (nav click-to-jump root-cause gate)"
    return 0
  fi
}

find_chrome() {
  if [[ -n "${CHROME_BIN:-}" && -x "${CHROME_BIN:-}" ]]; then echo "$CHROME_BIN"; return 0; fi
  local c
  for c in google-chrome google-chrome-stable chromium chromium-browser; do
    command -v "$c" 2>/dev/null && return 0
  done
  c="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  [[ -x "$c" ]] && { echo "$c"; return 0; }
  return 1
}
chrome="$(find_chrome)" || {
  echo "SKIP: no Google Chrome found (set CHROME_BIN)"
  # --dump-text has nothing to export without Chrome — unchanged, exit 2.
  [[ "$dump_text" == "1" ]] && exit 2
  # Asserts 1-5 need Chrome and cannot run, but assert 6 needs neither Chrome
  # nor a live server (it greps a file on disk) — run it so a Chrome-less CI
  # box still gates the branch's flagship regression instead of skipping it
  # along with everything else.
  if assert6; then exit 2; else exit 1; fi
}

if [[ -z "$url" ]]; then
  port="$(meta_get "$slug" port)"; pid="$(meta_get "$slug" pid)"
  if [[ -z "$pid" ]] || ! pid_has_marker "$pid" "$slug"; then
    echo "SKIP: $slug has no live server (run serve.sh $slug, or pass --url)"; exit 2
  fi
  url="http://127.0.0.1:$port/"
fi

# Which markdown file the page will fetch: ?doc=X, else content.md.
doc="$(python3 -c 'import sys,urllib.parse as u; q=u.parse_qs(u.urlparse(sys.argv[1]).query); print(q.get("doc",["content.md"])[0])' "$url")"
md="$ws/app/$doc"
[[ -f "$md" ]] || { echo "FAIL: doc not found: $md"; exit 1; }
# Fence detection MUST mirror cherry-setup.js's frameAndRunDrawio() (the
# renderer) and lint.sh's own already-widened rule (lint.sh:464-485), not a
# plain ```drawio grep: the renderer also content-sniffs ANY fenced block
# (any language tag, or none) whose trimmed body starts with "<mxGraphModel"
# (cherry-setup.js's DRAWIO_HEAD = /^<mxGraphModel\b/ -- deliberately NOT
# <mxfile> or <?xml, see that file's own comment on why those two are
# excluded). A plain ```drawio-only count would report fences=0 for a real,
# live-rendered ```xml-fenced diagram -- a false FAIL on assert 1, and worse,
# a vacuous PASS on assert 7's interactivity check if that were the doc's
# only diagram. All three files (renderer, lint.sh, verify.sh) must agree on
# what counts as a drawio diagram.
#
# DELIBERATELY NOT stripping HTML comments here, unlike lint.sh:61-68's
# strip_comments() -- checked empirically, not assumed (PS_COMMU_VERIFY_DOM
# dump on a real served page), and lint.sh's premise does not hold for this
# renderer: Cherry-Markdown here does not implement <!-- ... --> as an HTML
# comment block at all -- a `<!--` line on its own renders as an ORDINARY
# escaped-text paragraph (confirmed: the dumped DOM shows literal
# `<p>&lt;!--</p>`, i.e. Cherry escaped it as plain text, which real
# comment-block passthrough never would), and any ```drawio fence physically
# positioned between `<!--`/`-->` lines still parses as a completely normal,
# independent code fence and DOES get picked up and rendered live by
# frameAndRunDrawio(). Stripping comments here would therefore UNDER-count a
# diagram that genuinely renders -- the exact same false-FAIL failure class
# this fix round exists to close, just pointed the other way (FAIL: 1 ...
# svg=1 fences=0 on a page with no defect). See
# test_verify_counts_html_commented_fence_because_it_still_renders in
# lifecycle_test.sh for the reproduction. This is a real discrepancy with
# lint.sh's own assumption (filed for the whole-branch review, not fixed here
# -- out of this file's scope): a "commented-out" diagram is skipped by
# lint.sh's validation but still renders live on the page, which is arguably
# backwards.
#
# Any failure reading the file (permissions, unexpected encoding) prints a
# plain error line instead of a raw traceback, and the bash-level guard below
# turns that into this script's normal FAIL: line + exit 1, never an
# unhandled ValueError from `int()` further down in the main heredoc.
fences="$(python3 -c '
import re, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        content = f.read()
except Exception as e:
    print(f"error reading {sys.argv[1]}: {e}")
    sys.exit(0)
DRAWIO_HEAD_RE = re.compile(r"^<mxGraphModel\b")
n = 0
for m in re.finditer(r"```([^\n`]*)\n(.*?)```", content, re.S):
    lang, body = m.group(1).strip(), m.group(2)
    if lang == "drawio" or DRAWIO_HEAD_RE.match(body.strip()):
        n += 1
print(n)
' "$md")"
[[ "$fences" =~ ^[0-9]+$ ]] || { echo "FAIL: could not count drawio fences in $md: $fences"; exit 1; }

python3 - "$chrome" "$url" "$fences" "$dump_text" <<'PY'
import os, re, select, shutil, signal, subprocess, sys, tempfile, time
from html.parser import HTMLParser
chrome, url, fences, dump_text = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4] == "1"
prof = tempfile.mkdtemp(prefix="ps-commu-verify-")
proc = None
out, err = b"", b""
try:
    cmd = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
           "--no-default-browser-check", "--disable-background-networking", "--disable-sync",
           "--disable-component-update", "--disable-extensions", "--window-size=1280,900",
           "--user-data-dir=" + prof, "--enable-logging=stderr", "--v=0",
           "--virtual-time-budget=8000", "--run-all-compositor-stages-before-draw",
           "--dump-dom", url]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    # This Chrome build prints the DOM and then hangs on shutdown, so read stdout
    # until </html> (or 90s; ~45s is normal on macOS) and kill it ourselves instead of waiting for exit.
    end = time.time() + 90
    fds = [proc.stdout, proc.stderr]
    while fds and time.time() < end and b"</html>" not in out:
        r, _, _ = select.select(fds, [], [], 0.5)
        for f in r:
            chunk = os.read(f.fileno(), 65536)
            if not chunk: fds.remove(f); continue
            if f is proc.stdout: out += chunk
            else: err += chunk
finally:
    # try/finally so the Chrome process group and the /tmp profile dir can
    # never be orphaned: a JSON/dict error, an unexpected exception anywhere
    # above, or an external SIGTERM (callers wrap this whole script in their
    # own `timeout`, on top of the 90s internal budget) must still reach this
    # cleanup. Kill the whole process group: renderer/GPU children hold the
    # stderr pipe, so a plain kill()+read() would block forever — and never
    # call a blocking read after this.
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc is not None:
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
    shutil.rmtree(prof, ignore_errors=True)
dom, log = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
lines, failed = [], 0
def report(status, n, text):
    global failed
    if status == "FAIL": failed += 1
    lines.append(f"{status}: {n} {text}")
if "</html>" not in dom:
    report("FAIL", 0, f"Chrome produced no complete DOM within 90s ({len(dom)} bytes)")
if not re.search(r'class="[^"]*\bis-ready\b', dom):
    report("FAIL", 0, "page never reached .is-ready (render pipeline did not finish in the 8s budget)")
m = re.search(r'class="explainer-error".*?</div>\s*</div>', dom, re.S)
if m: report("FAIL", 0, "page shows error panel: " + " ".join(re.sub(r"<[^>]+>", " ", m.group(0)).split())[:160])
if os.environ.get("PS_COMMU_VERIFY_DOM"):
    open(os.environ["PS_COMMU_VERIFY_DOM"], "w").write(dom)   # keep the dump for debugging
# Reader-visible text = the cherry preview subtree only. The dump also holds
# cherry's hidden editor pane (raw Markdown source), which innerText would never
# show, so a whole-body scan would flag every <div data-nav> as a leak.
class Preview(HTMLParser):
    def __init__(self):
        super().__init__(); self.depth = 0; self.skip = 0; self.code = 0; self.text = []; self.prose = []
    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class", "")
        if not self.depth and "cherry-previewer" in cls.split(): self.depth = 1; return
        if self.depth:
            self.depth += 1
            if tag in ("script", "style"): self.skip = self.depth
            if tag in ("code", "pre"): self.code = self.code or self.depth
    def handle_endtag(self, tag):
        if self.depth:
            if self.skip == self.depth: self.skip = 0
            if self.code == self.depth: self.code = 0
            self.depth -= 1
    def handle_data(self, data):
        if self.depth and not self.skip:
            self.text.append(data)
            if not self.code: self.prose.append(data)   # samples in <code> are legit
# Count-based draw.io inspection (assert 1 + assert 7's GraphViewer/toolbar
# checks) — depth-tracked like Preview above, NOT a naive "close on the first
# </div>": Task 0's DOM notes show a diagram's foreignObject label text is
# itself wrapped in nested <div>s (for centering), so a shallow close-on-
# </div> would end a diagram's capture at its own first label, silently
# truncating everything the label's sibling shapes/edges render after it.
_VOID_TAGS = {"br", "img", "input", "hr", "meta", "link", "area", "base",
              "col", "embed", "source", "track", "wbr"}
class MxGraphCount(HTMLParser):
    def __init__(self):
        super().__init__()
        self.divs = []       # finished {"svg": bool, "content": bool, "toolbar_init": bool}
        self.capture = None  # the in-progress record for the .mxgraph div being walked
        self.depth = 0       # tag-nesting depth *inside* that div (the div itself = 1)
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.capture is None:
            if tag == "div" and "mxgraph" in a.get("class", "").split():
                # "margin-top" is the addToolbar() side effect assert 7 checks for
                # (see the header comment above) — computed once at capture time
                # rather than carrying the raw style string forward for one check.
                self.capture = {"svg": False, "content": False,
                                 "toolbar_init": "margin-top" in a.get("style", "")}
                self.depth = 1
            return
        if tag == "svg": self.capture["svg"] = True
        if tag in ("rect", "path", "ellipse", "foreignobject"): self.capture["content"] = True
        if tag not in _VOID_TAGS: self.depth += 1
    def handle_endtag(self, tag):
        if self.capture is None: return
        self.depth -= 1
        if self.depth <= 0:
            self.divs.append(self.capture)
            self.capture = None
mx = MxGraphCount(); mx.feed(dom)

pv = Preview(); pv.feed(dom)
text, prose = "".join(pv.text), "".join(pv.prose)
no_preview_msg = "no .cherry-previewer subtree in the dump (page did not render)"
if dump_text:
    # Reuse the exact same extraction used by asserts 2/3 below — do not
    # duplicate it. This is the reader gate's input (SKILL.md Stage 5).
    if not pv.text:
        sys.stderr.write(f"FAIL: {no_preview_msg}\n")
        sys.exit(1)
    sys.stdout.write(text)
    sys.exit(0)
if not pv.text: report("FAIL", 0, no_preview_msg)
rendered = sum(1 for d in mx.divs if d["svg"] and d["content"])
empty = sum(1 for d in mx.divs if d["svg"] and not d["content"])
no_svg = sum(1 for d in mx.divs if not d["svg"])
report("PASS" if rendered == fences and empty == 0 and no_svg == 0 else "FAIL", 1,
       f"drawio svg={rendered} fences={fences} "
       f"(mxgraph-divs={len(mx.divs)} empty-render={empty} no-svg={no_svg})")
report("FAIL" if "~~CODE" in text else "PASS", 2, "~~CODE placeholder " + ("LEAKED in body text" if "~~CODE" in text else "absent"))
report("FAIL" if "data-nav" in prose else "PASS", 3, "raw data-nav text " + ("LEAKED in body text" if "data-nav" in prose else "absent"))
# Console: Chrome's stderr log lines look like
#   [pid:tid:ts:ERROR:CONSOLE(12)] "Uncaught ...", source: http://127.0.0.1:7700/x.js (12)
errs = []
for ln in log.splitlines():
    mm = re.match(r'\[[^\]]*:ERROR:CONSOLE\(\d+\)\]\s*(.*?)(?:, source: (\S+) \(\d+\))?$', ln)
    if mm and not (mm.group(2) or "").startswith("chrome-extension://"):
        errs.append((mm.group(1), mm.group(2) or ""))
report("FAIL" if errs else "PASS", 4, f"console errors={len(errs)}")
for t, u in errs[:10]: lines.append(f"      {t[:200]}  [{u}]")
report("SKIP", 5, "nav click: --dump-dom cannot dispatch clicks and DevTools Runtime.evaluate hangs on this Chrome build after page load")
# Assert 7 — see the header comment above for the full empirically-confirmed
# rationale. Never SKIP here (this code only runs once Chrome already
# produced a DOM dump, i.e. the same "Chrome available" condition asserts
# 1-5 run under) — a vacuous PASS only when the doc has no ```drawio fences
# to begin with, matching assert 1's own fences==0 behavior.
mxgraph_total = len(mx.divs)
toolbar_init = sum(1 for d in mx.divs if d["toolbar_init"])
if fences == 0:
    report("PASS", 7, "drawio interactivity: no ```drawio fences in doc, nothing to check")
elif mxgraph_total == 0:
    report("FAIL", 7, f"GraphViewer global absent: zero .mxgraph divs rendered for {fences} "
           "```drawio fence(s) (CDN miss, or frameAndRunDrawio bailed before wrapping)")
elif toolbar_init < mxgraph_total:
    # Per-diagram, all-or-nothing — mirrors assert 1's own rule. `> 0` alone
    # would PASS a partial regression (e.g. 1/3 diagrams initialized the
    # toolbar, 2 silently didn't): the whole gate must not go green while
    # any rendered diagram's pan/zoom is dead.
    report("FAIL", 7, f"toolbar not initialized on {mxgraph_total - toolbar_init}/{mxgraph_total} "
           "diagram(s): missing the addToolbar() margin-top side effect for at least one "
           "(pan/zoom toolbar did not take effect)")
else:
    report("PASS", 7, f"drawio interactivity: GraphViewer loaded, toolbar initialized on "
           f"{toolbar_init}/{mxgraph_total} diagram(s)")
print("\n".join(lines))
sys.exit(1 if failed else 0)
PY
py_status=$?

# --dump-text is a text-export mode, not an assert run: the python block
# above already printed the text (or a FAIL) and exited — skip assert 6 and
# report its own exit code directly.
[[ "$dump_text" == "1" ]] && exit "$py_status"

# Assert 6: static regression gate for the nav click-to-jump root cause. Assert
# 5 above is a permanent SKIP (--dump-dom cannot click, and the DevTools route
# hangs on this Chrome build) — so without this, the original defect (dead
# click-to-jump) has no scripted gate going forward, only one-time manual
# verification. `scroll-behavior: smooth` on <html> is the documented root
# cause (it turns window.scrollTo into a compositor animation that silently
# no-ops in a hidden/headless tab); this greps the SERVED explainer.css for
# it. Cheap, dependency-free, PASS/FAIL — never SKIP. It needs neither Chrome
# nor a live server, so it's also defined and runnable from the no-Chrome
# branch above `find_chrome` — see `assert6()`, called here too so the logic
# lives in one place.
# CSS comments are stripped first (python3, already a hard dependency of this
# script) so a rule like "/* no scroll-behavior:smooth here, see ... */" that
# EXPLAINS the fix in prose doesn't itself trip a false FAIL.
css_status=0; assert6 || css_status=$?

[[ "$py_status" -eq 0 && "$css_status" -eq 0 ]]
