# Cumulative Codex Persisted Count Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `codex_total_persisted_accounts` status field that reports the cumulative number of Codex accounts actually created in the database during the current service lifecycle.

**Architecture:** Extend `CodexRegisterService` state with one new cumulative counter and update it only at the points where DB-created results are already known. Reuse existing `summary["created"]` and parent persistence action outputs rather than inventing new counting paths, and expose the new field through the existing `/status` state payload automatically.

**Tech Stack:** Python 3, existing `CodexRegisterService` state machine, unittest/pytest in `tools/codex_register/test_codex_register_service.py`.

---

## File map

- Modify: `tools/codex_register/codex_register_service.py`
  - Add `codex_total_persisted_accounts` to default state.
  - Update main `/resume` success path to increment by child `created` count plus parent `created` delta.
  - Update loop round success path to increment by round `summary["created"]`.
  - Add the new field to the status payload builder.
- Modify: `tools/codex_register/test_codex_register_service.py`
  - Add focused tests for default state, `/status`, main resume counting, parent `created` vs `updated`, and loop counting behavior.

## Task 1: Add the new cumulative state field and expose it in status

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write a failing test for default state and `/status` exposure**

Add a test that verifies:
- `_default_state()` includes `codex_total_persisted_accounts == 0`
- `handle_path("/status")` returns that field

Example:

```python
def test_status_includes_cumulative_codex_persisted_accounts(self):
    ...
```

- [ ] **Step 2: Run the targeted test to verify it fails**

Run: `python -m pytest "D:/Code/sub2api/tools/codex_register/test_codex_register_service.py" -k "cumulative_codex_persisted_accounts and status" -v`
Expected: FAIL because the field is not present yet.

- [ ] **Step 3: Implement the minimal state change**

In `codex_register_service.py`:
- Add `"codex_total_persisted_accounts": 0` to `_default_state()`
- Include it in `_build_accounts_status_data(state)`

- [ ] **Step 4: Re-run the targeted test**

Run the same command.
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: expose cumulative codex persisted count in status"
```

## Task 2: Count DB-created child accounts in the main `/resume` flow

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write a failing test for child-created accumulation in `/resume`**

Add a test that simulates the `return_code == 0 and mode == "resume"` branch with:
- `_process_accounts_jsonl_records(state)` returning `{"created": 5, "failed": 0, ...}`
- parent normalization doing no extra parent create

Assert that `codex_total_persisted_accounts` increases by 5.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest "D:/Code/sub2api/tools/codex_register/test_codex_register_service.py" -k "resume child created count" -v`
Expected: FAIL

- [ ] **Step 3: Implement minimal `/resume` accumulation logic**

In the `mode == "resume"` success path, after `processing_summary` is known and before completion is saved:

```python
state["codex_total_persisted_accounts"] = int(state.get("codex_total_persisted_accounts") or 0) + int(processing_summary.get("created") or 0)
```

Keep this limited to `created`, not `updated` or `skipped`.

- [ ] **Step 4: Re-run the targeted test**

Run the same command.
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: count created child accounts in resume totals"
```

## Task 3: Count parent `created` only when parent persistence action is `created`

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write failing tests for parent action handling**

Add two tests:
1. parent persistence action is `created` → cumulative count gets `+1`
2. parent persistence action is `updated` or `skipped` → cumulative count gets `+0`

You can drive this by setting `state["last_parent_persist_action"]` from the normalization step or by stubbing `_normalize_parent_record_after_resume()` to add that field.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest "D:/Code/sub2api/tools/codex_register/test_codex_register_service.py" -k "parent persist action count" -v`
Expected: FAIL

- [ ] **Step 3: Implement the minimal parent delta logic**

In the `/resume` success path, compute:

```python
parent_action = str(state.get("last_parent_persist_action") or "")
parent_created_delta = 1 if parent_action == "created" else 0
```

and add that to `codex_total_persisted_accounts` together with the child `created` count.

- [ ] **Step 4: Re-run the targeted tests**

Run the same command.
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: count parent create action in cumulative persisted total"
```

## Task 4: Count loop-created accounts without double counting or parent counting

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write failing loop-count tests**

Add tests that verify:
- successful loop round with `summary["created"] == 3` adds 3 to `codex_total_persisted_accounts`
- failed loop round does not add to `codex_total_persisted_accounts`
- loop mode does not apply any extra parent `+1`

- [ ] **Step 2: Verify RED**

Run: `python -m pytest "D:/Code/sub2api/tools/codex_register/test_codex_register_service.py" -k "loop persisted count" -v`
Expected: FAIL

- [ ] **Step 3: Implement the minimal loop accumulation**

In `_run_loop_round(state, generation)`, when `summary` exists and the round has succeeded, add:

```python
state["codex_total_persisted_accounts"] = int(state.get("codex_total_persisted_accounts") or 0) + int(summary.get("created") or 0)
```

Do this only on the success path after DB-created counts are known.

- [ ] **Step 4: Re-run the targeted loop tests**

Run the same command.
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: count created loop accounts in cumulative persisted total"
```

## Task 5: Verify end-to-end status semantics and failure behavior

**Files:**
- Modify: `tools/codex_register/test_codex_register_service.py`
- Reference: `tools/codex_register/codex_register_service.py`

- [ ] **Step 1: Write a failing integration-style status test**

Add one higher-level test that simulates:
- an initial status with zero total
- one successful `/resume` path contributing child `created` plus optional parent `created`
- one loop round contributing additional created count
- one failure path that should not increment when no DB `created` occurs
- one path where DB `created` already happened and a later failure occurs, proving the cumulative value is retained and not rolled back

Then assert the final `/status` data returns the correct `codex_total_persisted_accounts`.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest "D:/Code/sub2api/tools/codex_register/test_codex_register_service.py" -k "cumulative persisted count integration" -v`
Expected: FAIL

- [ ] **Step 3: Implement only the glue needed for this full behavior**

If earlier task implementations are correct, this step should be minimal or no-op.

- [ ] **Step 4: Re-run the integration test**

Run the same command.
Expected: PASS

- [ ] **Step 5: Run the full relevant test file**

Run: `python -m pytest "D:/Code/sub2api/tools/codex_register/test_codex_register_service.py" -v`
Expected: PASS

- [ ] **Step 6: Run syntax verification**

Run: `python -m py_compile "D:/Code/sub2api/tools/codex_register/codex_register_service.py"`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "feat: add cumulative codex persisted account count"
```

## Notes for the implementing agent

- Treat `codex_total_persisted_accounts` as a lifecycle-local counter, not a DB snapshot.
- Only increment on confirmed DB `created` results.
- Do not subtract on later failures in the same workflow.
- Do not count `updated` or `skipped` actions.
- Keep `total_created` and `loop_total_created` semantics unchanged.
- Do not modify frontend code in this implementation.
