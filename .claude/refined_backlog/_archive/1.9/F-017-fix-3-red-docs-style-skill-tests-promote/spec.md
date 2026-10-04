---
title: "Fix 3 red docs-style skill tests (promote/ship body budget, sync-main lifecycle link)"
id: F-017
status: refined
from_idea: I-017
---

# Fix 3 red docs-style skill tests (promote/ship body budget, sync-main lifecycle link)

## Problem

Three docs-style tests in test_docs_single_source.py fail on main: promote (47 lines) and ship (45 lines) exceed the 40-line skill body budget, and sync-main links to lifecycle.md#main-sync-mechanics, which the test's ANCHORS list omits.

## Why now

Red tests on main hide real regressions; found while promoting 1.8.

## Sketch

Full design: docs/superpowers/specs/2026-09-30-fix-red-docs-tests-design.md

## Acceptance criteria

- [ ] test_docs_single_source.py reports 0 failed
- [ ] promote and ship SKILL.md each have <= 40 non-blank body lines and keep their lifecycle.md link
- [ ] full pytest shows no new failures versus the 788-passed baseline
