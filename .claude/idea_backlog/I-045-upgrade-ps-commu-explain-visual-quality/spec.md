---
title: "Upgrade ps-commu-explain visual quality and tailnet HTTPS"
id: I-045
status: idea
---

# Upgrade ps-commu-explain visual quality and tailnet HTTPS

## Problem

`ps-commu-explain` currently lacks a unified visual/interactive standard across its three tiers (`infographic`, `html`, `react`), relies on external runtime CDN fetches, has inconsistent Thai typography support, and binds strictly to `127.0.0.1` without an isolated, safe way to preview explainers from tailnet devices over HTTPS. Additionally, `~/.gemini/skills/ps-commu-explain` is a stale copy instead of a symlink to the canonical `~/.claude/skills/ps-commu-explain`.

## Why now

Daily production use across desktop and mobile tailnet devices requires self-contained, accessible, bilingual (Thai + English) explainers with reliable interactive controls and safe Tailscale HTTPS publishing that never interferes with existing Funnel/Serve listeners (`:8443`, `:8444`, `:9443`) or `:8789`.

## Sketch

1. **R1 — Visual & interactive quality (all three tiers: `infographic` default per C4, `html`, `react`):**
   - Unified light-mode editorial design tokens (type scale, spacing, colour roles; dark mode out of scope) shared across all three templates.
   - Self-contained vendored assets (draw.io viewer, cherry-markdown, Lucide icons, subset Latin+Thai woff2 fonts) with zero non-loopback runtime requests and total added vendored assets `<= 6 MB` (C7).
   - Interactivity floor: `infographic` and `html` provide `>= 2` declarative JS-free components authored in `content.md` (tabs, plus stepper or accordion), listed in `components-index.md`, validated by `lint.sh`, and asserted by `verify.sh`; `react` retains stateful controls (slider / step-sim / filter).
   - Thai + English typography: `lang` derived from `00-brief.md` (not hardcoded `en`); Thai font faces with matching weights; when `lang=th`, body `line-height >= 1.7`, heading `line-height >= 1.35`, no letter-spacing/uppercase transforms, and no `word-break: break-all`.
   - Design and QA guided by `impeccable` and `ui-visual-verify` without weakening existing gates (`lint.sh`, `verify.sh`, reader gate, `<= 5` cycle cap, C5).

2. **R2 — Tailnet-only HTTPS viewing:**
   - `serve.sh <slug> --tailnet` publishes on tailnet-only HTTPS port `loopback + 10000` (`17700–17799`) mounted at `/` proxying to `127.0.0.1:77xx` (C3), deriving hostname from `tailscale status --self --json` (C6). Without `--tailnet`, behavior is byte-for-byte identical.
   - Ownership & lifecycle: record HTTPS port/URL in `meta.json`; remove only listeners recorded there whose proxy target is `127.0.0.1:77xx` in `stop.sh`, `clean.sh`, TTL watchdog, 3-day `init.sh` sweep, and port-change re-serve. Never run `tailscale serve reset` or `tailscale funnel` or touch `:8443`, `:8444`, `:9443`, `:8789` (C2).
   - `list.sh` flags orphan `17700–17799` listeners and prints tailnet URLs; `handoff.sh` prints tailnet URL on its own line. `--tailnet` with `--dev` is refused; missing/logged-out `tailscale` warns, serves localhost, exits 0. `TAILSCALE_BIN` overrides binary for stub tests.
   - Harden `httpserve.py`: `127.0.0.1` only, GET/HEAD only, no directory listings, 404 for dotfiles and docroot realpath escapes, `X-Content-Type-Options: nosniff`.

3. **R3 & Constraints (C1–C7):**
   - Implement in a claimed feature worktree only (never main checkout, no `PS_RELEASE_WORKFLOW_SCRIPTED=1`, leave dirty/`.bak-*` files on main untouched, C1).
   - Update root `README.md` for new flag/env var; keep `SKILL.md` growth `<= 15` lines (C7); no new npm/pip dependencies for lifecycle scripts (C6).
   - Replace stale `~/.gemini/skills/ps-commu-explain` directory with a symlink to `~/.claude/skills/ps-commu-explain` and commit only that path in its repo.

## Acceptance criteria

- [ ] Three fresh non-example samples (one per tier, at least one in Thai, each with diagram, code block, `>= 5`-col table, `>= 60`-char unbroken token) pass `lint.sh`, render/verify checks, and reader gate (`PASS` within 5 cycles).
- [ ] `shoot.mjs --sizes 390x844,1280x800` (with `--click` per interactive control) passes on all 3 samples with visible state changes, `scrollWidth <= clientWidth`, 0 console/request errors, `>= 16px` body at 390px, `>= 44x44` targets, `>= 4.5:1` contrast, `prefers-reduced-motion` respected, and full offline rendering with non-loopback requests blocked.
- [ ] Unprimed visual reviewer scores `>= 4` on all 5 rubric axes with no blocking defect, prefers the new templates in blind pair comparisons across all 3 tiers, and owner phone/desktop preview links are prepared.
- [ ] `serve.sh <slug> --tailnet` serves `https://<derived-host>:177xx/` (HTTP 200), leaves `tailscale funnel status` on `:8443` only, restores `tailscale serve status --json` to baseline after `stop.sh`/`clean.sh` with `:8443`, `:8444`, `:9443` responsive, and `httpserve.py` rejects `/.ready`, `/../meta.json`, and dir listings.
- [ ] `bash skills/ps-commu-explain/tests/lifecycle_test.sh` passes from the worktree with `>=` baseline test count plus `TAILSCALE_BIN` stub tests; React build (`npm ci && npx tsc --noEmit && npm run build`) passes; vendored assets `<= 6 MB` and `SKILL.md` `<= +15` lines; `~/.gemini/skills/ps-commu-explain` symlink resolves to canonical skill.
