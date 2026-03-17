# GPT-team Token Alignment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align codex register token harvesting with `AI-Account-Toolkit/GPT-team/gpt-team-new.py` so successful registrations reliably persist `access_token`, `refresh_token`, `session_token`, and `account_id`.

**Architecture:** Keep the existing register pipeline, but unify post-callback token harvesting into one deterministic path: (1) read ChatGPT session, (2) always try callback `code -> oauth/token` exchange when `code` exists, (3) resolve account_id from JWT auth payload with session fallback. Apply this in all successful branches including `callback-complete`.

**Tech Stack:** Python 3.13, asyncio, curl_cffi AsyncSession wrapper, pytest/unittest mocks.

---

## Chunk 1: Compare and normalize token extraction flow

### Task 1: Make token collection deterministic and branch-consistent

**Files:**
- Modify: `chatgpt.py:1111-1210` (`_collect_register_session_tokens`)
- Modify: `chatgpt.py:1383-1465` (`about-you`, `callback-complete`, and full-flow success branches)
- Test: `test_chatgpt_register_service.py:575-640`

- [ ] **Step 1: Write failing test for callback-complete branch token harvesting**

```python
async def test_register_callback_complete_collects_tokens_with_callback_code(self):
    # authorize returns callback-complete URL with code
    # assert payload contains access/refresh/session/account after register()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest D:/Code/sub2api/tools/codex_register/test_chatgpt_register_service.py -k callback_complete_collects_tokens`
Expected: FAIL because callback-complete currently bypasses token collection.

- [ ] **Step 3: Implement minimal behavior in register()**

- In `callback-complete` branch, parse callback URL and call `_collect_register_session_tokens(..., callback_url=...)`.
- Merge collected fields through `_build_register_compat_payload(..., extra=session_tokens)`.
- Keep existing behavior for email/password/OTP pipeline untouched.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest D:/Code/sub2api/tools/codex_register/test_chatgpt_register_service.py -k callback_complete_collects_tokens`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add chatgpt.py test_chatgpt_register_service.py
git commit -m "fix: collect callback-complete tokens after register success"
```


### Task 2: Always attempt oauth token exchange when callback code is present

**Files:**
- Modify: `chatgpt.py:1111-1198` (`_collect_register_session_tokens`)
- Test: `test_chatgpt_register_service.py:575-624`

- [ ] **Step 1: Write failing test for oauth exchange trigger policy**

```python
async def test_collect_register_session_tokens_exchanges_code_even_with_session_refresh_present(self):
    # session returns refreshToken=rt_old
    # oauth/token returns refresh_token=rt_new, id_token=id_new
    # assert result uses oauth refresh/id values (gpt-team style)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest D:/Code/sub2api/tools/codex_register/test_chatgpt_register_service.py -k exchanges_code_even_with_session_refresh_present`
Expected: FAIL because exchange is currently conditional on missing refresh token.

- [ ] **Step 3: Implement minimal logic update**

- In `_collect_register_session_tokens`, when `callback_code` exists:
  - always call `POST https://auth.openai.com/oauth/token`
  - payload uses form encoding and callback code
  - if oauth returns refresh/id/access fields, prefer oauth values over session values where present
- Keep session values as fallback if oauth returns partial data.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest D:/Code/sub2api/tools/codex_register/test_chatgpt_register_service.py -k exchanges_code_even_with_session_refresh_present`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add chatgpt.py test_chatgpt_register_service.py
git commit -m "fix: prioritize oauth token exchange from callback code"
```


## Chunk 2: Account ID and payload completeness

### Task 3: Make account_id resolution follow GPT-team precedence

**Files:**
- Modify: `chatgpt.py:1178-1190`
- Test: `test_chatgpt_register_service.py:575-624`

- [ ] **Step 1: Write failing test for account_id precedence**

```python
async def test_collect_register_session_tokens_prefers_jwt_chatgpt_account_id(self):
    # session currentAccountId=acc_session
    # jwt auth.chatgpt_account_id=acc_jwt
    # assert account_id == acc_jwt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest D:/Code/sub2api/tools/codex_register/test_chatgpt_register_service.py -k prefers_jwt_chatgpt_account_id`
Expected: FAIL if session ID still wins.

- [ ] **Step 3: Implement minimal account_id ordering**

- Decode JWT from chosen access token.
- If JWT contains `chatgpt_account_id` (or `organization_id` fallback), use it.
- Else fallback to `currentAccountId`, else first `accounts` key.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest D:/Code/sub2api/tools/codex_register/test_chatgpt_register_service.py -k prefers_jwt_chatgpt_account_id`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add chatgpt.py test_chatgpt_register_service.py
git commit -m "fix: align account_id precedence with GPT-team jwt parsing"
```


### Task 4: Verify register payload persists all required fields

**Files:**
- Modify: `chatgpt.py:1158-1238` (`_build_register_compat_payload`, `_collect_register_session_tokens` output)
- Test: `test_chatgpt_register_service.py:520-640`

- [ ] **Step 1: Write failing end-to-end unit test for payload completeness**

```python
async def test_register_success_payload_contains_all_persisted_fields(self):
    # after register() assert non-empty: access_token, refresh_token, session_token, account_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest D:/Code/sub2api/tools/codex_register/test_chatgpt_register_service.py -k payload_contains_all_persisted_fields`
Expected: FAIL on missing fields.

- [ ] **Step 3: Implement minimal normalization**

- Ensure `_collect_register_session_tokens` returns all available fields with stable names.
- Ensure `_build_register_compat_payload` accepts and forwards: `access_token`, `refresh_token`, `session_token`, `account_id`, `id_token`.
- No new schema fields beyond current model (YAGNI).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest D:/Code/sub2api/tools/codex_register/test_chatgpt_register_service.py -k payload_contains_all_persisted_fields`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add chatgpt.py test_chatgpt_register_service.py
git commit -m "test: enforce complete persisted token payload on register success"
```


## Chunk 3: Full verification and handoff

### Task 5: Regression verification before completion

**Files:**
- Test: `test_chatgpt_register_service.py`
- Verify runtime behavior via service logs

- [ ] **Step 1: Run focused regression set**

Run:
`python -m pytest D:/Code/sub2api/tools/codex_register/test_chatgpt_register_service.py -k "collect_register_session_tokens or register_persists_tokens or validate_otp_code or register_create_account_uses_letters_and_spaces_only_name"`
Expected: all selected tests PASS.

- [ ] **Step 2: Run full register test file**

Run:
`python -m pytest D:/Code/sub2api/tools/codex_register/test_chatgpt_register_service.py`
Expected: full suite PASS, exit code 0.

- [ ] **Step 3: Optional runtime smoke check**

Run one real registration in workflow and verify `/accounts` shows non-empty `access_token`, `refresh_token`, `session_token`, `account_id` for new rows.
Expected: fields are persisted (not `-`) for newly created records.

- [ ] **Step 4: Final commit**

```bash
git add chatgpt.py test_chatgpt_register_service.py
git commit -m "fix: align codex register token extraction with gpt-team flow"
```

- [ ] **Step 5: Request code review**

Use `@superpowers:requesting-code-review` before merge.

---

## Implementation guardrails

- Follow `@superpowers:test-driven-development` for each behavior change.
- Use one failing test per behavior before code edits.
- Keep changes limited to token extraction and payload mapping (DRY/YAGNI).
- Do not refactor unrelated register pipeline logic.
- Before any completion claim, run `@superpowers:verification-before-completion`.
