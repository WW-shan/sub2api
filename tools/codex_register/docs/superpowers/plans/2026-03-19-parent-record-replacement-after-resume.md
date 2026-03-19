# Parent Record Replacement After Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/resume` replace the old `get_tokens` parent row with a single `gpt-team-new`-format parent record, ensure that parent is persisted to DB first, and avoid duplicates or offset corruption.

**Architecture:** Keep the current `enable -> get_tokens` and `resume -> gpt-team-new batch` split, but add a post-resume normalization stage inside `codex_register_service.py`. That stage will construct a parity-format parent record, upsert it into the database, atomically rewrite `accounts.jsonl` to remove the old `get_tokens` parent row and any duplicate parent rows, then recalculate state offsets from the rewritten file before marking the workflow completed.

**Tech Stack:** Python 3, stdlib file I/O and temp files, existing PostgreSQL upsert helpers in `codex_register_service.py`, unittest/pytest in `tools/codex_register/test_codex_register_service.py`.

---

## File map

- Modify: `tools/codex_register/codex_register_service.py`
  - Add a focused parent-record normalization helper chain.
  - Update the `mode == "resume"` success path to perform parent DB upsert, atomic JSONL rewrite, and offset recalculation before final completion.
  - Keep child-account batch processing logic intact.
- Modify: `tools/codex_register/test_codex_register_service.py`
  - Add targeted tests for parent record construction, DB-first ordering, atomic rewrite behavior, old-row deletion, duplicate parent cleanup, and offset recalculation.
- Reference only: `tools/codex_register/gpt-team-new.py`
  - Provides the target parent record shape semantics.
- Reference only: `tools/codex_register/get_tokens.py`
  - Continues to emit the initial temporary parent row.

## Task 1: Add failing tests for parent normalization trigger in resume success path

**Files:**
- Modify: `tools/codex_register/test_codex_register_service.py`
- Modify: `tools/codex_register/codex_register_service.py`

- [ ] **Step 1: Write a failing test that `/resume` success triggers parent normalization before completion**

Add a test that simulates the `mode == "resume"` branch in `_handle_process_exit()` and asserts a new helper (for example `_normalize_parent_record_after_resume`) is called before the state is moved to `completed`.

Example skeleton:

```python
def test_resume_success_normalizes_parent_record_before_completed_state(self):
    ...
```

- [ ] **Step 2: Run the targeted test to verify it fails**

Run: `python -m pytest "D:/Code/sub2api/tools/codex_register/test_codex_register_service.py" -k "normalize_parent_record_before_completed_state" -v`
Expected: FAIL because the helper does not exist or is not called.

- [ ] **Step 3: Add the minimal hook in `codex_register_service.py`**

Introduce a helper stub such as:

```python
def _normalize_parent_record_after_resume(self, state: Dict[str, Any], *, email: str) -> Dict[str, Any]:
    raise NotImplementedError
```

Then call it from the `return_code == 0 and mode == "resume"` success branch before the `completed` phase transition.

- [ ] **Step 4: Re-run the targeted test**

Run the same command and verify the test now reaches the helper call path.
Expected: PASS or moves to the next more specific failure.

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "refactor: hook parent normalization into resume success"
```

## Task 2: Build and validate the parity-format parent record

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write a failing test for parent record construction**

Add a test that feeds:
- an old `get_tokens` parent record
- a latest parent record snapshot
- a `resume_context`

and expects a constructed parent record with:
- `source == "gpt-team-new"`
- `codex_register_role == "parent"`
- `invited is False`
- field precedence matching the spec
- normalized email

- [ ] **Step 2: Verify the test fails for the intended reason**

Run: `python -m pytest "D:/Code/sub2api/tools/codex_register/test_codex_register_service.py" -k "parent record construction" -v`
Expected: FAIL because the record builder does not exist yet.

- [ ] **Step 3: Add a focused builder helper**

Implement a small helper such as:

```python
def _build_parent_record_after_resume(
    self,
    *,
    old_parent_record: Dict[str, Any],
    latest_parent_record: Dict[str, Any],
    resume_context: Dict[str, Any],
) -> Dict[str, Any]:
    ...
