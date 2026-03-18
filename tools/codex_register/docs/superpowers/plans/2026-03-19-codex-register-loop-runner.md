# Codex Register Loop Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent frontend-controlled start/stop loop for repeated `gpt-team-new.py` execution, with per-round and cumulative DB-created account counts surfaced on the Codex register page.

**Architecture:** Extend `CodexRegisterService` with a separate loop-runner state machine and endpoints that reuse the existing subprocess, JSONL parsing, and DB upsert logic without disturbing the current enable/resume workflow. Proxy the new loop endpoints through the Go admin handler, then add a loop panel to the existing Vue Codex registration card that polls loop status and renders recent round history.

**Tech Stack:** Python (`asyncio`, `threading`, subprocess management, unittest) in `tools/codex_register`; Go (`gin`) route/handler proxy; Vue 3 + TypeScript + Vitest in `frontend/src`.

---

## File Map

- **Python service core**
  - Modify: `tools/codex_register/codex_register_service.py`
    - Add loop state defaults and stale-state repair helpers.
    - Add loop endpoint handling in `handle_path`.
    - Add loop worker lifecycle, interruptible sleep, and per-round execution helpers.
    - Reuse `_process_accounts_jsonl_records` with a loop-specific committed offset contract.
    - Extend HTTP allowlist for `/loop/status`, `/loop/start`, `/loop/stop`.
- **Python service tests**
  - Modify: `tools/codex_register/test_codex_register_service.py`
    - Add loop endpoint, stale-state, success/failure/stopped round, and mutual exclusion tests.
- **Go admin proxy**
  - Modify: `backend/internal/handler/admin/codex_handler.go`
    - Add `GetLoopStatus`, `StartLoop`, `StopLoop` proxy methods.
  - Modify: `backend/internal/server/routes/admin.go`
    - Register `/admin/codex/loop/status`, `/admin/codex/loop/start`, `/admin/codex/loop/stop`.
  - Modify: `backend/internal/server/routes/admin_codex_routes_test.go`
    - Add routing/proxy coverage for the new loop endpoints.
- **Frontend API**
  - Modify: `frontend/src/api/admin/codex.ts`
    - Add loop status/history interfaces and API helpers.
- **Frontend UI**
  - Modify: `frontend/src/views/admin/settings/components/CodexRegistrationCard.vue`
    - Fetch loop status with existing polling.
    - Add loop control buttons, summary panel, and history table.
- **Frontend tests and i18n**
  - Modify: `frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts`
    - Add loop panel/button rendering and interaction tests.
  - Modify: `frontend/src/i18n/locales/zh.ts`
    - Add loop-specific strings.

---

## Task 1: Add failing Python tests for loop state and endpoints

**Files:**
- Modify: `tools/codex_register/test_codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write a failing test for `/loop/status` default shape**

```python
class LoopStateTests(ServiceTestCase):
    def test_loop_status_returns_default_loop_fields(self):
        async def _run():
            return await self.service.handle_path("/loop/status")

        result = asyncio.run(_run())

        self.assertTrue(result["success"])
        data = result["data"]
        self.assertFalse(data["loop_running"])
        self.assertEqual(data["loop_current_round"], 0)
        self.assertEqual(data["loop_total_created"], 0)
        self.assertEqual(data["loop_history"], [])
```

- [ ] **Step 2: Run the targeted loop-status test and verify it fails**

Run: `python -m unittest tools.codex_register.test_codex_register_service.LoopStateTests.test_loop_status_returns_default_loop_fields -v`
Expected: FAIL with `unsupported_path: /loop/status` or missing `loop_*` fields.

- [ ] **Step 3: Write a failing test for `/loop/stop` idempotency**

```python
def test_loop_stop_is_idempotent_when_already_stopped(self):
    async def _run():
        return await self.service.handle_path("/loop/stop", payload={})

    result = asyncio.run(_run())

    self.assertTrue(result["success"])
    self.assertFalse(result["data"]["loop_running"])
