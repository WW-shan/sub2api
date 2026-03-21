# Proxy Injection And Proxy List Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the loop-selected proxy actually reach `gpt-team-new.py` execution, and reject invalid `/proxy/list` payloads before saving state.

**Architecture:** Keep the service-side proxy selection unchanged. Close the runtime injection chain by reading `REGISTER_PROXY_URL` at the `gpt-team-new.py` batch entry and passing it explicitly into `register_one_account(proxy=...)`. Add strict validation in `codex_register_service.py` before normalizing and saving proxy pool entries.

**Tech Stack:** Python, unittest, asyncio, existing Codex register service tests

---

### Task 1: Add failing tests for `/proxy/list` validation

**Files:**
- Modify: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write failing tests** for empty `name`, empty `proxy_url`, duplicate `id`, duplicate `proxy_url`, and verify state is unchanged on failure.
- [ ] **Step 2: Run test to verify it fails**
  - Run: `pytest test_codex_register_service.py -k proxy_list -v`
- [ ] **Step 3: Write minimal implementation** in `codex_register_service.py` to validate payload before saving.
- [ ] **Step 4: Run tests to verify they pass**
  - Run: `pytest test_codex_register_service.py -k proxy_list -v`

### Task 2: Add failing tests for proxy env injection in `gpt-team-new.py`

**Files:**
- Modify: `tools/codex_register/gpt-team-new.py`
- Modify: `tools/codex_register/test_gpt_team_new.py`

- [ ] **Step 1: Write failing tests** verifying `run_batch()` reads `REGISTER_PROXY_URL` and passes it to `register_one_account(proxy=...)`.
- [ ] **Step 2: Run test to verify it fails**
  - Run: `pytest test_gpt_team_new.py -k proxy -v`
- [ ] **Step 3: Write minimal implementation** in `gpt-team-new.py`.
- [ ] **Step 4: Run tests to verify they pass**
  - Run: `pytest test_gpt_team_new.py -k proxy -v`

### Task 3: Run focused verification

**Files:**
- Modify: none

- [ ] **Step 1: Run focused service tests**
  - Run: `pytest test_codex_register_service.py -k 'proxy_list or proxy' -v`
- [ ] **Step 2: Run focused script tests**
  - Run: `pytest test_gpt_team_new.py -k proxy -v`
- [ ] **Step 3: Review results and confirm no unexpected regressions**
