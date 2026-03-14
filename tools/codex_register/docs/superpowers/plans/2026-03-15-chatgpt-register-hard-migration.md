# ChatGPTService Register Hard-Migration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move registration flow into `ChatGPTService.register(...)`, keep post-register Team API usage in the same session model, and fully remove `codex_register_service.py`.

**Architecture:** Extend `chatgpt.py` with a register domain that follows existing `ChatGPTService` conventions: fixed response envelope, `_make_request` as the default request path, and centralized structured header builders. Implement in strict micro-step TDD so fallback semantics and session continuity are proven before deleting legacy code.

**Tech Stack:** Python 3, `curl_cffi.requests` / `curl_cffi.requests.AsyncSession`, `unittest` + `unittest.mock`, existing `ChatGPTService` async session cache (`self._sessions`).

---

## File Structure (locked before implementation)

- Modify: `chatgpt.py`
  - Add `register(register_input, db_session=None, identifier="default")`
  - Add focused register private methods
  - Add structured header builders (`_build_browser_base_headers`, `_build_auth_headers`, `_build_sentinel_headers`)
  - Keep existing Team methods signatures/behavior intact

- Create: `test_chatgpt_register_service.py`
  - Register contract tests (fixed response shape + error mapping)
  - Structured-header and request-path enforcement tests
  - Fallback tests (`passwordless_signup_disabled`)
  - Same-session tests (sentinel→signup→otp→create_account)
  - Register→Team continuity tests (same instance, same identifier)

- Delete: `codex_register_service.py`
  - Remove only after parity tests are green

**Hard scope boundary:** Do not modify `Dockerfile` or unrelated files for this migration unless tests are objectively blocked and the reason is documented in the commit message.

---

## Chunk 1: Lock contracts first (response shape + continuity)

### Task 1: Add failing register envelope contract tests

**Files:**
- Create: `test_chatgpt_register_service.py`
- Modify: `chatgpt.py`

- [ ] **Step 1: Write failing test for fixed top-level envelope keys**

```python
import unittest
from chatgpt import ChatGPTService


class ChatGPTRegisterContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_response_contains_fixed_top_level_keys(self):
        service = ChatGPTService()
        result = await service.register({"mail_worker_base_url": "x"})
        self.assertEqual(
            set(result.keys()),
            {"success", "status_code", "data", "error", "error_code"},
        )
```

- [ ] **Step 2: Run test to confirm failure**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_response_contains_fixed_top_level_keys -v`
Expected: FAIL with missing `register` method.

- [ ] **Step 3: Add minimal `register` stub and envelope helpers**

```python
async def register(self, register_input, db_session=None, identifier="default"):
    return self._error_result(0, "not implemented", "unknown_error")


def _success_result(self, data: dict) -> dict:
    return {
        "success": True,
        "status_code": 200,
        "data": data,
        "error": None,
        "error_code": None,
    }


def _error_result(self, status_code: int, error: str, error_code: str) -> dict:
    return {
        "success": False,
        "status_code": status_code,
        "data": None,
        "error": error,
        "error_code": error_code,
    }
```

- [ ] **Step 4: Re-run same test**

Run: same as Step 2
Expected: PASS for key-shape contract.

- [ ] **Step 5: Commit**

```bash
git add test_chatgpt_register_service.py chatgpt.py
git commit -m "test: lock register response envelope contract"
```

### Task 2: Add failing identifier and register→team continuity tests

**Files:**
- Modify: `test_chatgpt_register_service.py`
- Modify: `chatgpt.py`

- [ ] **Step 1: Write failing test that successful register payload includes `identifier`**

```python
async def test_register_success_payload_contains_identifier(self):
    service = ChatGPTService()
    # mock only external calls; execute real register once implementation exists
    result = await service.register(
        {
            "mail_worker_base_url": "x",
            "mail_worker_token": "y",
            "fixed_email": "a@b.com",
            "fixed_password": "pw",
            "mail_domain": "b.com",
        }
    )
    self.assertTrue(result["success"])
    self.assertIn("identifier", result["data"])