```

- [ ] **Step 4: Run the targeted stop test and verify it fails**

Run: `python -m unittest tools.codex_register.test_codex_register_service.LoopStateTests.test_loop_stop_is_idempotent_when_already_stopped -v`
Expected: FAIL with `unsupported_path: /loop/stop`.

- [ ] **Step 3b: Write a failing test for `/loop/start` success and duplicate start protection**

```python
def test_loop_start_sets_running_state(self):
    with patch.object(self.service, "_start_loop_worker"):
        result = asyncio.run(self.service.handle_path("/loop/start", payload={}))

    self.assertTrue(result["success"])
    self.assertTrue(result["data"]["loop_running"])


def test_loop_start_rejects_when_already_running(self):
    state = self.service._default_state()
    state["loop_running"] = True
    asyncio.run(self.service._save_state(state))

    result = asyncio.run(self.service.handle_path("/loop/start", payload={}))

    self.assertFalse(result["success"])
    self.assertEqual(result["error"], "already_running")
```

- [ ] **Step 3c: Run the targeted start tests and verify they fail**

Run: `python -m unittest tools.codex_register.test_codex_register_service.LoopStateTests.test_loop_start_sets_running_state tools.codex_register.test_codex_register_service.LoopStateTests.test_loop_start_rejects_when_already_running -v`
Expected: FAIL with `unsupported_path: /loop/start`.

- [ ] **Step 5: Commit the red tests**

```bash
git add tools/codex_register/test_codex_register_service.py
git commit -m "test: add failing codex loop endpoint coverage"
```

---

## Task 2: Implement loop state defaults, endpoint plumbing, and stale-state repair

**Files:**
- Modify: `tools/codex_register/codex_register_service.py:56-84`
- Modify: `tools/codex_register/codex_register_service.py:1014-1043`
- Modify: `tools/codex_register/codex_register_service.py:1104-1108`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Extend `_default_state` with loop fields**

Add these keys to the returned dict:

```python
"loop_running": False,
"loop_stopping": False,
"loop_started_at": None,
"loop_current_round": 0,
"loop_last_round_started_at": None,
"loop_last_round_finished_at": None,
"loop_last_round_created": 0,
"loop_last_round_updated": 0,
"loop_last_round_skipped": 0,
"loop_last_round_failed": 0,
"loop_total_created": 0,
"loop_last_error": "",
"loop_history": [],
"loop_committed_accounts_jsonl_offset": 0,
```

- [ ] **Step 2: Add a stale-loop-state repair helper**

Implement a helper shaped like:

```python
def _repair_loop_state_if_stale(self, state: Dict[str, Any]) -> bool:
    if not state.get("loop_running"):
        return False
    if self._loop_worker_thread is not None and self._loop_worker_thread.is_alive():
        return False
    if self._loop_owned_process is not None and self._has_process_running(self._loop_owned_process):
        return False
    state["loop_running"] = False
    state["loop_stopping"] = False
    state["loop_last_error"] = "loop_worker_missing_after_restart"
    return True
```

- [ ] **Step 3: Add `/loop/status`, `/loop/start`, and `/loop/stop` branches to `handle_path`**

Use the same authorization guard as `/enable`, `/resume`, `/disable` for loop start/stop. `GET /loop/status` should return only the loop slice or the full state with loop fields, but it must include the fields asserted by the tests.

- [ ] **Step 4: Extend HTTP allowlists for the new loop routes**

Update `method_allowlist` to include:

```python
"GET": {"/status", "/logs", "/accounts", "/loop/status"},
"POST": {"/enable", "/resume", "/disable", "/loop/start", "/loop/stop"},
```

- [ ] **Step 5: Run the targeted endpoint tests and verify they pass**

Run: `python -m unittest tools.codex_register.test_codex_register_service.LoopStateTests -v`
Expected: PASS for the new `/loop/status`, `/loop/start`, and `/loop/stop` endpoint-plumbing tests, including duplicate-start protection.

- [ ] **Step 6: Commit the green endpoint plumbing**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: add codex loop state endpoints"
```

---

## Task 3: Add failing Python tests for one-round execution semantics

