/* ============================================================================
   cherry-setup.js — ENGINE + DIAGRAMS + TERSE AUTHORING
   ----------------------------------------------------------------------------
   - Instantiates cherry-markdown in preview-only / no-toolbar mode.
   - Wires Mermaid via PATH B (post-render): cherry renders ```mermaid fences as
     normal <pre><code class="language-mermaid"> blocks, then we hand those nodes
     to mermaid.run(). This mirrors spec-style.html exactly and keeps FULL
     control of the diagram frame styling and the locked dark theme.
     PATH A (cherry's bundled mermaid addon) is deliberately NOT used, and this
     is WHY shell.html loads the *core* build (cherry-markdown.core.js) rather
     than the full cherry-markdown.min.js: the full build auto-registers that
     addon with a HARDCODED light `theme:"default"` that cannot be overridden
     via instance config, and it consumes the fences into <figure><svg> before
     we ever see them. The core build ships no addon, so fences survive as
     language-mermaid code blocks for Path B to frame + theme. Verified in a
     real browser: Path B nodes fill with the locked light node colors below
     (default #ffffff, one structural accent stroke), on the cream diagram frame.
   - Adds ONE custom syntax hook (`::: callout <kind>`) because a fenced callout
     shorthand is meaningfully terser than hand-writing <div class="callout ...">.
     Everything else (tiles, schematic, rows, hero) maps cleanly to plain
     HTML-in-markdown, so per YAGNI we add no further hooks.

   CHERRY GLOBAL SHAPE (0.8.58 UMD): `window.Cherry` is an ESM-interop *namespace*
   object, NOT the constructor. The real constructor and all statics
   (createSyntaxHook, constants) live on `window.Cherry.default`. We resolve that
   once in resolveCherry() and use the resolved constructor everywhere.

   COLOR RULE (theme.css): a neutral cream ramp, ONE structural accent, and two
   reserved hues (pitfall, check) that mean something. Diagrams follow it: every
   node/actor is cream with the accent stroke; only `class N pitfall` /
   `class N check` may recolor a node. No per-node rainbow. Raw hex here is
   intentional and permitted: Mermaid reads a JS object, not CSS custom
   properties — each key is annotated with the theme.css token it mirrors.
   ============================================================================ */

/* ---- Mermaid theme — MIRRORS theme.css tokens ------------------------------
   Mermaid reads a JS object, not CSS custom properties, so these must be raw
   hex/rgba here. Each key is annotated with the theme.css token it mirrors so
   any drift is caught in review. Palette = "Cream Infographic" — light cream/
   white diagram background, dark readable node text, warm styled edges. The
   per-node vivid category colors come from `classDef` lines authored in the
   markdown (see CLASSDEF_PRELUDE below), which reference these same hues. */
const MERMAID_THEME_VARIABLES = {
  background: "#f7f1e6", // --surface (card cream)
  primaryColor: "#fcf8f0", // --n-4 (cleanest surface — default node fill)
  primaryTextColor: "#211c15", // --text (warm near-black — readable on light)
  primaryBorderColor: "#1c4f8f", // --accent (the one structural hue)
  lineColor: "#6b6152", // --text-3 (edge lines, ≥4.5:1 on paper)
  secondaryColor: "#f7f1e6", // --surface
  tertiaryColor: "#efe6d3", // --bg (cream paper)
  tertiaryBorderColor: "#e6dcc7", // --border
  clusterBkg: "#e9dfca", // --n-1 (cream shade — subgraph background)
  clusterBorder: "#d9ccb2", // --border-strong
  titleColor: "#211c15", // --text
  actorBkg: "#fcf8f0", // --n-4 (sequence actor fill)
  actorBorder: "#1c4f8f", // --accent
  actorTextColor: "#211c15", // --text
  signalColor: "#6b6152", // --text-3 (signal lines)
  signalTextColor: "#211c15", // --text (signal labels must read at 14px)
  noteBkgColor: "#e2ebfb", // --accent-tint (note fill)
  noteBorderColor: "#1c4f8f", // --accent
  noteTextColor: "#211c15", // --text
  fontSize: "14px",
};

