# Loop Start Baseline Offset Delta Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change codex register loop startup so the first loop persistence only imports accounts appended after loop start, excluding any pre-existing `accounts.jsonl` records.

**Architecture:** This is a narrowly scoped delta fix on top of the already-implemented loop-runner behavior in `CodexRegisterService`. Keep the existing loop round processing, failure/continue behavior, bounded history, cumulative counters, stop semantics, and frontend/API wiring unchanged; change only the `/loop/start` initialization semantics so a fresh loop snapshots the current JSONL tail before its first round. Add a focused regression test to lock in the behavior.

**Tech Stack:** Python, `unittest`, existing `CodexRegisterService` loop state helpers in `tools/codex_register`.

---

## Scope and invariants

This plan is **not** a full implementation plan for the original loop-runner spec. It is a **targeted bugfix plan** for an already-landed loop feature.

Required invariants that must remain unchanged:
- `/loop/start`, `/loop/status`, `/loop/stop` endpoint contracts remain unchanged except for the initial loop baseline.
- `_process_loop_accounts_jsonl_round()` still processes records after `loop_committed_accounts_jsonl_offset`.
- `_run_loop_round()` still updates history, per-round stats, cumulative counts, and failure/stopped states the same way.
- Stale loop-state repair and loop/main-workflow mutual exclusion behavior remain unchanged.
- The fix only affects a **fresh accepted loop start**. Rejected starts (`already_running`, `loop_stopping`, `main_workflow_running`) must not alter persisted offsets.

---

## File Map

- **Service implementation**
  - Modify: `tools/codex_register/codex_register_service.py`
    - Update `_handle_loop_start()` to initialize `loop_committed_accounts_jsonl_offset` from the current JSONL file offset instead of leaving the default historical value.
- **Service tests**
  - Modify: `tools/codex_register/test_codex_register_service.py`
    - Add a regression test proving loop start snapshots the current JSONL end offset and therefore excludes pre-start records from the first round.

---

## Task 1: Add failing regression tests for fresh-loop baseline behavior

