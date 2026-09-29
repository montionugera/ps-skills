---
title: "Deterministic Mermaid validation and error trap for ps-commu-explain HTML tier"
id: I-015
status: idea
---

# Deterministic Mermaid validation and error trap for ps-commu-explain HTML tier

## Problem

When authoring explainer pages in `ps-commu-explain` using the HTML tier (`--tier html`), `lint.sh` and `verify.sh` perform zero validation on Mermaid diagrams inside `app/index.html`. Syntactically invalid Mermaid code (such as unquoted paths in sequence diagrams, raw double brackets `[[...]]` inside edge labels, or unescaped ampersands) passes `lint.sh` and gets served without warning, resulting in client-side runtime errors (`Syntax error in text mermaid version 11.x`) visible in the browser.

## Why now

Developers and AI agents rely on `ps-commu-explain` to produce visual artifacts autonomously. Without a deterministic pre-serve machine gate, agents produce broken diagrams that require manual human bug reports and multiple debugging round trips.

## Sketch

1. In `skills/ps-commu-explain/scripts/lint.sh`: Add a validation pass for `app/index.html` (and any `<div class="mermaid">` blocks) using the official Mermaid CLI (`mmdc`) or a headless syntax check to reject malformed diagrams before serving.
2. In `skills/ps-commu-explain/assets/template-html/index.html`: Add a `mermaid.parseError` handler to trap client-side render failures, attaching `class="explainer-error"` to the DOM.
3. In `skills/ps-commu-explain/scripts/verify.sh`: Extend the verification gate to support the HTML tier by checking for `.explainer-error` and verifying that rendered SVG count matches the `.mermaid` div count.

## Acceptance criteria

- [ ] `skills/ps-commu-explain/scripts/lint.sh` validates all `<div class="mermaid">` blocks in `app/index.html` when tier is `html`, reporting syntax errors and exiting 1 before `serve.sh` binds.
- [ ] `skills/ps-commu-explain/assets/template-html/index.html` handles `mermaid.parseError` by setting `.explainer-error` on `document.body`.
- [ ] `scripts/precheck.sh` and existing tests pass.