/* ---- classDef prelude — the two reserved hues, nothing else --------------
   Injected into every flowchart/graph/state diagram that doesn't already carry
   classDefs. Nodes are cream + accent stroke by default; an author may mark a
   node `class N pitfall` (the thing that goes wrong) or `class N check` (the
   verified outcome). Mirrors theme.css: pitfall #a8321f/#fbeae5 ·
   check #186a42/#daf1ec · accent #1c4f8f/#e2ebfb · text #211c15. */
const CLASSDEF_PRELUDE = [
  "classDef accent  fill:#e2ebfb,stroke:#1c4f8f,stroke-width:2px,color:#211c15;",
  "classDef pitfall fill:#fbeae5,stroke:#a8321f,stroke-width:2px,color:#211c15;",
  "classDef check   fill:#daf1ec,stroke:#186a42,stroke-width:2px,color:#211c15;",
].join("\n");

/* ---- Lucide icon names per callout kind (rendered into a colored chip) ---- */
const CALLOUT_ICONS = {
  note: "info",
  pitfall: "triangle-alert",
  check: "circle-check",
};

/* ---- resolve the real Cherry constructor from the UMD namespace ----------- */
function resolveCherry() {
  const ns = window.Cherry;
  const Ctor = ns && ns.default ? ns.default : ns;
  if (typeof Ctor !== "function") {
    throw new Error("cherry-setup: Cherry constructor not found on window.Cherry(.default)");
  }
  return Ctor;
}

/* ---- mermaid source detection (Cherry 0.8.58 does not tag fences with a
   language-mermaid class, so we detect by content) -------------------------- */
const MERMAID_HEAD = /^(flowchart|graph|sequenceDiagram|stateDiagram(-v2)?|classDiagram|erDiagram|gantt|pie|journey|mindmap|timeline|gitGraph|quadrantChart|requirementDiagram|C4Context)\b/;

/* ---- custom syntax hook: ::: callout <kind> ... :::  ----------------------
   Authors write:
       ::: callout pitfall
       **Heads up.** Body text, *markdown* allowed.
       :::
   which expands to <div class="callout pitfall"> … the same structure
   explainer.css styles. Kinds: note | pitfall | check. Anything else
   (including no kind) falls back to note.

   The body is rendered with the inline parser Cherry passes in
   (`sentenceMakeFunc`) and the whole block is returned through `pushCache`
   with `needCache: true`. We must NOT call `this.$engine.makeHtml(body)`
   re-entrantly: that shares the engine's inline-code cache pool with the
   outer pass, so a `~~CODE<hash>$` placeholder from an unrelated inline
   `code` span downstream would leak into the output unresolved. Verified in
   the browser: the re-entrant version leaked, this one does not. ----------- */
function registerCalloutHook(Cherry) {
  const KINDS = ["note", "pitfall", "check"];
  const CalloutHook = Cherry.createSyntaxHook(
    "explainerCallout",
    Cherry.constants.HOOKS_TYPE_LIST.PAR,
    {
      needCache: true,
      makeHtml(str, sentenceMakeFunc) {
        return str.replace(this.RULE.reg, (whole, kind, body) => {
          const raw = (kind || "").trim();
          const k = KINDS.includes(raw) ? raw : "note";
          const cls = ` ${k}`;
          const lines = this.getLineCount(whole);
          const { sign, html } = sentenceMakeFunc(body.trim());
          // A colored icon chip (populated with a Lucide SVG in post-render via
          // data-ico) plus the rendered body in its own column.
          const result =
            `<div data-sign="${sign}" data-lines="${lines}" class="callout${cls}">` +
            `<span class="co-ico" data-ico="${k}"></span>` +
            `<div class="co-body">${html}</div>` +
            `</div>`;
          return this.pushCache(result, sign, lines);
        });
      },
      rule() {
        // ::: callout <kind>\n <body> \n:::
        return {
          reg: /^[ \t]*:::[ \t]+callout[ \t]*([a-z]*)[ \t]*\n([\s\S]*?)\n[ \t]*:::[ \t]*$/gm,
        };
      },
    }
  );
  return CalloutHook;
}

