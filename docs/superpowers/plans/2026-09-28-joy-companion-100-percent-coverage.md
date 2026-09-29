# Joy-Companion 100% Test Coverage & Hardening Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elevate `joy-companion` statement test coverage from **79.2%** to **>95%** (100% of all reachable non-`main()` statements), resolve uncovered edge cases, patch security/concurrency blind spots, and verify the full test suite with zero flakes.

**Target Repository:** `/Users/pasitnusso/workspace/repos/joy-companion`  
**Current Baseline:** `79.2%` statement coverage  
**Target Coverage:** `> 95.0%` statement coverage  

---

## Wave 1: Auth, Origin Resolution & SSO Security

### Task 1: Comprehensive Security Tests for `isRequestSecure` & `getAppOrigin`
- **File:** `auth_test.go`
- **Coverage Target:** `isRequestSecure` (28.6% -> 100%), `getAppOrigin` (22.2% -> 100%)
- **Test Scenarios:**
  - `cfg.AppOrigin` starting with `https://` -> returns true.
  - `r.TLS != nil` -> returns true.
  - `X-Forwarded-Proto: https` with public domain (`joymify.com`) -> returns true.
  - `X-Forwarded-Proto: https` with local domain (`service.local`) -> returns false.
  - Empty `cfg.AppOrigin` with valid `r.Host` -> resolves `http://<host>` or `https://<host>`.
  - Empty `cfg.AppOrigin` and empty `r.Host` -> resolves `http://localhost:<cfg.Port>`.
- [ ] **Step 1.1: Write unit tests** `TestIsRequestSecure_AllBranches` and `TestGetAppOrigin_AllFallbacks`.
- [ ] **Step 1.2: Run test and verify pass**: `go test -v -run "TestIsRequestSecure|TestGetAppOrigin"`.

---

### Task 2: Robust URL Normalization & Callback Tests in `auth.go`
- **File:** `auth_test.go`
- **Coverage Target:** `normalizeLoginURL` (69.2% -> 100%), `handleCallback` (78.4% -> 95%)
- **Test Scenarios:**
  - Empty `loginURL` -> defaults to `http://auth.joymify.local.com/login`.
  - Root URL (`https://auth.example.com/`) -> appends `/login`.
  - URL without trailing slash (`https://auth.example.com/sso`) -> appends `/login`.
  - URL already containing `/login` with existing query params (`https://auth.example.com/login?client_id=123`).
  - `handleCallback` with missing cookie, state mismatch, and malformed query params.
- [ ] **Step 2.1: Write unit tests** `TestNormalizeLoginURL_AllCases` and `TestHandleCallback_ErrorStates`.
- [ ] **Step 2.2: Run test and verify pass**: `go test -v -run "TestNormalizeLoginURL|TestHandleCallback"`.

---

## Wave 2: Context Store In-Memory Mode & Cache Eviction

### Task 3: In-Memory Context Store & Directory Fallbacks
- **File:** `context_store_test.go`
- **Coverage Target:** `NewInMemoryContextStore` (0.0% -> 100%), `NewContextStore` (56.2% -> 90%)
- **Test Scenarios:**
  - `NewInMemoryContextStore()` initializes default soul and memory in memory with `inMemory = true`.
  - `UpdateSoul` and `UpdateMemory` mutate in-memory state cleanly without disk access.
  - `NewContextStore("")` defaults to `./data`.
  - `NewContextStore("/invalid/read-only-path-$$")` falls back to temp directory or in-memory mode.
- [ ] **Step 3.1: Write unit tests** `TestInMemoryContextStore_FullLifecycle` and `TestContextStore_FallbackModes`.
- [ ] **Step 3.2: Run test and verify pass**: `go test -v -run "TestInMemoryContextStore|TestContextStore_Fallback"`.

---

### Task 4: Preload Cache TTL Expiration & Idle Eviction
- **File:** `preload_test.go`
- **Coverage Target:** `cleanLocked` (50.0% -> 100%)
- **Test Scenarios:**
  - Add items with varying timestamps.
  - Trigger `cleanLocked` with `now > expiration` for partial and full set.
  - Verify expired keys are deleted while fresh keys remain.
