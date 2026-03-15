# Register Env-Only Migration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `register_input` from public registration entry and drive registration config from exactly three environment variables: `REGISTER_MAIL_DOMAIN`, `REGISTER_MAIL_WORKER_BASE_URL`, `REGISTER_MAIL_WORKER_TOKEN`.

**Architecture:** Keep `ChatGPTService.register(...)` as the single public entry, but change it to read runtime config from process environment instead of caller input. Continue using the same internal register pipeline and session model so post-register Team APIs still work with returned `identifier`. Preserve password-based registration and worker OTP fetch semantics already aligned to user requirements.

**Tech Stack:** Python 3, `os.environ`, `urllib.parse.quote`, `unittest` + `unittest.mock`, existing async session cache in `ChatGPTService`.

---

## File Structure (locked before implementation)

- Modify: `chatgpt.py`
  - Change `register` signature to remove `register_input`
  - Read env vars in runtime-context construction
  - Keep fixed defaults for timeout/poll values in code (not env)
  - Keep password registration + worker OTP flow unchanged in behavior

- Modify: `test_chatgpt_register_service.py`
  - Replace public `register(register_input)` call sites with env-patched `register()` calls
  - Add env-contract tests (required vars + error mapping)
  - Keep/adjust existing behavior tests for URL/auth/session continuity

- Do not modify unrelated files.

---

## Chunk 1: Public API hard-cut to env-only

### Task 1: Convert register entry contract to env-only and lock failing tests first

**Files:**
- Modify: `test_chatgpt_register_service.py`
- Modify: `chatgpt.py`

- [ ] **Step 1: Add failing tests for new public contract (`register()` with no input object)**

```python
@patch.dict(os.environ, {
    "REGISTER_MAIL_DOMAIN": "example.com",
    "REGISTER_MAIL_WORKER_BASE_URL": "https://worker.example.com",
    "REGISTER_MAIL_WORKER_TOKEN": "token",
}, clear=False)
async def test_register_reads_runtime_from_env(self):
    service = self.ChatGPTService()
    with patch.object(service, "_run_register_pipeline", new=AsyncMock(return_value={
        "success": True,
        "status_code": 200,
        "data": {"email": "a@example.com", "account_id": "123"},
        "error": None,
        "error_code": None,
    })), patch.object(service, "_finalize_registration_result", new=AsyncMock(return_value={
        "success": True,
        "status_code": 200,
        "data": {"identifier": "acc_123"},
        "error": None,
        "error_code": None,
    })):
        result = await service.register(identifier="acc_123")
    self.assertTrue(result["success"])
```

- [ ] **Step 2: Add failing tests for required env vars missing -> `input_invalid`**

```python
@patch.dict(os.environ, {}, clear=True)
async def test_register_fails_when_required_env_missing(self):
    service = self.ChatGPTService()
    result = await service.register()
    self.assertFalse(result["success"])
    self.assertEqual(result["error_code"], "input_invalid")
```

- [ ] **Step 3: Run targeted tests to confirm RED**

Run:
`python3 -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_reads_runtime_from_env test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_fails_when_required_env_missing -v`

Expected: FAIL (old signature still expects input path and no env loader).

- [ ] **Step 4: Implement minimal env runtime loader + register signature change**

```python
import os

async def register(self, db_session=None, identifier="default"):
    runtime_context_result = self._build_runtime_context(identifier)
    ...

def _build_runtime_context(self, identifier: str) -> dict:
    mail_domain = str(os.environ.get("REGISTER_MAIL_DOMAIN") or "").strip().lower()
    worker_base = str(os.environ.get("REGISTER_MAIL_WORKER_BASE_URL") or "").strip().rstrip("/")
    worker_token = str(os.environ.get("REGISTER_MAIL_WORKER_TOKEN") or "").strip()
    # validate required
    # build normalized register_input with fixed defaults
```

- [ ] **Step 5: Re-run targeted tests (GREEN)**

Run: same as Step 3
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add chatgpt.py test_chatgpt_register_service.py
git commit -m "refactor: make register entry env-only"
```

### Task 2: Lock env-only defaults (random email + random password, no extra env config)

**Files:**
- Modify: `test_chatgpt_register_service.py`
- Modify: `chatgpt.py`

- [ ] **Step 1: Add failing test that env-only run still generates random email under domain**

```python
@patch.dict(os.environ, {
    "REGISTER_MAIL_DOMAIN": "wwcloud.me",
    "REGISTER_MAIL_WORKER_BASE_URL": "https://worker.example.com",
    "REGISTER_MAIL_WORKER_TOKEN": "token",
}, clear=True)
async def test_prepare_identity_generates_email_from_register_mail_domain(self):
    service = self.ChatGPTService()
    ctx_result = service._build_runtime_context("acc_123")
    prepared = service._prepare_identity({"register_input": ctx_result["data"]["register_input"]})
    self.assertTrue(prepared["success"])
    email = prepared["data"]["register_input"]["resolved_email"]
    self.assertTrue(email.endswith("@wwcloud.me"))
