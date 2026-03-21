# Codex Register Loop Proxy Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add preset proxy-pool management and per-round proxy rotation for the Codex register loop so each loop round probes the real target site, prefers a different proxy than the previous round, cools down failed proxies, and injects the chosen proxy into the loop child process.

**Architecture:** Extend `codex_register_service.py` with persisted proxy-pool state, deterministic proxy selection, and new `/proxy/*` endpoints. Proxy selection happens inside the loop runner before each round, while the selected proxy is passed into `gpt-team-new.py` through child-process environment. Backend handler and frontend admin code proxy and render the new proxy-pool controls and loop proxy runtime state.

**Tech Stack:** Python asyncio/threaded service state machine, Go Gin admin proxy handler, Vue 3 + TypeScript admin UI, Vitest, Python unittest/async mocks.

---

## File map

- Modify: `tools/codex_register/codex_register_service.py`
  - Add proxy state defaults, `/proxy/status|list|select|test` handlers, proxy validation helpers, target-site probing, loop-round proxy selection, loop-status enrichment, and child-process env injection.
- Modify: `tools/codex_register/test_codex_register_service.py`
  - Add focused tests for proxy list persistence, selection rules, cooldown behavior, no-available-proxy handling, loop status enrichment, and env injection.
- Modify: `backend/internal/handler/admin/codex_handler.go`
  - Add GET/POST passthrough methods for new proxy endpoints and JSON-body forwarding for POST requests.
- Modify: `backend/internal/server/routes/admin.go`
  - Register `/admin/codex/proxy/status`, `/admin/codex/proxy/list`, `/admin/codex/proxy/select`, `/admin/codex/proxy/test`.
- Modify: `backend/internal/server/routes/admin_codex_routes_test.go`
  - Add route tests for the new proxy endpoints.
- Modify: `frontend/src/api/admin/codex.ts`
  - Add proxy types, normalization helpers, and API calls for get/save/select/test proxy operations; extend loop status typing with current/last proxy fields.
- Modify: `frontend/src/views/admin/settings/components/CodexRegistrationCard.vue`
  - Add proxy-pool panel, table/form state, save/test/select actions, and loop proxy runtime display.
- Modify: `frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts`
  - Add tests for proxy panel rendering and actions.

## Notes before execution

- Worktree created at `/Users/ww/Project/sub2api/.worktrees/loop-proxy-rotation` on branch `feature/loop-proxy-rotation`.
- Baseline Python test command `pytest` is unavailable in the current environment (`command not found`). During execution, use the project’s actual Python test entrypoint if available (for example `python -m pytest ...`) and record the exact working command once confirmed.
- Keep changes YAGNI: no weighted routing, no random scheduling, no main `/enable`/`/resume` proxy migration in this plan.

### Task 1: Add proxy state defaults and endpoint surface in the Python service

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write the failing state/endpoint tests**

Add tests covering:
- `_default_state()` includes proxy fields such as `proxy_enabled`, `proxy_pool`, `proxy_current_id`, `proxy_last_used_id`, `proxy_last_checked_at`, `proxy_last_error`, `proxy_rotation_cursor`, `proxy_last_switch_reason`
- `handle_path("/proxy/status")` returns success and proxy defaults
- unsupported proxy path still returns `unsupported_path`

Example skeleton:

```python
def test_default_state_includes_proxy_rotation_fields(self):
    state = self.service._default_state()
    assert state["proxy_enabled"] is False
    assert state["proxy_pool"] == []
    assert state["proxy_rotation_cursor"] == 0
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:
```bash
python -m pytest tools/codex_register/test_codex_register_service.py -k "proxy_rotation_fields or proxy_status" -q
```

Expected: FAIL because proxy fields/handlers do not exist yet.

- [ ] **Step 3: Implement minimal service defaults and routing**

In `codex_register_service.py`:
- Add `/proxy/status`, `/proxy/list`, `/proxy/select`, `/proxy/test` handling in `handle_path`
- Extend allowed GET/POST path sets near `codex_register_service.py:1916`
- Extend `_default_state()` with the persisted proxy fields from the spec
- Define explicit `proxy_enabled` semantics for v1: set it to `True` when there is at least one enabled proxy in `proxy_pool`, set it to `False` when the stored pool has no enabled proxies, and return that value from `/proxy/status`
- Add `_handle_proxy_status()` returning the current state envelope slice or the full enriched state if that matches existing style

- [ ] **Step 4: Run the focused tests to verify they pass**

Run the same command from Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: add codex loop proxy state surface"
```

