# GPT-team OAuth Full Alignment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make register success reliably return `refresh_token` by aligning token acquisition with `AI-Account-Toolkit/GPT-team/gpt-team-new.py` independent OAuth method.

**Architecture:** Keep current registration flow for account creation/OTP, then run an independent OAuth continuation/token-exchange pipeline as the primary token source. Reuse existing session/cookies (`oai-client-auth-session`) and follow `workspace/select`/`organization/select` continuation branches to recover auth code, then call `/oauth/token`. Keep existing session-harvest path as fallback only.

**Tech Stack:** Python 3.13, asyncio, `curl_cffi` `AsyncSession`, `unittest` + `AsyncMock`, existing `ChatGPTService` result envelope pattern.

---

Reference spec: `docs/superpowers/specs/2026-03-17-gpt-team-oauth-alignment-design.md`

## File Structure & Responsibilities

- Modify: `chatgpt.py`
  - Add focused OAuth helper methods near existing register token helpers (`chatgpt.py:1112-1290` area).
  - Keep helpers isolated and composable:
    - code extraction
    - redirect/continue traversal
    - workspace/organization select branching
    - code exchange
  - Update `register(...)` (`chatgpt.py:1306+`) to use independent OAuth token fetch as primary source.

- Modify: `test_chatgpt_register_service.py`
  - Add failing-first tests for independent OAuth primary path and workspace/organization continuation branches.
  - Preserve existing behavior tests and avoid removing current coverage.

## Chunk 1: Lock in behavior with failing tests

### Task 1: Add independent OAuth primary-path regression tests

**Files:**
- Modify: `test_chatgpt_register_service.py`
- Test: `test_chatgpt_register_service.py`

- [ ] **Step 1: Add failing test for workspace continuation code recovery**

```python
async def test_oauth_independent_flow_recovers_code_from_workspace_continue_url(self):
    # arrange: callback url has no code, auth-session cookie has workspace id/code_verifier
    # workspace/select returns continue_url containing callback code
    # oauth/token returns refresh_token
    ...
    self.assertEqual(tokens["refresh_token"], "rt_from_independent_oauth")
```

- [ ] **Step 2: Run single test to verify RED**

Run:
`python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_oauth_independent_flow_recovers_code_from_workspace_continue_url`

Expected: `FAIL` (method missing or behavior absent)

- [ ] **Step 3: Add failing test for register() preferring independent OAuth token source**

```python
async def test_register_prefers_independent_oauth_refresh_token(self):
    # arrange: callback/session collection returns empty refresh_token
    # independent oauth helper returns refresh_token
    ...
    self.assertEqual(result["data"]["refresh_token"], "rt_independent")
```

- [ ] **Step 4: Run both new tests to verify RED**

Run:
`python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_oauth_independent_flow_recovers_code_from_workspace_continue_url test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_prefers_independent_oauth_refresh_token`

Expected: both `FAIL` for expected reason.

- [ ] **Step 5: Commit tests-only red state (optional if policy allows red commits)**

```bash
git add test_chatgpt_register_service.py
git commit -m "test: add failing regressions for independent OAuth refresh token flow"
```

## Chunk 2: Implement independent OAuth helpers and register integration

### Task 2: Implement minimal independent OAuth helper chain in ChatGPTService

**Files:**
- Modify: `chatgpt.py`
- Test: `test_chatgpt_register_service.py`

- [ ] **Step 1: Add URL code extractor helper**

```python
def _oauth_extract_code_from_url(self, url: str) -> str:
    # parse query code=...
```

- [ ] **Step 2: Add redirect/continue traversal helper**

```python
async def _oauth_follow_and_extract_code(self, session, url, db_session, identifier, proxy=None) -> str:
    # bounded follow; supports continue_url/location
```

- [ ] **Step 3: Add workspace/organization continuation helper**

```python
async def _oauth_resolve_code_via_workspace_org(self, session, auth_session_payload, ... ) -> str:
    # POST /api/accounts/workspace/select
    # optional POST /api/accounts/organization/select
    # follow continue_url/location and extract code
```

- [ ] **Step 4: Add token exchange helper**

