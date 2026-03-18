# GPT Team Accounts JSONL Service Upsert Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `gpt-team-new.py` emit success-only `accounts.jsonl` records and make `codex_register_service.py` read those records and upsert accounts into Postgres with invited/team vs free group routing.

**Architecture:** Keep generation and import separated. `gpt-team-new.py` stays responsible for registration/invite/token acquisition and appends one structured JSONL record only when an account is directly importable. `codex_register_service.py` gains self-contained JSONL parsing, offset tracking, Postgres upsert helpers, and env-based group binding logic rewritten locally instead of importing the old service.

**Tech Stack:** Python 3, stdlib `json`/`pathlib`/`datetime`, existing `requests` flow in `gpt-team-new.py`, existing async service state machine in `codex_register_service.py`, Postgres via `psycopg2` imported lazily.

---

## File Structure

- Modify: `tools/codex_register/gpt-team-new.py`
  - Add a new JSONL success-output constant and append helper.
  - Reuse `build_token_dict()` output to construct importable records.
  - Emit JSONL only after token acquisition succeeds.
  - Include `invited` and `team_name` in the emitted record.
- Modify: `tools/codex_register/codex_register_service.py`
  - Replace the current `results.txt`-only parsing path with a structured accounts JSONL parser for the enable flow.
  - Add Postgres helper functions rewritten from old behavior: env parsing, DB connection, JSON wrapping, lookup, update decision, credentials/extra builders, group binding, record upsert.
  - Track accounts JSONL offsets in service state so only newly appended records are processed.
  - Route groups using `CODEX_GROUP_IDS_TEAM` and `CODEX_GROUP_IDS_FREE`.
- Modify: `tools/codex_register/test_codex_register_service.py`
  - Add tests for JSONL parsing, offset handling, group routing, record validation, and upsert helper behavior.
  - Update existing tests that currently patch `_extract_latest_valid_results_record()` so they patch the new accounts-record reader instead.
- Optional modify if tests warrant it: `tools/codex_register/docs/superpowers/specs/2026-03-18-gpt-team-new-accounts-jsonl-service-upsert-design.md`
  - Only if implementation reveals a necessary contract adjustment.

## Chunk 1: Emit importable account records from gpt-team-new

### Task 1: Add a structured accounts JSONL output helper

**Files:**
- Modify: `tools/codex_register/gpt-team-new.py:57-60`
- Modify: `tools/codex_register/gpt-team-new.py:1752-1760`

- [ ] **Step 1: Write the failing test (or minimal red assertion target)**

Add a focused test case or, if no direct test harness exists for this file yet, define the helper contract in code comments near the new helper target and plan to validate with `py_compile` plus a targeted import/execution snippet. The helper contract must require one JSON object per line and no writes for non-importable accounts.

- [ ] **Step 2: Run a syntax-safe baseline check**

Run: `python -m py_compile tools/codex_register/gpt-team-new.py`
Expected: PASS before edits.

- [ ] **Step 3: Add new output constants and append helper**

Implement a new constant such as:

```python
ACCOUNTS_JSONL_FILE: str = "accounts.jsonl"
```

Add a new thread-safe helper near the existing txt writer, for example:

```python
_jsonl_lock = threading.Lock()

def append_importable_account_record(record: Dict[str, Any]) -> None:
    with _jsonl_lock:
        with open(ACCOUNTS_JSONL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
```

Do not remove the existing txt output unless the implementation makes it unnecessary and the user has approved that separately.

- [ ] **Step 4: Run syntax check**

Run: `python -m py_compile tools/codex_register/gpt-team-new.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/gpt-team-new.py
git commit -m "feat: add accounts jsonl output helper"
```

### Task 2: Emit JSONL records only for directly importable successes

**Files:**
- Modify: `tools/codex_register/gpt-team-new.py:1096-1122`
- Modify: `tools/codex_register/gpt-team-new.py:1767-1843`

- [ ] **Step 1: Write the failing behavior expectation**

Document or codify the expected record shape using a small focused assertion around token-derived output fields:

```python
record = build_importable_account_record(
    email="user@example.com",
    password="pw",
    token_dict={
        "access_token": "at",
        "refresh_token": "rt",
        "id_token": "id",
        "account_id": "acc",
        "expired": "2026-03-18T12:00:00+08:00",
    },
    invited=True,
    team_name="1",
)
assert record["email"] == "user@example.com"
assert record["invited"] is True
assert record["account_id"] == "acc"
```