### Task 2: Implement proxy list persistence, validation, and manual operations

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write failing tests for proxy list save/select/test flows**

Add tests for:
- saving a valid proxy list through `handle_path("/proxy/list", payload=...)`
- rejecting duplicate ids
- rejecting duplicate normalized proxy URLs
- rejecting empty `name`
- rejecting empty `proxy_url`
- defaulting `enabled` to `True` when omitted
- clearing `proxy_current_id` when the selected proxy is removed/disabled
- selecting a preferred proxy through `/proxy/select`
- `/proxy/test` invoking the probe helper for a specific proxy id
- `/proxy/status` returning current proxy summary, previous proxy summary, pool status/cooldown metadata, `proxy_last_error`, and `proxy_last_switch_reason`

Example skeleton:

```python
def test_proxy_list_rejects_duplicate_proxy_url(self):
    payload = {"proxies": [
        {"id": "a", "name": "A", "proxy_url": "http://one", "enabled": True},
        {"id": "b", "name": "B", "proxy_url": "http://one/", "enabled": True},
    ]}
    result = asyncio.run(self.service.handle_path("/proxy/list", payload=payload))
    assert result["success"] is False
    assert result["error"] == "duplicate_proxy_url"
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:
```bash
python -m pytest tools/codex_register/test_codex_register_service.py -k "proxy_list or proxy_select or proxy_test" -q
```

Expected: FAIL.

- [ ] **Step 3: Implement proxy normalization, validation, and handlers**

Add focused helpers in `codex_register_service.py`:
- `_normalize_proxy_entry(...)`
- `_normalize_proxy_url(...)`
- `_validate_proxy_pool_payload(...)`
- `_merge_proxy_runtime_metadata(...)`
- `_find_proxy_by_id(...)`
- `_handle_proxy_list(...)`
- `_handle_proxy_select(...)`
- `_handle_proxy_test(...)`

Keep handlers small and deterministic:
- list replacement is atomic
- preserve runtime timestamps/counters for unchanged proxy IDs where possible
- `/proxy/test` does not mutate loop-running state

- [ ] **Step 4: Run the focused tests to verify they pass**

Run the command from Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: add codex proxy pool management"
```

### Task 3: Implement target-site probe and loop-round proxy selection

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write failing tests for selection order and cooldown behavior**

Add tests for:
- a round prefers a proxy different from `proxy_last_used_id`
- candidate ordering starts from `proxy_rotation_cursor`
- stable ordered polling is preserved among eligible proxies
- a failed probe moves to the next candidate
- failed proxies are skipped during cooldown
- previous-round proxy is only retried as fallback
- all proxies unavailable returns round history with `error == "no_available_proxy"`

Example skeleton:

```python
def test_select_loop_proxy_prefers_different_proxy_than_previous_round(self):
    state = self.service._default_state()
    state["proxy_enabled"] = True
    state["proxy_last_used_id"] = "p1"
    state["proxy_pool"] = [ ... ]
    with patch.object(self.service, "_probe_proxy_target", side_effect=[False, True]):
        selected = asyncio.run(self.service._select_loop_proxy(state))
    assert selected["id"] == "p2"
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:
```bash
python -m pytest tools/codex_register/test_codex_register_service.py -k "select_loop_proxy or no_available_proxy or cooldown" -q
```

Expected: FAIL.

- [ ] **Step 3: Implement minimal probe and selection helpers**

In `codex_register_service.py` add:
- `_probe_proxy_target(proxy_url)` using a short timeout against a deterministic target-site URL from existing registration dependencies
- `_is_proxy_in_cooldown(...)`
- `_compute_proxy_cooldown_until(...)`
- `_build_proxy_candidates(...)`
- `_select_loop_proxy(state)`
- state updates for `proxy_last_used_id`, `proxy_last_checked_at`, `proxy_rotation_cursor`, `proxy_last_error`, `proxy_last_switch_reason`

Keep the first version simple:
- fixed cooldown window
- deterministic ordered polling
- fallback to previous-round proxy only after alternatives fail

- [ ] **Step 4: Run the focused tests to verify they pass**

Run the command from Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: add loop proxy rotation selection"
```