```python
async def _oauth_exchange_code_for_tokens(self, session, code, code_verifier, oauth_client_id, ...):
    # POST https://auth.openai.com/oauth/token (form-urlencoded)
```

- [ ] **Step 5: Add orchestrator helper**

```python
async def _oauth_fetch_tokens_via_independent_flow(self, db_session, identifier, proxy, callback_url, oauth_client_id):
    # 1) parse callback code
    # 2) if absent, resolve via workspace/org
    # 3) exchange code for tokens
    # 4) return normalized dict: access_token/refresh_token/id_token
```

- [ ] **Step 6: Run the new tests to verify GREEN for helper behavior**

Run:
`python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_oauth_independent_flow_recovers_code_from_workspace_continue_url`

Expected: `OK`.

### Task 3: Make register() use independent OAuth result as primary source

**Files:**
- Modify: `chatgpt.py`
- Test: `test_chatgpt_register_service.py`

- [ ] **Step 1: Integrate helper call at register success exits**

Apply in all successful exits after callback/session establishment:
- about-you branch return path
- callback-complete branch return path
- default/full flow return path

- [ ] **Step 2: Merge payload with clear precedence**

Precedence order:
1. independent OAuth (`refresh_token` strongest)
2. existing `_collect_register_session_tokens(...)` values
3. default empty fields

- [ ] **Step 3: Keep fallback compatibility path**

Do not remove existing `_collect_register_session_tokens(...)`; use it for account/session fields and fallback token values.

- [ ] **Step 4: Run register preference test to verify GREEN**

Run:
`python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_prefers_independent_oauth_refresh_token`

Expected: `OK` and payload contains independent OAuth refresh token.

- [ ] **Step 5: Commit implementation**

```bash
git add chatgpt.py test_chatgpt_register_service.py
git commit -m "feat: align register token acquisition with independent GPT-team OAuth flow"
```

## Chunk 3: Regression verification and handoff

### Task 4: Verify no regressions and document evidence

**Files:**
- Modify (if needed): `test_chatgpt_register_service.py`
- Verify: `chatgpt.py`, `test_chatgpt_register_service.py`

- [ ] **Step 1: Run targeted token-flow suite**

Run:
`python -m unittest test_chatgpt_register_service.ChatGPTRegisterContractTests.test_collect_register_session_tokens_recovers_code_via_workspace_select_when_callback_has_no_code test_chatgpt_register_service.ChatGPTRegisterContractTests.test_collect_register_session_tokens_uses_code_verifier_from_auth_session_top_level test_chatgpt_register_service.ChatGPTRegisterContractTests.test_collect_register_session_tokens_prefers_oauth_refresh_token_when_present test_chatgpt_register_service.ChatGPTRegisterContractTests.test_collect_register_session_tokens_uses_dynamic_client_id_from_signin_authorize_url test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_unknown_path_uses_dynamic_client_id_for_token_exchange test_chatgpt_register_service.ChatGPTRegisterContractTests.test_oauth_independent_flow_recovers_code_from_workspace_continue_url test_chatgpt_register_service.ChatGPTRegisterContractTests.test_register_prefers_independent_oauth_refresh_token`

Expected: all `OK`.

- [ ] **Step 2: Run full register contract suite**

Run:
`python -m unittest test_chatgpt_register_service.py`

Expected: full suite `OK`.

- [ ] **Step 3: Inspect diff for scope control (DRY/YAGNI)**

Run:
`git diff -- chatgpt.py test_chatgpt_register_service.py`

Expected: only token acquisition alignment and test additions.

- [ ] **Step 4: Final verification before completion (@superpowers:verification-before-completion)**

Re-run the full suite command immediately before claiming done.

- [ ] **Step 5: Commit verification cleanups (if any)**

```bash
git add chatgpt.py test_chatgpt_register_service.py
git commit -m "test: lock independent OAuth token flow regressions"
```

## Skills to apply during execution

- `@superpowers:subagent-driven-development` (preferred execution mode)
- `@superpowers:test-driven-development` (strict red-green)
- `@superpowers:systematic-debugging` (if any test fails unexpectedly)
- `@superpowers:verification-before-completion` (before success claims)
