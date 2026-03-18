# get_tokens Data Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `tools/codex_register/get_tokens.py` emit the same importable account-record shape as `gpt-team-new.py` while keeping `results.txt` unchanged.

**Architecture:** Keep `get_tokens.py` as the only execution script and reuse `gpt-team-new.py` as the source of truth for token normalization and ChatGPT session metadata collection. Avoid rewriting the long OAuth login body; instead, adapt `process_one()` around the current tuple return and switch JSONL output to the shared `build_importable_account_record()` contract.

**Tech Stack:** Python 3, requests, stdlib `importlib.util`, unittest/pytest contract tests, existing OpenAI OAuth + ChatGPT session HTTP flows.

---

## File map

- Modify: `tools/codex_register/get_tokens.py`
  - Add dynamic loading of `gpt-team-new.py` helper functions.
  - Keep the current `oauth_login()` flow intact.
  - Split `results.txt` writing from `accounts.jsonl` writing.
  - Build JSONL records through `build_token_dict()` + `build_importable_account_record()`.
  - Override `record["source"] = "get_tokens"`.
- Modify: `tools/codex_register/test_codex_register_service.py`
  - Add tests for the richer `get_tokens` JSONL output contract.
  - Add tests for helper-loading fallback behavior.
  - Add tests that verify `process_one()` adapts the existing `(access_token, refresh_token)` tuple.
- Reference: `tools/codex_register/gpt-team-new.py:1098-1159`
  - Source of truth for `build_token_dict()` and `build_importable_account_record()`.
- Reference: `tools/codex_register/gpt-team-new.py:1179-1633`
  - Source of truth for `chatgpt_http_login()`.
- Reference: `tools/codex_register/codex_register_service.py:499-540`
  - Confirms the service already parses `plan_type`, `organization_id`, `workspace_id`, and `codex_register_role`.
- Reference: `tools/codex_register/codex_register_service.py:630-642`
  - Confirms routing already uses `plan_type` with legacy fallback.

## Task 1: Add helper loading and preserve the current login flow

**Files:**
- Modify: `tools/codex_register/get_tokens.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write a failing test for helper discovery**

Add a test that imports `tools.codex_register.get_tokens` and verifies `_get_gpt_team_helpers()` returns a dict with keys:
- `build_token_dict`
- `build_importable_account_record`
- `chatgpt_http_login`

Also add a failure-path version where the loader returns `None` and the helper dict contains `None` values.

- [ ] **Step 2: Implement dynamic helper loading**

In `tools/codex_register/get_tokens.py`, add:
- `_load_gpt_team_new_module()`
- `_get_gpt_team_helpers()`

Use `importlib.util.spec_from_file_location()` against `tools/codex_register/gpt-team-new.py` in the same directory. Do not import by package name alone because the filename contains `-`.

- [ ] **Step 3: Verify syntax**

Run: `python -m py_compile tools/codex_register/get_tokens.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tools/codex_register/get_tokens.py tools/codex_register/test_codex_register_service.py
git commit -m "refactor: load gpt-team helpers in get_tokens"
```

## Task 2: Split `results.txt` writing from JSONL writing

**Files:**
- Modify: `tools/codex_register/get_tokens.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write a failing test for results.txt-only writing**

Add a test that verifies a helper like `save_result_to_results_txt()` writes only:

```text
email|password|access_token|refresh_token
```

and does **not** write any JSONL side effects.

- [ ] **Step 2: Add the dedicated helper**

Implement:

```python
def save_result_to_results_txt(email: str, password: str, access_token: str, refresh_token: str) -> None:
    results_line = f"{email}|{password}|{access_token}|{refresh_token}\n"
    with _save_lock:
        with open(RESULTS_FILE, "a", encoding="utf-8") as f:
            f.write(results_line)
```

- [ ] **Step 3: Stop using the legacy combined writer from `process_one()`**

Either:
- delete `save_result()` and `build_accounts_jsonl_record()` if they become dead code, or
- leave them temporarily but ensure `process_one()` does not call them anymore.

The steady-state requirement is:
- `results.txt` comes from `save_result_to_results_txt()`
- `accounts.jsonl` comes from the parity record path only

- [ ] **Step 4: Run focused tests**

Run: `pytest tools/codex_register/test_codex_register_service.py -k get_tokens -v`
Expected: PASS for the new output-splitting tests.

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/get_tokens.py tools/codex_register/test_codex_register_service.py
git commit -m "refactor: separate get_tokens text and jsonl outputs"
```

## Task 3: Adapt `process_one()` around the current tuple-returning `oauth_login()`

**Files:**
- Modify: `tools/codex_register/get_tokens.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write a failing compatibility test**

Add a test that stubs:

```python
oauth_login(...) -> ("at", "rt")
```

and verifies `process_one()` wraps it into:

```python
{
    "access_token": "at",
    "refresh_token": "rt",
    "id_token": "",
}
```

before passing the dict into `build_token_dict()`.

- [ ] **Step 2: Update `process_one()` without changing `oauth_login()`**

Do **not** rewrite `oauth_login()` in this plan. Instead, keep the current signature and adapt `process_one()` like this:

```python
token_pair = oauth_login(...)
if not token_pair:
    save_result_to_results_txt(email, password, "", "")
    return False

access_token, refresh_token = token_pair
tokens = {
    "access_token": access_token,
    "refresh_token": refresh_token,
    "id_token": "",
}
```

- [ ] **Step 3: Verify failure behavior remains unchanged**

When login fails after registration, `process_one()` must still:
- log warning
- write an empty `results.txt` line
- return `False`

- [ ] **Step 4: Run tests**