**Files:**
- Modify: `tools/codex_register/test_codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write a failing test for successful round count accumulation**

Add a focused helper-level test instead of a thread timing test:

```python
class LoopRoundTests(ServiceTestCase):
    def test_loop_round_updates_created_counts_and_committed_offset(self):
        state = self.service._default_state()
        state["loop_committed_accounts_jsonl_offset"] = 0
        summary = {
            "start_offset": 0,
            "end_offset": 44,
            "records_seen": 1,
            "created": 1,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        with patch.object(self.service, "_run_loop_process_once", return_value=0):
            with patch.object(self.service, "_process_loop_accounts_jsonl_round", return_value=summary):
                asyncio.run(self.service._run_loop_round(state))

        self.assertEqual(state["loop_last_round_created"], 1)
        self.assertEqual(state["loop_total_created"], 1)
        self.assertEqual(state["loop_committed_accounts_jsonl_offset"], 44)
        self.assertEqual(state["loop_history"][-1]["status"], "success")
```

- [ ] **Step 2: Run the targeted successful-round test and verify it fails**

Run: `python -m unittest tools.codex_register.test_codex_register_service.LoopRoundTests.test_loop_round_updates_created_counts_and_committed_offset -v`
Expected: FAIL because `_run_loop_round` and/or `_process_loop_accounts_jsonl_round` do not exist.

- [ ] **Step 3: Write a failing test for failed processing preserving committed offset**

```python
def test_loop_round_failure_keeps_committed_offset(self):
    state = self.service._default_state()
    state["loop_committed_accounts_jsonl_offset"] = 12

    with patch.object(self.service, "_run_loop_process_once", return_value=0):
        with patch.object(self.service, "_process_loop_accounts_jsonl_round", side_effect=RuntimeError("db boom")):
            asyncio.run(self.service._run_loop_round(state))

    self.assertEqual(state["loop_committed_accounts_jsonl_offset"], 12)
    self.assertEqual(state["loop_history"][-1]["status"], "failed")
    self.assertIn("db boom", state["loop_last_error"])
```

- [ ] **Step 4: Run the targeted failure test and verify it fails**

Run: `python -m unittest tools.codex_register.test_codex_register_service.LoopRoundTests.test_loop_round_failure_keeps_committed_offset -v`
Expected: FAIL because loop-round failure handling is not implemented.

- [ ] **Step 4b: Write a failing test for interrupted rounds recorded as `stopped`**

```python
def test_loop_round_stop_records_stopped_history_entry(self):
    state = self.service._default_state()
    state["loop_committed_accounts_jsonl_offset"] = 12
    self.service._loop_stop_event.set()

    with patch.object(self.service, "_run_loop_process_once", return_value=-15):
        asyncio.run(self.service._run_loop_round(state))

    self.assertEqual(state["loop_committed_accounts_jsonl_offset"], 12)
    self.assertEqual(state["loop_history"][-1]["status"], "stopped")
```

- [ ] **Step 4c: Run the targeted stopped-round test and verify it fails**

Run: `python -m unittest tools.codex_register.test_codex_register_service.LoopRoundTests.test_loop_round_stop_records_stopped_history_entry -v`
Expected: FAIL because stopped-round handling is not implemented yet.

- [ ] **Step 5: Commit the red round tests**

```bash
git add tools/codex_register/test_codex_register_service.py
git commit -m "test: add failing codex loop round coverage"
```

---

## Task 4: Implement loop round execution, stop handling, and workflow mutual exclusion

**Files:**
- Modify: `tools/codex_register/codex_register_service.py:24-55`
- Modify: `tools/codex_register/codex_register_service.py:135-252`
- Modify: `tools/codex_register/codex_register_service.py:843-930`
- Modify: `tools/codex_register/codex_register_service.py:935-1055`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Add loop-owned runtime fields in `__init__`**

Add only the minimum needed runtime members:

```python
self._loop_worker_thread: Optional[threading.Thread] = None
self._loop_stop_event = threading.Event()
self._loop_owned_process: Optional[Any] = None
```

- [ ] **Step 2: Extract a loop-round processor helper**

Implement a helper that temporarily maps the durable loop offset into the existing JSONL processor contract and advances the committed offset only on success:

```python
def _process_loop_accounts_jsonl_round(self, state: Dict[str, Any]) -> Dict[str, Any]:
    original_offset = int(state.get("accounts_jsonl_offset") or 0)
    state["accounts_jsonl_offset"] = int(state.get("loop_committed_accounts_jsonl_offset") or 0)
    summary = self._process_accounts_jsonl_records(state)
    state["loop_committed_accounts_jsonl_offset"] = int(summary.get("end_offset") or state["loop_committed_accounts_jsonl_offset"] or 0)
    state["accounts_jsonl_offset"] = original_offset
    return summary
```

If `_process_accounts_jsonl_records` mutates more state than desired, wrap and restore only the fields that should remain main-workflow-owned.

- [ ] **Step 3: Implement `_run_loop_round` with success/failure/stopped history entries**

It should:
- increment `loop_current_round`
- record start/finish times
- call `_run_loop_process_once()` for `gpt-team-new.py`
- on success, call `_process_loop_accounts_jsonl_round()` and update `loop_last_round_*`, `loop_total_created`, `loop_history`
- on exception/non-zero exit, append a failed history entry and keep the committed offset unchanged
- if stop interrupted the subprocess, append a `stopped` history entry
- bound `loop_history` to the latest 20 items

- [ ] **Step 4: Implement `_handle_loop_start`, `_handle_loop_stop`, and the worker loop**

Use a background thread that repeatedly:
- loads state under the existing state lock
- runs `_run_loop_round`
- sleeps with an interruptible wait, e.g. `self._loop_stop_event.wait(timeout=sleep_seconds)`

`_handle_loop_start` must reject if the main workflow already has an active process.

`_handle_enable` and `_handle_resume` must reject if `loop_running` is true.

`_handle_loop_stop` must:
- set the stop event
- terminate `self._loop_owned_process` if present
- return success even when already stopped

- [ ] **Step 5: Add/adjust tests for mutual exclusion and stale-state repair on all loop endpoints**

Include tests like:

```python
def test_enable_rejects_while_loop_running(self):
    state = self.service._default_state()
    state["loop_running"] = True
    asyncio.run(self.service._save_state(state))

    result = asyncio.run(self.service.handle_path("/enable", payload={}))

    self.assertFalse(result["success"])
    self.assertEqual(result["error"], "loop_running")
```

and:

```python
def test_loop_status_repairs_stale_running_state_without_worker(self):
    state = self.service._default_state()
    state["loop_running"] = True
    asyncio.run(self.service._save_state(state))

    result = asyncio.run(self.service.handle_path("/loop/status"))

    self.assertFalse(result["data"]["loop_running"])
    self.assertEqual(result["data"]["loop_last_error"], "loop_worker_missing_after_restart")
```

Also add equivalent stale-state repair assertions for `/loop/start` and `/loop/stop`, so all loop endpoints are forced through the same preflight contract before returning.

- [ ] **Step 6: Run all Python codex-register tests**

Run: `python -m unittest tools.codex_register.test_codex_register_service -v`
Expected: PASS.

- [ ] **Step 7: Commit the loop runner implementation**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: add codex register loop runner"
```

---

## Task 5: Add Go proxy coverage first, then wire loop routes

**Files:**
- Modify: `backend/internal/server/routes/admin_codex_routes_test.go`
- Modify: `backend/internal/handler/admin/codex_handler.go`
- Modify: `backend/internal/server/routes/admin.go`
- Test: `backend/internal/server/routes/admin_codex_routes_test.go`

- [ ] **Step 1: Write a failing route test for `GET /admin/codex/loop/status`**

```go
func TestRegisterCodexRoutesIncludesLoopStatusEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			t.Fatalf("unexpected method: %s", r.Method)
		}
		if r.URL.Path != "/loop/status" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"success":true,"data":{"loop_running":false},"error":null}`))
	}))
	defer upstream.Close()

	t.Setenv("CODEX_REGISTER_BASE_URL", upstream.URL)

	router := gin.New()
	adminGroup := router.Group("/admin")
	registerCodexRoutes(adminGroup, &handler.Handlers{Admin: &handler.AdminHandlers{Codex: adminhandler.NewCodexHandler()}})

	req := httptest.NewRequest(http.MethodGet, "/admin/codex/loop/status", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
}
```

- [ ] **Step 2: Run the new Go route test and verify it fails**

Run: `go test ./backend/internal/server/routes -run TestRegisterCodexRoutesIncludesLoopStatusEndpoint -v`
Expected: FAIL with 404/not found because the route is not registered.

- [ ] **Step 3: Add handler methods and route registrations**

In `codex_handler.go`, add:

```go
func (h *CodexHandler) GetLoopStatus(c *gin.Context) {
	h.proxyGet(c, "/loop/status")
}

