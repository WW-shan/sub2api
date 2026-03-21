# Codex Register Loop Proxy Rotation Design

Date: 2026-03-21

## Goal
Add a proxy-pool control flow for the Codex register loop runner so `POST /loop/start` uses a preconfigured proxy pool, verifies target-site reachability before each round, automatically rotates away from failed proxies, and prefers using a different proxy than the previous round.

## Scope
- Modify `tools/codex_register/codex_register_service.py`
- Modify `tools/codex_register/test_codex_register_service.py`
- Modify `backend/internal/handler/admin/codex_handler.go`
- Modify the frontend Codex admin API client and Codex register page UI
- Keep the existing `/enable`, `/resume`, and existing loop runner behavior intact except for adding proxy selection before each loop round

## User-approved decisions
- Proxy control applies to the loop runner started by `POST /loop/start`
- Proxy configuration is managed in the service/API layer, not via env-only or per-start request payloads
- The frontend manages a preset proxy list
- Before each loop round, the service checks whether a proxy can reach the real target site
- Proxy rotation uses ordered polling plus cooldown for failed proxies
- Each loop round should preferably use a different proxy than the previous round

## Non-goals
- Do not change the main `/enable` or `/resume` workflow to use proxy rotation in this phase
- Do not add weighted balancing, random scheduling, or external proxy-provider integration
- Do not redesign `gpt-team-new.py` into a daemon or long-lived service
- Do not make the loop exit permanently when all proxies are temporarily unavailable

## High-level behavior
Each loop round should run this sequence before spawning `gpt-team-new.py`:
1. Load the configured proxy pool and runtime proxy state.
2. Build an ordered candidate list from enabled proxies that are not currently in cooldown.
3. Prefer candidates that are different from the previous round's selected proxy.
4. Probe the real target site through each candidate proxy in order.
5. Select the first proxy whose probe succeeds.
6. If all normal candidates fail, optionally retry the previous round proxy as a last fallback if it is not permanently disabled.
7. If no proxy is usable, record the round as failed, persist `no_available_proxy`, and continue to the next scheduled round after the normal sleep interval.
8. If a proxy is selected, spawn `gpt-team-new.py` for that round with the selected proxy injected through process environment.

## State model
Persist proxy state alongside the existing Codex register service state.

### Top-level fields
- `proxy_enabled: bool`
- `proxy_pool: list[proxy]`
- `proxy_current_id: str`
- `proxy_last_used_id: str`
- `proxy_last_checked_at: str`
- `proxy_last_error: str`
- `proxy_rotation_cursor: int`
- `proxy_last_switch_reason: str`

### Per-proxy fields
Each proxy item should contain:
- `id: str`
- `name: str`
- `proxy_url: str`
- `enabled: bool`
- `last_status: "unknown" | "ok" | "failed" | "cooldown"`
- `last_checked_at: str | ""`
- `last_success_at: str | ""`
- `last_failure_at: str | ""`
- `cooldown_until: str | ""`
- `failure_count: int`

### Loop status additions
Expose loop proxy runtime fields through loop status so the frontend can show which proxy was actually used:
- `loop_current_proxy_id`
- `loop_current_proxy_name`
- `loop_last_proxy_id`
- `loop_last_proxy_name`
- `loop_last_switch_reason`

## API design
Add dedicated proxy endpoints next to the existing Codex register admin endpoints.

### `GET /proxy/status`
Returns:
- whether proxy rotation is enabled
- current selected proxy summary
- previous round proxy summary
- proxy pool entries with status and cooldown metadata
- last proxy error
- last switch reason

### `POST /proxy/list`
Persists the preset proxy list.

Request body should replace the stored list atomically with a validated array of proxy entries. Validation rules:
- `name` required and non-empty
- `proxy_url` required and non-empty
- `enabled` optional, defaults to true
- duplicate `id` values rejected
- duplicate normalized `proxy_url` values rejected

When the list is replaced:
- remove stale runtime metadata for deleted proxies
- preserve runtime metadata for unchanged proxies where feasible
- clear `proxy_current_id` if the selected proxy no longer exists or is disabled

### `POST /proxy/select`
Optional manual selection endpoint for choosing the preferred current proxy. This does not disable automatic rotation; it only sets the preferred starting point for the next selection cycle.

### `POST /proxy/test`
Runs an on-demand target-site reachability check for a specific proxy and returns the result without starting a loop round.

## Proxy selection algorithm
The selection logic should be deterministic and shared by loop rounds and manual proxy test flows where appropriate.

### Candidate ordering
1. Start from `proxy_rotation_cursor`.
2. Consider only proxies with `enabled = true`.
3. Skip proxies currently in cooldown.
4. Reorder candidates so proxies different from `proxy_last_used_id` are tried first.
5. Preserve stable ordered polling among eligible proxies.

### Probe and choose
For each candidate:
1. Probe the target site through that proxy.
2. On success:
   - set `last_status = ok`
   - update `last_checked_at` and `last_success_at`
   - clear cooldown and failure streak as appropriate
   - choose this proxy for the round
   - advance `proxy_rotation_cursor` so the next round starts after the selected proxy