/* ---- wrap each rendered mermaid code block in a themed frame --------------
   Returns the mermaid.run() promise (or a resolved promise if nothing to run)
   so the caller can await diagrams before revealing the page. */
function frameAndRunMermaid(rootEl) {
  if (typeof mermaid === "undefined") return Promise.resolve();

  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "loose",
    theme: "base",
    themeVariables: MERMAID_THEME_VARIABLES,
    flowchart: { curve: "basis", useMaxWidth: true },
    sequence: { useMaxWidth: true },
  });

  // The core build emits fenced mermaid as <pre><code class="language-mermaid">.
  // We match that primarily, and also fall back to content-sniffing any code
  // block whose text starts with a mermaid diagram keyword — so the frame still
  // works even if a future build labels fences differently.
  const candidates = rootEl.querySelectorAll(
    "code.language-mermaid, pre.language-mermaid, .mermaid, pre code"
  );

  const seen = new Set();
  const targets = [];
  candidates.forEach((node) => {
    const source = (node.textContent || "").trim();
    if (!source || seen.has(node)) return;
    const isLabelled =
      node.classList.contains("language-mermaid") ||
      node.classList.contains("mermaid");
    if (!isLabelled && !MERMAID_HEAD.test(source)) return;
    seen.add(node);

    const pre = node.tagName === "CODE" ? node.closest("pre") : node;

    // Give node-based diagrams the reserved-hue classDefs for free (only if
    // the author didn't already define their own). Sequence diagrams don't use
    // classDef, so skip them.
    let src = source;
    const isNodeDiagram = /^(flowchart|graph|stateDiagram)/.test(src);
    if (isNodeDiagram && !/classDef\s/.test(src)) {
      src = src + "\n" + CLASSDEF_PRELUDE;
    }

    const frame = document.createElement("div");
    frame.className = "mermaid-frame is-pending";
    const holder = document.createElement("div");
    holder.className = "mermaid";
    holder.textContent = src;
    frame.appendChild(holder);

    if (pre && pre.parentNode) {
      pre.parentNode.replaceChild(frame, pre);
    } else if (node.parentNode) {
      node.parentNode.replaceChild(frame, node);
    }
    targets.push({ holder, frame });
  });

  if (!targets.length) return Promise.resolve();

  // mermaid.run renders its own inline error per-diagram on bad syntax, so a
  // single malformed diagram never white-screens the rest of the doc.
  return mermaid
    .run({ nodes: targets.map((t) => t.holder) })
    .catch((err) => {
      console.warn("[explainer-kit] mermaid.run reported:", err);
    })
    .finally(() => {
      // fade each freshly-populated frame in so diagrams never pop in dead,
      // even though they land after the initial staggered reveal.
      targets.forEach(({ frame }) => frame.classList.remove("is-pending"));
    });
}

/* ---- populate callout icon chips + render all Lucide icons ---------------- */
function renderIcons(preview) {
  // Fill each callout's icon chip with the Lucide icon name for its kind.
  preview.querySelectorAll(".co-ico[data-ico]").forEach((chip) => {
    if (chip.querySelector("[data-lucide], svg")) return; // already populated
    const kind = chip.getAttribute("data-ico") || "";
    const name = CALLOUT_ICONS[kind] || CALLOUT_ICONS.note;
    const i = document.createElement("i");
    i.setAttribute("data-lucide", name);
    chip.appendChild(i);
  });
  // Turn every <i data-lucide="…"> in the doc into an inline SVG. Guarded so
  // the page still renders (sans icons) if the Lucide CDN failed to load.
  if (window.lucide && typeof window.lucide.createIcons === "function") {
    window.lucide.createIcons({ attrs: { class: "lucide" } });
  }
}

