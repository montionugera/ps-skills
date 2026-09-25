/* ============================================================================
   cherry-setup.js — ENGINE + DIAGRAMS + TERSE AUTHORING
   ----------------------------------------------------------------------------
   - Instantiates cherry-markdown in preview-only / no-toolbar mode.
   - Wires draw.io via PATH B (post-render): cherry renders ```drawio fences as
     normal <pre><code class="language-drawio"> blocks, then we hand those nodes
     to draw.io's static viewer (`GraphViewer.processElements()`). Authors write
     plain mxGraph XML with `role=accent`/`role=pitfall`/`role=check` tokens
     inside a vertex/edge's `style="..."` attribute (mxGraph ignores unknown
     style keys, so this is inert until we substitute it below); we read the
     real hex straight off the page's own CSS custom properties (theme.css is
     the single source of truth — no duplicated hex here) and swap the token
     for `strokeColor=<hex>` before injecting the XML into a `data-mxgraph`
     div. `viewer-static.min.js`'s own bootstrap only scans `.mxgraph` elements
     present in the DOM at the moment the script itself finishes loading (read
     from its source: a single `GraphViewer.processElements()` IIFE call, no
     MutationObserver) — divs built here, after Cherry's async render, would
     stay inert without the explicit `GraphViewer.processElements()` call this
     file makes once they're inserted.
   - Adds ONE custom syntax hook (`::: callout <kind>`) because a fenced callout
     shorthand is meaningfully terser than hand-writing <div class="callout ...">.
     Everything else (reader-questions, claim-card, before-after, worked-example,
     wrong-without, receipts, schematic, rows) maps cleanly to plain
     HTML-in-markdown, so per YAGNI we add no further hooks.

   CHERRY GLOBAL SHAPE (0.8.58 UMD): `window.Cherry` is an ESM-interop *namespace*
   object, NOT the constructor. The real constructor and all statics
   (createSyntaxHook, constants) live on `window.Cherry.default`. We resolve that
   once in resolveCherry() and use the resolved constructor everywhere.

   COLOR RULE (theme.css): a neutral cream ramp, ONE structural accent, and two
   reserved hues (pitfall, check) that mean something. Diagrams follow it: every
   node/actor defaults to draw.io's own white/black look unless the author
   opts a vertex/edge into `role=accent` / `role=pitfall` / `role=check`, which
   recolors its stroke to the matching theme hue. No per-node rainbow.
   ============================================================================ */

/* ---- role-token substitution — reads theme.css's OWN computed hex ---------
   Unlike Mermaid (which read a JS object, forcing raw hex duplicated from
   theme.css), draw.io's mxGraph style strings are plain key=value text and we
   run in the same page as theme.css, so we read the real, live values off
   :root at render time instead of hardcoding them here — zero drift risk. */
function readRoleColors() {
  const cs = getComputedStyle(document.documentElement);
  return {
    accent: cs.getPropertyValue("--accent").trim(),
    pitfall: cs.getPropertyValue("--pitfall").trim(),
    check: cs.getPropertyValue("--check").trim(),
  };
}

/* ---- substitute role=<kind> tokens inside style="..."/'...' attributes ----
   mxGraph has no `role` style key, so it's inert until we turn it into a real
   `strokeColor=#hex` — the same border-only recoloring Mermaid's
   primaryBorderColor/actorBorder/noteBorderColor all used for --accent above,
   now generalized to draw.io's plain-text style syntax. Works uniformly on
   both vertex and edge styles (edges have no fillColor concept). The
   attribute regex accepts EITHER quote character (XML permits both, and
   hand-authored XML is exactly where a single-quoted style="'..'" shows up)
   via a backreference so the same quote closes what it opened. A console.warn
   fires if a role= token survives — a typo, an unsupported quote/compression
   shape, or a missing CSS var all fail SILENTLY otherwise (mxGraph just
   ignores the unknown key), which is exactly the kind of silent-pass bug the
   plan's Global Constraints call out as the thing to never repeat. */