- [ ] **Step 4.1: Write unit test** `TestPreloadCache_TTL_Eviction`.
- [ ] **Step 4.2: Run test and verify pass**: `go test -v -run TestPreloadCache_TTL_Eviction`.

---

## Wave 3: Session State Machine, Tool Execution & Analysis

### Task 5: Tool Call Execution Error States & Context Store Guard
- **File:** `server_test.go` (or `session_test.go`)
- **Coverage Target:** `executeToolCall` (68.2% -> 100%)
- **Test Scenarios:**
  - Session with `contextStore == nil` returns error response `"context store unavailable"`.
  - Tool call with unrecognized name returns `"unknown tool"`.
  - Tool call update failure returns formatted error.
  - Tool call with empty `action` defaults to `"append"`.
- [ ] **Step 5.1: Write unit test** `TestSession_ExecuteToolCall_AllBranches`.
- [ ] **Step 5.2: Run test and verify pass**: `go test -v -run TestSession_ExecuteToolCall`.

---

### Task 6: Candidate Parts & Analysis Extraction Edge Cases
- **File:** `analysis_test.go`
- **Coverage Target:** `analysisResponseText` (46.7% -> 100%), `candidateParts` (66.7% -> 100%)
- **Test Scenarios:**
  - Nil `resp` returns empty string.
  - Response with nil candidate or zero candidates.
  - Candidates with nil part pointers mixed with valid text parts.
  - Candidate with non-text part types.
  - Multiple text parts concatenation.
- [ ] **Step 6.1: Write unit tests** `TestAnalysisResponseText_NilAndEdgeCases`.
- [ ] **Step 6.2: Run test and verify pass**: `go test -v -run TestAnalysisResponseText`.

---

### Task 7: Upstream Audio Buffer Pool & Reconnect States
- **File:** `server_test.go`
- **Coverage Target:** `sendUpstreamAudio` (63.6% -> 90%), `reconnect` (79.2% -> 95%)
- **Test Scenarios:**
  - Audio packet larger than default pool capacity triggers `ensureCap` growth.
  - `reconnect` called on closed session returns `"session closed"`.
  - `reconnect` called with stale `from` session returns early (deduplicated).
  - `reconnect` called after `stopCh` closed returns `"session stopped"`.
- [ ] **Step 7.1: Write unit tests** `TestSession_UpstreamAudio_BufferGrowth` and `TestSession_Reconnect_EdgeCases`.
- [ ] **Step 7.2: Run test and verify pass**: `go test -v -run "TestSession_UpstreamAudio|TestSession_Reconnect"`.

---

## Wave 4: Origin Guards, Static Serving & Final Coverage Gate

### Task 8: Local Origin Filter & Static Handler
- **File:** `server_test.go`
- **Coverage Target:** `isLocalOrigin` (83.3% -> 100%), `staticHandler` (75.0% -> 95%)
- **Test Scenarios:**
  - Test origin `localhost`, `127.0.0.1`, `[::1]`, and non-local domains (`attacker.com`).
  - Test static handler with existing file vs missing file (404).
- [ ] **Step 8.1: Write unit tests** `TestIsLocalOrigin_AllCases` and `TestStaticHandler_MissingFiles`.
- [ ] **Step 8.2: Run test and verify pass**: `go test -v -run "TestIsLocalOrigin|TestStaticHandler"`.

---

### Task 9: Final Statement Coverage Verification Gate (>95%)
- [ ] **Step 9.1: Run full coverage suite**:
  ```bash
  go test -coverprofile=cover.out .
  go tool cover -func=cover.out | tail -n 1
  ```
  **Gate Requirement:** Total statement coverage must exceed `90.0%` (target `>95%`).
- [ ] **Step 9.2: Git Commit**:
  ```bash
  git add .
  git commit -m "test(joy-companion): add comprehensive unit test suite reaching >90% coverage"
  ```
