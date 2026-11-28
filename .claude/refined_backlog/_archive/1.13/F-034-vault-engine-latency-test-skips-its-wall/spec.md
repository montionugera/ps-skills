---
title: "Vault-engine latency test skips its wall-clock budget under the race detector"
id: F-034
status: refined
from_idea: I-049
---

# Vault-engine latency test skips its wall-clock budget under the race detector

## Problem

Gate 2 runs `go test -race ./...` in `tools/vault-engine`. `TestContext_QueryStaysFastAt2000Notes`
asserts a p95 under 200 ms. Under the race detector the p95 is about 330 ms on every run, idle or
busy (without `-race` the whole 20-query test takes 0.33 s), so Gate 2 always fails and release 1.13
cannot be promoted.

## Why now

It blocks the 1.13 promote.

## Sketch

A `race`-tagged test file sets a `raceEnabled` constant; the latency test calls `t.Skip` when it is
true. `BenchmarkContextByQuery` keeps the 50 ms budget, and the non-race `go test` run still checks
200 ms.

## Acceptance criteria

- [ ] `go test -race -run TestContext_QueryStaysFastAt2000Notes ./pkg/vault` passes (test reported as skipped)
- [ ] `go test -run TestContext_QueryStaysFastAt2000Notes ./pkg/vault` still runs the 200 ms check and passes
- [ ] `go test -count=1 -race ./...` in `tools/vault-engine` passes