### Task 4: Inject the selected proxy into loop process execution and loop status

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write failing tests for env injection and loop status enrichment**

Add tests for:
- `_run_loop_round(...)` selecting a proxy before spawning the child process
- `_spawn_process(...)` or a loop-specific wrapper receiving env with `REGISTER_PROXY_URL` (or the existing env var contract if already present)
- `loop/status` including `loop_current_proxy_id`, `loop_current_proxy_name`, `loop_last_proxy_id`, `loop_last_proxy_name`, `loop_last_switch_reason`
- child-process failure does not automatically mark the selected proxy failed if the probe had already succeeded
- updating the proxy list during an in-progress round does not change the proxy used by the already-running child process
- disabling or removing the currently selected proxy mid-round does not break the current round, but prevents future rounds from reselecting it
- `/loop/start` uses stored proxy-pool state and does not require or consume a per-request proxy argument

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:
```bash
python -m pytest tools/codex_register/test_codex_register_service.py -k "loop_current_proxy or register_proxy_url or loop_status" -q
```

Expected: FAIL.

- [ ] **Step 3: Implement loop-round integration**

Update the loop path in `codex_register_service.py` around:
- `_handle_loop_status()`
- `_run_loop_round(...)`
- `_merge_loop_round_state(...)`
- `_run_loop_process_once(...)` / `_spawn_process(...)`

Implementation details:
- select a proxy before spawning `gpt-team-new.py`
- if no proxy is available, create a failed history entry and skip process spawn for that round
- pass the selected proxy via child-process env rather than global mutable process state
- persist current/last proxy display fields into loop state

If `_spawn_process` currently cannot accept env overrides, minimally extend it to accept an optional `env` dict and preserve current callers.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run the command from Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: inject rotated proxy into codex loop rounds"
```

### Task 5: Expose proxy endpoints through the Go admin layer

**Files:**
- Modify: `backend/internal/handler/admin/codex_handler.go`
- Modify: `backend/internal/server/routes/admin.go`
- Test: `backend/internal/server/routes/admin_codex_routes_test.go`

- [ ] **Step 1: Write failing route tests**

Add tests verifying these routes exist and proxy upstream correctly:
- `GET /admin/codex/proxy/status` -> `/proxy/status`
- `POST /admin/codex/proxy/list` -> `/proxy/list`
- `POST /admin/codex/proxy/select` -> `/proxy/select`
- `POST /admin/codex/proxy/test` -> `/proxy/test`

Also add one body-forwarding test for a POST proxy endpoint if existing behavior does not already cover request payload passthrough.

- [ ] **Step 2: Run the Go tests to verify they fail**

Run:
```bash
go test ./backend/internal/server/routes -run Codex -count=1
```

Expected: FAIL because routes/handlers do not exist yet.

- [ ] **Step 3: Implement the minimal Go proxy surface**

In `codex_handler.go`:
- add methods `GetProxyStatus`, `SaveProxyList`, `SelectProxy`, `TestProxy`
- extend `proxyPost` to forward JSON request bodies from Gin to upstream instead of always sending `nil`

In `admin.go`:
- register the new proxy routes under `/admin/codex`

- [ ] **Step 4: Run the Go tests to verify they pass**

Run the command from Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/internal/handler/admin/codex_handler.go backend/internal/server/routes/admin.go backend/internal/server/routes/admin_codex_routes_test.go
git commit -m "feat: expose codex proxy endpoints"
```

### Task 6: Extend frontend API types and calls for proxy management

**Files:**
- Modify: `frontend/src/api/admin/codex.ts`
- Test: existing frontend tests that consume the API module indirectly

- [ ] **Step 1: Write or update the failing consumer tests first**

If there are direct API module tests, add them; otherwise update the card tests in Task 7 first and return here when they fail due to missing API functions/types.