- [ ] **Step 2: Add a record builder next to `build_token_dict()`**

Implement a helper similar to:

```python
def build_importable_account_record(
    *,
    email: str,
    password: str,
    token_dict: Dict[str, Any],
    invited: bool,
    team_name: str = "",
    auth_file: str = "",
) -> Optional[Dict[str, Any]]:
    access_token = str(token_dict.get("access_token") or "").strip()
    if not email or "@" not in email or not access_token:
        return None
    return {
        "email": email,
        "password": password,
        "access_token": access_token,
        "refresh_token": str(token_dict.get("refresh_token") or ""),
        "id_token": str(token_dict.get("id_token") or ""),
        "account_id": str(token_dict.get("account_id") or ""),
        "expires_at": str(token_dict.get("expired") or ""),
        "auth_file": auth_file,
        "invited": bool(invited),
        "team_name": team_name,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "gpt-team-new",
    }
```

- [ ] **Step 3: Wire emission into `register_one_account()`**

After token acquisition succeeds and after the token JSON is saved, build the record and append it:

```python
token_dict = build_token_dict(email, tokens)
record = build_importable_account_record(
    email=email,
    password=password,
    token_dict=token_dict,
    invited=invited,
    team_name=(team.get("name") if invited else ""),
)
if record is not None:
    append_importable_account_record(record)
```

You will need a stable `team_name` variable from the invite path. Keep the change minimal: capture the selected/used team name only when invite succeeded. If token acquisition fails, do not append to JSONL.

- [ ] **Step 4: Run syntax check**

Run: `python -m py_compile tools/codex_register/gpt-team-new.py`
Expected: PASS.

- [ ] **Step 5: Run a targeted smoke execution (non-networked import only)**

Run: `python - <<'PY'
import importlib.util, pathlib
p = pathlib.Path('tools/codex_register/gpt-team-new.py').resolve()
spec = importlib.util.spec_from_file_location('gpt_team_new_runtime', p)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(hasattr(mod, 'build_importable_account_record'))
PY`
Expected: `True` on stdout and no import errors.

- [ ] **Step 6: Commit**

```bash
git add tools/codex_register/gpt-team-new.py
git commit -m "feat: emit importable account records from gpt team flow"
```

## Chunk 2: Teach codex_register_service to read accounts JSONL

### Task 3: Replace results.txt parsing with accounts.jsonl parsing for enable completion

**Files:**
- Modify: `tools/codex_register/codex_register_service.py:80-127`
- Modify: `tools/codex_register/codex_register_service.py:305-347`
- Modify: `tools/codex_register/codex_register_service.py:383-460`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write the failing test**

Add tests that replace the old parser contract:

```python
record = {
    "email": "mother@example.com",
    "access_token": "tok",
    "refresh_token": "rt",
    "account_id": "acc-1",
    "invited": True,
}
with patch.object(self.service, "_extract_latest_valid_account_record", return_value={**record, "line_end_offset": 1}):
    ...
```

Update the existing enable/resume tests that currently patch `_extract_latest_valid_results_record` so they patch the new method name and assert resume context now comes from the JSONL record.

- [ ] **Step 2: Run the targeted failing tests**

Run: `python -m unittest tools.codex_register.test_codex_register_service -v`
Expected: FAIL because `_extract_latest_valid_account_record` and the new state fields do not exist yet.

- [ ] **Step 3: Implement accounts file offset capture and JSONL parsing**

Replace the current `results.txt` helpers with accounts JSONL equivalents:

```python
def _capture_accounts_baseline_offset(self) -> int:
    path = self._base_dir / "accounts.jsonl"
    ...

def _extract_latest_valid_account_record(self, *, baseline_offset: int) -> Optional[Dict[str, Any]]:
    ...

def _parse_account_jsonl_line(self, line: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(line)
    except Exception:
        return None
    email = str(data.get("email") or "").strip()
    access_token = str(data.get("access_token") or "").strip()
    if not email or "@" not in email or not access_token:
        return None
    data["invited"] = bool(data.get("invited"))
    return data
```

Preserve `line_offset`/`line_end_offset` tracking so the service can resume from the correct byte position.

