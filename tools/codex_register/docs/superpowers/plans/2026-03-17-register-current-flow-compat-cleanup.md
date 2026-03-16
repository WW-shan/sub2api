# Register Current-Flow Compatibility Cleanup Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep `ChatGPTService.register(...)` on the current branch-driven flow, remove unused new pipeline code, and guarantee successful `register` output can immediately continue `codex_register_service.py` Team operations without re-login.

**Architecture:** We keep `chatgpt.py` current `register()` as the single truth and patch only reliability/compatibility gaps in-place. We enforce stable return payload + identifier/session continuity so `get_members`/`send_invite` can run immediately after registration. We delete unused new-pipeline helpers and update tests to assert current-flow behavior and downstream Team continuity.

**Tech Stack:** Python 3, asyncio, curl_cffi AsyncSession, unittest/pytest-style async tests, existing ChatGPTService session cache model.

---

## File Map (before coding)

- Modify: `chatgpt.py`
  - Keep and patch current `register()` control flow.
  - Implement real OTP polling in `_poll_otp_from_mail_worker`.
  - Tighten completion branch conditions.
  - Remove unused new-pipeline functions and their orphan helpers.
- Modify: `test_chatgpt_register_service.py`
  - Add/adjust tests for current-flow guarantees and Team continuity after register.
  - Remove tests tied only to deleted new-pipeline internals.
- Verify (read-only): `codex_register_service.py`
  - Confirm call contract remains compatible (`register(...)` output consumed by follow-up Team steps).

---

## Chunk 1: Lock in current-flow behavior + Team continuity contracts

### Task 1: Add failing tests for current-flow hard requirements

**Files:**
- Modify: `test_chatgpt_register_service.py`
- Verify: `codex_register_service.py`

- [ ] **Step 1: Add failing test for unknown-branch failure propagation**

```python
async def test_register_unknown_branch_stops_when_register_user_fails(self):
    service = self.ChatGPTService()
    # Setup final_url to hit unknown branch
    # Mock _register_user_with_password => failure
    # Assert register() returns failure immediately
```

- [ ] **Step 2: Run the single new test to confirm failure first**

Run: `pytest test_chatgpt_register_service.py::TestChatGPTRegisterService::test_register_unknown_branch_stops_when_register_user_fails -v`
Expected: FAIL because current unknown branch does not check the step result.

- [ ] **Step 3: Add failing test for strict completion condition**

```python
async def test_register_does_not_mark_completed_on_generic_chatgpt_url(self):
    service = self.ChatGPTService()
    # Mock final_url containing chatgpt.com but not valid completion callback
    # Assert register() does not short-circuit to completed incorrectly
```

- [ ] **Step 4: Run the strict-completion test and verify it fails**

Run: `pytest test_chatgpt_register_service.py::TestChatGPTRegisterService::test_register_does_not_mark_completed_on_generic_chatgpt_url -v`
Expected: FAIL with current broad completion branch.

- [ ] **Step 5: Add failing test for OTP polling retries**

```python
async def test_poll_otp_from_mail_worker_retries_until_code_arrives(self):
    service = self.ChatGPTService()
    # Mock mail worker responses: first no code, then code
    # Assert polling retries and eventually succeeds
```

- [ ] **Step 6: Run OTP polling test and verify failure**

Run: `pytest test_chatgpt_register_service.py::TestChatGPTRegisterService::test_poll_otp_from_mail_worker_retries_until_code_arrives -v`
Expected: FAIL because current implementation performs only one fetch.

- [ ] **Step 7: Add failing continuity test for immediate Team operations after register**

```python
async def test_register_success_can_immediately_call_get_members_and_send_invite(self):
    service = self.ChatGPTService()
    # Mock register path success with tokens/account_id/identifier
    # Then call get_members and send_invite without refresh/login
    # Assert both requests execute with returned identifier/account context
```

- [ ] **Step 8: Run continuity test and confirm expected gap (if any) is exposed**

Run: `pytest test_chatgpt_register_service.py::TestChatGPTRegisterService::test_register_success_can_immediately_call_get_members_and_send_invite -v`
Expected: FAIL before implementation if continuity assumptions are not fully enforced.

- [ ] **Step 9: Commit test scaffolding**

```bash
git add test_chatgpt_register_service.py
git commit -m "test: capture register current-flow compatibility requirements"
```

### Task 2: Implement minimal fixes in current register flow

**Files:**
- Modify: `chatgpt.py`
- Test: `test_chatgpt_register_service.py`

- [ ] **Step 1: Patch unknown branch in `register()` to check both step results**

```python
register_user_result = await self._register_user_with_password(...)
if not register_user_result.get("success"):
    return register_user_result

send_otp_result = await self._send_otp_email(...)
if not send_otp_result.get("success"):
    return send_otp_result
```

- [ ] **Step 2: Tighten completion condition in `register()`**

```python
elif "callback" in final_path:
    return self._success_result({"email": email, "status": "completed"})
```

