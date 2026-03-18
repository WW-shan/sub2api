# Codex Register Loop Runner Design

## Goal
Add an independent frontend-controlled loop runner to the Codex register page so an admin can start and stop repeated executions of `tools/codex_register/gpt-team-new.py`, automatically persist newly created accounts into the existing `accounts` table, and record both per-round and cumulative created-account counts.

## Scope
- Modify `tools/codex_register/codex_register_service.py`
- Modify `tools/codex_register/test_codex_register_service.py`
- Modify `backend/internal/handler/admin/codex_handler.go`
- Modify frontend Codex admin API client and Codex register card UI
- Keep the existing `/enable`, `/resume`, `/disable` workflow intact
- Add a separate loop-control workflow that does not replace the current primary flow

## User-approved decisions
- The loop is controlled by a new independent button set in the frontend.
- The loop runs until an admin manually stops it.
- “Added account count” means rows actually created in the existing `accounts` table, not merely JSONL output count.
- The system must retain per-round history plus a cumulative created count.

## Non-goals
- Do not replace the current parent-account / resume workflow.
- Do not redesign `gpt-team-new.py` into a daemon.
- Do not add automatic stop-after-N behavior.
- Do not change the counting contract to include JSONL-only records.

## API design
Add a dedicated loop-control API alongside the existing Codex register endpoints:

- `GET /loop/status`
  - Returns the loop runner state, current round metadata, cumulative created count, recent history, and last error.
  - All loop endpoints should run a shared preflight that repairs stale persisted loop state before continuing. If persisted state says the loop was running but no loop worker or loop-owned subprocess exists after service restart, the service should repair the stale state by setting `loop_running = false`, `loop_stopping = false`, and `loop_last_error = "loop_worker_missing_after_restart"`.
- `POST /loop/start`
  - Starts the background loop if it is not already running.
  - Returns `already_running` if the loop is active.
- `POST /loop/stop`
  - Requests loop shutdown and stops the current `gpt-team-new.py` process if one is active.
  - Is idempotent: if the loop is already stopped, return success with the current stopped state instead of an error.

The Go admin handler should proxy these endpoints the same way it already proxies `/status`, `/logs`, `/accounts`, `/enable`, `/resume`, and `/disable`.

## State model
Persist loop state in the same service state store used by the Codex register service so status survives process restarts.

Recommended fields:
- `loop_running: bool`
- `loop_stopping: bool`
- `loop_started_at: str | None`
- `loop_current_round: int`
- `loop_last_round_started_at: str | None`
- `loop_last_round_finished_at: str | None`
- `loop_last_round_created: int`
- `loop_last_round_updated: int`
- `loop_last_round_skipped: int`
- `loop_last_round_failed: int`
- `loop_total_created: int`
- `loop_last_error: str`
- `loop_history: list[dict]`
- `loop_committed_accounts_jsonl_offset: int`

Each history entry should include:
- `round`
- `started_at`
- `finished_at`
- `created`
- `updated`
- `skipped`
- `failed`
- `status` (`success`, `failed`, or `stopped`)
- `error`

Keep only a bounded number of history entries in state, such as the latest 20, to avoid unbounded state growth.

## Execution flow
The loop runner should be independent from the current enable/resume state machine, but it should reuse the same process spawning, monitoring, JSONL parsing, and DB upsert helpers where possible.

### Start flow
When `POST /loop/start` is called:
1. Reject if the loop is already running.
2. Reject if the existing Codex workflow is already executing a different process.
3. Set loop state to running, clear last loop error, preserve cumulative counts, and start a background loop worker.

### One round
Each loop round should:
1. Read `loop_committed_accounts_jsonl_offset` as the durable processing baseline.
2. Increment the round counter.
3. Record the round start time.
4. Spawn `gpt-team-new.py` from the current tool directory.
5. Wait for the process to finish unless a stop request terminates it first.
6. On successful exit, process only JSONL records appended after `loop_committed_accounts_jsonl_offset`.
7. Use the resulting `_process_accounts_jsonl_records(...)` summary as the authoritative round result.
8. Advance `loop_committed_accounts_jsonl_offset` only after JSONL parsing and DB upsert complete successfully for that processed range.
9. Update `loop_last_round_*` fields.
10. Add `summary["created"]` into `loop_total_created`.
11. Append a bounded history entry.
12. Sleep for the existing service delay range (`sleep_min`/`sleep_max`) before the next round.

