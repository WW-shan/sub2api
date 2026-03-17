# GPT-team Register Strong-Clone Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `ChatGPTService.register(...)` internals to strongly match `AI-Account-Toolkit/GPT-team/gpt-team-new.py` two-stage flow (register landing + independent OAuth token fetch), while preserving existing `register` API and output contract.

**Architecture:** Keep current registration landing path to ensure account creation/OTP completion, then always execute a GPT-team-style independent OAuth login/token exchange pipeline as the primary token source. Use callback/session-derived data only as supplemental metadata and fallback for non-token fields. Treat missing `refresh_token` after independent OAuth as hard failure so successful `register` always returns a usable refresh token.

**Tech Stack:** Python 3.13, asyncio, curl_cffi `AsyncSession`, existing `ChatGPTService` request wrappers, `unittest` + `AsyncMock`.

---

Reference spec: `docs/superpowers/specs/2026-03-17-gpt-team-oauth-alignment-design.md`
Reference behavior source: `AI-Account-Toolkit/GPT-team/gpt-team-new.py` (`ProtocolRegistrar.register` + `perform_http_oauth_login`)

## File Structure & Responsibilities

- Modify: `chatgpt.py`
  - Add focused independent OAuth helper chain in register token area.
  - Rewire `register(...)` success exits to run independent OAuth stage unconditionally.
  - Keep outward response envelope and payload schema unchanged.

- Modify: `test_chatgpt_register_service.py`
  - Add failing-first tests for strong-clone behavior and hard-failure semantics.
  - Keep existing regression coverage for session-token compatibility.

- Verify only (no schema change): `codex_register_service.py`
  - Ensure returned fields still satisfy downstream persistence and resume/invite workflow expectations.

## Chunk 1: Lock required behavior with failing tests

### Task 1: Encode strong-clone token semantics in tests

**Files:**
- Modify: `test_chatgpt_register_service.py`
- Test: `test_chatgpt_register_service.py`

- [ ] **Step 1: Add failing test for workspace/select `final_url` code recovery (if absent, add)**

```python
async def test_collect_register_session_tokens_extracts_code_from_workspace_select_final_url(self):
    ...
    self.assertEqual(payload.get("refresh_token"), "rt_final_url")
```

- [ ] **Step 2: Run the single test and verify RED**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_collect_register_session_tokens_extracts_code_from_workspace_select_final_url`
Expected: `FAIL` before implementation.

- [ ] **Step 3: Add failing test: register must fail when independent OAuth returns no refresh_token**

```python
async def test_register_fails_when_independent_oauth_missing_refresh_token(self):
    # arrange register landing success + independent oauth returns access only
    self.assertFalse(result["success"])
    self.assertEqual(result["error_code"], "refresh_token_missing_after_oauth")
```

- [ ] **Step 4: Add failing test: register success uses independent OAuth refresh token as authoritative**

```python
async def test_register_strong_clone_uses_independent_oauth_refresh_token(self):
    self.assertTrue(result["success"])
    self.assertEqual(result["data"]["refresh_token"], "rt_independent")
```

- [ ] **Step 5: Run new tests and verify RED**

Run:
`python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_fails_when_independent_oauth_missing_refresh_token test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_strong_clone_uses_independent_oauth_refresh_token`
Expected: both `FAIL` for missing behavior.

## Chunk 2: Implement GPT-team-style independent OAuth pipeline

### Task 2: Add independent OAuth helper chain in `chatgpt.py`

**Files:**
- Modify: `chatgpt.py` (token collection / register helper section)
- Test: `test_chatgpt_register_service.py`

- [ ] **Step 1: Add `_oauth_extract_code_from_url(...)` helper**

```python
def _oauth_extract_code_from_url(self, raw_url: str) -> str:
    ...
```

- [ ] **Step 2: Add `_oauth_follow_and_extract_code(...)` helper with bounded depth**

```python
async def _oauth_follow_and_extract_code(self, *, session, url, db_session, identifier, proxy, max_depth=10):
    ...