(Do not treat generic `chatgpt.com` URL as terminal success.)

- [ ] **Step 3: Implement true retry loop in `_poll_otp_from_mail_worker`**

```python
poll_seconds = int(register_input.get("mail_poll_seconds") or 3)
max_attempts = int(register_input.get("mail_poll_max_attempts") or 40)
for attempt in range(max_attempts):
    result = await self._make_register_request(...)
    # success with code => return
    # transient missing code => sleep and continue
```

- [ ] **Step 4: Keep error code semantics stable during polling**

```python
# Preserve network_timeout/network_error passthrough
# Use otp_validate_failed for exhausted retries/no code
```

- [ ] **Step 5: Ensure successful `register()` payload still includes Team-follow-up fields**

```python
return self._success_result({
    "email": email,
    "identifier": final_identifier,
    "account_id": account_id,
    "access_token": access_token,
    ...
})
```

(Use existing return contract; avoid introducing new keys.)

- [ ] **Step 6: Run targeted tests for fixed behaviors**

Run: `pytest test_chatgpt_register_service.py -k "unknown_branch or generic_chatgpt_url or poll_otp or immediately_call_get_members" -v`
Expected: PASS for the newly added behavior tests.

- [ ] **Step 7: Commit current-flow fix set**

```bash
git add chatgpt.py test_chatgpt_register_service.py
git commit -m "fix: harden current register flow and team continuity"
```

---

## Chunk 2: Remove new pipeline code and finalize compatibility regression

### Task 3: Delete unused new pipeline path and orphan helpers

**Files:**
- Modify: `chatgpt.py`
- Modify: `test_chatgpt_register_service.py`

- [ ] **Step 1: Remove new-pipeline entry/aggregate functions from `chatgpt.py`**

Remove these functions if no longer referenced:
- `_run_register_pipeline`
- `_finalize_registration_result`
- `_exchange_tokens`
- `_merge_pipeline_artifacts`
- `_check_network_and_region`

- [ ] **Step 2: Remove helper methods used only by deleted path (after reference check)**

Examples to evaluate and remove only if orphaned:
- `_verify_callback_state`
- `_parse_callback_url`
- `_extract_token_claims_without_verification`
- `_extract_session_access_token`
- `_build_register_oauth_url`
- `_ensure_oauth_bootstrap`
- `_build_deterministic_oauth_state`
- `_start_auth_flow`
- `_submit_signup`
- `_send_otp_with_fallback`
- `_create_account`

- [ ] **Step 3: Run repository search to ensure deleted symbols are not referenced**

Run: `python -m pytest test_chatgpt_register_service.py -k "not slow" -q`
Expected: No `AttributeError`/missing symbol failures from tests that should remain.

- [ ] **Step 4: Update tests to remove assertions tied only to deleted internals**

```python
# Replace direct unit tests of deleted internals with register black-box behavior tests
```

- [ ] **Step 5: Run focused compatibility regression for `codex_register_service.py` contract path**

Run: `pytest test_chatgpt_register_service.py -k "register and get_members and send_invite" -v`
Expected: PASS; register output can drive immediate Team calls.

- [ ] **Step 6: Commit pipeline-deletion cleanup**

```bash
git add chatgpt.py test_chatgpt_register_service.py
git commit -m "refactor: remove unused register pipeline and keep single current flow"
```

### Task 4: Full verification before completion

**Files:**
- Verify: `chatgpt.py`
- Verify: `test_chatgpt_register_service.py`
- Verify: `codex_register_service.py`

- [ ] **Step 1: Run full register service test suite**

Run: `pytest test_chatgpt_register_service.py -v`
Expected: PASS.

- [ ] **Step 2: Run any codex workflow tests touching `codex_register_service.py` (if present)**

Run: `pytest -k "codex_register_service or register" -v`
Expected: PASS for relevant tests, no contract regressions.

- [ ] **Step 3: Manual smoke path (mocked/stubbed) for required continuity**

```python
# In test/mocked flow:
# reg = await chatgpt_service.register(...)
# await chatgpt_service.get_members(reg["data"]["access_token"], reg["data"]["account_id"], ..., identifier=reg["data"]["identifier"])
# await chatgpt_service.send_invite(..., identifier=reg["data"]["identifier"])
```

Expected: both calls succeed without refresh/re-login.

- [ ] **Step 4: Final commit for verification adjustments (if needed)**

```bash
git add chatgpt.py test_chatgpt_register_service.py
git commit -m "test: finalize register-to-team continuity regression coverage"
```

- [ ] **Step 5: Prepare concise change summary for handoff**

Include:
- Removed symbols list.
- Current `register` branch behavior changes.
- Evidence that `register -> get_members/send_invite` works without re-login.

---

## Skills to apply during execution

- `@superpowers:subagent-driven-development` (required execution mode in this harness)
- `@superpowers:test-driven-development` (before each behavior change)
- `@superpowers:verification-before-completion` (before claiming done)
- `@superpowers:requesting-code-review` (after major chunk completion)

