/* ============================================================================
   cherry-setup.js — ENGINE + DIAGRAMS + DECLARATIVE INTERACTIVITY
   ----------------------------------------------------------------------------
   - Instantiates vendored cherry-markdown engine (CherryEngine) and mounts
     <div class="cherry-previewer cherry-markdown theme__explainer">...</div>.
   - Wires draw.io via PATH B (post-render) using GraphViewer.processElements()
     with live theme.css role colors substituted for role=accent|pitfall|check.
   - Wires declarative zero-JS-in-markdown components: .tabs and .accordion.
   - Wraps wide tables in .table-wrap for mobile scroll safety.
   - Respects document.documentElement.lang for locale selection.
   ============================================================================ */

function readRoleColors() {
  const cs = getComputedStyle(document.documentElement);
  return {
    accent: cs.getPropertyValue("--accent").trim(),
    pitfall: cs.getPropertyValue("--pitfall").trim(),
    check: cs.getPropertyValue("--check").trim(),
  };
}

const ROLE_KINDS = ["accent", "pitfall", "check"];
const ROLE_TOKEN = /\brole=(accent|pitfall|check)\b;?/g;
function substituteRoleTokens(xml, colors) {
  const substituted = xml.replace(/style=(["'])([^"']*)\1/g, (whole, quote, body) => {
    const swapped = body.replace(ROLE_TOKEN, (token, kind) => {
      const hex = colors[kind];
      if (!hex) {
        console.warn(
          `[explainer-kit] role=${kind} could not be substituted: CSS custom property --${kind} is missing or empty on :root (check theme.css)`
        );
        return token;
      }
      return `strokeColor=${hex};`;
    });
    return `style=${quote}${swapped}${quote}`;
  });
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

const CALLOUT_ICONS = {
  note: "info",
  pitfall: "triangle-alert",
  check: "circle-check",
};

function resolveCherry() {
  const ns = window.CherryEngine || window.Cherry;
  const Ctor = ns && ns.default ? ns.default : ns;
  if (typeof Ctor !== "function") {
    throw new Error("cherry-setup: CherryEngine constructor not found on window.CherryEngine(.default)");
  }
  return Ctor;
}

const DRAWIO_HEAD = /^<mxGraphModel\b/;

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
          const result =
            `<div data-sign="${sign}" data-lines="${lines}" class="callout${cls}">` +
            `<span class="co-ico" data-ico="${k}"></span>` +
            `<div class="co-body">${html}</div>` +
            `</div>`;
          return this.pushCache(result, sign, lines);
        });
      },
      rule() {
        return {
          reg: /^[ \t]*:::[ \t]+callout[ \t]*([a-z]*)[ \t]*\n([\s\S]*?)\n[ \t]*:::[ \t]*$/gm,
        };
      },
    }
  );
  return CalloutHook;
}

/* ---- strip Cherry-injected <br> elements inside layout containers --------- */
function stripLayoutBreaks(preview) {
  const containers = preview.querySelectorAll(
    ".tabs, .tab-list, .tab-panel, .accordion, .acc-item, .acc-panel, " +
    ".section-head, .steps, .step, .step-body, .compare, .compare-panel, " +
    ".worked-example .we-flow, .chip-row, .legend"
  );
  containers.forEach((el) => {
    Array.from(el.children).forEach((ch) => {
      if (ch.tagName === "BR") ch.remove();
    });
  });
}

/* ---- wrap markdown tables in .table-wrap & stamp data-label for mobile ---- */
function wrapTables(preview) {
  preview.querySelectorAll("table").forEach((tbl) => {
    const headers = Array.from(tbl.querySelectorAll("thead th")).map((th) =>
      (th.textContent || "").trim()
    );
    if (headers.length) {
      tbl.querySelectorAll("tbody tr").forEach((tr) => {
        Array.from(tr.children).forEach((cell, idx) => {
          if (cell.tagName !== "TD") return;
          if (!cell.hasAttribute("data-label") && headers[idx]) {
            cell.setAttribute("data-label", headers[idx]);
          }
          if (!cell.querySelector(":scope > .td-val")) {
            const val = document.createElement("div");
            val.className = "td-val";
            while (cell.firstChild) val.appendChild(cell.firstChild);
            cell.appendChild(val);
          }
        });
      });
    }
    if (tbl.parentElement && tbl.parentElement.classList.contains("table-wrap")) return;
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    tbl.parentNode.insertBefore(wrap, tbl);
    wrap.appendChild(tbl);
  });
}

/* ---- keep short inline code commands unbroken outside tables -------------- */
function markShortCodeTokens(preview) {
  preview.querySelectorAll(":not(pre) > code").forEach((el) => {
    if (el.closest("table")) return;
    const txt = (el.textContent || "").trim();
    if (txt.length > 0 && txt.length <= 22) {
      el.classList.add("code-nowrap");
    }
  });
}

