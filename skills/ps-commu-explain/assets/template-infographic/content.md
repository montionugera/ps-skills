<div class="reader-questions" data-nav-title="Serve Lifecycle" data-nav-sub="init → lint → verify">
  <div class="rq-kicker"><i data-lucide="help-circle"></i> This explainer answers</div>
  <div class="rq-list">
    <div class="rq-q"><span class="rq-num">1</span><span class="rq-text">What actually happens when I run <code>init.sh &lt;slug&gt;</code> and then <code>serve.sh &lt;slug&gt;</code>?</span></div>
    <div class="rq-q"><span class="rq-num">2</span><span class="rq-text">Why does <code>serve.sh</code> sometimes refuse to serve, and what has to be true for it to pass?</span></div>
    <div class="rq-q"><span class="rq-num">3</span><span class="rq-text">How does <code>verify.sh</code> prove the page is really rendering, not just that a server responded?</span></div>
  </div>
</div>

<div class="chip-row"><span class="topic-chip">init.sh</span><span class="topic-chip">serve.sh</span><span class="topic-chip">lint.sh</span><span class="topic-chip">verify.sh</span><span class="topic-chip">headless-chrome</span></div>

<div class="section-head bookend" data-nav="Overview" data-nav-icon="compass" id="overview">
  <span class="icon-chip lg"><i data-lucide="compass"></i></span>
  <div class="sh-text">
    <span class="sh-kicker">Start here</span>
    <div class="sh-title">How a Markdown file becomes a verified local URL</div>
  </div>
</div>

This page describes the exact mechanism it went through to reach your browser. `ps-commu-explain` is always served through `scripts/serve.sh` — never an ad-hoc server (F1) — and its default look is the infographic tier: run `init.sh <slug>` with no `--tier` flag and you get a cream, Markdown-driven explainer rendered by cherry-markdown, draw.io and Lucide (F2). Nothing below is invented: every fact traces to a real line in `SKILL.md` or `scripts/`, and every one of them is listed in the Receipts footer.

<div class="section-head" data-nav="Mechanism" data-nav-icon="git-branch" id="mechanism">
  <span class="icon-chip lg"><i data-lucide="git-branch"></i></span>
  <div class="sh-text">
    <span class="sh-kicker">1 · how it works</span>
    <div class="sh-title">Two scripts, one lifecycle</div>
  </div>
</div>

`init.sh` first rejects any slug that isn't kebab-case (F3), then scaffolds a fresh workspace: the authoring-chain docs — `00-brief.md`, `01-facts.md`, `02-storyboard.md` — land in the workspace root, sibling to `app/`, so they are never served to a reader (F4). It also probes ports 7700–7799 with `lsof` for an advisory candidate (F5), and only sweeps a workspace that has sat idle more than 3 days *and* has no live, marker-verified server (F7). `serve.sh` then takes over: it runs the lint gate detailed in Claims below, and its own bind attempt is the one that actually matters — on failure it walks forward to the next port, up to 7799 (F6).

