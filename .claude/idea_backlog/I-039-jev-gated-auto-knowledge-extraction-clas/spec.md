---
title: "Jev-gated auto knowledge extraction: classify-lesson lens on Stop-hook session summaries, cheap flash extractor drafts to _inbox, Argon review before publish-knowledge"
id: I-039
status: idea
---

# Jev-gated auto knowledge extraction: classify-lesson lens on Stop-hook session summaries, cheap flash extractor drafts to _inbox, Argon review before publish-knowledge

## Problem

The agentic-vault only gets a raw session summary (Stop hook `vault-session-summary.sh` -> `_inbox/agent/session-summaries.md`). Lessons reach `04_Knowledge/` only if an agent or human runs `publish-knowledge` / `/review-inbox` by hand, so most durable lessons are lost. Retrieval is already automatic (SessionStart `vault-bootstrap.py`).

## Why now

`jev-gate` already gives a cheap System 1 classifier with a confidence floor (0.85) and `escalate_to_frontier` fallback; recent commit added Atlas/Svelte/DB lenses, so adding a lens is a known pattern.

## Sketch

1. Keep the Stop hook appending the raw summary.
2. New `jev-gate classify-lesson` subcommand (new lens): does the summary hold a durable lesson/decision/trap?
   - confident no: drop. confident yes: cheap extractor (`gemini-3.8-flash-high` via `dispatch-worker`) writes a draft to `_inbox/agent/`. unsure: leave for `/review-inbox` (no frontier spend).
3. Draft -> `04_Knowledge/` stays gated: Argon review, then `vault-engine publish-knowledge` (LLMs propose, engine commits).
4. Hook stays async with a timeout; fails open if `TYPESAFE_API_KEY` unset.

Open risks: Jev is calibrated for SDLC routing, so the new lens needs calibration data; a wrongly confident yes must not reach `04_Knowledge/` without review.

## Acceptance criteria

- [ ] (one observable, testable outcome per item; refine refuses a spec without any)