/* ---- build the sticky navigation from the section headers -----------------
   Reads every `.section-head[data-nav]` (and the hero) to construct the left
   sidebar / top strip. Each nav item carries the section's Lucide icon (one
   accent hue for all — section order is never colored). Returns the list of {id, el} section targets for scrollspy. */
function buildNav(preview) {
  const heads = Array.from(preview.querySelectorAll(".section-head[data-nav]"));
  if (!heads.length) return [];

  const nav = document.createElement("nav");
  nav.className = "explainer-nav";
  nav.setAttribute("aria-label", "Document sections");

  // brand row (reads optional data-* on the hero)
  const hero = preview.querySelector(".hero");
  const brandTitle = (hero && hero.getAttribute("data-nav-title")) || "Explainer";
  const brandSub = (hero && hero.getAttribute("data-nav-sub")) || "contents";
  nav.innerHTML =
    '<div class="nav-brand">' +
    '<span class="icon-chip sm"><i data-lucide="sparkles"></i></span>' +
    '<div><div class="nav-title">' + brandTitle + "</div>" +
    '<div class="nav-sub">' + brandSub + "</div></div></div>" +
    '<div class="nav-kicker">On this page</div>';

  const ul = document.createElement("ul");
  const targets = [];
  heads.forEach((head, idx) => {
    const icon = head.getAttribute("data-nav-icon") || head.getAttribute("data-icon") || "hash";
    const label = head.getAttribute("data-nav") || "Section";
    const bookend = head.classList.contains("bookend");
    const id = head.id || "sec-" + idx;
    head.id = id;

    const li = document.createElement("li");
    const a = document.createElement("a");
    a.className = "nav-link" + (bookend ? " is-bookend" : "");
    a.href = "#" + id;
    a.setAttribute("data-target", id);
    a.innerHTML =
      '<span class="nav-ico"><i data-lucide="' + icon + '"></i></span>' +
      '<span class="nav-label">' + label + "</span>";
    li.appendChild(a);
    ul.appendChild(li);
    targets.push({ id, el: head, link: a });
  });
  nav.appendChild(ul);

  // Click-to-jump. ROOT CAUSE of the old "hash lands, page doesn't move" bug:
  // explainer.css set `html { scroll-behavior: smooth }`, which turns
  // window.scrollTo(0, y) into a compositor animation. That animation only
  // advances while the tab paints — in a hidden/occluded tab (and every
  // headless or extension-driven audit) it never starts, so replaceState landed
  // and the viewport stayed at 0. Fix by construction: an explicit INSTANT
  // scrollIntoView (overrides any CSS scroll-behavior), the target re-resolved
  // at click time (Cherry may have re-rendered the DOM since nav build), and
  // the active class set here — not only by the scroll observer.
  nav.addEventListener("click", (e) => {
    const link = e.target.closest(".nav-link");
    if (!link) return;
    const id = link.getAttribute("data-target");
    const el = document.getElementById(id);
    if (!el) return;
    e.preventDefault();
    el.scrollIntoView({ block: "start", behavior: "instant" });
    history.replaceState(null, "", "#" + id);
    nav.querySelectorAll(".nav-link").forEach((a) => a.classList.toggle("is-active", a === link));
  });

  document.body.classList.add("has-nav");
  document.body.insertBefore(nav, document.body.firstChild);
  return targets;
}

/* ---- scrollspy — highlight the nav item for the section in view -----------
   Uses an IntersectionObserver purely as a cheap "something scrolled" trigger,
   then recomputes the active section by geometry: the active section is the
   LAST one whose header top has crossed a line ~26% down the viewport. This is
   robust to the long gaps between headers (a thin observer band would flicker
   or lag), yet stays dependency-light and only recomputes on intersection. */