```drawio
<mxGraphModel dx="800" dy="600" grid="1" gridSize="10" guides="1" tooltips="1"
    connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1400"
    pageHeight="400" math="0" shadow="0">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="A" value="init.sh" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="40" y="140" width="160" height="60" as="geometry" />
    </mxCell>
    <mxCell id="B" value="00-brief / 01-facts / 02-storyboard + app/"
        style="rounded=1;whiteSpace=wrap;html=1;role=accent;" vertex="1" parent="1">
      <mxGeometry x="240" y="140" width="200" height="60" as="geometry" />
    </mxCell>
    <mxCell id="C" value="serve.sh" style="rounded=1;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="480" y="140" width="160" height="60" as="geometry" />
    </mxCell>
    <mxCell id="D" value="lint clean?" style="rhombus;whiteSpace=wrap;html=1;role=accent;"
        vertex="1" parent="1">
      <mxGeometry x="680" y="130" width="140" height="80" as="geometry" />
    </mxCell>
    <mxCell id="E" value="live at 127.0.0.1:PORT"
        style="rounded=1;whiteSpace=wrap;html=1;role=check;" vertex="1" parent="1">
      <mxGeometry x="860" y="140" width="200" height="60" as="geometry" />
    </mxCell>
    <mxCell id="F" value="6 PASS/FAIL/SKIP asserts"
        style="rounded=1;whiteSpace=wrap;html=1;role=check;" vertex="1" parent="1">
      <mxGeometry x="1100" y="140" width="220" height="60" as="geometry" />
    </mxCell>
    <mxCell id="e1" value="scaffold workspace + advisory port" style="html=1;"
        edge="1" parent="1" source="A" target="B">
      <mxGeometry relative="1" as="geometry">
        <mxPoint x="0" y="-24" as="offset" />
      </mxGeometry>
    </mxCell>
    <mxCell id="e2" value="author edits content.md" style="html=1;" edge="1" parent="1"
        source="B" target="C">
      <mxGeometry relative="1" as="geometry">
        <mxPoint x="0" y="-24" as="offset" />
      </mxGeometry>
    </mxCell>
    <mxCell id="e3" value="run lint.sh gate" style="html=1;" edge="1" parent="1"
        source="C" target="D">
      <mxGeometry relative="1" as="geometry">
        <mxPoint x="0" y="-24" as="offset" />
      </mxGeometry>
    </mxCell>
    <mxCell id="e4" value="no: exit 1" style="html=1;role=pitfall;" edge="1" parent="1"
        source="D" target="B">
      <mxGeometry relative="1" as="geometry">
        <Array as="points"><mxPoint x="750" y="60" /></Array>
      </mxGeometry>
    </mxCell>
    <mxCell id="e5" value="yes: bind 127.0.0.1 + watchdog" style="html=1;role=check;"
        edge="1" parent="1" source="D" target="E">
      <mxGeometry relative="1" as="geometry">
        <mxPoint x="0" y="-24" as="offset" />
      </mxGeometry>
    </mxCell>
    <mxCell id="e6" value="verify.sh: headless Chrome" style="html=1;" edge="1" parent="1"
        source="E" target="F">
      <mxGeometry relative="1" as="geometry">
        <mxPoint x="0" y="-24" as="offset" />
      </mxGeometry>
    </mxCell>
  </root>
</mxGraphModel>
```

<div class="schematic">/tmp/ps-commu/&lt;slug&gt;/
├── meta.json           ← slug, tier, port, pid, started_at
├── 00-brief.md         ← 3 reader questions + section budget
├── 01-facts.md         ← F&lt;n&gt; rows, source = path:line
├── 02-storyboard.md    ← section → question → facts
├── server.log
└── app/                ← the ONLY served directory (docroot)
    ├── content.md
    ├── index.html
    ├── explainer.css
    └── components.md</div>

<div class="section-head" data-nav="Worked example" data-nav-icon="flask-conical" id="workedexample">
  <span class="icon-chip lg"><i data-lucide="flask-conical"></i></span>
  <div class="sh-text">
    <span class="sh-kicker">2 · make it concrete</span>
    <div class="sh-title">The lint gate and the render gate, run for real</div>
  </div>
</div>

<div class="worked-example">
  <div class="we-label"><i data-lucide="flask-conical"></i> Worked example — the lint gate</div>
  <div class="we-flow">
    <div class="we-stage"><span class="we-stage-k">Input</span><div class="we-stage-v">scripts/serve.sh how-serve-works</div></div>
    <i class="we-arrow" data-lucide="arrow-right"></i>
    <div class="we-stage"><span class="we-stage-k">Mechanism</span><div class="we-stage-v">scripts/lint.sh authoring-chain gate</div></div>
    <i class="we-arrow" data-lucide="arrow-right"></i>
    <div class="we-stage"><span class="we-stage-k">Output</span><div class="we-stage-v">exit 1 + defect lines, or a live URL</div></div>
  </div>
  <p>Point <code>serve.sh</code> at a workspace whose <code>00-brief.md</code> still has an unfilled <code>Q1: (...)</code> and it refuses before a single byte is served by default. There is a documented escape hatch — <code>--no-lint</code>, meant for the html/react tiers' dev loops, not for skipping this check — but using it prints a visible warning; it is not a silent bypass (F8).</p>
</div>

<div class="worked-example">
  <div class="we-label"><i data-lucide="flask-conical"></i> Worked example — the render gate</div>
  <div class="we-flow">
    <div class="we-stage"><span class="we-stage-k">Input</span><div class="we-stage-v">scripts/verify.sh how-serve-works</div></div>
    <i class="we-arrow" data-lucide="arrow-right"></i>
    <div class="we-stage"><span class="we-stage-k">Mechanism</span><div class="we-stage-v">headless Chrome --dump-dom, 6 asserts</div></div>
    <i class="we-arrow" data-lucide="arrow-right"></i>
    <div class="we-stage"><span class="we-stage-k">Output</span><div class="we-stage-v">one PASS/FAIL/SKIP line per assert</div></div>
  </div>
  <p>Assert 1 counts rendered draw.io diagrams against the fenced <code>drawio</code> blocks in this very doc (F13); without Chrome the run still exits 2 for asserts 1&ndash;5, but assert 6's static <code>scroll-behavior</code> check needs no browser and can still fail the run (F15).</p>