- [ ] **Step 4: Update state keys and enable completion path**

Replace `results_baseline_offset` usage with `accounts_baseline_offset` (or support both briefly if needed inside the service state only). On successful enable completion, parse the latest valid accounts JSONL record, build resume context from that record, and fail with a new deterministic error like `accounts_result_missing` if no importable record exists.

- [ ] **Step 5: Update `_build_resume_context_from_parsed_result()`**

It should extract the same email/access-token hint from the JSONL record and may also carry invited/team metadata forward if useful. Keep secrets minimized in public status payloads.

- [ ] **Step 6: Run the targeted tests**

Run: `python -m unittest tools.codex_register.test_codex_register_service -v`
Expected: PASS for the parser/enable/resume contract tests.

- [ ] **Step 7: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "refactor: read accounts jsonl in codex register service"
```

## Chunk 3: Rebuild Postgres upsert logic inside codex_register_service

### Task 4: Add env parsing, DB connection, and group-selection helpers

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write the failing test**

Add unit tests for group parsing and invited routing:

```python
with patch.dict(self.module.os.environ, {
    "CODEX_GROUP_IDS_TEAM": "1,2",
    "CODEX_GROUP_IDS_FREE": "3",
}, clear=False):
    self.assertEqual(self.module.parse_group_ids_by_invited(True), [1, 2])
    self.assertEqual(self.module.parse_group_ids_by_invited(False), [3])
```

- [ ] **Step 2: Run the focused failing tests**

Run: `python -m unittest tools.codex_register.test_codex_register_service.GroupRoutingTests -v`
Expected: FAIL because the helpers do not exist yet.

- [ ] **Step 3: Implement helper functions in the new service module**

Recreate minimal versions of the old helpers directly in `codex_register_service.py`:

```python
def _get_env(name: str, default: str = "", required: bool = False) -> str: ...
def _parse_group_ids(raw: str, fallback: Optional[List[int]] = None) -> List[int]: ...
def parse_group_ids_by_invited(invited: bool) -> List[int]: ...
def create_db_connection(): ...
def pg_json(value: Any): ...
def normalize_extra_for_compare(extra: Dict[str, Any]) -> Dict[str, Any]: ...
def should_update_account(...): ...
def compute_group_binding_changes(...): ...
```

`parse_group_ids_by_invited(True)` must read `CODEX_GROUP_IDS_TEAM`; `False` must read `CODEX_GROUP_IDS_FREE`.

- [ ] **Step 4: Run the focused tests**

Run: `python -m unittest tools.codex_register.test_codex_register_service.GroupRoutingTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: add env-driven group routing helpers"
```

### Task 5: Add credentials/extra builders and account upsert helpers

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:
- `get_existing_account()` query selection by email/account_id
- `build_credentials()` setting source/model mapping/email/account_id/token fields
- `build_extra()` preserving/adding codex metadata
- `upsert_account_record()` updating existing rows vs inserting new rows

Use fake cursor objects; do not require a real database.

Example target behavior:

```python
token_info = {
    "email": "user@example.com",
    "access_token": "at",
    "refresh_token": "rt",
    "id_token": "id",
    "account_id": "acc-1",
    "auth_file": "output_tokens/user@example.com.json",
    "invited": True,
}
```

- [ ] **Step 2: Run the focused failing tests**

Run: `python -m unittest tools.codex_register.test_codex_register_service.AccountUpsertHelperTests -v`
Expected: FAIL because helper implementations do not exist yet.

- [ ] **Step 3: Implement the local upsert helpers**

Add service-module helpers modeled after the old service, but adapted to the new record schema:

```python
def get_existing_account(cur, email: str, account_id: str): ...
def build_model_mapping() -> Dict[str, str]: ...
def build_credentials(existing: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]: ...
def build_extra(existing: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]: ...
def bind_groups(cur, account_id: int, group_ids: List[int]) -> None: ...
def upsert_account_record(cur, record: Dict[str, Any]) -> str: ...
```

Required behavior:
- skip if no `email` and no `account_id`
- skip if no `access_token`
- use `invited` to select team/free group ids
- set `credentials["source"] = "codex-auto-register"`
- set `credentials["model_mapping"] = build_model_mapping()`
- preserve old compare/update behavior so unchanged rows become `skipped`
- update `extra["codex_auto_register"] = True`
- update `extra["codex_auto_register_updated_at"]` on create/update

- [ ] **Step 4: Run the focused tests**

Run: `python -m unittest tools.codex_register.test_codex_register_service.AccountUpsertHelperTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: add account upsert helpers to codex register service"
```

## Chunk 4: Process new JSONL records and expose useful status

### Task 6: Add record-processing flow to the service

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests for a new processing method, for example `_process_new_account_records()`:
- reads only records after the saved offset
- upserts valid records in order
- advances offset only after successful handling
- increments created/updated/skipped counters
- records useful status such as last processed email

Example assertion shape:

```python
state = await self.store.load_state()
state["accounts_baseline_offset"] = 0
await self.store.save_state(state)
with patch.object(self.service, "_read_account_records_since", return_value=[...]), ...:
    updated_state = await self.service._process_new_account_records(...)
