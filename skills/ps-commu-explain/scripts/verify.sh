#!/usr/bin/env bash
# verify.sh — render gate for a ps-commu workspace (infographic tier).
# Usage: verify.sh <slug> [--url URL]
#   Loads the served page in headless Google Chrome (--dump-dom under a virtual
#   time budget, so the client-side fetch() + Markdown + Mermaid render has
#   completed before the DOM is dumped; console output is captured from Chrome's
#   stderr log) and prints one PASS/FAIL/SKIP line per assert:
#     1  rendered Mermaid <svg> count == fenced ```mermaid count in the doc
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
#        SKIP, so defect 1 keeps a scripted gate even while assert 5 can't run)
#   --url  page URL to load (default: http://127.0.0.1:<port> from meta.json;
#          requires a live marker-verified server). A ?doc=X query selects
#          which app/X markdown file the fence count is taken from.
#   Chrome: $CHROME_BIN, else google-chrome/chromium on PATH, else the macOS app.
# Exit 0 = every non-skipped assert passed; 1 = defects listed; 2 = cannot run
# (no Chrome / no server) — callers treat 2 as SKIP, never as pass.
set -uo pipefail
source "$(dirname "$0")/common.sh"

usage() { grep '^#' "$0" | cut -c3-; exit "${1:-0}"; }
slug="" url=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) [[ $# -ge 2 ]] || { echo "--url requires a value" >&2; exit 1; }
           url="$2"; shift ;;
    -h|--help) usage ;;
    *) slug="$1" ;;
  esac
  shift
done
[[ -n "$slug" ]] || usage 1
ws="$PS_COMMU_ROOT/$slug"
[[ -d "$ws/app" ]] || { echo "no workspace app dir: $ws/app (run init.sh first)" >&2; exit 1; }

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
chrome="$(find_chrome)" || { echo "SKIP: no Google Chrome found (set CHROME_BIN)"; exit 2; }

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
fences="$(grep -cE '^[[:space:]]*```[[:space:]]*mermaid' "$md" || true)"

python3 - "$chrome" "$url" "$fences" <<'PY'
import os, re, select, shutil, signal, subprocess, sys, tempfile, time
from html.parser import HTMLParser
chrome, url, fences = sys.argv[1], sys.argv[2], int(sys.argv[3])
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
pv = Preview(); pv.feed(dom)
text, prose = "".join(pv.text), "".join(pv.prose)
if not pv.text: report("FAIL", 0, "no .cherry-previewer subtree in the dump (page did not render)")
frames = len(re.findall(r'class="mermaid-frame', dom))
roles = re.findall(r'<svg[^>]*aria-roledescription="([^"]+)"', dom)
err_svgs = roles.count("error")
svgs = len([r for r in roles if r != "error"])
report("PASS" if svgs == fences else "FAIL", 1,
       f"mermaid svg={svgs} fences={fences} (frames={frames} error-svgs={err_svgs})")
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
print("\n".join(lines))
sys.exit(1 if failed else 0)
PY
py_status=$?

# Assert 6: static regression gate for the nav click-to-jump root cause. Assert
# 5 above is a permanent SKIP (--dump-dom cannot click, and the DevTools route
# hangs on this Chrome build) — so without this, the original defect (dead
# click-to-jump) has no scripted gate going forward, only one-time manual
# verification. `scroll-behavior: smooth` on <html> is the documented root
# cause (it turns window.scrollTo into a compositor animation that silently
# no-ops in a hidden/headless tab); this greps the SERVED explainer.css for
# it. Cheap, dependency-free, PASS/FAIL — never SKIP.
# CSS comments are stripped first (python3, already a hard dependency of this
# script) so a rule like "/* no scroll-behavior:smooth here, see ... */" that
# EXPLAINS the fix in prose doesn't itself trip a false FAIL.
explainer_css="$ws/app/explainer.css"
if [[ ! -f "$explainer_css" ]]; then
  echo "FAIL: 6 explainer.css not found at $explainer_css"
  css_status=1
elif python3 -c "
import re, sys
css = open(sys.argv[1]).read()
css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
sys.exit(0 if 'scroll-behavior' in css else 1)
" "$explainer_css"; then
  echo "FAIL: 6 explainer.css declares scroll-behavior (reintroduces the nav click-to-jump root cause)"
  css_status=1
else
  echo "PASS: 6 explainer.css does not declare scroll-behavior (nav click-to-jump root-cause gate)"
  css_status=0
fi

[[ "$py_status" -eq 0 && "$css_status" -eq 0 ]]