const ROLE_KINDS = ["accent", "pitfall", "check"];
const ROLE_TOKEN = /\brole=(accent|pitfall|check)\b;?/g;
function substituteRoleTokens(xml, colors) {
  const substituted = xml.replace(/style=(["'])([^"']*)\1/g, (whole, quote, body) => {
    const swapped = body.replace(ROLE_TOKEN, (token, kind) => {
      const hex = colors[kind];
      if (!hex) {
        // Fail LOUD, not silent: leave the token in place (instead of
        // deleting it) so the failure shows up as literal `role=<kind>` text
        // in the rendered SVG label/style — never throw, a missing var must
        // not break rendering.
        console.warn(
          `[explainer-kit] role=${kind} could not be substituted: CSS custom property --${kind} is missing or empty on :root (check theme.css)`
        );
        return token;
      }
      return `strokeColor=${hex};`;
    });
    return `style=${quote}${swapped}${quote}`;
  });
  // A fresh regex here (not the shared, stateful ROLE_TOKEN above) so this
  // check never depends on ROLE_TOKEN's lastIndex bookkeeping. Widened to
  // match ANY role=<word> survivor, not just the 3 known-good kinds, so an
  // unsupported/misspelled kind (role=pitfal, role=danger, ...) — which
  // ROLE_TOKEN never matches in the first place, so it passes through the
  // replace above completely untouched — is still caught and reported
  // instead of staying silently inert. Known-kind survivors (missing CSS
  // var) are already warned above, in the substitution step itself, so skip
  // those here to avoid a duplicate warning for the same failure.
  const SURVIVOR_TOKEN = /\brole=([A-Za-z0-9_-]+)\b/g;
  let match;
  while ((match = SURVIVOR_TOKEN.exec(substituted))) {
    const kind = match[1];
    if (ROLE_KINDS.includes(kind)) continue;
    console.warn(
      `[explainer-kit] unrecognized role=${kind} token found (expected one of: ${ROLE_KINDS.join(", ")}):`,
      substituted
    );
  }
  return substituted;
}

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

/* ---- drawio source detection (content-sniff fallback for fences a future
   Cherry build might not tag with a language-drawio class) ------------------
   Deliberately narrow: ONLY the bare <mxGraphModel> root the spec's authoring
   convention actually asks for (plain, uncompressed mxGraph XML — see Task
   0's verified exemplar). Earlier drafts also matched a leading <?xml
   declaration and <mxfile>, but both are real false-positive/silent-failure
   traps in a skill whose whole job is showing worked examples: a generic
   ```xml sample starting "<?xml ...?>" would get hijacked and handed to
   GraphViewer (which writes its parse error into the frame), and draw.io's
   own compressed <mxfile> app-export format has no <style="..."> for
   substituteRoleTokens to find — role colors would silently vanish with no
   diagnostic. Neither shape is part of the supported authoring format, so
   neither is detected. */
const DRAWIO_HEAD = /^<mxGraphModel\b/;

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

/* ---- wrap each ```drawio code block in a themed frame + render it ---------
   Same call signature and return contract as the retired frameAndRunMermaid:
   returns a Promise the caller awaits before revealing the page. Every
   data-mxgraph div this builds carries "toolbar":"zoom" and "nav":1 (per the
   spec's explicit-config-key requirement — draw.io does NOT turn these on by
   default) plus "resize":1 so the frame reflows with its container. */
function frameAndRunDrawio(rootEl) {
  if (typeof GraphViewer === "undefined") return Promise.resolve();

  const colors = readRoleColors();

  // The core build emits fenced drawio as <pre><code class="language-drawio">
  // (mirrors how ```mermaid fences were matched). We match that primarily,
  // and also fall back to content-sniffing any code block whose text looks
  // like mxGraph XML — so the frame still works even if a future build
  // labels fences differently.
  const candidates = rootEl.querySelectorAll(
    "code.language-drawio, pre.language-drawio, .drawio, pre code"
  );

  const seen = new Set();
  const targets = [];
  candidates.forEach((node) => {
    const source = (node.textContent || "").trim();
    if (!source || seen.has(node)) return;
    const isLabelled =
      node.classList.contains("language-drawio") ||
      node.classList.contains("drawio");
    if (!isLabelled && !DRAWIO_HEAD.test(source)) return;
    seen.add(node);

    const pre = node.tagName === "CODE" ? node.closest("pre") : node;
    const xml = substituteRoleTokens(source, colors);

    const frame = document.createElement("div");
    frame.className = "diagram-frame is-pending";
    const holder = document.createElement("div");
    holder.className = "mxgraph";
    holder.setAttribute(
      "data-mxgraph",
      JSON.stringify({ xml, toolbar: "zoom", nav: 1, resize: 1 })
    );
    frame.appendChild(holder);

    if (pre && pre.parentNode) {
      pre.parentNode.replaceChild(frame, pre);
    } else if (node.parentNode) {
      node.parentNode.replaceChild(frame, node);
    }
    targets.push(frame);
  });

  if (!targets.length) return Promise.resolve();

  // GraphViewer's own bootstrap (read straight from viewer-static.min.js's
  // source: a single `GraphViewer.processElements()` call in an IIFE at the
  // bottom of the script, no MutationObserver) only scans .mxgraph elements
  // present in the DOM the moment the script itself finishes loading. Divs
  // built here land AFTER that — Cherry-Markdown renders content
  // asynchronously, which is this skill's real usage pattern — so without
  // this explicit call they would sit inert forever. GraphViewer catches its
  // own per-element render errors internally (never throws out to us), but
  // wrap defensively anyway so one malformed diagram never white-screens the
  // rest of the doc.
  try {
    GraphViewer.processElements();
  } catch (err) {
    console.warn("[explainer-kit] GraphViewer.processElements reported:", err);
  }

  // fade each freshly-populated frame in so diagrams never pop in dead, even
  // though they land after the initial staggered reveal.
  targets.forEach((frame) => frame.classList.remove("is-pending"));
  return Promise.resolve();
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

  // brand row (reads optional data-* on the top-of-page reader-questions box —
  // this replaced .hero as the page's top-level component in v3)
  const brandSrc = preview.querySelector(".reader-questions");
  const brandTitle = (brandSrc && brandSrc.getAttribute("data-nav-title")) || "Explainer";
  const brandSub = (brandSrc && brandSrc.getAttribute("data-nav-sub")) || "contents";
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
    targets.forEach((t) => t.link.classList.toggle("is-active", t.link === link));
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

/* ---- post-render pipeline: theme class + drawio + icons + nav + reveal ----
   Runs manually after construction because callback.afterInit does NOT fire in
   previewOnly mode in Cherry 0.8.58. We locate the mounted preview surface,
   tag it with the theme class, frame + run drawio, render icons, build the
   sticky nav + scrollspy, THEN reveal. */
function runPostRender(container) {
  const preview =
    container.querySelector(".cherry-previewer") ||
    container.querySelector(".cherry-markdown") ||
    container;
  // ensure our theme class is present on the preview surface
  preview.classList.add("cherry-markdown", "theme__explainer");

  // icons + navigation are independent of drawio and safe to run immediately.
  renderIcons(preview);
  const targets = buildNav(preview);
  wireScrollspy(targets);

  // await diagrams so the framed SVGs are populated when the stagger plays,
  // instead of animating empty <pre>s that then snap to SVG.
  // Reveal AFTER diagrams resolve so framed SVGs are populated when the stagger
  // plays. frameAndRunDrawio resolves synchronously today (GraphViewer's
  // render pass is synchronous), but it keeps the Promise contract so this
  // await boundary still holds if that ever changes.
  Promise.resolve(frameAndRunDrawio(preview)).finally(() => {
    // re-run icons in case any deferred content landed after the first pass.
    // Cheap + idempotent.
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