self.assertEqual(updated_state["total_created"], 1)
```

- [ ] **Step 2: Run focused failing tests**

Run: `python -m unittest tools.codex_register.test_codex_register_service.AccountRecordProcessingTests -v`
Expected: FAIL because the processor does not exist yet.

- [ ] **Step 3: Implement record processing**

Add a service method that:
- opens a DB connection lazily
- reads new JSONL records from the saved offset
- processes them one by one using `upsert_account_record()`
- updates state counters like `total_created`, `total_updated`, `total_skipped`
- stores the advanced offset back into state
- appends logs for create/update/skip/error outcomes

Keep failures isolated per record where practical. If a record fails unexpectedly, log it and do not advance past that record unless your implementation explicitly marks it as invalid and skipped.

- [ ] **Step 4: Invoke processing at the correct lifecycle point**

Hook the processor into the successful `resume` completion path (`return_code == 0 and mode == "resume"`) before setting the state to `completed`, or immediately after it, depending on where state handling remains simplest and deterministic. The important part is: after the gpt batch finishes successfully, newly written JSONL records are imported into Postgres.

- [ ] **Step 5: Expose useful `/accounts` data**

Replace the placeholder `return []` with lightweight status data, for example the latest processed account summary/counters from state. Keep it minimal; no need for a full DB listing unless already easy and requested.

- [ ] **Step 6: Run the service test suite**

Run: `python -m unittest tools.codex_register.test_codex_register_service -v`
Expected: PASS.

- [ ] **Step 7: Run syntax check**

Run: `python -m py_compile tools/codex_register/codex_register_service.py tools/codex_register/gpt-team-new.py`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py tools/codex_register/gpt-team-new.py
git commit -m "feat: import gpt team accounts into postgres on completion"
```

## Chunk 5: Final verification

### Task 7: Verify end-to-end contract without relying on the old module

**Files:**
- Modify if needed: `tools/codex_register/test_codex_register_service.py`
- Validate: `tools/codex_register/gpt-team-new.py`
- Validate: `tools/codex_register/codex_register_service.py`
- Reference spec: `tools/codex_register/docs/superpowers/specs/2026-03-18-gpt-team-new-accounts-jsonl-service-upsert-design.md`

- [ ] **Step 1: Run parser/upsert focused tests**

Run: `python -m unittest tools.codex_register.test_codex_register_service -v`
Expected: PASS.

- [ ] **Step 2: Run compile validation**

Run: `python -m py_compile tools/codex_register/gpt-team-new.py tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py`
Expected: PASS.

- [ ] **Step 3: Run a grep guard to ensure no old-module dependency was introduced**

Run: `python - <<'PY'
from pathlib import Path
content = Path('tools/codex_register/codex_register_service.py').read_text(encoding='utf-8')
print('codex_register_service_old' in content)
PY`
Expected: `False`.

- [ ] **Step 4: Verify env names are referenced exactly as designed**

Run: `python - <<'PY'
from pathlib import Path
content = Path('tools/codex_register/codex_register_service.py').read_text(encoding='utf-8')
print('CODEX_GROUP_IDS_TEAM' in content, 'CODEX_GROUP_IDS_FREE' in content)
PY`
Expected: `True True`.

- [ ] **Step 5: Commit final adjustments if any**

```bash
git add tools/codex_register/gpt-team-new.py tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "test: verify jsonl account import contract"
```