```

- [ ] **Step 2: Write failing continuity test (real register call then real Team-method call shape)**

```python
from unittest.mock import AsyncMock, patch


async def test_register_then_get_members_uses_returned_identifier_without_relogin(self):
    service = ChatGPTService()

    # Arrange register internals to avoid real network while running real register()
    with patch.object(service, "_run_register_pipeline", new=AsyncMock(return_value={
        "success": True,
        "status_code": 200,
        "data": {
            "email": "a@b.com",
            "identifier": "acc_123",
            "account_id": "123",
            "access_token": "at",
            "refresh_token": "rt",
            "id_token": "id",
            "session_token": "",
            "expires_at": "x",
            "plan_type": "",
            "organization_id": "",
            "workspace_id": "",
        },
        "error": None,
        "error_code": None,
    })):
        reg = await service.register({"mail_worker_base_url": "x", "mail_worker_token": "y", "fixed_email": "a@b.com", "mail_domain": "b.com"})

    with patch.object(service, "_make_request", new=AsyncMock(return_value={"success": True, "status_code": 200, "data": {"items": [], "total": 0}, "error": None})) as mocked:
        await service.get_members(
            reg["data"]["access_token"],
            reg["data"]["account_id"],
            db_session=None,
            identifier=reg["data"]["identifier"],
        )

    self.assertEqual(mocked.await_args.kwargs["identifier"], "acc_123")
```

- [ ] **Step 3: Run tests to confirm failure**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests -k identifier -v`
Expected: FAIL.

- [ ] **Step 4: Add minimal `_run_register_pipeline` hook and identifier pass-through in `register`**

```python
async def _run_register_pipeline(self, ctx: dict) -> dict:
    return self._error_result(0, "not implemented", "unknown_error")
```

- [ ] **Step 5: Re-run tests**

Run: same as Step 3
Expected: PASS for continuity contract assertions.

- [ ] **Step 6: Commit**

```bash
git add test_chatgpt_register_service.py chatgpt.py
git commit -m "feat: add register identifier and continuity contract scaffolding"
```

---

## Chunk 2: Register pipeline implementation in strict micro-TDD

### Task 3: Runtime/input validation and context construction

**Files:**
- Modify: `test_chatgpt_register_service.py`
- Modify: `chatgpt.py`

- [ ] **Step 1: Add failing test for missing `mail_worker_token` -> `input_invalid`**
- [ ] **Step 2: Add failing test for `mail_domain` required when `fixed_email` absent**
- [ ] **Step 3: Add failing test for non-positive timeout/poll values -> `input_invalid`**

- [ ] **Step 4: Run validation tests**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests -k input_invalid -v`
Expected: FAIL.

- [ ] **Step 5: Implement `_build_runtime_context` minimally**

```python
def _build_runtime_context(self, register_input: dict, identifier: str) -> dict:
    ...
```

- [ ] **Step 6: Re-run validation tests**

Run: same as Step 4
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add test_chatgpt_register_service.py chatgpt.py
git commit -m "feat: implement register runtime validation and context defaults"
```

### Task 4: Structured header builders + default request path enforcement

**Files:**
- Modify: `test_chatgpt_register_service.py`
- Modify: `chatgpt.py`

- [ ] **Step 1: Add failing tests for `_build_browser_base_headers`, `_build_auth_headers`, `_build_sentinel_headers`**
- [ ] **Step 2: Add failing test that non-special register steps call `_make_request`**

- [ ] **Step 3: Run header/path tests**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests -k "header" -v`
Expected: FAIL.

- [ ] **Step 4: Implement `_build_browser_base_headers`**
- [ ] **Step 5: Re-run only related header test**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_uses_build_browser_base_headers -v`
Expected: PASS.

