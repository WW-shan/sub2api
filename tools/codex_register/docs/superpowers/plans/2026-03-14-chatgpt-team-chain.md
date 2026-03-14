# ChatGPT Team Single-Chain Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the existing registration-to-login flow unchanged, then run Team/Workspace operations through a new single entrypoint `ChatGPTService.register_and_setup_team(...)`.

**Architecture:** Build a focused `ChatGPTService` facade that orchestrates two phases: (1) existing register flow output normalization, (2) team action execution using request/response patterns aligned with `team-manage` chatgpt/team services. Keep current script behavior intact by integrating through minimal adapters and a deterministic result contract.

**Tech Stack:** Python 3, curl_cffi.requests, unittest/mock, existing codex_register workflow utilities.

---

## Invariants (Must Hold)
1. `codex_register_service.run(...)` control flow and return semantics do not change.
2. `ChatGPTService.register_and_setup_team(...)` is the only public entrypoint for the new single chain.
3. Team migration is limited to service-level chatgpt/team API semantics; no DB/ORM/infra migration.
4. Team phase consumes register phase output context; no second login flow is introduced.

## File Structure

- Create: `chatgpt_service.py`
  - Responsibility: `ChatGPTService` orchestration and private team action helpers.
- Modify: `codex_register_service.py`
  - Responsibility: add pure register-output context normalization helper only (no register behavior rewrite).
- Modify: `test_codex_register_invite_flow.py`
  - Responsibility: TDD coverage for phase gating, result contract, action dispatch, and compatibility.

## Contracts

### Public method contract
```python
class ChatGPTService:
    def register_and_setup_team(self, register_input: dict, team_plan: list[dict]) -> dict:
        ...
```

### `team_plan` schema
Each action item is one dict:
- `{"action": "invite_member", "email": "child@example.com"}`
- `{"action": "list_members"}`
- `{"action": "list_invites"}`
- `{"action": "revoke_invite", "email": "child@example.com"}`
- `{"action": "delete_member", "user_id": "usr_123"}`
- `{"action": "get_account_info"}` (required for team metadata preflight parity with reference semantics)

If `team_plan` is empty and register succeeds: return `ok=True`, `phase="done"`, `team_results=[]`.

### Result schema
```python
{
  "ok": bool,
  "phase": "register" | "team" | "done",
  "reason": str,
  "error_code": str,
  "register_result": dict,
  "team_results": list[dict]
}
```

### Error code mapping table
- Register path:
  - `register_failed`
  - `register_payload_invalid`
  - `auth_context_missing`
- Team path:
  - `team_action_invalid`
  - `network_timeout`
  - `http_4xx`
  - `http_5xx`
  - `auth_invalid`
  - `business_conflict`

### Header/context source-of-truth
- `Authorization: Bearer <access_token>` ← `AuthContext.access_token`
- `chatgpt-account-id` ← `AuthContext.account_id`
- `workspace_id` usage in API query/body ← `AuthContext.workspace_id`
- `organization_id` usage in API query/body ← `AuthContext.organization_id`

## Chunk 1: Introduce service contract and failing tests

### Task 1: Define public single-chain contract first (tests)

**Files:**
- Modify: `test_codex_register_invite_flow.py`
- Create: `chatgpt_service.py` (stub only after failing tests)

- [ ] **Step 1: Write failing tests for required flows and empty-plan behavior**

```python
def test_register_and_setup_team_stops_at_register_failure(): ...
def test_register_and_setup_team_returns_done_on_team_success(): ...
def test_register_and_setup_team_returns_team_phase_on_team_failure(): ...
def test_register_and_setup_team_allows_empty_team_plan_after_register_success(): ...
```

- [ ] **Step 2: Run one contract test to verify failure**

Run: `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests.test_register_and_setup_team_stops_at_register_failure`
Expected: FAIL with missing `ChatGPTService`/`register_and_setup_team`.

- [ ] **Step 3: Add minimal service stub with explicit signature**

```python
class ChatGPTService:
    def register_and_setup_team(self, register_input: dict, team_plan: list[dict]) -> dict:
        raise NotImplementedError
```

- [ ] **Step 4: Re-run same test to keep behavioral failure (not import failure)**

Run: same command as Step 2
Expected: FAIL on assertion mismatch/NotImplementedError.

- [ ] **Step 5: Commit**

```bash
git add test_codex_register_invite_flow.py chatgpt_service.py
git commit -m "test: add failing single-chain ChatGPTService contract tests"
```

### Task 2: Add result schema and phase/error normalization tests