```

Required field precedence:
- `password`: old get_tokens record first
- `access_token`, `refresh_token`, `id_token`, `account_id`, `auth_file`, `expires_at`: latest record first, then old record, then empty string
- `created_at`: old record first, then now
- `updated_at`: now
- `plan_type`, `organization_id`, `workspace_id`: latest current state, with `organization_id` / `workspace_id` falling back to empty string when missing
- `source`: always `gpt-team-new`
- `codex_register_role`: always `parent`
- `invited`: always `False`
- `team_name`: `resume_context.team_name`

- [ ] **Step 4: Re-run the targeted test**

Run the same test command.
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: build parity parent record after resume"
```

## Task 3: Enforce DB-first persistence before deleting the old parent row

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write a failing test for DB-first ordering**

Add a test asserting:
1. parent record is upserted first
2. file rewrite happens second
3. if upsert raises, old `get_tokens` parent row is not removed and workflow does not complete

- [ ] **Step 1.5: Add failing tests for build-failure and rewrite-failure state handling**

Add tests asserting that if:
- parent record construction fails, or
- JSONL rewrite fails,

then the workflow:
- does not enter `completed`
- preserves the old `get_tokens` parent row
- records an explicit error label such as `parent_record_rewrite_failed` or a similarly specific failure code

- [ ] **Step 2: Verify RED**

Run: `python -m pytest "D:/Code/sub2api/tools/codex_register/test_codex_register_service.py" -k "db first parent" -v`
Expected: FAIL because ordering and failure behavior are not implemented.

- [ ] **Step 3: Add a single-purpose helper to persist one parent record**

Implement something like:

```python
def _persist_single_parent_record(self, record: Dict[str, Any]) -> str:
    ...
```

Use existing helpers:
- `_create_db_connection()`
- `_upsert_account()`
- `_safe_close()`

Return the upsert action (`created`, `updated`, or `skipped`) or raise on failure.

- [ ] **Step 4: Wire DB-first behavior into normalization flow**

In `_normalize_parent_record_after_resume(...)`:
1. build the new parent record
2. persist it to DB
3. only if that succeeds, continue to JSONL rewrite

- [ ] **Step 5: Re-run the targeted test**

Run the same DB-first test command.
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: persist parent record before jsonl replacement"
```

## Task 4: Atomically rewrite `accounts.jsonl` and remove the old `get_tokens` parent row

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write a failing test for JSONL rewrite semantics**

Add a test that starts with a file containing:
- one old `get_tokens` parent row
- optional malformed/raw line
- one duplicate `gpt-team-new` parent row
- child rows

Expect the final rewritten file to:
- preserve malformed/raw lines unchanged
- preserve malformed/raw lines in their original relative order
- remove the old `get_tokens` parent row
- remove duplicate rows matching `source == "gpt-team-new" and codex_register_role == "parent"` for the same normalized email
- contain exactly one latest `gpt-team-new` parent row
- preserve child rows

- [ ] **Step 2: Verify RED**

Run: `python -m pytest "D:/Code/sub2api/tools/codex_register/test_codex_register_service.py" -k "jsonl rewrite semantics" -v`
Expected: FAIL

- [ ] **Step 3: Implement raw-line-aware file parsing for rewrite**

Add a helper that reads the file into a structure preserving:
- original raw line text
- parsed record when valid
- normalized email and source when available

Do not reuse `_read_accounts_jsonl_records()` for this rewrite step because it drops invalid lines.

- [ ] **Step 4: Implement temp-file + atomic replace rewrite**

Add a helper such as:

```python
def _rewrite_accounts_jsonl_with_parent_record(
    self,
    *,
    normalized_email: str,
    parent_record: Dict[str, Any],
) -> Dict[str, Any]:
    ...