func (h *CodexHandler) StartLoop(c *gin.Context) {
	h.proxyPost(c, "/loop/start")
}

func (h *CodexHandler) StopLoop(c *gin.Context) {
	h.proxyPost(c, "/loop/stop")
}
```

In `registerCodexRoutes`, add:

```go
codex.GET("/loop/status", h.Admin.Codex.GetLoopStatus)
codex.POST("/loop/start", h.Admin.Codex.StartLoop)
codex.POST("/loop/stop", h.Admin.Codex.StopLoop)
```

- [ ] **Step 4: Add tests for loop start and loop stop route registration**

Mirror the existing retry/resume route tests for:
- `POST /admin/codex/loop/start` → `/loop/start`
- `POST /admin/codex/loop/stop` → `/loop/stop`

- [ ] **Step 5: Run the codex route tests and verify they pass**

Run: `go test ./backend/internal/server/routes -run CodexRoutes -v`
Expected: PASS.

- [ ] **Step 6: Commit the Go proxy changes**

```bash
git add backend/internal/handler/admin/codex_handler.go backend/internal/server/routes/admin.go backend/internal/server/routes/admin_codex_routes_test.go
git commit -m "feat: proxy codex loop endpoints"
```

---

## Task 6: Add frontend API tests by usage, then implement loop API client and UI

**Files:**
- Modify: `frontend/src/api/admin/codex.ts`
- Modify: `frontend/src/views/admin/settings/components/CodexRegistrationCard.vue`
- Modify: `frontend/src/i18n/locales/zh.ts`
- Modify: `frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts`
- Test: `frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts`

- [ ] **Step 1: Add failing component test for loop controls rendering**

Extend the existing mocked admin API with loop mocks:

```ts
const codexApiMocks = vi.hoisted(() => ({
  getStatus: vi.fn(),
  getLogs: vi.fn(),
  getAccounts: vi.fn(),
  getLoopStatus: vi.fn(),
  startLoop: vi.fn(),
  stopLoop: vi.fn(),
  enable: vi.fn(),
  disable: vi.fn(),
  resume: vi.fn(),
  retry: vi.fn(),
}))
```

Then add a test such as:

```ts
it('renders loop controls and summary from loop status', async () => {
  codexApiMocks.getLoopStatus.mockResolvedValueOnce({
    loop_running: true,
    loop_current_round: 3,
    loop_last_round_created: 2,
    loop_total_created: 7,
    loop_last_error: '',
    loop_history: [],
  })

  const wrapper = mount(CodexRegistrationCard, { props: { active: true }, global: { stubs: { StatCard: StatCardStub } } })
  await flushPromises()

  expect(wrapper.text()).toContain('开始循环注册')
  expect(wrapper.text()).toContain('停止循环注册')
  expect(wrapper.text()).toContain('7')
}
```

- [ ] **Step 2: Run the targeted component test and verify it fails**

Run: `pnpm vitest run frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts -t "renders loop controls and summary from loop status"`
Expected: FAIL because loop API mocks/UI are not wired.

- [ ] **Step 3: Implement loop API types and helpers in `frontend/src/api/admin/codex.ts`**

Add minimal interfaces:

```ts
export interface CodexLoopHistoryEntry {
  round: number
  started_at: string | null
  finished_at: string | null
  created: number
  updated: number
  skipped: number
  failed: number
  status: 'success' | 'failed' | 'stopped'
  error?: string | null
}

export interface CodexLoopStatus {
  loop_running: boolean
  loop_stopping: boolean
  loop_started_at: string | null
  loop_current_round: number
  loop_last_round_started_at: string | null
  loop_last_round_finished_at: string | null
  loop_last_round_created: number
  loop_last_round_updated: number
  loop_last_round_skipped: number
  loop_last_round_failed: number
  loop_total_created: number
  loop_last_error: string | null
  loop_history: CodexLoopHistoryEntry[]
}
```

and helpers:

```ts
export async function getLoopStatus(): Promise<CodexLoopStatus> { ... }
export async function startLoop(): Promise<CodexLoopStatus> { ... }
export async function stopLoop(): Promise<CodexLoopStatus> { ... }
```

- [ ] **Step 4: Implement loop polling and UI in `CodexRegistrationCard.vue`**

Add:
- `const loopStatus = ref<CodexLoopStatus | null>(null)`
- calls to `adminAPI.codex.getLoopStatus()` inside the existing refresh path
- button handlers calling `startLoop()` / `stopLoop()`
- a new section with `data-testid` markers such as:
  - `codex-loop-panel`
  - `codex-loop-start`
  - `codex-loop-stop`
  - `codex-loop-history`

Keep the existing main workflow controls untouched.

- [ ] **Step 5: Add loop-specific zh strings**

Under `admin.codexRegister`, add a `loop` section with keys for:
- title
- description
- start
- stop
- running
- stopped
- currentRound
- lastRoundCreated
- totalCreated
- startedAt
- finishedAt
- lastError
- historyTitle
- emptyHistory
- statusSuccess
- statusFailed
- statusStopped

- [ ] **Step 6: Add a failing/then passing interaction test for start and stop**

Add tests that click the new buttons and assert the correct mock is called, for example:

```ts
await wrapper.find('[data-testid="codex-loop-start"]').trigger('click')
expect(codexApiMocks.startLoop).toHaveBeenCalledTimes(1)
```

and similar for stop when `loop_running` is true.

- [ ] **Step 6: Add explicit frontend tests for button enabled states and history rendering**

Add assertions that:
- start is enabled and stop is disabled when `loop_running` is false
- start is disabled and stop is enabled when `loop_running` is true
- history rows render round/status/count values from `loop_history`

For example:

```ts
expect((wrapper.find('[data-testid="codex-loop-start"]').element as HTMLButtonElement).disabled).toBe(false)
expect((wrapper.find('[data-testid="codex-loop-stop"]').element as HTMLButtonElement).disabled).toBe(true)
expect(wrapper.find('[data-testid="codex-loop-history"]').text()).toContain('3')
expect(wrapper.find('[data-testid="codex-loop-history"]').text()).toContain('success')
```

- [ ] **Step 7: Run the full component test file and verify it passes**

Run: `pnpm vitest run frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts`
Expected: PASS.

- [ ] **Step 8: Commit the frontend loop UI changes**


---

## Task 7: Run cross-stack verification and sanity-check behavior

**Files:**
- Verify only: `tools/codex_register/codex_register_service.py`
- Verify only: `backend/internal/handler/admin/codex_handler.go`
- Verify only: `frontend/src/views/admin/settings/components/CodexRegistrationCard.vue`

- [ ] **Step 1: Run Python unit tests again**

Run: `python -m unittest tools.codex_register.test_codex_register_service -v`
Expected: PASS.

- [ ] **Step 2: Run Go codex route tests again**

Run: `go test ./backend/internal/server/routes -run CodexRoutes -v`
Expected: PASS.

- [ ] **Step 3: Run frontend Codex registration card tests again**

Run: `pnpm vitest run frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts`
Expected: PASS.

- [ ] **Step 4: Manually inspect final behavior contract**

Confirm in code that:
- loop start/stop is independent from main enable/resume controls
- loop count uses DB `created` count only
- loop history is bounded
- stale loop state is repaired on all loop endpoints
- stop uses interruptible sleep between rounds

- [ ] **Step 5: Commit final verification-only adjustments if needed**

```bash
git add tools/codex_register/codex_register_service.py backend/internal/handler/admin/codex_handler.go backend/internal/server/routes/admin.go backend/internal/server/routes/admin_codex_routes_test.go frontend/src/api/admin/codex.ts frontend/src/views/admin/settings/components/CodexRegistrationCard.vue frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts frontend/src/i18n/locales/zh.ts
git commit -m "test: verify codex loop runner integration"
```

---

## Completion Checklist

- [ ] `CodexRegisterService` exposes `/loop/status`, `/loop/start`, and `/loop/stop`.
- [ ] Loop state is persisted, stale state is repaired, and stop is idempotent.
- [ ] Successful rounds update per-round and cumulative DB-created counts.
- [ ] Failed rounds keep the durable JSONL committed offset unchanged.
- [ ] The main enable/resume workflow and the loop workflow are mutually exclusive.
- [ ] Go admin routes proxy the new loop endpoints.
- [ ] The Codex register page shows separate loop controls, loop summary, and loop history.
- [ ] Python, Go, and frontend targeted tests all pass.
