# Codex Register Team Six-Account Flow Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the parent+5-child registration workflow with manual parent-upgrade gate, resume-after-upgrade execution, strict six-member team verification, and storage in `codex_register_accounts` while keeping existing frontend interaction endpoints.

**Architecture:** Re-introduce a focused `codex_register_service.py` HTTP worker that exposes `/enable`, `/resume`, `/disable`, `/status`, `/accounts`, `/logs` and orchestrates a deterministic state machine. Reuse `ChatGPTService` for registration/team API calls, persist parent/child rows immediately, then continue through resume gate (`setCurrentAccount` first, subscription check second). Keep backend admin proxy and frontend card as thin orchestration surfaces; remove deprecated `/run-once` entrypoint entirely.

**Tech Stack:** Python 3.10 + unittest + psycopg2/curl_cffi, Go (Gin + testing), Vue3 + TypeScript + Vitest.

---

## File Structure

### Create
- `tools/codex_register/codex_register_service.py`
  - Responsibility: codex-register HTTP service, state machine, resume orchestration, DB persistence for `codex_register_accounts`.
- `tools/codex_register/test_codex_register_service.py`
  - Responsibility: unit tests for workflow phases, API handlers, resume gate order, and persistence contract.

### Modify
- `tools/codex_register/Dockerfile`
  - Responsibility: keep startup command aligned with real service entrypoint (`codex_register_service.py`).
- `tools/codex_register/chatgpt.py`
  - Responsibility: add only minimal helper(s) needed for deterministic invite/verify orchestration (if existing methods are insufficient).
- `backend/internal/handler/admin/codex_handler.go`
  - Responsibility: remove `RunOnce` proxy method.
- `backend/internal/server/routes/admin.go`
  - Responsibility: remove `POST /admin/codex/run-once` route registration.
- `backend/internal/server/routes/admin_codex_routes_test.go`
  - Responsibility: assert resume route still exists and run-once route is removed.
- `frontend/src/api/admin/codex.ts`
  - Responsibility: remove `runOnce()` API and export; keep `enable/resume/disable/status/accounts/logs` contract.
- `frontend/src/views/admin/settings/components/CodexRegistrationCard.vue`
  - Responsibility: keep action logic start/resume/stop only; remove dead run-once-related assumptions and phase mapping no longer used.
- `frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts`
  - Responsibility: update mocks and assertions after run-once removal and phase simplification.
- `frontend/src/i18n/locales/zh.ts`
  - Responsibility: remove or update obsolete phase labels (notably `running:pre_resume_check` if dropped).
- `frontend/src/i18n/locales/en.ts`
  - Responsibility: same as zh locale.

### Verify (no intended code changes)
- `backend/internal/handler/admin/codex_handler_test.go`
- `tools/codex_register/test_chatgpt_register_service.py`

---

## Chunk 1: Remove deprecated `/run-once` and align UI/API contract

### Task 1: Delete run-once from backend routes and proxy (TDD)

**Files:**
- Modify: `backend/internal/server/routes/admin.go`
- Modify: `backend/internal/server/routes/admin_codex_routes_test.go`
- Modify: `backend/internal/handler/admin/codex_handler.go`
- Verify: `backend/internal/handler/admin/codex_handler_test.go`

- [ ] **Step 1: Write failing route test asserting `/admin/codex/run-once` is not registered**

```go
func TestRegisterCodexRoutesRunOnceRemoved(t *testing.T) {
    req := httptest.NewRequest(http.MethodPost, "/admin/codex/run-once", nil)
    // expect 404 after route removal
}
```

- [ ] **Step 2: Run route test to confirm failure**

Run: `cd backend && go test ./internal/server/routes -run CodexRoutesRunOnceRemoved -v`
Expected: FAIL (route still exists).

- [ ] **Step 3: Remove route registration in `admin.go`**

```go
// remove:
// codex.POST("/run-once", h.Admin.Codex.RunOnce)
```

- [ ] **Step 4: Remove `RunOnce` handler in `codex_handler.go`**

```go
// delete method:
// func (h *CodexHandler) RunOnce(c *gin.Context) { h.proxyPost(c, "/run-once") }
```

- [ ] **Step 5: Re-run related Go tests**

Run: `cd backend && go test ./internal/handler/admin ./internal/server/routes -run Codex -v`
Expected: PASS.

- [ ] **Step 6: Commit backend run-once removal**

```bash
git add backend/internal/server/routes/admin.go backend/internal/server/routes/admin_codex_routes_test.go backend/internal/handler/admin/codex_handler.go
git commit -m "refactor: remove deprecated codex run-once endpoint"
```

### Task 2: Remove run-once from frontend API/types/tests

**Files:**
- Modify: `frontend/src/api/admin/codex.ts`
- Modify: `frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts`
- Modify: `frontend/src/views/admin/settings/components/CodexRegistrationCard.vue`
- Modify: `frontend/src/i18n/locales/zh.ts`
- Modify: `frontend/src/i18n/locales/en.ts`

- [ ] **Step 1: Write failing frontend test for API mock shape without `runOnce`**

```ts
expect(Object.keys(codexApiMocks)).not.toContain('runOnce')
```