- [ ] **Step 6: Implement `_build_auth_headers`**
- [ ] **Step 7: Re-run only related header test**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_uses_build_auth_headers -v`
Expected: PASS.

- [ ] **Step 8: Implement `_build_sentinel_headers`**
- [ ] **Step 9: Re-run only related header test**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_uses_build_sentinel_headers -v`
Expected: PASS.

- [ ] **Step 10: Wire non-special steps to `_make_request` and run request-path test**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_non_session_special_requests_go_through_make_request -v`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add test_chatgpt_register_service.py chatgpt.py
git commit -m "feat: add structured register header builders and request-path constraints"
```

### Task 5: Same-session special sequence + fallback semantics

**Files:**
- Modify: `test_chatgpt_register_service.py`
- Modify: `chatgpt.py`

- [ ] **Step 1: Add failing test for `_start_auth_flow` failure mapping (`auth_flow_failed`)**
- [ ] **Step 2: Run the single test and confirm FAIL**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_maps_start_auth_flow_failure -v`
Expected: FAIL.

- [ ] **Step 3: Implement `_start_auth_flow` minimally**
- [ ] **Step 4: Re-run the single test**

Run: same as Step 2
Expected: PASS.

- [ ] **Step 5: Add failing test for `_submit_signup` non-200 mapping (`signup_failed`)**
- [ ] **Step 6: Run single test and confirm FAIL**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_maps_signup_non_200_to_signup_failed -v`
Expected: FAIL.

- [ ] **Step 7: Implement `_submit_signup` minimally**
- [ ] **Step 8: Re-run single test**

Run: same as Step 6
Expected: PASS.

- [ ] **Step 9: Add failing fallback test (`passwordless_signup_disabled` triggers fallback path)**
- [ ] **Step 10: Run fallback test and confirm FAIL**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_uses_fallback_when_passwordless_disabled -v`
Expected: FAIL.

- [ ] **Step 11: Implement `_send_otp_with_fallback` minimally**
- [ ] **Step 12: Re-run fallback test**

Run: same as Step 10
Expected: PASS.

- [ ] **Step 13: Add failing OTP validate test (`otp_validate_failed`)**
- [ ] **Step 14: Run OTP validate test and confirm FAIL**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_maps_otp_validate_non_200_to_otp_validate_failed -v`
Expected: FAIL.

- [ ] **Step 15: Implement `_poll_and_validate_otp` minimally**
- [ ] **Step 16: Re-run OTP validate test**

Run: same as Step 14
Expected: PASS.

- [ ] **Step 17: Add failing create-account test (`create_account_failed`)**
- [ ] **Step 18: Run create-account test and confirm FAIL**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_maps_create_account_non_200_to_create_account_failed -v`
Expected: FAIL.

- [ ] **Step 19: Implement `_create_account` minimally**
- [ ] **Step 20: Re-run create-account test**

Run: same as Step 18
Expected: PASS.

- [ ] **Step 21: Add failing same-session invariant test (sentinel→signup→otp→create_account same session/cookie jar)**
- [ ] **Step 22: Run same-session test and confirm FAIL**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_special_steps_share_single_session_cookie_jar -v`
Expected: FAIL.

- [ ] **Step 23: Wire `_run_register_pipeline` to reuse one session object across special steps**
- [ ] **Step 24: Re-run same-session test**

Run: same as Step 22
Expected: PASS.

- [ ] **Step 25: Commit**

```bash
git add test_chatgpt_register_service.py chatgpt.py
git commit -m "feat: implement register special-step pipeline with fallback and same-session guarantees"
```

---

## Chunk 3: Token finalization, legacy deletion, and full verification

### Task 6: Token exchange + enrichment + real continuity check

**Files:**
- Modify: `test_chatgpt_register_service.py`
- Modify: `chatgpt.py`

- [ ] **Step 1: Add failing test for token finalization success payload**
- [ ] **Step 2: Add failing test mapping token exchange failure -> `token_finalize_failed`**

