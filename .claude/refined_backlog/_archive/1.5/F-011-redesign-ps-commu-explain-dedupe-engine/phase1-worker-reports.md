# Phase 1 worker reports (relayed from the previous session, 2026-09-22)

## Tasks 1–2 (assets visual fixes) — DONE, uncommitted in working tree
Files: assets/template-infographic/{cherry-setup.js, theme.css, explainer.css, components.md}; content.md one line (table row ~257, empty chip + autolink fix). index.html untouched.
- Root cause of dead click-to-jump: explainer.css `html{scroll-behavior:smooth}` turned window.scrollTo into a compositor animation that never advances in hidden/headless tabs. Fix: rule removed; handler re-resolves the target at click time, `scrollIntoView({block:'start',behavior:'instant'})`, replaceState, sets `.is-active`. Measured scrollY 0→3957 (content.md), 0→3966 (components.md).
- Centering: `body.has-nav{padding-left:var(--nav-w)}`; measured 158px gaps both sides at 1680px.
- Contrast (computed): --text-3 #6b6152 = 4.90:1 on paper; kicker --accent #1c4f8f = 6.60; --pitfall #a8321f = 5.39; --check #186a42 = 5.33; step ramp numerals ≥3:1 large bold.
- Color rule: theme.css = cream ramp + --accent/--pitfall/--check (solid/-weak/-tint); all old semantic + six-hue tokens deleted. explainer.css `grep -c cat-` = 0; callouts note|pitfall|check; cherry-setup.js KINDS note|pitfall|check (unknown→note), Mermaid themeVariables accent-only.
- components.md: 3 callout kinds, first gallery diagram = labeled sequenceDiagram, three-noun flowchart deleted.
- Verified: 0 page-origin console errors (content.md ?v=3, components.md ?v=2); SVG count == fence count (2/2, 1/1); lifecycle_test.sh 20 passed, 0 failed.
- Caveat: lifecycle test's clean step wipes /tmp/ps-commu (kills any running app servers). content.md still carries no-op cat-*/data-cat classes until Task 7 rewrites it.
- NEXT for these: Phase 1 gate (code-reviewer on the diff + design-review Chrome re-audit for defects 1,2,7,8,9), refactor, then commit as one commit per task.

## Task 3 (verify.sh + tests) — DONE, uncommitted in working tree
Files: scripts/verify.sh (new, 151 lines, --help, --url, $CHROME_BIN → PATH → macOS app; exit 0 pass / 1 defects / 2 cannot-run=SKIP); tests/lifecycle_test.sh (+check_or_skip helper with SKIP counter; test_verify_passes_template, test_verify_fails_on_leak, test_verify_help). common.sh and assets/ untouched.
- DOM capture that works: `--headless=new --dump-dom --virtual-time-budget=8000 --run-all-compositor-stages-before-draw` (captures `.is-ready` + Mermaid SVGs; error SVGs `aria-roledescription="error"` excluded from the count). Console errors via `--enable-logging=stderr`, chrome-extension:// filtered. Chrome 153 prints the DOM then never exits → Python reads stdout until `</html>` (90s cap, ~45s typical) and killpg's the group. DevTools route abandoned (Runtime.evaluate hangs after load on this build). Text checks parse only the `.cherry-previewer` subtree (hidden editor pane holds raw source); assert 3 ignores <code>/<pre>.
- verify.sh on template: exit 0 — PASS 1 svg=2 fences=2; PASS 2 no ~~CODE; PASS 3 no raw data-nav; PASS 4 console errors=0; SKIP 5 nav click (dump-dom cannot click). Leak fixture: exit 1 with FAIL 1 + FAIL 2.
- Tests: `lifecycle_test.sh` → 23 passed, 0 failed, 0 skipped.
- Notes: assert 5 is a permanent SKIP with this approach (nav fix from Task 1 is not observable by this gate; the Chrome MCP measurement in the Tasks 1–2 report is the evidence). No-Chrome SKIP path only exercised via the rc-2 branch. `PS_COMMU_VERIFY_DOM=<file>` saves the dump. Concurrent lifecycle_test runs wipe /tmp/ps-commu mid-run → never run two at once.
- NEXT: Phase 1 gate on the combined diff, then commit Tasks 1, 2, 3 as separate commits.

## Both workers finished. This file is the complete Phase 1 relay; the previous session has no more background work.