- [ ] **Step 2: Run targeted Vitest to confirm failure**

Run: `cd frontend && npm run test:run -- src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts`
Expected: FAIL (mock currently includes runOnce).

- [ ] **Step 3: Remove `runOnce()` from `frontend/src/api/admin/codex.ts` export surface**

```ts
// delete function and remove from default export
```

- [ ] **Step 4: Update component tests and mocks accordingly**

- remove `runOnce: vi.fn()` from test mock object
- keep start/resume/retry assertions unchanged

- [ ] **Step 5: Remove obsolete phase label mapping only if unreachable**

In `CodexRegistrationCard.vue`, remove `running:pre_resume_check` mapping if service no longer emits it.

- [ ] **Step 6: Update locale keys to match remaining phases**

Remove/adjust translation keys for dropped phase labels.

- [ ] **Step 7: Re-run frontend tests**

Run: `cd frontend && npm run test:run -- src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts`
Expected: PASS.

- [ ] **Step 8: Commit frontend contract cleanup**

```bash
git add frontend/src/api/admin/codex.ts frontend/src/views/admin/settings/components/CodexRegistrationCard.vue frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts frontend/src/i18n/locales/zh.ts frontend/src/i18n/locales/en.ts
git commit -m "refactor: remove codex run-once client contract"
```

---

## Chunk 2: Build codex-register orchestration service (6 accounts + resume gate)

### Task 3: Create failing service tests for state machine and endpoint contract

**Files:**
- Create: `tools/codex_register/test_codex_register_service.py`
- Reference: `tools/codex_register/chatgpt.py`

- [ ] **Step 1: Add failing test for status payload fields required by frontend**

```python
def test_status_payload_contains_frontend_contract_fields(self):
    payload = service.get_status_payload()
    for key in [
        "enabled", "sleep_min", "sleep_max", "total_created",
        "last_success", "last_error", "proxy", "job_phase",
        "workflow_id", "waiting_reason", "can_start", "can_resume",
        "can_abandon", "last_transition", "last_resume_gate_reason", "recent_logs_tail"
    ]:
        self.assertIn(key, payload)
```

- [ ] **Step 2: Add failing test for enable path creating phase `running:create_parent`**

```python
def test_enable_transitions_to_running_create_parent(self):
    payload = service.handle_enable_request()
    self.assertEqual(payload["job_phase"], "running:create_parent")
```

- [ ] **Step 3: Add failing test for manual wait transition after parent+children creation**

```python
def test_create_phase_enters_waiting_parent_upgrade(self):
    # mock 6 successful register calls
    # assert waiting_manual:parent_upgrade
```

- [ ] **Step 4: Add failing test for resume ordering (switch first, gate second)**

```python
def test_resume_calls_set_current_account_before_subscription_gate(self):
    # assert call order:
    # refresh_access_token_with_session_token -> get_account_info
```

- [ ] **Step 5: Add failing test for strict six-member verification**

```python
def test_verify_requires_all_six_accounts_in_members(self):
    # if only 5 found => not completed
```

- [ ] **Step 6: Add failing test for immediate DB persistence with parent/child role**

```python
def test_register_success_immediately_persists_codex_register_role(self):
    # first account parent, rest child
```

- [ ] **Step 7: Add failing test for `/resume` when not waiting state (no-op)**

```python
def test_resume_ignored_when_not_waiting_manual(self):
    # expect unchanged phase + resume_request_ignored log
```

- [ ] **Step 8: Run service test file and confirm failures**

Run: `python -m unittest tools.codex_register.test_codex_register_service -v`
Expected: FAIL (service file/methods not implemented).

- [ ] **Step 9: Commit failing tests**

```bash
git add tools/codex_register/test_codex_register_service.py
git commit -m "test: define codex six-account workflow contract"
```

### Task 4: Implement `codex_register_service.py` with deterministic workflow

**Files:**
- Create: `tools/codex_register/codex_register_service.py`
- Modify (if needed): `tools/codex_register/Dockerfile`
- Verify: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Add minimal HTTP server skeleton and routes**

Implement handler routes:
- `GET /status`
- `GET /logs`
- `GET /accounts`
- `POST /enable`
- `POST /resume`
- `POST /disable`

- [ ] **Step 2: Implement in-memory workflow state model**

State fields:
- `job_phase`
- `workflow_id`
- `waiting_reason`
- `can_start/can_resume/can_abandon`
- `last_transition`
- `last_resume_gate_reason`
- `recent_logs_tail`

- [ ] **Step 3: Implement `/enable` start path**

- transition `idle|completed|abandoned|failed -> running:create_parent`
- execute one-shot worker thread

- [ ] **Step 4: Implement create-parent phase logic**

- call `ChatGPTService.register()` six times sequentially
- first result => parent, remaining => child
- persist each success immediately into `codex_register_accounts`
- set `codex_register_role` = `parent` / `child`
- after six successes => `waiting_manual:parent_upgrade`

- [ ] **Step 5: Implement `/resume` guard and phase entry**

- only allowed when `job_phase` starts with `waiting_manual:`
- transition to `running:accept_and_switch`

