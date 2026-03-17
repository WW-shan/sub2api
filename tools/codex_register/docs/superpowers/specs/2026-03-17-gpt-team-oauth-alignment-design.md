# GPT-team OAuth Alignment Design

Date: 2026-03-17

## Goal

Fully align `chatgpt.py` refresh token acquisition with the independent OAuth method used in `AI-Account-Toolkit/GPT-team/gpt-team-new.py`, so registration completion can reliably produce `refresh_token`.

## Problem Summary

Current flow still primarily depends on registration callback/session token harvesting (`/api/auth/callback/openai` + `/api/auth/session` + optional `/oauth/token`), which is not always sufficient in production runs.

Observed runtime symptom:
- Registration steps succeed through OTP + `create_account`
- Callback and session request succeed
- `/oauth/token` is called but final payload still lacks `refresh_token`

## Scope

In scope:
- `chatgpt.py` register/token harvesting logic
- New independent OAuth token acquisition path modeled after GPT-team
- Targeted and full regression tests in `test_chatgpt_register_service.py`

Out of scope:
- Unrelated refactors
- API contract changes for returned register payload fields

## Design

### 1) Add independent OAuth helpers in `ChatGPTService`

Add internal helpers mirroring GPT-team behavior:

- `_oauth_extract_code_from_url(url)`
  - Parse OAuth `code` from query string.

- `_oauth_follow_and_extract_code(session, url)`
  - Follow redirects with bounded depth and extract `code` from redirect targets.

- `_oauth_exchange_code_for_tokens(session, code, code_verifier, client_id, redirect_uri, ...)`
  - Submit `authorization_code` exchange to `https://auth.openai.com/oauth/token`.

- `_oauth_fetch_tokens_via_independent_flow(...)`
  - Use existing session/cookies from register flow.
  - If direct callback code unavailable/insufficient, execute workspace/organization continuation path:
    - `POST /api/accounts/workspace/select`
    - optionally `POST /api/accounts/organization/select`
    - follow `continue_url` / redirect Location chain
  - Resolve `code_verifier` from `oai-client-auth-session` (top-level first, then workspace fallback).
  - Exchange final `code` via `/oauth/token`.

### 2) Register success path uses independent OAuth as primary RT source

At successful register completion, after callback/session establishment:
- Call `_oauth_fetch_tokens_via_independent_flow(...)` as primary token source.
- Merge returned `access_token` / `refresh_token` / `id_token` into compatibility payload.
- Keep current `_collect_register_session_tokens(...)` as fallback for compatibility.

### 3) Data merge policy

- Prefer independent OAuth refresh token when present.
- Keep session-derived account/workspace identifiers if OAuth token payload lacks them.
- Preserve existing output shape in `_build_register_compat_payload`.

## Testing Strategy (TDD)

1. Add failing tests first:
   - Independent OAuth path returns `refresh_token` when callback URL lacks code but workspace/organization continuation provides it.
   - Independent OAuth path is used as primary source on register completion.

2. Implement minimal production code to pass tests.

3. Re-run targeted regression tests for token extraction and register completion.

4. Re-run full `test_chatgpt_register_service.py` suite.

## Risk & Mitigation

- Risk: branching complexity in OAuth continuation flow.
  - Mitigation: bounded redirect follower + strict parsing + isolated helper functions.

- Risk: regressions in existing callback-compatible behavior.
  - Mitigation: keep fallback path and preserve existing tests.
