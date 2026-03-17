# Unify Worker Email/OTP in gpt-team-new.py Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all legacy multi-mailbox/JWT email logic from `gpt-team-new.py` and use one unified Worker-based email+OTP flow (same method family as `chatgpt.py`) for both child registration and mother-account OTP login.

**Architecture:** Keep a single-file runtime (`gpt-team-new.py`) while replacing old mailbox helpers with a compact Worker adapter layer copied/adapted from `chatgpt.py` patterns: resolve email, poll OTP from Worker endpoint, normalize OTP payload extraction. Wire both registration and mother login OTP branches to this adapter. Delete all old temp-mail/JWT-based paths with no compatibility fallback.

**Tech Stack:** Python 3, requests, YAML config, existing HTTP OAuth/Sentinel flow in `gpt-team-new.py`.

---

## File Structure / Responsibility Map

- Modify: `gpt-team-new.py`
  - Replace config contract from `temp_mail.*` to unified Worker config (`mail_worker_base_url`, `mail_worker_token`, optional polling knobs).
  - Remove old mailbox/JWT helpers and references.
  - Add Worker OTP adapter helpers (ported from `chatgpt.py` behavior, synchronous requests style for this file).
  - Rewire registration OTP and mother OTP login to use unified adapter.
- Modify: `test_chatgpt_register_service.py`
  - Add focused tests for Worker OTP payload extraction semantics (mirroring `chatgpt.py` key priority).
- Create: `test_gpt_team_new_worker_mail.py`
  - Add unit-level tests for new helper methods in `gpt-team-new.py` (payload extraction + polling loop behavior with mocked HTTP responses).

---

## Chunk 1: Replace config contract and remove legacy mailbox layer

### Task 1: Switch to unified Worker config in `gpt-team-new.py`

**Files:**
- Modify: `gpt-team-new.py` (config load section near top)
- Test: `test_gpt_team_new_worker_mail.py`

- [ ] **Step 1: Write failing test for new config keys being required/used**

```python
# test_gpt_team_new_worker_mail.py

def test_worker_config_keys_present_in_module_contract():
    # assert module exposes unified mail worker keys and does not require temp_mail domains/admin password
    ...
```

- [ ] **Step 2: Run targeted test to verify failure**

Run: `pytest test_gpt_team_new_worker_mail.py::test_worker_config_keys_present_in_module_contract -v`
Expected: FAIL because module still depends on `temp_mail` structure.

- [ ] **Step 3: Implement minimal config refactor**

In `gpt-team-new.py`:
- Remove:
  - `TEMP_MAIL_WORKER_DOMAIN`
  - `TEMP_MAIL_EMAIL_DOMAINS`
  - `TEMP_MAIL_ADMIN_PASSWORD`
- Add:
  - `MAIL_WORKER_BASE_URL`
  - `MAIL_WORKER_TOKEN`
  - optional: `MAIL_POLL_SECONDS`, `MAIL_POLL_MAX_ATTEMPTS`

- [ ] **Step 4: Re-run targeted test**

Run: `pytest test_gpt_team_new_worker_mail.py::test_worker_config_keys_present_in_module_contract -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gpt-team-new.py test_gpt_team_new_worker_mail.py
git commit -m "refactor: switch gpt-team-new to unified mail worker config"
```

### Task 2: Delete legacy mailbox/JWT helpers and call sites

**Files:**
- Modify: `gpt-team-new.py`
- Test: `test_gpt_team_new_worker_mail.py`

- [ ] **Step 1: Write failing test asserting legacy helper symbols are removed**

```python

def test_legacy_mail_helpers_removed():
    # ensure removed: create_temp_email, _get_jwt_for_address, fetch_emails_list, wait_for_otp
    ...
```

- [ ] **Step 2: Run test to verify it fails initially**

Run: `pytest test_gpt_team_new_worker_mail.py::test_legacy_mail_helpers_removed -v`
Expected: FAIL while legacy functions still exist.