/* ---- declarative .tabs wiring --------------------------------------------- */
function wireTabs(preview) {
  preview.querySelectorAll(".tabs").forEach((tabs) => {
    const btns = Array.from(tabs.querySelectorAll(":scope > .tab-list > .tab-btn"));
    const panels = Array.from(tabs.querySelectorAll(":scope > .tab-panel"));
    if (!btns.length || !panels.length) return;

    const activate = (targetIdx) => {
      btns.forEach((b, i) => {
        const key = b.getAttribute("data-tab");
        const active = key !== null ? key === String(targetIdx) : String(i) === String(targetIdx);
        b.setAttribute("aria-pressed", active ? "true" : "false");
        b.classList.toggle("is-active", active);
      });
      panels.forEach((p, i) => {
        const key = p.getAttribute("data-panel");
        const active = key !== null ? key === String(targetIdx) : String(i) === String(targetIdx);
        p.classList.toggle("is-active", active);
        p.hidden = !active;
      });
    };

    const initialBtn =
      btns.find((b) => b.getAttribute("aria-pressed") === "true" || b.classList.contains("is-active")) ||
      btns[0];
    const initKey = initialBtn.getAttribute("data-tab") ?? btns.indexOf(initialBtn);
    activate(initKey);

    btns.forEach((btn, idx) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-tab");
        activate(key !== null ? key : idx);
      });
    });
    tabs.classList.add("is-wired");
  });
}

/* ---- declarative .accordion wiring ---------------------------------------- */
function wireAccordions(preview) {
  preview.querySelectorAll(".accordion").forEach((acc) => {
    const items = Array.from(acc.querySelectorAll(":scope > .acc-item"));
    if (!items.length) return;

    items.forEach((item) => {
      const btn = item.querySelector(":scope > .acc-btn");
      const panel = item.querySelector(":scope > .acc-panel");
      if (!btn || !panel) return;

      const sync = (open) => {
        item.classList.toggle("is-open", open);
        btn.setAttribute("aria-expanded", open ? "true" : "false");
        panel.hidden = !open;
      };

      const startOpen =
        item.classList.contains("is-open") || btn.getAttribute("aria-expanded") === "true";
      sync(startOpen);

      btn.addEventListener("click", () => {
        const nextOpen = btn.getAttribute("aria-expanded") !== "true";
        sync(nextOpen);
      });
    });
    acc.classList.add("is-wired");
  });
}

