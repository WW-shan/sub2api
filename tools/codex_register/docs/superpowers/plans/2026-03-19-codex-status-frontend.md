# Codex /admin/codex/accounts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose a `/admin/codex/accounts` endpoint that returns a list of codex registration accounts to the frontend, by reading the `accounts.jsonl` output from `get_tokens.py` / `gpt-team-new.py` and proxying it through the existing backend.

**Architecture:** The codex-register Python service (`CodexRegisterService`) will gain a new JSONL-to-DTO helper that reads `accounts.jsonl`, normalizes records into a `CodexRegisterAccount`-like shape, and returns them as the payload for its `GET /accounts` route. The Go backend will continue to proxy `/admin/codex/accounts` to the Python service without extra logic, and the Vue frontend will keep using `getAccounts()` unchanged.

**Tech Stack:** Python (asyncio, subprocess, Postgres helpers) in `tools/codex_register`; Go (gin) backend proxy; Vue/TypeScript frontend using `frontend/src/api/admin/codex.ts`.

---

## File Map

- **Python service (core behavior)**
  - Modify: `tools/codex_register/codex_register_service.py`
    - Add a JSONL account listing helper (e.g., `_list_accounts_for_frontend`).
    - Change `/accounts` handling in `handle_path` to return account list instead of summary, or to return a shape compatible with the frontend contract.
- **Python tests (service contract)**
  - Modify: `tools/codex_register/test_codex_register_service.py`
    - Add tests for the new accounts listing helper and `/accounts` path behavior against a temporary `accounts.jsonl`.
- **Go backend (already wired)**
  - Verify only: `backend/internal/handler/admin/codex_handler.go`
    - Confirm `GetAccounts` proxies to `/accounts` (no code change expected).
- **Frontend (already wired)**
  - Verify only: `frontend/src/api/admin/codex.ts`
    - Confirm `getAccounts()` expects `CodexRegisterAccount[]` via either `{accounts}` or envelope `data`.

---

## Task 1: Add JSONL → account DTO helper in CodexRegisterService

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Implement `_list_accounts_for_frontend` helper**

  In `CodexRegisterService`, near the JSONL helpers (`_read_accounts_jsonl_records`, `_parse_account_jsonl_line`), implement:

  ```python
  def _list_accounts_for_frontend(self) -> List[Dict[str, Any]]:
      """Read accounts.jsonl and normalize into frontend-ready records.

      Fields:
        - id: monotonically increasing integer (1-based)
        - email: normalized email
        - refresh_token/access_token: optional, may be empty strings
        - account_id: optional string or None
        - source: record source (e.g., 'get_tokens', 'gpt-team-new', 'accounts_jsonl')
        - codex_register_role, plan_type, organization_id, workspace_id: currently None
        - created_at/updated_at: best-effort timestamps from record or empty string
      """
      records, _next_offset = self._read_accounts_jsonl_records(start_offset=0)
      accounts: List[Dict[str, Any]] = []
      next_id = 1
      for record in records:
          email = str(record.get("email") or "").strip()
          if not email:
              continue
          account = {
              "id": next_id,
              "email": email,
              "refresh_token": record.get("refresh_token") or "",
              "access_token": record.get("access_token") or "",
              "account_id": (record.get("account_id") or "") or None,
              "source": record.get("source") or "accounts_jsonl",
              "codex_register_role": None,
              "plan_type": None,
              "organization_id": None,
              "workspace_id": None,
              "created_at": record.get("created_at") or "",
              "updated_at": record.get("created_at") or "",
          }
          accounts.append(account)
          next_id += 1
      return accounts
  ```

- [ ] **Step 2: Add unit test for helper**

  In `JsonlParsingTests` or a new test class in `test_codex_register_service.py`, add:

  ```python
  def test_list_accounts_for_frontend_normalizes_jsonl_records(self):
      with tempfile.TemporaryDirectory() as tmpdir:
          path = pathlib.Path(tmpdir) / "accounts.jsonl"
          line1 = json.dumps({
              "email": "user1@example.com",
              "access_token": "at1",
              "refresh_token": "rt1",
              "account_id": "acct-1",
              "source": "gpt-team-new",
              "created_at": "2026-03-19T00:00:00Z",
          }) + "\n"
          line2 = json.dumps({
              "email": "user2@example.com",
              "access_token": "at2",
          }) + "\n"
          path.write_text(line1 + "not-json\n" + line2, encoding="utf-8")
          self.service._accounts_jsonl_path = path

          accounts = self.service._list_accounts_for_frontend()

      self.assertEqual(len(accounts), 2)
      self.assertEqual(accounts[0]["id"], 1)
      self.assertEqual(accounts[0]["email"], "user1@example.com")
      self.assertEqual(accounts[0]["access_token"], "at1")
      self.assertEqual(accounts[0]["account_id"], "acct-1")
      self.assertEqual(accounts[0]["source"], "gpt-team-new")
      self.assertEqual(accounts[1]["id"], 2)
      self.assertEqual(accounts[1]["email"], "user2@example.com")
      self.assertEqual(accounts[1]["access_token"], "at2")
  ```