**Files:**
- Modify: `tools/codex_register/test_codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Write a failing round-level test proving pre-start rows are excluded**

```python
def test_loop_start_baseline_excludes_preexisting_jsonl_rows_from_first_round(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "accounts.jsonl"
        old_line = json.dumps({"email": "old@example.com", "access_token": "old-token"}) + "\n"
        path.write_text(old_line, encoding="utf-8")
        self.service._accounts_jsonl_path = path

        with patch.object(self.service, "_start_loop_worker", return_value=(None, "")):
            start_result = asyncio.run(self.service.handle_path("/loop/start", payload={}))

        self.assertTrue(start_result["success"])

        new_line = json.dumps({"email": "new@example.com", "access_token": "new-token"}) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(new_line)

        state = asyncio.run(self.service._load_state())

        with patch.object(self.service, "_run_loop_process_once", return_value=0), \
             patch.object(self.service, "_create_db_connection", return_value=FakeConnection(FakeCursor(insert_ids=[901]))), \
             patch.object(self.service, "_pg_json", side_effect=lambda value: value):
            history = asyncio.run(self.service._run_loop_round(state))

        self.assertEqual(history["status"], "success")
        self.assertEqual(history["created"], 1)
        self.assertEqual(history["updated"], 0)
        self.assertEqual(history["skipped"], 0)
        self.assertEqual(history["failed"], 0)
        summary = history["summary"]
        self.assertEqual(summary["records_seen"], 1)
        self.assertEqual(summary["start_offset"], len(old_line.encode("utf-8")))
        self.assertEqual(summary["end_offset"], len((old_line + new_line).encode("utf-8")))
```

This test must fail before the fix because a fresh loop start currently leaves `loop_committed_accounts_jsonl_offset = 0`, so the first round would process both old and new rows instead of only post-start rows.

- [ ] **Step 2: Write a failing start-endpoint test proving accepted loop start snapshots the current file tail**

```python
def test_loop_start_captures_current_accounts_jsonl_offset_as_first_round_baseline(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "accounts.jsonl"
        existing_lines = [
            json.dumps({"email": "old1@example.com", "access_token": "t1"}),
            json.dumps({"email": "old2@example.com", "access_token": "t2"}),
        ]
        path.write_text("\n".join(existing_lines) + "\n", encoding="utf-8")
        self.service._accounts_jsonl_path = path

        with patch.object(self.service, "_start_loop_worker", return_value=(None, "")):
            result = asyncio.run(self.service.handle_path("/loop/start", payload={}))

        self.assertTrue(result["success"])
        expected_offset = len(path.read_bytes())
        self.assertEqual(result["data"]["loop_committed_accounts_jsonl_offset"], expected_offset)

        persisted = asyncio.run(self.service._load_state())
        self.assertEqual(persisted["loop_committed_accounts_jsonl_offset"], expected_offset)
```

- [ ] **Step 3: Write a failing negative-path test proving rejected starts do not mutate the offset**

```python
def test_loop_start_rejection_keeps_existing_loop_committed_offset(self):
    state = self.service._default_state()
    state["loop_running"] = True
    state["loop_committed_accounts_jsonl_offset"] = 123
    asyncio.run(self.service._save_state(state))

    result = asyncio.run(self.service.handle_path("/loop/start", payload={}))

    self.assertFalse(result["success"])
    self.assertEqual(result["error"], "already_running")
    latest = asyncio.run(self.service._load_state())
    self.assertEqual(latest["loop_committed_accounts_jsonl_offset"], 123)
```

- [ ] **Step 4: Run the targeted tests to verify they fail**

Run: `python -m unittest tools.codex_register.test_codex_register_service.LoopStateTests.test_loop_start_captures_current_accounts_jsonl_offset_as_first_round_baseline tools.codex_register.test_codex_register_service.LoopStateTests.test_loop_start_rejection_keeps_existing_loop_committed_offset tools.codex_register.test_codex_register_service.LoopRoundTests.test_loop_start_baseline_excludes_preexisting_jsonl_rows_from_first_round -v`
Expected: FAIL because accepted loop start currently leaves the committed offset at `0`.

- [ ] **Step 5: Commit the red tests**

```bash
git add tools/codex_register/test_codex_register_service.py
git commit -m "test: cover loop start baseline semantics"
```

---

## Task 2: Initialize loop baseline from current JSONL end offset

**Files:**
- Modify: `tools/codex_register/codex_register_service.py`
- Test: `tools/codex_register/test_codex_register_service.py`

- [ ] **Step 1: Update `/loop/start` state initialization**

Inside `tools/codex_register/codex_register_service.py:_handle_loop_start`, after the loop run is accepted and **before** `_start_loop_worker(generation)` is invoked, capture the current JSONL tail:

```python
state["loop_committed_accounts_jsonl_offset"] = self._capture_accounts_jsonl_offset()
```

Capturing the baseline before worker launch is required so rows appended immediately after the user clicks start are included in the first round, while rows that already existed before start remain excluded.

- [ ] **Step 2: Keep the rest of the loop semantics unchanged**

Do not modify:
- `_process_loop_accounts_jsonl_round()`
- `_run_loop_round()`
- main workflow `accounts_jsonl_baseline_offset`
- cumulative loop counters/history behavior

The only contract change is the starting committed offset for a newly started loop.

- [ ] **Step 3: Run the targeted regression test to verify it passes**

Run: `python -m unittest tools.codex_register.test_codex_register_service.LoopStateTests.test_loop_start_captures_current_accounts_jsonl_offset_as_first_round_baseline -v`
Expected: PASS

- [ ] **Step 4: Run the relevant loop test class to catch regressions**

Run: `python -m unittest tools.codex_register.test_codex_register_service.LoopStateTests tools.codex_register.test_codex_register_service.LoopRoundTests -v`
Expected: PASS

- [ ] **Step 5: Commit the green change**

```bash
git add tools/codex_register/codex_register_service.py tools/codex_register/test_codex_register_service.py
git commit -m "fix: start codex loop from current jsonl offset"
```

---

## Verification Notes

- The new test should prove the loop snapshots the file tail at start time.
- Existing loop-round tests should still pass, confirming only the start baseline changed.
- No frontend, Go proxy, or non-loop workflow changes are needed for this request.