3. On failure:
   - set `last_status = failed`
   - update `last_checked_at` and `last_failure_at`
   - increment `failure_count`
   - compute `cooldown_until`
   - continue to the next candidate

### Previous-proxy fallback
If all eligible non-previous proxies fail, the service may retry the previous round proxy once as a final fallback, but only if:
- it is still enabled
- it is not deleted
- it can pass the same target-site probe

This preserves the user requirement that each round should preferably use a different proxy, while still allowing progress if only the previous proxy is currently healthy.

## Probe design
The probe should verify real target-site reachability, not just generic internet access.

Requirements:
- Use the actual target registration site or a deterministic target-domain endpoint required by the registration flow
- Use the candidate proxy for the probe request
- Use a short timeout so failed proxies do not stall loop progress
- Treat connection errors, timeouts, TLS failures, and clearly invalid responses as probe failures
- Treat a successful reachable response from the target domain as probe success even if the response is not a business-success response for registration itself

The probe should be lightweight and should not consume the full registration flow.

## Proxy injection into loop rounds
Proxy choice is made by the service, but the actual round should use the chosen proxy through child-process environment variables.

Recommended contract:
- The loop runner spawns `gpt-team-new.py` with an env var such as `REGISTER_PROXY_URL`
- If the current register path already reads an existing proxy env var, the service should reuse that variable name instead of introducing a parallel contract
- The selected proxy should apply to the full child-process run for that round

This keeps proxy orchestration in the service while minimizing changes inside the registration script.

## Cooldown policy
Use ordered polling plus cooldown.

Initial implementation should be simple and deterministic:
- First probe failure puts the proxy into a fixed cooldown window
- Additional consecutive failures may extend cooldown in a small stepwise manner, but exponential backoff is not required in v1
- A successful probe clears the failure streak or resets it to zero

This is enough to avoid repeatedly selecting a clearly unhealthy proxy without overcomplicating the scheduler.

## Failure handling

### Probe failure
- Mark only the proxy state as failed/cooldown
- Continue trying the next proxy
- Do not stop the loop

### Round execution failure after proxy selection
If `gpt-team-new.py` fails after a proxy was selected:
- record the round as failed in loop history
- persist the process failure in `loop_last_error`
- do not automatically mark the selected proxy unusable solely because the child process failed

This avoids conflating generic registration failures with confirmed proxy unavailability.

### No available proxy
If all proxies are unavailable:
- do not spawn `gpt-team-new.py`
- record the round as failed
- set `loop_last_error = "no_available_proxy"`
- keep the loop active so the next round can retry after sleep

## Frontend design
Add a separate proxy-pool panel in the existing Codex register admin UI.

### Proxy list section
Display each preset proxy with:
- name
- proxy URL
- enabled/disabled state
- last status
- cooldown-until timestamp
- last success time
- last failure time

### Controls
Add controls for:
- saving the proxy list
- enabling or disabling an individual proxy
- testing an individual proxy
- optionally choosing a preferred proxy manually

### Loop runtime display
Show:
- current round proxy
- previous round proxy
- last switch reason
- available proxy count
- last proxy error

The frontend should poll proxy status and loop status with the same refresh cycle already used by the Codex register page.

## Concurrency and safety
- Proxy selection must happen inside the same service-controlled loop path that already owns round execution
- Updating the proxy list must not corrupt an in-progress round; the selected proxy for a running child process remains fixed until that round ends
- If a proxy is disabled or removed while it is currently selected for a running round, the current round may finish with it, but future rounds must not reuse it unless it is restored and re-enabled

## Testing strategy

### Python service tests
Add coverage for:
- saving and reading proxy pool state
- duplicate proxy validation
- per-round selection preferring a proxy different from the previous round
- failed probe causing automatic rotation to the next proxy
- failed proxies entering cooldown and being skipped while cooling down
- fallback to previous-round proxy only when alternatives are unavailable
- all proxies unavailable producing `no_available_proxy` while keeping the loop alive
- loop status exposing current and last proxy information
- child-process env includes the selected proxy for the round
- child-process execution failure does not automatically poison the selected proxy

### Go handler tests
Verify proxy endpoints proxy correctly to:
- `/proxy/status`
- `/proxy/list`
- `/proxy/select`
- `/proxy/test`

### Frontend tests
Add or update tests for:
- rendering proxy pool rows and statuses
- save/test/select actions calling the correct API helpers
- displaying current round proxy and previous round proxy
- showing cooldown and failure state clearly

## Acceptance criteria
- An admin can configure a preset proxy list from the Codex register UI
- `POST /loop/start` uses the stored proxy pool rather than a per-request proxy argument
- Before each loop round, the service probes the real target site through candidate proxies
- Failed proxies enter cooldown and the service automatically rotates to the next candidate
- Each round prefers a different proxy than the previous round whenever another usable proxy exists
- The selected proxy is injected into the `gpt-team-new.py` child process for that round
- If no proxy is currently usable, the round fails with `no_available_proxy` and the loop remains running for future retries
- The UI shows proxy pool health and which proxy the current or previous loop round used