```

- [ ] **Step 2: Add failing test that password is internally generated (not env)**

```python
self.assertTrue(bool(prepared["data"]["register_input"]["fixed_password"]))
```

- [ ] **Step 3: Run targeted tests (RED)**

Run:
`python3 -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_prepare_identity_generates_email_from_register_mail_domain -v`

Expected: FAIL before defaults are fully locked for env-only context.

- [ ] **Step 4: Implement minimal defaults in `_build_runtime_context` and keep `_prepare_identity` generation path**

Implementation constraints:
- `fixed_email` default `""`
- `fixed_password` default `""` (so `_prepare_identity` generates)
- hardcoded defaults for `register_http_timeout=15`, `mail_poll_seconds=3`, `mail_poll_max_attempts=40`
- no additional env reads

- [ ] **Step 5: Re-run targeted tests (GREEN)**

Run: same as Step 3
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add chatgpt.py test_chatgpt_register_service.py
git commit -m "test: lock env-only identity generation defaults"
```

---

## Chunk 2: Keep registration semantics while removing input-object dependency

### Task 3: Update register orchestration tests to env-driven invocation

**Files:**
- Modify: `test_chatgpt_register_service.py`
- Modify: `chatgpt.py` (only if orchestration adjustments are required)

- [ ] **Step 1: Replace `service.register({...})` call sites with `service.register(...)` + env patch helper**

Add helper:

```python
def _register_env(self, **overrides):
    base = {
        "REGISTER_MAIL_DOMAIN": "example.com",
        "REGISTER_MAIL_WORKER_BASE_URL": "https://worker.example.com",
        "REGISTER_MAIL_WORKER_TOKEN": "token",
    }
    base.update(overrides)
    return patch.dict(os.environ, base, clear=True)
```

- [ ] **Step 2: Run a focused subset that previously passed input dict into `register` (RED expected initially)**

Run:
`python3 -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_success_payload_contains_identifier test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_then_get_members_uses_returned_identifier_without_relogin test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_identifier_can_be_passed_to_get_members_without_relogin -v`

Expected: FAIL until all call sites are migrated.

- [ ] **Step 3: Finish minimal call-site migration and any signature fallout**

Rules:
- No compatibility shim for old `register_input`
- Keep `identifier` parameter behavior unchanged
- Keep envelope unchanged

- [ ] **Step 4: Re-run focused subset (GREEN)**

Run: same as Step 2
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add test_chatgpt_register_service.py chatgpt.py
git commit -m "refactor: migrate register tests to env-driven invocation"
```

### Task 4: Guard worker auth and query URL under env-only flow

**Files:**
- Modify: `test_chatgpt_register_service.py`
- Modify: `chatgpt.py` (only if test reveals mismatch)

- [ ] **Step 1: Add/adjust failing guard test for worker auth header + URL shape**

```python
self.assertEqual(called_url, "https://worker.example.com/v1/code?email=user%40example.com")
self.assertEqual(headers["Authorization"], "Bearer token")
self.assertEqual(method, "GET")
```

- [ ] **Step 2: Run the single guard test (RED if mismatch)**

Run:
`python3 -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_poll_otp_from_mail_worker_uses_v1_code_query_url -v`

Expected: PASS after prior fixes; if FAIL, fix minimally and re-run.

- [ ] **Step 3: Commit (only if code/test changed in this task)**

```bash
git add chatgpt.py test_chatgpt_register_service.py
git commit -m "test: enforce env-worker auth and OTP query-url contract"
```

---

## Chunk 3: Full-suite stabilization and verification gate

### Task 5: Remove obsolete input-based tests and keep only env contract

**Files:**
- Modify: `test_chatgpt_register_service.py`

- [ ] **Step 1: Identify tests that only validate legacy input-object knobs (non-positive runtime value from input, etc.)**

Legacy examples to remove/replace:
- tests asserting invalid `register_http_timeout` from input dict
- tests asserting invalid `mail_poll_seconds` from input dict
- tests asserting invalid `mail_poll_max_attempts` from input dict

- [ ] **Step 2: Replace with env-focused validation tests (required 3 vars only)**

```python
# missing REGISTER_MAIL_DOMAIN -> input_invalid
# missing REGISTER_MAIL_WORKER_BASE_URL -> input_invalid
# missing REGISTER_MAIL_WORKER_TOKEN -> input_invalid
```

- [ ] **Step 3: Run only replaced validation tests (GREEN)**

Run:
`python3 -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests -k "register_input_invalid_when_required_env" -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add test_chatgpt_register_service.py
git commit -m "test: replace input validation cases with env-required contract"
```

### Task 6: Final verification

**Files:**
- Verify only

- [ ] **Step 1: Run full migration test suite**

Run:
`python3 -m unittest test_chatgpt_register_service.py -v`

Expected: all PASS.

- [ ] **Step 2: Run syntax check**

Run:
`python3 -m py_compile chatgpt.py test_chatgpt_register_service.py`

Expected: no output.

- [ ] **Step 3: Validate changed file scope**

Run:
`git status --short`

Expected: only intended files changed (`chatgpt.py`, `test_chatgpt_register_service.py`, plan/spec docs if intentionally updated).

- [ ] **Step 4: Re-run continuity smoke test**

Run:
`python3 -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_identifier_can_be_passed_to_get_members_without_relogin -v`

Expected: PASS.

---

## Notes for implementers

- Keep DRY/YAGNI: do not add extra environment knobs beyond the three approved variables.
- Do not add fallback compatibility for old `register_input` API.
- Preserve response envelope and existing Team continuity semantics.
- Preserve password registration path and worker auth semantics already required by user.