- [ ] **Step 3: Remove legacy helpers and dead references**

Delete from `gpt-team-new.py`:
- `create_temp_email`
- `_get_jwt_for_address`
- `fetch_emails_list`
- `wait_for_otp`
- any old temp-mail JWT usage in child and mother flows.

- [ ] **Step 4: Run full worker-mail test file**

Run: `pytest test_gpt_team_new_worker_mail.py -v`
Expected: PASS for removal checks.

- [ ] **Step 5: Commit**

```bash
git add gpt-team-new.py test_gpt_team_new_worker_mail.py
git commit -m "refactor: remove legacy temp-mail and jwt mailbox logic"
```

---

## Chunk 2: Introduce unified Worker OTP adapter (ported behavior)

### Task 3: Add OTP payload extractor compatible with `chatgpt.py`

**Files:**
- Modify: `gpt-team-new.py`
- Modify: `test_chatgpt_register_service.py`
- Test: `test_gpt_team_new_worker_mail.py`

- [ ] **Step 1: Write failing tests for payload extraction precedence**

```python
# prioritize keys in this order: otp_code, code, otp, verification_code
# then nested data.{same keys}
```

- [ ] **Step 2: Run tests to verify failure**

Run:
- `pytest test_gpt_team_new_worker_mail.py::test_extract_otp_from_worker_payload_priority -v`
- `pytest test_chatgpt_register_service.py -k otp -v`
Expected: FAIL for new helper missing.

- [ ] **Step 3: Implement extractor in `gpt-team-new.py`**

Add helper:
- `_extract_otp_code_from_payload(payload: Dict[str, Any]) -> str`

Match `chatgpt.py` semantics:
- top-level key scan first
- nested `data` scan second
- return empty string when absent.

- [ ] **Step 4: Re-run tests**

Run same commands; expected PASS.

- [ ] **Step 5: Commit**

```bash
git add gpt-team-new.py test_gpt_team_new_worker_mail.py test_chatgpt_register_service.py
git commit -m "feat: add worker otp payload extraction compatible with chatgpt flow"
```

### Task 4: Add unified Worker OTP polling helper

**Files:**
- Modify: `gpt-team-new.py`
- Test: `test_gpt_team_new_worker_mail.py`

- [ ] **Step 1: Write failing tests for polling success/timeout/auth failure**

