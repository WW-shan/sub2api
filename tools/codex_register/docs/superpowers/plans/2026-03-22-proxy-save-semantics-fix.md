# Proxy Save Semantics Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make saving the proxy list preserve the global routing toggle and per-row enabled state when the frontend sends its current minimal payload.

**Architecture:** Keep the current frontend payload unchanged. Fix `/proxy/list` on the service side so missing `proxy_enabled` preserves the existing global flag, and missing row-level `enabled` preserves the saved row value instead of being rewritten to `True`.

**Tech Stack:** Python, unittest, existing Codex register service tests

---

### Task 1: Add failing tests for proxy save preservation

**Files:**
- Modify: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write the failing test** for preserving `proxy_enabled` when `/proxy/list` omits the field.
- [ ] **Step 2: Run test to verify it fails**
  - Run: `python3 -m unittest -v test_codex_register_service.ProxyEndpointTests.<test_name>`
- [ ] **Step 3: Write the failing test** for preserving saved row `enabled` when `/proxy/list` omits row-level `enabled`.
- [ ] **Step 4: Run test to verify it fails**
  - Run: `python3 -m unittest -v test_codex_register_service.ProxyEndpointTests.<test_name>`
- [ ] **Step 5: Implement minimal service fix** in `codex_register_service.py`.
- [ ] **Step 6: Run focused proxy endpoint tests**
  - Run: `python3 -m unittest -v test_codex_register_service.ProxyEndpointTests`

### Task 2: Verify no regression in proxy injection path

**Files:**
- Modify: none

- [ ] **Step 1: Run `test_gpt_team_new` suite**
  - Run: `python3 -m unittest -v test_gpt_team_new`
- [ ] **Step 2: Confirm proxy injection behavior still passes**
