---
title: "Show vault project goals with live release feature status"
id: F-016
status: refined
from_idea: I-016
---

# Show vault project goals with live release feature status

## Problem

Vault project notes hold goals and context, while ps-release-workflow owns claimed, shipped, epic, and release state. A reader must inspect both systems separately to answer what matters and how far delivery has progressed.

## Why now

The user asked for the two skills to work together without tightly coupling their storage or write paths, and approved a small working slice: JSON release status, a project-to-feature link, and a read-only combined view.

## Design

- Add versioned, minimal `psrw status --json`; keep text and zero-exit behavior.
- Add optional scalar `release_repo` (absolute main-checkout root) and `release_feature_id` (`F-NNN`) to project metadata.
- Add `ps-work link`, which validates the feature and writes only the link through `vault-engine commit` with OCC.
- Add read-only `ps-work show`, which reads project title/outcome and live release status by linked ID, with clear missing/unavailable states.
- Both operations pass `VAULT_ROOT` to the vault child; no release status is copied into vault notes. Full interface and failure behavior: `docs/superpowers/specs/2026-09-29-vault-release-view-design.md`.

## Acceptance criteria

- [ ] `psrw status --json` emits parseable JSON with feature, epic, and release status while preserving current text output.
- [ ] A project can hold optional repo and feature link fields through its existing vault commit path.
- [ ] `ps-work-view` shows a linked project's goal and feature status from a live release snapshot.
- [ ] Missing link, unknown feature, and unavailable release status are distinct and readable.
- [ ] Focused tests and an end-to-end fixture prove the view does not mutate either source.