```python
# cases:
# 1) returns otp when worker responds with code
# 2) returns None/"" on timeout
# 3) aborts early on auth/network errors (non-retriable policy per design)
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `pytest test_gpt_team_new_worker_mail.py -k poll_worker_otp -v`
Expected: FAIL because helper missing.

- [ ] **Step 3: Implement polling helper in `gpt-team-new.py`**

Add helper(s):
- `_poll_otp_from_worker(email: str, poll_seconds: float, poll_max_attempts: int) -> Optional[str]`

Behavior:
- GET `{MAIL_WORKER_BASE_URL}/v1/code?email=<urlencoded>`
- `Authorization: Bearer {MAIL_WORKER_TOKEN}`
- parse via `_extract_otp_code_from_payload`
- poll with configured interval/attempts
- timeout returns no code.

- [ ] **Step 4: Re-run polling tests**

Run: `pytest test_gpt_team_new_worker_mail.py -k poll_worker_otp -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gpt-team-new.py test_gpt_team_new_worker_mail.py
git commit -m "feat: add unified worker otp polling helper"
```

---

## Chunk 3: Rewire child registration and mother OTP login

### Task 5: Rewire child registration flow to unified Worker email+OTP

**Files:**
- Modify: `gpt-team-new.py`
- Test: `test_gpt_team_new_worker_mail.py`

- [ ] **Step 1: Write failing integration-style unit test for register path OTP source**

```python
# assert ProtocolRegistrar.register and register_one_account no longer consume jwt_token mailbox flow
# and call worker polling helper for OTP retrieval
```

- [ ] **Step 2: Run test and verify failure**

Run: `pytest test_gpt_team_new_worker_mail.py -k register_flow_uses_worker_otp -v`
Expected: FAIL with old signature/old flow.

- [ ] **Step 3: Implement minimal rewiring**

In `gpt-team-new.py`:
- `ProtocolRegistrar.register(...)` remove `jwt_token` dependency.
- Replace OTP wait call to unified Worker helper using resolved child email.
- In `register_one_account(...)`, replace old mailbox creation logic with single worker-email generation strategy based on config contract (one worker source only), then proceed with registration.

- [ ] **Step 4: Re-run targeted tests**

Run: `pytest test_gpt_team_new_worker_mail.py -k "register_flow_uses_worker_otp or extract_otp or poll_worker_otp" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gpt-team-new.py test_gpt_team_new_worker_mail.py
git commit -m "refactor: route child registration otp through unified worker"
```

### Task 6: Rewire mother account OTP login to unified Worker

**Files:**
- Modify: `gpt-team-new.py`
- Test: `test_gpt_team_new_worker_mail.py`

- [ ] **Step 1: Write failing test for mother OTP branch using worker helper**

```python
# refresh_team_session_http / chatgpt_http_login otp branch uses unified worker polling
# no _get_jwt_for_address path remains
```

- [ ] **Step 2: Run test and confirm failure**

Run: `pytest test_gpt_team_new_worker_mail.py -k mother_otp_uses_worker -v`
Expected: FAIL while old path still expected/exists.

- [ ] **Step 3: Implement mother OTP rewiring**

In `gpt-team-new.py`:
- Remove `_get_jwt_for_address` usage in `refresh_team_session_http`.
- Make `chatgpt_http_login` OTP branch fetch OTP from unified Worker helper by mother email.
- Keep password branch unchanged except for removed fallback references.

- [ ] **Step 4: Re-run targeted tests**

Run: `pytest test_gpt_team_new_worker_mail.py -k mother_otp_uses_worker -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gpt-team-new.py test_gpt_team_new_worker_mail.py
git commit -m "refactor: use unified worker otp for mother account otp login"
```

---

## Chunk 4: Verification and cleanup

### Task 7: Verify no legacy mailbox symbols and run regression checks

**Files:**
- Modify: `gpt-team-new.py` (only if cleanup required)
- Test: `test_gpt_team_new_worker_mail.py`, `test_chatgpt_register_service.py`

- [ ] **Step 1: Add/confirm guard test for forbidden legacy symbols**

```python
# assert source string does not contain:
# create_temp_email, _get_jwt_for_address, /api/mails legacy path usage, wait_for_otp
```

- [ ] **Step 2: Run complete relevant tests**

Run:
- `pytest test_gpt_team_new_worker_mail.py -v`
- `pytest test_chatgpt_register_service.py -v`

Expected: PASS.

- [ ] **Step 3: Run syntax check**

Run: `python -m py_compile gpt-team-new.py`
Expected: no output / success exit.

- [ ] **Step 4: Manual smoke checklist (documented output only)**

Run (dry or controlled env):
- start script with `total_accounts: 1`
- verify logs show Worker OTP polling path for child registration
- verify mother OTP mode log path uses same Worker helper when password absent

Expected: no legacy mail/JWT flow logs.

- [ ] **Step 5: Commit final cleanup**

```bash
git add gpt-team-new.py test_gpt_team_new_worker_mail.py test_chatgpt_register_service.py
git commit -m "chore: finalize unified worker email and otp flow"
```

---

## Notes for Implementers

- No backward compatibility layer is allowed for old mailbox APIs.
- Keep single-file runtime for production script (`gpt-team-new.py` only).
- Reuse `chatgpt.py` semantics for OTP payload extraction and polling contract; adapt async patterns into current file’s sync `requests` style.
- Prefer minimal edits outside mailbox/OTP boundaries (YAGNI).
- If a test requires network, mock HTTP responses; do not rely on live Worker in unit tests.