- [ ] **Step 6: Implement accept-and-switch phase with strict order**

Order is mandatory:
1) validate parent context (account_id, session_token)
2) call `refresh_access_token_with_session_token(..., account_id=parent)`
3) call `get_account_info` using refreshed token
4) gate requires `plan_type=team && has_active_subscription=true`

- [ ] **Step 7: Implement invite children phase**

- call `send_invite` for each child email
- collect per-child results in logs

- [ ] **Step 8: Implement verify-and-bind phase**

- call `get_members`
- strict success: parent + 5 children all present
- success => `completed`; otherwise => `failed` with reason

- [ ] **Step 9: Implement `/disable` abandon behavior**

- set `job_phase=abandoned`
- clear resumable flags safely

- [ ] **Step 10: Re-run service tests**

Run: `python -m unittest tools.codex_register.test_codex_register_service -v`
Expected: PASS.

- [ ] **Step 11: Commit service implementation**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py tools/codex_register/Dockerfile
git commit -m "feat: add codex six-account resume workflow service"
```

### Task 5: Add DB persistence helpers and `/accounts` query contract

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Verify: `backend/migrations/071_add_codex_register_accounts.sql`
- Verify: `backend/migrations/073_add_codex_register_parent_gate_columns.sql`

- [ ] **Step 1: Add failing test for `/accounts` ordering and fields**

```python
def test_accounts_endpoint_returns_expected_fields(self):
    payload = service.handle_accounts_request()
    # includes id,email,refresh_token,access_token,account_id,source,created_at,updated_at
```

- [ ] **Step 2: Run targeted test to confirm failure**

Run: `python -m unittest tools.codex_register.test_codex_register_service.CodexRegisterServiceTests.test_accounts_endpoint_returns_expected_fields -v`
Expected: FAIL.

- [ ] **Step 3: Implement SQL helpers for insert/update/select**

- upsert on `(email, source)`
- update token/account/workspace fields on re-run
- preserve parent/child role

- [ ] **Step 4: Re-run targeted + full service tests**

Run:
- `python -m unittest tools.codex_register.test_codex_register_service.CodexRegisterServiceTests.test_accounts_endpoint_returns_expected_fields -v`
- `python -m unittest tools.codex_register.test_codex_register_service -v`
Expected: PASS.

- [ ] **Step 5: Commit persistence contract**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: persist parent-child codex accounts and expose accounts endpoint"
```

---

## Chunk 3: End-to-end integration alignment and verification

### Task 6: Align backend proxy tests and phase expectations

**Files:**
- Modify: `backend/internal/handler/admin/codex_handler_test.go`
- Modify: `backend/internal/server/routes/admin_codex_routes_test.go`

- [ ] **Step 1: Update resume proxy expectations to new phase (`running:accept_and_switch`)**

- [ ] **Step 2: Add route test ensuring `/admin/codex/run-once` now returns 404**

- [ ] **Step 3: Run backend codex tests**

Run: `cd backend && go test ./internal/handler/admin ./internal/server/routes -run Codex -v`
Expected: PASS.

- [ ] **Step 4: Commit backend integration alignment**

```bash
git add backend/internal/handler/admin/codex_handler_test.go backend/internal/server/routes/admin_codex_routes_test.go
git commit -m "test: align codex admin proxy tests with run-once removal"
```

### Task 7: Full verification before handoff

**Files:**
- Verify only

- [ ] **Step 1: Run codex-register Python tests**

Run: `python -m unittest tools.codex_register.test_codex_register_service -v`
Expected: PASS.

- [ ] **Step 2: Run chatgpt register regression tests**

Run: `python -m unittest tools.codex_register.test_chatgpt_register_service -v`
Expected: PASS.

- [ ] **Step 3: Run backend codex tests**

Run: `cd backend && go test ./internal/handler/admin ./internal/server/routes -run Codex -v`
Expected: PASS.

- [ ] **Step 4: Run frontend codex component tests**

Run: `cd frontend && npm run test:run -- src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts`
Expected: PASS.

- [ ] **Step 5: Run quick frontend type check**

Run: `cd frontend && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Confirm changed files are expected**

Run: `git status --short`
Expected: only files listed in this plan are modified.

- [ ] **Step 7: Final integration commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py tools/codex_register/chatgpt.py tools/codex_register/Dockerfile backend/internal/handler/admin/codex_handler.go backend/internal/server/routes/admin.go backend/internal/server/routes/admin_codex_routes_test.go frontend/src/api/admin/codex.ts frontend/src/views/admin/settings/components/CodexRegistrationCard.vue frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts frontend/src/i18n/locales/zh.ts frontend/src/i18n/locales/en.ts
git commit -m "feat: implement codex parent-child resume workflow and remove run-once"
```

---

## Quality Gates
- Use `@superpowers:test-driven-development` before each implementation task.
- Use `@superpowers:verification-before-completion` before declaring task done.
- Keep scope strict (YAGNI): do not add new API endpoints beyond existing `/admin/codex/*` set (minus removed `/run-once`).
- Keep data contract stable for frontend `CodexStatus` and accounts table display fields.