```

- [ ] **Step 3: Add `_oauth_resolve_code_via_workspace_org(...)` helper**

```python
async def _oauth_resolve_code_via_workspace_org(self, *, session, auth_session_payload, consent_url, ...):
    # POST /api/accounts/workspace/select
    # optional POST /api/accounts/organization/select
    # parse continue_url/redirect_url/final_url/url/Location
```

- [ ] **Step 4: Add `_oauth_exchange_code_for_tokens(...)` helper**

```python
async def _oauth_exchange_code_for_tokens(self, *, session, code, code_verifier, oauth_client_id, oauth_redirect_uri, ...):
    # POST https://auth.openai.com/oauth/token
```

- [ ] **Step 5: Add orchestrator `_fetch_independent_oauth_tokens_after_register(...)`**

```python
async def _fetch_independent_oauth_tokens_after_register(self, *, db_session, identifier, proxy, email, password, authorize_client_id):
    # mirror perform_http_oauth_login flow using existing session
```

- [ ] **Step 6: Run helper-specific tests to verify GREEN**

Run:
`python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_collect_register_session_tokens_extracts_code_from_workspace_select_redirect_url test_chatgpt_register_service.ChatGPTRegisterContractTests.test_collect_register_session_tokens_extracts_code_from_workspace_select_final_url`
Expected: `OK`.

## Chunk 3: Rewire register() to strong-clone two-stage flow

### Task 3: Enforce independent OAuth as required second stage

**Files:**
- Modify: `chatgpt.py` (`register(...)` success branches)
- Test: `test_chatgpt_register_service.py`

- [ ] **Step 1: Keep stage A (register landing) unchanged in semantics**

Preserve current account creation/OTP/callback flow and branching.

- [ ] **Step 2: Replace dual `_collect_register_session_tokens(...)` token strategy with explicit stage B independent OAuth call**

At each success exit:
1. collect session-derived metadata (`session_token`, `account_id`, etc.)
2. execute independent OAuth helper
3. if independent OAuth missing refresh token -> fail with `refresh_token_missing_after_oauth`
4. merge payload with priority:
   - independent OAuth token fields first
   - session-derived non-token metadata next

- [ ] **Step 3: Keep payload/output compatibility**

Ensure `_build_register_compat_payload(...)` still returns same keys used by `codex_register_service.py`.

- [ ] **Step 4: Run register-focused tests and verify GREEN**

Run:
`python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_strong_clone_uses_independent_oauth_refresh_token test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_fails_when_independent_oauth_missing_refresh_token test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_prefers_independent_oauth_refresh_token`
Expected: `OK`.

## Chunk 4: Regression verification and evidence

### Task 4: Validate no regressions and downstream compatibility

**Files:**
- Verify: `chatgpt.py`, `test_chatgpt_register_service.py`, `codex_register_service.py`

- [ ] **Step 1: Run full register contract suite**

Run: `python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests`
Expected: all tests `OK`.

- [ ] **Step 2: Run codex register service suite**

Run: `python -m unittest test_codex_register_service`
Expected: all tests `OK`.

- [ ] **Step 3: Verify scope with diff**

Run: `git diff -- chatgpt.py test_chatgpt_register_service.py`
Expected: only strong-clone flow + tests changes.

- [ ] **Step 4: Final verification gate (@superpowers:verification-before-completion)**

Immediately rerun both full suites before claiming completion.

- [ ] **Step 5: Commit in focused chunks**

```bash
git add chatgpt.py test_chatgpt_register_service.py
git commit -m "feat: strong-clone GPT-team independent OAuth token flow in register"
```

## Skills required during execution

- `@superpowers:subagent-driven-development`
- `@superpowers:test-driven-development`
- `@superpowers:systematic-debugging`
- `@superpowers:verification-before-completion`