- [ ] **Step 3: Run token tests and confirm failure**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests -k token -v`
Expected: FAIL.

- [ ] **Step 4: Implement `_exchange_tokens` minimally**
- [ ] **Step 5: Re-run token tests**

Run: same as Step 3
Expected: PARTIAL PASS.

- [ ] **Step 6: Implement `_enrich_account_context` minimally (best-effort fill plan/org/workspace)**
- [ ] **Step 7: Re-run enrichment-related tests**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests -k enrich -v`
Expected: PASS.

- [ ] **Step 8: Implement `_finalize_registration_result` and full `register` orchestration**
- [ ] **Step 9: Re-run token tests**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests -k token -v`
Expected: PASS.

- [ ] **Step 10: Add failing real continuity test (real `register` call + `get_members` with returned identifier)**
- [ ] **Step 11: Run continuity test and confirm FAIL**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_identifier_can_be_passed_to_get_members_without_relogin -v`
Expected: FAIL.

- [ ] **Step 12: Implement minimal continuity fixes (no relogin path, identifier propagation only)**
- [ ] **Step 13: Re-run continuity test**

Run: same as Step 11
Expected: PASS.

- [ ] **Step 14: Commit**

```bash
git add test_chatgpt_register_service.py chatgpt.py
git commit -m "feat: finalize register token pipeline and register-to-team continuity"
```

### Task 7: Remove legacy file and enforce no dangling references

**Files:**
- Delete: `codex_register_service.py`
- Modify: `test_chatgpt_register_service.py`

- [ ] **Step 1: Add failing deletion guard test with stable path resolution**

```python
from pathlib import Path


class LegacyRemovalGuards(unittest.TestCase):
    def test_legacy_codex_register_service_file_removed(self):
        repo_root = Path(__file__).resolve().parent
        self.assertFalse((repo_root / "codex_register_service.py").exists())
```

- [ ] **Step 2: Run guard test pre-delete to confirm FAIL**

Run: `python -m unittest test_chatgpt_register_service.LegacyRemovalGuards.test_legacy_codex_register_service_file_removed -v`
Expected: FAIL (file exists).

- [ ] **Step 3: Delete `codex_register_service.py`**

Action: remove file from repository.

- [ ] **Step 4: Re-run guard test**

Run: same as Step 2
Expected: PASS.

- [ ] **Step 5: Search for dangling references to legacy module**

Run: `git grep -n "codex_register_service" -- "*.py" || true`
Expected: no output.

- [ ] **Step 6: Search for legacy `run(proxy)` call shape**

Run: `git grep -n "run(proxy" -- "*.py" || true`
Expected: no output.

- [ ] **Step 7: Run full register test file**

Run: `python -m unittest test_chatgpt_register_service.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -u chatgpt.py test_chatgpt_register_service.py codex_register_service.py
git commit -m "refactor: remove codex_register_service after ChatGPTService register migration"
```

### Task 8: Final verification gate

**Files:**
- Verify only

- [ ] **Step 1: Run full unit suite for this migration**

Run: `python -m unittest test_chatgpt_register_service.py -v`
Expected: all PASS.

- [ ] **Step 2: Run syntax check**

Run: `python -m py_compile chatgpt.py test_chatgpt_register_service.py`
Expected: no output.

- [ ] **Step 3: Validate working tree scope**

Run: `git status --short`
Expected: only intended files changed (`chatgpt.py`, `test_chatgpt_register_service.py`, deletion of `codex_register_service.py`, plan/spec docs if updated).

- [ ] **Step 4: Validate continuity smoke test once more**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_identifier_can_be_passed_to_get_members_without_relogin -v`
Expected: PASS.

---

## Notes for implementers

- Keep scope tight (DRY/YAGNI): registration migration only.
- Do not rewrite Team methods except minimal continuity glue required by tests.
- Keep structured content reusable: no copied static header blocks from legacy file.
- Default request path stays `_make_request`; special same-session steps are the only allowed exception.