</div>

<div class="section-head" data-nav="Claims" data-nav-icon="badge-check" id="claims">
  <span class="icon-chip lg"><i data-lucide="badge-check"></i></span>
  <div class="sh-text">
    <span class="sh-kicker">3 · back it with a citation</span>
    <div class="sh-title">What the gates actually check</div>
  </div>
</div>

<div class="claim-card">
  <div class="claim-text">serve.sh refuses to serve a workspace until its authoring chain (00-brief.md, 01-facts.md, 02-storyboard.md) passes scripts/lint.sh.</div>
  <div class="claim-meta"><span class="claim-fact">F8</span><span class="claim-source">scripts/serve.sh:44</span></div>
  <div class="claim-check"><i data-lucide="search"></i> Check it: run <code>grep -n "lint failed for" scripts/serve.sh</code></div>
</div>

<div class="claim-card">
  <div class="claim-text">Every server serve.sh starts binds 127.0.0.1 only — never an interface reachable off the machine.</div>
  <div class="claim-meta"><span class="claim-fact">F9</span><span class="claim-source">scripts/serve.sh:12</span></div>
  <div class="claim-check"><i data-lucide="search"></i> Check it: run <code>grep -n "bind 127.0.0.1" scripts/serve.sh</code></div>
</div>

<div class="claim-card">
  <div class="claim-text">A live server is only ever killed if its own process command line contains the workspace path — never an unverified PID.</div>
  <div class="claim-meta"><span class="claim-fact">F10</span><span class="claim-source">scripts/common.sh:13</span></div>
  <div class="claim-check"><i data-lucide="search"></i> Check it: run <code>grep -n pid_has_marker -A4 scripts/common.sh</code></div>
</div>

<div class="claim-card">
  <div class="claim-text">lint.sh rejects five exact stale-CSS class names, plus any class prefixed cat-, in app/content.md.</div>
  <div class="claim-meta"><span class="claim-fact">F16</span><span class="claim-source">scripts/lint.sh:186</span></div>
  <div class="claim-check"><i data-lucide="search"></i> Check it: run <code>grep -n forbidden_exact scripts/lint.sh</code></div>
</div>

<div class="claim-card">
  <div class="claim-text">Every unlabeled draw.io edge in app/content.md is reported as its own lint defect, not just the first one found.</div>
  <div class="claim-meta"><span class="claim-fact">F17</span><span class="claim-source">scripts/lint.sh:314</span></div>
  <div class="claim-check"><i data-lucide="search"></i> Check it: run <code>grep -n "has no label" scripts/lint.sh</code></div>
</div>

<div class="claim-card">
  <div class="claim-text">A single draw.io diagram may declare at most 7 vertex cells — the diagram in the Mechanism section above stops at 6 for exactly this reason.</div>
  <div class="claim-meta"><span class="claim-fact">F18</span><span class="claim-source">scripts/lint.sh:359</span></div>
  <div class="claim-check"><i data-lucide="search"></i> Check it: run <code>grep -n DRAWIO_MAX_VERTICES scripts/lint.sh</code></div>
</div>

<div class="section-head" data-nav="Wrong, without this" data-nav-icon="triangle-alert" id="wrongwithout">
  <span class="icon-chip lg"><i data-lucide="triangle-alert"></i></span>
  <div class="sh-text">
    <span class="sh-kicker">4 · name the failure mode</span>
    <div class="sh-title">What breaks if these gates are skipped</div>
  </div>
</div>

<div class="wrong-without">
  <span class="ww-ico"><i data-lucide="triangle-alert"></i></span>
  <div class="ww-body">
    <div class="ww-title">Wrong, without the lint gate</div>
    <p>Skip scripts/lint.sh and a page with an invented fact that cites nothing real, or a diagram full of unlabeled arrows, ships anyway — the exact hallucination-and-mystery-diagram failure mode the whole authoring chain exists to catch before a reader ever sees it.</p>
  </div>
</div>

<div class="wrong-without">
  <span class="ww-ico"><i data-lucide="triangle-alert"></i></span>
  <div class="ww-body">
    <div class="ww-title">Wrong, without the marker check</div>
    <p>A bare <code>kill $pid</code> on an unverified PID can kill an unrelated process that happened to reuse that PID after the original server exited. pid_has_marker checks the live process's own command line for the workspace path first, so a stale or recycled PID is never touched.</p>
  </div>