function wireScrollspy(targets) {
  if (!targets.length) return;
  let activeId = null;
  const setActive = (id) => {
    if (id === activeId) return;
    activeId = id;
    targets.forEach((t) => t.link.classList.toggle("is-active", t.id === id));
    const active = targets.find((t) => t.id === id);
    if (active) active.link.scrollIntoView({ block: "nearest", inline: "nearest" });
  };
  const recompute = () => {
    const line = window.innerHeight * 0.26;
    let current = targets[0].id;
    for (const t of targets) {
      if (t.el.getBoundingClientRect().top <= line) current = t.id;
      else break;
    }
    setActive(current);
  };

  if (typeof IntersectionObserver !== "undefined") {
    // Fire recompute whenever any header enters/leaves a wide band; the band is
    // wide so transitions are caught early, and recompute (not the entries)
    // decides the winner — so no lag/flicker in the gaps between sections.
    const io = new IntersectionObserver(recompute, {
      rootMargin: "0px 0px -60% 0px",
      threshold: [0, 1],
    });
    targets.forEach((t) => io.observe(t.el));
  }
  // A passive scroll listener keeps the highlight exact between IO callbacks.
  window.addEventListener("scroll", recompute, { passive: true });
  window.addEventListener("resize", recompute, { passive: true });
  recompute();
}

/* ---- post-render pipeline: theme class + mermaid + icons + nav + reveal ----
   Runs manually after construction because callback.afterInit does NOT fire in
   previewOnly mode in Cherry 0.8.58. We locate the mounted preview surface,
   tag it with the theme class, frame + run mermaid, render icons, build the
   sticky nav + scrollspy, THEN reveal. */
function runPostRender(container) {
  const preview =
    container.querySelector(".cherry-previewer") ||
    container.querySelector(".cherry-markdown") ||
    container;
  // ensure our theme class is present on the preview surface
  preview.classList.add("cherry-markdown", "theme__explainer");

  // icons + navigation are independent of mermaid and safe to run immediately.
  renderIcons(preview);
  const targets = buildNav(preview);
  wireScrollspy(targets);

  // await diagrams so the framed SVGs are populated when the stagger plays,
  // instead of animating empty <pre>s that then snap to SVG.
  // Reveal AFTER diagrams resolve so framed SVGs are populated when the stagger
  // plays. The mermaid promise is a real async boundary, so a plain microtask
  // (not requestAnimationFrame) is enough — and rAF can be starved when the tab
  // isn't painting, which would leave the page permanently pre-reveal.
  Promise.resolve(frameAndRunMermaid(preview)).finally(() => {
    // mermaid may inject <i data-lucide> inside labels? no — but re-run icons in
    // case any deferred content landed after the first pass. Cheap + idempotent.
    renderIcons(preview);
    preview.classList.add("is-ready");
  });
}

/* ---- public: render markdown text into a container ------------------------ */
/* eslint-disable-next-line no-unused-vars */
function renderExplainer(containerId, markdownText) {
  const container = document.getElementById(containerId);
  if (!container) throw new Error(`renderExplainer: #${containerId} not found`);

  const Cherry = resolveCherry();
  const calloutHook = registerCalloutHook(Cherry);

  // eslint-disable-next-line no-new
  new Cherry({
    id: containerId,
    value: markdownText,
    locale: "en_US", // English UI (TOC title etc.) — Cherry defaults to zh_CN
    editor: {
      defaultModel: "previewOnly", // preview-only, no editor pane
      keepDocumentScrollAfterInit: true,
    },
    toolbars: {
      toolbar: false,
      toolbarRight: [], // NOT `false` — `false` crashes the 0.8.58 constructor
      bubble: false,
      float: false,
      sidebar: false,
    },
    engine: {
      global: { flowSessionContext: false },
      // Cherry reads custom hooks from engine.customSyntax DIRECTLY (not
      // engine.syntax.customSyntax). Nested under syntax → silently ignored.
      customSyntax: {
        explainerCallout: {
          syntaxClass: calloutHook,
          before: "br",
        },
      },
    },
  });

  // afterInit does not fire in previewOnly; run the post-render step ourselves.
  // The preview DOM is mounted synchronously by the constructor above.
  runPostRender(container);
}

// expose for shell.html
window.renderExplainer = renderExplainer;