```

Requirements:
- write to a temp file in the same directory
- flush/fsync if available
- atomically replace the original file
- leave original untouched on failure

- [ ] **Step 5: Re-run the rewrite test**

Run the same targeted command.
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: atomically replace old parent jsonl row after resume"
```

## Task 5: Recalculate offsets after rewrite and prevent duplicate/skip behavior

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write a failing test for offset recalculation after rewrite**

Add a test that simulates a rewritten file and verifies state updates after normalization set:
- `accounts_jsonl_offset`
- `accounts_jsonl_baseline_offset`
- `last_processed_offset`

to valid positions for the rewritten file, not stale old byte offsets.
Also assert the recalculated offsets lead to no duplicate-processing and no skipped-processing of the rewritten parent record and retained child records in the next processing step.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest "D:/Code/sub2api/tools/codex_register/test_codex_register_service.py" -k "offset recalculation" -v`
Expected: FAIL

- [ ] **Step 3: Implement offset recalculation helper**

Implement something like:

```python
def _recalculate_offsets_after_parent_rewrite(self, state: Dict[str, Any]) -> None:
    ...
```

It should rescan the rewritten file and set safe post-rewrite offsets. Prefer deterministic values based on actual `line_end_offset` or final EOF, and ensure no follow-up processing will duplicate or skip newly rewritten records.

- [ ] **Step 4: Re-run the offset test**

Run the same command.
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "fix: recalculate offsets after parent jsonl rewrite"
```

## Task 6: Verify end-to-end resume normalization behavior

**Files:**
- Modify: `tools/codex_register/test_codex_register_service.py`
- Reference: `tools/codex_register/codex_register_service.py`

- [ ] **Step 1: Write an end-to-end regression test for resume success**

Add one high-level service test that simulates:
- old parent `get_tokens` row present
- child rows appended by resume batch
- successful parent normalization

And verifies all of these together:
- DB parent upsert happened before rewrite
- final file contains one `gpt-team-new` parent row
- old `get_tokens` parent row is gone
- child rows remain
- workflow ends in `completed`

- [ ] **Step 2: Verify RED**

Run: `python -m pytest "D:/Code/sub2api/tools/codex_register/test_codex_register_service.py" -k "resume success parent normalization" -v`
Expected: FAIL until the integrated flow is complete.

- [ ] **Step 3: Implement the minimal glue needed for the full flow**

Wire together:
- parent record selection
- parent record build
- parent DB-first persistence
- atomic file rewrite
- offset recalculation
- final state save

Do not refactor unrelated workflow branches.

- [ ] **Step 4: Re-run the regression test**

Run the same targeted command.
Expected: PASS

- [ ] **Step 5: Run the full relevant test file**

Run: `python -m pytest "D:/Code/sub2api/tools/codex_register/test_codex_register_service.py" -v`
Expected: PASS

- [ ] **Step 6: Run syntax verification**

Run: `python -m py_compile "D:/Code/sub2api/tools/codex_register/codex_register_service.py" "D:/Code/sub2api/tools/codex_register/get_tokens.py" "D:/Code/sub2api/tools/codex_register/gpt-team-new.py"`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: replace temporary parent row after resume"
```

## Notes for the implementing agent

- Keep the parent rewrite logic separate from `_process_accounts_jsonl_records()`; that batch path remains for child accounts.
- Do not delete the old parent row before the new parent record has been built and upserted successfully.
- Do not use in-place line editing for `accounts.jsonl`; temp-file + atomic replace is required.
- Preserve malformed/unparseable lines exactly as-is during rewrite.
- Normalize parent email matching with `strip().lower()` consistently in both implementation and tests.
- Avoid broad refactors. The right amount of change is the minimum needed to normalize the parent record after resume.