</div>

<div class="section-head" data-nav="Before / after" data-nav-icon="columns-2" id="beforeafter">
  <span class="icon-chip lg"><i data-lucide="columns-2"></i></span>
  <div class="sh-text">
    <span class="sh-kicker">5 · prove the improvement</span>
    <div class="sh-title">An ad-hoc server vs. serve.sh</div>
  </div>
</div>

<div class="before-after">
  <div class="ba-panel">
    <span class="ba-label">Before</span>
    <div class="ba-value">python -m http.server</div>
    <p>Hand-started, by habit. Binds every interface, has no scoped docroot, and never stops on its own — it exposes all of /tmp on the network, forever, until someone remembers to kill it.</p>
  </div>
  <i class="ba-arrow" data-lucide="arrow-right"></i>
  <div class="ba-panel">
    <span class="ba-label">After</span>
    <div class="ba-value">scripts/serve.sh</div>
    <p>Binds 127.0.0.1 only, serves just the workspace's app/ directory, and self-destructs after its keep-alive TTL — 24h by default.</p>
  </div>
</div>

That's the difference between an ad-hoc server (F19) and the one this skill mandates (F1): loopback-only binding (F9) with a watchdog that eventually cleans up after itself (F11).

<div class="section-head bookend" data-nav="Receipts" data-nav-icon="receipt" id="receipts">
  <span class="icon-chip lg"><i data-lucide="receipt"></i></span>
  <div class="sh-text">
    <span class="sh-kicker">6 · close the chain</span>
    <div class="sh-title">Every citation on this page</div>
  </div>
</div>

<div class="receipts">
  <div class="receipts-label"><i data-lucide="receipt"></i> Receipts</div>
  <ul class="receipts-list">
    <li><span class="receipts-fact">F1</span> SKILL.md:8 — always serve via scripts/serve.sh</li>
    <li><span class="receipts-fact">F2</span> SKILL.md:18 — infographic is the default tier</li>
    <li><span class="receipts-fact">F3</span> scripts/init.sh:39 — kebab-case slug validation</li>
    <li><span class="receipts-fact">F4</span> scripts/init.sh:82 — authoring docs never served</li>
    <li><span class="receipts-fact">F5</span> scripts/init.sh:100 — advisory port probe, 7700-7799</li>
    <li><span class="receipts-fact">F6</span> scripts/serve.sh:14 — the real bind is authoritative</li>
    <li><span class="receipts-fact">F7</span> scripts/init.sh:59 — 3-day sweep, live servers spared</li>
    <li><span class="receipts-fact">F8</span> scripts/serve.sh:44 — lint gate refusal</li>
    <li><span class="receipts-fact">F9</span> scripts/serve.sh:12 — loopback-only bind</li>
    <li><span class="receipts-fact">F10</span> scripts/common.sh:13 — marker-verified kill</li>
    <li><span class="receipts-fact">F11</span> scripts/serve.sh:136 — self-destruct watchdog</li>
    <li><span class="receipts-fact">F12</span> scripts/verify.sh:4 — headless Chrome dump-dom</li>
    <li><span class="receipts-fact">F13</span> scripts/verify.sh:337 — draw.io diagram-count assert</li>
    <li><span class="receipts-fact">F14</span> scripts/verify.sh:98 — scroll-behavior regression gate</li>
    <li><span class="receipts-fact">F15</span> scripts/verify.sh:135 — no-Chrome exit 2 for asserts 1-5, assert 6 still runs</li>
    <li><span class="receipts-fact">F16</span> scripts/lint.sh:186 — forbidden CSS classes</li>
    <li><span class="receipts-fact">F17</span> scripts/lint.sh:314 — unlabeled edge, per-edge defect</li>
    <li><span class="receipts-fact">F18</span> scripts/lint.sh:359 — 7-vertex diagram cap</li>
    <li><span class="receipts-fact">F19</span> SKILL.md:103 — the ad-hoc server it replaced</li>
  </ul>
</div>

::: callout check
Every claim above cites a real line in this skill's own source. Run the `grep` in any "Check it" line yourself — that's the point of the chain.
:::

<details>
<summary>Why doesn't this page just say "trust me"?</summary>

Because the whole point of the authoring chain — `00-brief.md` → `01-facts.md` → `02-storyboard.md` → `app/content.md` — is that nothing enters a page unless it traces to a real fact first. This page is the chain explaining itself, which only works if it holds itself to its own rule.

</details>