- [ ] **Step 3: Run targeted tests for JSONL helpers**

  ```bash
  cd tools/codex_register
  python -m unittest test_codex_register_service.JsonlParsingTests -v
  ```

---

## Task 2: Wire `/accounts` path to return account list

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Modify: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Change `/accounts` handling in `handle_path`**

  Replace the existing `/accounts` branch:

  ```python
  if path == "/accounts":
      state = await self._load_state()
      return self._result(True, data=self._build_accounts_status_data(state))
  ```

  With:

  ```python
  if path == "/accounts":
      accounts = self._list_accounts_for_frontend()
      return self._result(True, data=accounts)
  ```

- [ ] **Step 2: Add/adjust service test for `/accounts` path contract**

  In `ProcessingFlowTests` or a new test class, add:

  ```python
  def test_accounts_path_returns_list_of_accounts_from_jsonl(self):
      with tempfile.TemporaryDirectory() as tmpdir:
          path = pathlib.Path(tmpdir) / "accounts.jsonl"
          path.write_text(
              "\n".join([
                  json.dumps({"email": "one@example.com", "access_token": "t1", "source": "gpt-team-new"}),
                  json.dumps({"email": "two@example.com", "access_token": "t2", "source": "get_tokens"}),
              ]) + "\n",
              encoding="utf-8",
          )
          self.service._accounts_jsonl_path = path

          async def _run():
              return await self.service.handle_path("/accounts")

          result = asyncio.run(_run())

      self.assertTrue(result["success"])
      accounts = result["data"]
      self.assertEqual(len(accounts), 2)
      self.assertEqual(accounts[0]["email"], "one@example.com")
      self.assertEqual(accounts[1]["email"], "two@example.com")
  ```

  If `test_accounts_endpoint_returns_useful_state_summary` still exists and refers to `/accounts`, either update it to call `_build_accounts_status_data` directly, or adjust expectations to match the new list-based response.

- [ ] **Step 3: Run full codex-register service tests**

  ```bash
  cd tools/codex_register
  python -m unittest test_codex_register_service -v
  ```

---

## Task 3: Verify backend proxy and frontend integration

**Files:**
- Verify only: `backend/internal/handler/admin/codex_handler.go`
- Verify only: `frontend/src/api/admin/codex.ts`

- [ ] **Step 1: Confirm Go proxy routes `/admin/codex/accounts` → `/accounts`**

  Ensure:

  ```go
  func (h *CodexHandler) GetAccounts(c *gin.Context) {
      h.proxyGet(c, "/accounts")
  }
  ```

- [ ] **Step 2: Confirm frontend `getAccounts()` handles `{success,data:[...]}`**

  `getAccounts()` already unwraps either `{accounts}` or a `CodexEnvelope` with `data`. With the Python service now returning `{ success, data: [...] }`, the second branch continues to work without changes.

- [ ] **Step 3: (Optional) Run backend/admin codex route tests**

  ```bash
  cd backend
  go test ./internal/handler/admin ./internal/server/routes -run Codex -v
  ```

---

## Task 4: Docker persistence sanity check

**Files:**
- Verify only: `tools/codex_register/Dockerfile`
- Verify only: Docker compose / deployment manifests

- [ ] **Step 1: Ensure `accounts.jsonl` is on a volume shared by codex-register service and worker scripts**

  - Confirm the codex-register container either:
    - Mounts the `tools/codex_register` directory (containing `accounts.jsonl`), or
    - Writes `accounts.jsonl` to a dedicated data directory (e.g., `/data/codex_register/accounts.jsonl`) that is volume-mounted.

- [ ] **Step 2: Run a manual E2E smoke test**

  1. In Docker, trigger a codex registration flow so that `get_tokens.py` / `gpt-team-new.py` append records to `accounts.jsonl`.
  2. From the admin UI, open the Codex registration card (which calls `getAccounts()` under the hood).
  3. Verify that the listed accounts in the UI correspond to those in `accounts.jsonl` (emails and approximate creation times).

---

## Completion Checklist

- [ ] `_list_accounts_for_frontend` implemented and covered by tests.
- [ ] `/accounts` path returns a JSON array of normalized account records.
- [ ] `python -m unittest tools.codex_register.test_codex_register_service -v` passes.
- [ ] Go backend proxy and frontend API client work unchanged with the new response shape.
- [ ] Docker volume configuration ensures `accounts.jsonl` is persisted and shared.