**Files:**
- Modify: `test_codex_register_invite_flow.py`
- Modify: `chatgpt_service.py`

- [ ] **Step 1: Add failing tests for output schema and deterministic phase mapping**

```python
self.assertEqual(result["phase"], "register")
self.assertIn("error_code", result)
self.assertIn("register_result", result)
self.assertIn("team_results", result)
```

- [ ] **Step 2: Run targeted schema tests**

Run: `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests.test_register_and_setup_team_returns_team_phase_on_team_failure`
Expected: FAIL on missing keys/wrong phase.

- [ ] **Step 3: Implement minimal `_result(...)` builder**

```python
def _result(self, ok, phase, reason, error_code, register_result, team_results): ...
```

- [ ] **Step 4: Re-run targeted schema tests**

Run: same as Step 2
Expected: PASS for schema assertions.

- [ ] **Step 5: Commit**

```bash
git add test_codex_register_invite_flow.py chatgpt_service.py
git commit -m "feat: add normalized phase/result contract for single-chain service"
```

## Chunk 2: Implement register phase bridge without behavior drift

### Task 3: Add register-output context helper using strict TDD

**Files:**
- Modify: `codex_register_service.py`
- Modify: `test_codex_register_invite_flow.py`

- [ ] **Step 1: Add regression guard test for existing `run()` behavior (baseline PASS)**

```python
def test_run_existing_registration_flow_unchanged_when_bridge_unused(): ...
```

- [ ] **Step 2: Run baseline regression guard**

Run: `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests.test_run_existing_registration_flow_unchanged_when_bridge_unused`
Expected: PASS.

- [ ] **Step 3: Add failing helper test first (`build_auth_context_from_token_payload`)**

```python
def test_build_auth_context_from_token_payload_extracts_required_fields(): ...
```

- [ ] **Step 4: Run helper test to confirm FAIL**

Run: `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests.test_build_auth_context_from_token_payload_extracts_required_fields`
Expected: FAIL (helper missing).

- [ ] **Step 5: Implement pure helper in `codex_register_service.py`**

```python
def build_auth_context_from_token_payload(token_payload: dict) -> dict:
    # read-only mapping; no mutation of register flow behavior
```

- [ ] **Step 6: Re-run helper + regression tests**

Run:
- `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests.test_build_auth_context_from_token_payload_extracts_required_fields`
- `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests.test_run_existing_registration_flow_unchanged_when_bridge_unused`

Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add codex_register_service.py test_codex_register_invite_flow.py
git commit -m "feat: add pure auth-context helper without changing run flow"
```

### Task 4: Wire `ChatGPTService` register phase to existing callable

**Files:**
- Modify: `chatgpt_service.py`
- Modify: `test_codex_register_invite_flow.py`

**Existing callable to reuse:** `codex_register_service.run(proxy: Optional[str]) -> Optional[str]`.

- [ ] **Step 1: Add failing test for register-phase gating by mocking `codex_register_service.run`**
- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests.test_register_and_setup_team_stops_at_register_failure`
Expected: FAIL.

- [ ] **Step 3: Implement register phase call + payload parse + helper mapping**

```python
token_json = codex_register_service.run(proxy)
if not token_json: return _result(... phase="register" ...)
```

- [ ] **Step 4: Re-run register-phase tests**

Run: `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests -k register_and_setup_team`
Expected: register-phase tests PASS.

- [ ] **Step 5: Commit**

```bash
git add chatgpt_service.py test_codex_register_invite_flow.py
git commit -m "feat: connect single-chain register phase to existing run callable"
```

## Chunk 3: Implement team phase with reference semantics

### Task 5: Implement request wrapper and action helpers in micro-steps

**Files:**
- Modify: `chatgpt_service.py`
- Modify: `test_codex_register_invite_flow.py`

- [ ] **Step 1: Add failing tests for `_make_request` normalization**
- [ ] **Step 2: Run `_make_request` tests and confirm FAIL**

Run: `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests -k make_request`
Expected: FAIL.

- [ ] **Step 3: Implement `_make_request` only**
- [ ] **Step 4: Re-run `_make_request` tests**

Expected: PASS.

- [ ] **Step 5: Add failing tests for `_send_invite` + `_get_members`**
- [ ] **Step 6: Run those tests and confirm FAIL**

Run: `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests -k "send_invite or get_members"`
Expected: FAIL.

- [ ] **Step 7: Implement `_send_invite` + `_get_members`**
- [ ] **Step 8: Re-run those tests**

Expected: PASS.