If JSONL/DB processing fails for a round, do not advance `loop_committed_accounts_jsonl_offset`. This ensures the next round retries the same uncommitted appended records instead of skipping them.

### Failure behavior
If `gpt-team-new.py` exits non-zero or JSONL/DB processing fails for a round:
- Mark the round history entry as `failed`.
- Persist the error in `loop_last_error`.
- Keep `loop_running = true` unless a manual stop was requested.
- Continue into the next round after the normal sleep interval.

This preserves the user-approved contract that the loop keeps running until an admin manually stops it, while still surfacing failures in status and history.

### Stop behavior
When `POST /loop/stop` is called:
- Set a loop stop flag.
- If a loop-owned subprocess is running, terminate it using the existing process termination pattern.
- If the worker is between rounds and sleeping, the sleep must be interruptible so stop takes effect immediately rather than waiting for the full sleep interval.
- Record the interrupted round as `stopped` if it did not finish normally.
- Set `loop_running = false` and `loop_stopping = false` once shutdown completes.

## Concurrency and safety rules
The service should enforce mutual exclusion between the current Codex workflow and the new loop workflow:
- If `/enable` or `/resume` is active, `/loop/start` must reject.
- If the loop is active, `/enable` and `/resume` must reject.
- `/disable` should continue to affect only the existing main flow unless explicitly extended.

This avoids one service instance trying to run two unrelated automation modes at the same time.

## Counting contract
The product contract for “added accounts” is:
- Count only accounts whose DB upsert action is `created`.
- Do not count `updated`, `skipped`, or JSONL-only output.
- Surface both per-round counts and cumulative loop totals.

This ensures the displayed count matches actual new rows added to the system account table.

## Frontend design
Keep the current Codex register control bar and workflow UI intact. Add a separate loop-runner panel within the same admin card component.

### New frontend controls
Add two independent controls:
- `开始循环注册`
- `停止循环注册`

Behavior:
- Start is enabled only when the loop is not running.
- Stop is enabled only when the loop is running.
- Both are disabled while the specific request is in flight.

### Loop status panel
Display:
- loop running state
- current round
- last round created count
- cumulative created count
- last round start time
- last round end time
- last loop error

### Loop history panel
Display recent rounds in a compact list or table with:
- round number
- status
- created
- updated
- skipped
- failed
- started at
- finished at
- error

The frontend should poll loop status alongside the existing page refresh cycle.

## Frontend API client
Extend `frontend/src/api/admin/codex.ts` with dedicated loop helpers:
- `getLoopStatus()`
- `startLoop()`
- `stopLoop()`

These should unwrap the same envelope format as the existing Codex API helpers.

## Testing strategy
### Python service tests
Add coverage for:
- `/loop/start` starts the loop state
- duplicate start returns `already_running`
- `/loop/stop` stops the loop and is idempotent when already stopped
- stale persisted `loop_running` state is repaired after restart/status read
- one successful round records created counts and cumulative totals correctly
- failed process exit records failed history and last error while the loop remains eligible for the next round
- interrupted process exit records stopped history
- loop/main-workflow mutual exclusion rules

Prefer extracting a single-round helper so round behavior is unit-testable without relying on fragile background-thread timing.

### Go handler tests
Verify the new admin routes proxy correctly to:
- `/loop/status`
- `/loop/start`
- `/loop/stop`

### Frontend tests
Add or update tests to cover:
- loop status rendering
- start/stop button enabled states
- start button calling `startLoop()`
- stop button calling `stopLoop()`
- loop history rendering

## Acceptance criteria
- The Codex register page shows a separate loop-runner control area without replacing the existing main workflow.
- An admin can start and stop repeated `gpt-team-new.py` execution from the frontend.
- Each successful round processes only newly appended JSONL records into the `accounts` table.
- The UI shows the DB-created count for the last round and the cumulative loop-created total.
- The service keeps a bounded recent history of loop rounds.
- The loop and the existing main workflow cannot run simultaneously.