Run: `pytest tools/codex_register/test_codex_register_service.py -k get_tokens -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/get_tokens.py tools/codex_register/test_codex_register_service.py
git commit -m "fix: adapt get_tokens process_one to oauth tuple output"
```

## Task 4: Build parity JSONL records through shared helpers

**Files:**
- Modify: `tools/codex_register/get_tokens.py`
- Reference: `tools/codex_register/gpt-team-new.py:1098-1159`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write a failing helper-integration test**

Stub `_get_gpt_team_helpers()` to return fake callables for:
- `build_token_dict`
- `build_importable_account_record`
- `chatgpt_http_login`

Verify `process_one()`:
- calls `build_token_dict(email, tokens)`
- enriches `token_dict` with `plan_type`, `organization_id`, and `codex_register_role = "parent"`
- calls `build_importable_account_record(...)`
- appends a JSONL line

- [ ] **Step 2: Implement token normalization via shared helper**

In `process_one()`:

```python
helpers = _get_gpt_team_helpers()
build_token_dict = helpers.get("build_token_dict")
```

If callable, use:

```python
token_dict = build_token_dict(email, tokens)
```

Otherwise create a minimal fallback dict with:
- `type`
- `email`
- `access_token`
- `refresh_token`
- `id_token`
- `account_id`
- `expired`
- `last_refresh`

- [ ] **Step 3: Implement best-effort ChatGPT metadata enrichment**

If `chatgpt_http_login` is callable, call it and on success write:

```python
if plan_type:
    token_dict["plan_type"] = plan_type
if org_id_chatgpt:
    token_dict["organization_id"] = org_id_chatgpt
token_dict["codex_register_role"] = "parent"
```

Failures must log warnings and continue.

- [ ] **Step 4: Generate the importable parity record**

If `build_importable_account_record` is callable, call:

```python
record = build_importable_account_record(
    email=email,
    password=password,
    token_dict=token_dict,
    invited=False,
    team_name="",
    auth_file="",
)
```

If the helper is unavailable or returns `None`, log a warning and return `False` after writing `results.txt`.

- [ ] **Step 5: Override the record source and role**

Because `gpt-team-new.py` hardcodes:

```python
"source": "gpt-team-new"
```

set immediately after record creation:

```python
record["source"] = "get_tokens"
record["codex_register_role"] = "parent"
```

This explicit post-build override is required even if `token_dict["codex_register_role"]` was already set, so every successful JSONL write guarantees the final record contract.

- [ ] **Step 6: Append the parity record to `accounts.jsonl`**

Write exactly one JSON object line to `ACCOUNTS_JSONL_FILE`.

- [ ] **Step 7: Run focused tests**

Run: `pytest tools/codex_register/test_codex_register_service.py -k "get_tokens or plan_type" -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add tools/codex_register/get_tokens.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: emit parity account records from get_tokens"
```

## Task 5: Add explicit record-contract tests

**Files:**
- Modify: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write field-contract assertions for emitted JSONL**

Add a test that verifies a `get_tokens` JSONL record includes:
- `email`
- `password`
- `access_token`
- `refresh_token`
- `id_token`
- `account_id`
- `auth_file`
- `expires_at`
- `invited`
- `team_name`
- `plan_type`
- `organization_id`
- `workspace_id`
- `codex_register_role`
- `created_at`
- `updated_at`
- `source`

Also assert:
- `source == "get_tokens"`
- `invited is False`
- `team_name == ""`
- `codex_register_role == "parent"`

- [ ] **Step 2: Add degradation-path coverage**

Add a test that verifies when helper loading fails:
- `results.txt` is still written
- the flow does not crash
- the function returns `False` if it cannot build a parity record

- [ ] **Step 3: Run the full relevant test module**

Run: `pytest tools/codex_register/test_codex_register_service.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tools/codex_register/test_codex_register_service.py tools/codex_register/get_tokens.py
git commit -m "test: cover get_tokens parity record contract"
```

## Task 6: Verify integration with the existing service contract

**Files:**
- Reference: `tools/codex_register/codex_register_service.py:499-540`
- Reference: `tools/codex_register/codex_register_service.py:630-642`

- [ ] **Step 1: Re-read service parsing and routing**

Confirm the service already reads:
- `plan_type`
- `organization_id`
- `workspace_id`
- `codex_register_role`

and routes:
- `plan_type == "team"` → team groups
- other truthy `plan_type` → free groups
- empty `plan_type` → legacy `invited` fallback

- [ ] **Step 2: Run optional service-side verification slice**

Run: `pytest tools/codex_register/test_codex_register_service.py -k "plan_type or accounts_path or frontend" -v`
Expected: PASS

- [ ] **Step 3: Run syntax validation across touched scripts**

Run: `python -m py_compile tools/codex_register/get_tokens.py tools/codex_register/gpt-team-new.py tools/codex_register/codex_register_service.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tools/codex_register/get_tokens.py tools/codex_register/test_codex_register_service.py
git commit -m "chore: verify get_tokens parity integrates with existing routing"
```

## Notes for the implementing agent

- Respect the current state of `tools/codex_register/get_tokens.py`; do not revert recent user-intentional edits.
- The low-risk path is adapting `process_one()` around the existing tuple-returning `oauth_login()`.
- Do not modify `codex_register_service.py` unless a failing test proves the current service contract is insufficient.
- If helper loading or `build_importable_account_record()` is unavailable, the intended degradation path is: keep writing `results.txt`, skip JSONL parity output, and return `False` without crashing.
- Do not add new plan-type inference heuristics; only use metadata produced by `chatgpt_http_login()` and `build_token_dict()`.
