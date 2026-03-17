# Codex Register Service Minimal Rebuild Design

Date: 2026-03-18

## Goal
Rebuild `tools/codex_register/codex_register_service.py` into a minimal orchestrator that only does:
1. `/enable` starts `get_tokens.py` once.
2. Wait for manual `/resume` with one email.
3. `/resume` starts `gpt-team-new.py` default `run_batch()` with injected single-team email.

All previous business logic in this service is removed.

## Hard Requirements (Approved)
- Keep frontend-required endpoints:
  - `/status`
  - `/enable`
  - `/resume`
  - `/logs`
  - `/disable`
  - `/accounts`
- Keep API response envelope: `{"success": bool, "data": any, "error": string|null}`
- `/enable` and `/resume` must be non-blocking (immediate HTTP return)
- `/resume` accepts exactly one `email`
- One active background task at a time

## Runtime/Process Contract

### Path + interpreter rules (deterministic)
- Use `sys.executable` for child process Python interpreter.
- Resolve script paths from `Path(__file__).resolve().parent`:
  - `get_tokens.py`
  - `gpt-team-new.py`
- Child process `cwd` is set to the same service directory (`tools/codex_register`).

### `/enable` behavior
- Preconditions:
  - no active child process
  - `job_phase` in `{idle, completed, failed, abandoned, waiting_manual:resume_email}`
- Action:
  - reset to new round state and set `job_phase=running:get_tokens`
  - spawn child process: `<sys.executable> <abs_get_tokens_path>`
  - return immediately
- On child exit:
  - code 0 -> `waiting_manual:resume_email`
  - non-zero / spawn error -> `failed`

### `/resume` behavior
- Input: JSON payload with `email`.
- Preconditions:
  - current `job_phase == waiting_manual:resume_email`
  - payload contains exactly one usable email field as a string (`email: str`)
  - `email` is non-empty after trim
  - no active child process
- Input validation rules (strict):
  - reject missing `email`
  - reject non-string `email` (array/object/number)
  - reject comma/semicolon-separated multi-email strings
  - normalized runtime email = `email.strip()`
- Injection mechanism (explicit):
  - spawn child process via `sys.executable -c "..."` wrapper code
  - wrapper loads `gpt-team-new.py` via `importlib.util.spec_from_file_location`
  - wrapper sets:
    - `module.TEAMS = [{"name":"1","email":"<email>","password":""}]`
  - wrapper calls `module.run_batch()`
- Return immediately after spawn.
- On child exit:
  - code 0 -> `completed`
  - non-zero / spawn error -> `failed`

### `/disable` behavior
- If active child process exists: terminate it.
- Deterministic phase/result:
  - `enabled=false`
  - `job_phase=abandoned`
  - `waiting_reason=""`
- Return immediately.

## Endpoint Contracts

### `/status`
Must always return a state object with these keys (never missing):
- `enabled` (bool)
- `job_phase` (string)
- `waiting_reason` (string)
- `can_start` (bool)
- `can_resume` (bool)
- `can_abandon` (bool)
- `last_error` (string)
- `last_success` (ISO string or empty)
- `recent_logs_tail` (array)

Phase defaults:
- `idle`: `can_start=true`, `can_resume=false`, `can_abandon=false`
- `running:get_tokens`: `can_start=false`, `can_resume=false`, `can_abandon=true`
- `waiting_manual:resume_email`: `can_start=false`, `can_resume=true`, `can_abandon=true`
- `running:gpt_team_batch`: `can_start=false`, `can_resume=false`, `can_abandon=true`
- `completed`: `can_start=true`, `can_resume=false`, `can_abandon=false`
- `failed`: `can_start=true`, `can_resume=false`, `can_abandon=true`
- `abandoned`: `can_start=true`, `can_resume=false`, `can_abandon=false`

### `/logs`
Returns in-memory event list; each log has at least `time`, `level`, `event`.

### `/accounts`
Frontend shell endpoint for this rebuild version.
- Deterministic behavior: always return `[]`.

## Validation + Error Precedence

### Validation order
1. auth check (if enabled)
2. path support check
3. active-process guard (`already_running`) for start-like actions
4. phase check (`invalid_phase`)
5. payload check (`email_required`)

### Result matrix (key cases)
- `/enable` while task active -> `already_running`
- `/resume` while task active -> `already_running`
- `/resume` in non-waiting phase -> `invalid_phase`
- `/resume` waiting phase but empty email -> `email_required`
- unknown endpoint -> `unsupported_path`

## Removed Scope (Explicit)
Delete old service internals:
- old register/invite/verify flow (`run_once`, manual parent upgrade gates, member verification)
- old auto worker loop and scheduling
- old ChatGPT service integration chain
- old DB-backed account persistence in this file
- old non-required endpoint logic (e.g., `/retry`)

## Verification Checklist
- Syntax/import check passes for rebuilt `codex_register_service.py`.
- Non-blocking checks:
  - `/enable` returns immediately while child process is alive.
  - `/resume` returns immediately while child process is alive.
- Transition checks:
  - `/enable` -> `running:get_tokens` -> `waiting_manual:resume_email`.
  - `/resume(email)` -> `running:gpt_team_batch` -> `completed|failed`.
  - `/disable` while running -> process terminates + `job_phase=abandoned`.
- Contract checks:
  - `/status` always includes required schema keys.
  - `/logs` callable at all phases.
  - `/accounts` returns empty list shell.
  - unsupported path returns `unsupported_path`.