Needed API surface:
- `CodexProxyEntry`
- `CodexProxyStatus`
- loop status fields for current/last proxy
- `getProxyStatus()`
- `saveProxyList(payload)`
- `selectProxy(payload)`
- `testProxy(payload)`

- [ ] **Step 2: Run the relevant frontend tests to verify failure**

Run something like:
```bash
pnpm vitest frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts --run
```

Expected: FAIL because proxy API helpers/types are missing.

- [ ] **Step 3: Implement the API layer changes**

In `frontend/src/api/admin/codex.ts`:
- define proxy entry/status types
- add default/normalize helpers matching backend envelopes
- expose the four new API methods
- extend `CodexLoopStatus` normalization to include the new proxy runtime fields

Keep names aligned with backend response keys to avoid extra mapping complexity.

- [ ] **Step 4: Re-run the relevant frontend tests**

Run the command from Step 2.
Expected: fewer failures or PASS if UI work is already complete.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/admin/codex.ts
git commit -m "feat: add codex proxy admin api"
```


### Task 7: Add proxy-pool UI to the Codex registration card

**Files:**
- Modify: `frontend/src/views/admin/settings/components/CodexRegistrationCard.vue`
- Modify: `frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts`
- Optionally modify: `frontend/src/i18n/locales/en.ts` and matching locale files if the component relies on central messages instead of test-local stubs

- [ ] **Step 1: Write the failing component tests**

Add tests for:
- proxy pool rows render from API data
- save action sends edited proxy list
- test action calls `testProxy`
- loop panel displays current round proxy and previous round proxy
- cooldown / failed state is visible in the UI
- available proxy count is displayed
- last proxy error is displayed

Example skeleton:

```ts
it('shows the current and previous loop proxy', async () => {
  codexApiMocks.getLoopStatus.mockResolvedValue(makeLoopStatus({
    loop_current_proxy_name: 'Proxy B',
    loop_last_proxy_name: 'Proxy A'
  }))
  const wrapper = mountCard()
  await flushPromises()
  expect(wrapper.text()).toContain('Proxy B')
  expect(wrapper.text()).toContain('Proxy A')
})
```

- [ ] **Step 2: Run the component tests to verify they fail**

Run:
```bash
pnpm vitest frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts --run
```

Expected: FAIL.

- [ ] **Step 3: Implement the minimal UI**

In `CodexRegistrationCard.vue`:
- fetch proxy status during the same polling cycle as loop/status
- render a focused proxy panel/table
- add save/test/select/enable-disable interactions using the new API methods
- display loop current/last proxy fields in the loop summary area
- display available proxy count and last proxy error

Keep the UI compact and admin-oriented; do not redesign the whole page.

- [ ] **Step 4: Run the component tests to verify they pass**

Run the command from Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/admin/settings/components/CodexRegistrationCard.vue frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts frontend/src/i18n/locales/en.ts frontend/src/i18n/locales/zh-CN.ts
 git commit -m "feat: add codex proxy rotation controls"
```

### Task 8: Run full verification and fix any regressions

**Files:**
- Modify only files required by failures discovered in verification

- [ ] **Step 1: Run Python service tests**

Run:
```bash
python -m pytest tools/codex_register/test_codex_register_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run targeted Python regressions for unchanged main workflow paths**

Run:
```bash
python -m pytest tools/codex_register/test_codex_register_service.py -k "enable or resume" -q
```

Expected: PASS, confirming `/enable` and `/resume` still behave as before.

- [ ] **Step 3: Run Go codex route tests**

Run:
```bash
go test ./backend/internal/server/routes -run Codex -count=1
```

Expected: PASS.

- [ ] **Step 4: Run frontend codex card tests**

Run:
```bash
pnpm vitest frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts --run
```

Expected: PASS.

- [ ] **Step 5: Fix any discovered regressions minimally**

Only change files implicated by failing verification.

- [ ] **Step 6: Re-run the failed verification commands until all pass**

Document the exact passing commands/output in the final handoff.

- [ ] **Step 7: Commit**

```bash
git add <verified-files>
git commit -m "fix: finalize codex loop proxy rotation"
```