- [ ] **Step 9: Add failing tests for `_get_invites` + `_delete_invite` + `_delete_member`**
- [ ] **Step 10: Run and confirm FAIL**

Run: `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests -k "get_invites or delete_invite or delete_member"`
Expected: FAIL.

- [ ] **Step 11: Implement `_get_invites` + `_delete_invite` + `_delete_member`**
- [ ] **Step 12: Re-run tests**

Expected: PASS.

- [ ] **Step 13: Add failing tests for `_get_account_info` preflight**
- [ ] **Step 14: Run and confirm FAIL**

Run: `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests -k get_account_info`
Expected: FAIL.

- [ ] **Step 15: Implement `_get_account_info`**
- [ ] **Step 16: Re-run preflight tests**

Expected: PASS.

- [ ] **Step 17: Commit**

```bash
git add chatgpt_service.py test_codex_register_invite_flow.py
git commit -m "feat: add private team action helpers aligned to reference semantics"
```

### Task 6: Implement `team_plan` dispatcher in strict micro-steps

**Files:**
- Modify: `chatgpt_service.py`
- Modify: `test_codex_register_invite_flow.py`

- [ ] **Step 1: Add failing tests for unknown action mapping to `team_action_invalid`**
- [ ] **Step 2: Run and confirm FAIL**

Run: `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests -k unknown_action`
Expected: FAIL.

- [ ] **Step 3: Implement action validation + error mapping only**
- [ ] **Step 4: Re-run unknown-action tests**

Expected: PASS.

- [ ] **Step 5: Add failing tests for ordered execution**
- [ ] **Step 6: Run and confirm FAIL**

Run: `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests -k ordered_execution`
Expected: FAIL.

- [ ] **Step 7: Implement ordered dispatch**
- [ ] **Step 8: Re-run ordered tests**

Expected: PASS.

- [ ] **Step 9: Add failing tests for short-circuit on first team failure**
- [ ] **Step 10: Run and confirm FAIL**

Run: `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests -k short_circuit`
Expected: FAIL.

- [ ] **Step 11: Implement short-circuit + aggregate `team_results`**
- [ ] **Step 12: Re-run short-circuit tests**

Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add chatgpt_service.py test_codex_register_invite_flow.py
git commit -m "feat: add deterministic team plan dispatcher and aggregation"
```

## Chunk 4: Compatibility and full verification

### Task 7: Preserve legacy helpers while adding new chain

**Files:**
- Modify: `codex_register_service.py` (minimal bridge only)
- Modify: `test_codex_register_invite_flow.py`

- [ ] **Step 1: Add new failing integration test for chain + legacy coexistence**

```python
def test_new_chain_does_not_break_legacy_invite_recent_children_path(): ...
```

- [ ] **Step 2: Run legacy + new coexistence selectors**

Run:
- `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests.test_invite_recent_children_invites_with_parent_headers`
- `python -m unittest test_codex_register_invite_flow.CodexRegisterInviteFlowTests.test_new_chain_does_not_break_legacy_invite_recent_children_path`

Expected: legacy PASS, new test FAIL initially.

- [ ] **Step 3: Apply minimal compatibility adjustment (if needed)**
- [ ] **Step 4: Re-run the two selectors above**

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add codex_register_service.py chatgpt_service.py test_codex_register_invite_flow.py
git commit -m "fix: preserve legacy invite helpers while adding single-chain service"
```

### Task 8: Full verification before completion

**Files:**
- Verify only

- [ ] **Step 1: Run full test file**

Run: `python -m unittest test_codex_register_invite_flow.py`
Expected: all PASS.

- [ ] **Step 2: Run syntax check**

Run: `python -m py_compile codex_register_service.py chatgpt_service.py test_codex_register_invite_flow.py`
Expected: no output, exit 0.

- [ ] **Step 3: Confirm no unintended file drift**

Run: `git status --short`
Expected: only planned files changed.

- [ ] **Step 4: Final commit**

```bash
git add codex_register_service.py chatgpt_service.py test_codex_register_invite_flow.py
git commit -m "feat: add ChatGPTService single-chain registration and team workflow"
```

- [ ] **Step 5: Prepare review handoff**

Run:
- `git log --oneline -n 5`
- `git diff --stat main...HEAD`

Expected: clean summary for PR/review.

---

## Quality Gates
- Use @superpowers:test-driven-development before each implementation task.
- Use @superpowers:verification-before-completion before any “done” claim.
- No DB/ORM/infra/config/env/dependency changes.
- Keep DRY/YAGNI: no async pool backport.
- Protect invariants: registration flow semantics unchanged.