function frameAndRunDrawio(rootEl) {
  if (typeof GraphViewer === "undefined") return Promise.resolve();

  const colors = readRoleColors();
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
    const pwMatch = xml.match(/\bpageWidth=["'](\d+(?:\.\d+)?)["']/);
    const pw = pwMatch ? parseFloat(pwMatch[1]) : 0;
    frame.className = "diagram-frame is-pending" + (pw > 0 && pw <= 560 ? " is-compact" : "");
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

  try {
    GraphViewer.processElements();
  } catch (err) {
    console.warn("[explainer-kit] GraphViewer.processElements reported:", err);
  }

  // Ensure each rendered draw.io container is tall enough for its full SVG
  // (avoids the 6-7px min-height vs container-height delta that spawns scrollbars).
  targets.forEach((frame) => {
    const holder = frame.querySelector(".mxgraph");
    const svg = holder && holder.querySelector("svg");
    if (holder && svg) {
      const mh = parseFloat(svg.style.minHeight) || 0;
      const curH = parseFloat(holder.style.height) || 0;
      if (mh > curH) holder.style.height = Math.ceil(mh + 4) + "px";
      holder.style.overflow = "visible";
    }
    frame.classList.remove("is-pending");
  });
  return Promise.resolve();
}

function renderIcons(preview) {
  preview.querySelectorAll(".co-ico[data-ico]").forEach((chip) => {
    if (chip.querySelector("[data-lucide], svg")) return;
    const kind = chip.getAttribute("data-ico") || "";
    const name = CALLOUT_ICONS[kind] || CALLOUT_ICONS.note;
    const i = document.createElement("i");
    i.setAttribute("data-lucide", name);
    chip.appendChild(i);
  });
  if (window.lucide && typeof window.lucide.createIcons === "function") {
    window.lucide.createIcons({ attrs: { class: "lucide" } });
  }
}

function buildNav(preview) {
  const heads = Array.from(preview.querySelectorAll(".section-head[data-nav]"));
  if (!heads.length) return [];

  const nav = document.createElement("nav");
  nav.className = "explainer-nav";
  nav.setAttribute("aria-label", "Document sections");

  const brandSrc = preview.querySelector(".reader-questions");
  const brandTitle = (brandSrc && brandSrc.getAttribute("data-nav-title")) || "Explainer";
  const brandSub = (brandSrc && brandSrc.getAttribute("data-nav-sub")) || "contents";
  const navId = "explainer-nav-links";
  nav.innerHTML =
    '<div class="nav-bar">' +
    '<div class="nav-brand">' +
    '<span class="icon-chip sm"><i data-lucide="sparkles"></i></span>' +
    '<div><div class="nav-title">' + brandTitle + "</div>" +
    '<div class="nav-sub">' + brandSub + "</div></div></div>" +
    '<button type="button" class="nav-toggle" aria-expanded="false" aria-controls="' + navId + '">Sections</button>' +
    "</div>" +
    '<div class="nav-kicker">On this page</div>';

  const ul = document.createElement("ul");
  ul.className = "nav-links";
  ul.id = navId;
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

  const toggle = nav.querySelector(".nav-toggle");
  const setNavOpen = (open) => {
    ul.classList.toggle("is-open", open);
    if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
  };
  if (toggle) {
    toggle.addEventListener("click", () => {
      setNavOpen(!ul.classList.contains("is-open"));
    });
  }

  nav.addEventListener("click", (e) => {
    const link = e.target.closest(".nav-link");
    if (!link) return;
    const id = link.getAttribute("data-target");
    const el = document.getElementById(id);
    if (!el) return;
    e.preventDefault();
    setNavOpen(false);
    el.scrollIntoView({ block: "start", behavior: "instant" });
    history.replaceState(null, "", "#" + id);
    targets.forEach((t) => t.link.classList.toggle("is-active", t.link === link));
  });

  document.body.classList.add("has-nav");
  document.body.insertBefore(nav, document.body.firstChild);
  return targets;
}

function wireScrollspy(targets) {
  if (!targets.length) return;
  let activeId = null;
  const setActive = (id) => {
    if (id === activeId) return;
    activeId = id;
    targets.forEach((t) => t.link.classList.toggle("is-active", t.id === id));
    const active = targets.find((t) => t.id === id);
    const navEl = active && active.link.closest(".explainer-nav");
    if (active && navEl && getComputedStyle(navEl).position === "fixed") {
      active.link.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  };
  const recompute = () => {
    const nearBottom =
      window.scrollY > 0 &&
      window.innerHeight + window.scrollY >=
        document.documentElement.scrollHeight - 48;
    if (nearBottom) {
      setActive(targets[targets.length - 1].id);
      return;
    }
    const line = window.innerHeight * 0.45;
    let current = targets[0].id;
    for (const t of targets) {
      if (t.el.getBoundingClientRect().top <= line) current = t.id;
      else break;
    }
    setActive(current);
  };

  if (typeof IntersectionObserver !== "undefined") {
    const io = new IntersectionObserver(recompute, {
      rootMargin: "0px 0px -45% 0px",
      threshold: [0, 1],
    });
    targets.forEach((t) => io.observe(t.el));
  }
  window.addEventListener("scroll", recompute, { passive: true });
  window.addEventListener("resize", recompute, { passive: true });
  recompute();
}

function runPostRender(container) {
  const preview =
    container.querySelector(".cherry-previewer") ||
    container.querySelector(".cherry-markdown") ||
    container;
  preview.classList.add("cherry-markdown", "theme__explainer");

  stripLayoutBreaks(preview);
  wrapTables(preview);
  markShortCodeTokens(preview);
  wireTabs(preview);
  wireAccordions(preview);
  renderIcons(preview);
  const targets = buildNav(preview);
  wireScrollspy(targets);

  Promise.resolve(frameAndRunDrawio(preview)).finally(() => {
    renderIcons(preview);
    preview.classList.add("is-ready");
  });
}

function renderExplainer(containerId, markdownText) {
  const container = document.getElementById(containerId);
  if (!container) throw new Error(`renderExplainer: #${containerId} not found`);

  const Cherry = resolveCherry();
  const calloutHook = registerCalloutHook(Cherry);
  const docLang = (document.documentElement.lang || "en").toLowerCase();
  const tocLabel = docLang.startsWith("th")
    ? "สารบัญ"
    : docLang.startsWith("zh")
      ? "目录"
      : "Table of Contents";
  const locale = { toc: tocLabel };

  const engine = new Cherry({
    id: containerId,
    value: markdownText,
    locale,
    editor: {
      defaultModel: "previewOnly",
      keepDocumentScrollAfterInit: true,
    },
    toolbars: {
      toolbar: false,
      toolbarRight: [],
      bubble: false,
      float: false,
      sidebar: false,
    },
    engine: {
      global: { flowSessionContext: false, htmlWhiteList: "button" },
      customSyntax: {
        explainerCallout: {
          syntaxClass: calloutHook,
          before: "br",
        },
      },
    },
  });

  if (typeof engine.makeHtml === "function") {
    const renderedHtml = engine.makeHtml(markdownText);
    container.innerHTML =
      '<div class="cherry cherry--preview-only theme__light">' +
      '<div class="cherry-previewer cherry-markdown theme__explainer">' +
      renderedHtml +
      "</div></div>";
  }

  runPostRender(container);
}

window.renderExplainer = renderExplainer;
