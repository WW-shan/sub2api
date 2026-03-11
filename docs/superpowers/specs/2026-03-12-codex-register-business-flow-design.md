# Codex Register Business Flow (Invite → Register → Verify → Persist)

Date: 2026-03-12
Status: Proposed

## Context
Current child workflow registers first, writes to `codex_register_accounts`, then invites, validates, and promotes to the pool. This allows `plan_type` gaps and causes resume gating on `plan_type_missing`. The desired sequence is: **invite first, then register, then verify planType, then persist**.

## Goals
- Enforce the sequence: **invite → register (select business workspace) → planType verify → persist**.
- Only persist child records after planType is confirmed (`team` counts as business).
- Keep existing promote-to-pool steps intact.

## Non-Goals
- Changing parent flow or parent verification logic.
- Removing resume gating or changing gate reasons.
- Changing DB schemas or adding new tables.

## Current Child Round (Simplified)
1) `run_one_cycle(write_to_accounts=False, register_role="child")` → registers and writes to `codex_register_accounts` (note: `write_to_accounts` only controls writes to the **accounts pool**, not the register table).
2) `invite_recent_children()`.
3) `validate_recent_child_records()` (session exchange / planType).
4) `promote_recent_child_records_to_pool()` (writes to `accounts`).

## Proposed Child Round (New Order)
1) **Generate child identity** (email/password) before registration.
2) **Invite first** using parent token to the generated email.
3) **Register child** using the same email, selecting the target business workspace.
4) **Verify planType** via `/api/auth/session?...exchange_workspace_token=true` (see Verification Rules).
5) **Persist only if verified** → write to `codex_register_accounts`, then continue existing promote-to-pool.
6) **(Optional) validate_recent_child_records** can be skipped if verification already succeeded in step 4; if retained, it should be a no-op or consistency check only.

> Verification accepts `planType` in `{"team","business"}` and follows the Verification Rules section.

## Design Changes
### 1) Pre-generate Child Identity
- Extract/introduce a helper to generate child email/password **before** registration.
- Ensure registration uses the exact same email that was invited.

### 2) Invite Before Registration
- Move `invite_recent_children()` earlier in the child round so the invite happens before registration.
- If invite fails, stop the round; do not register or persist.

### 3) Register Without Immediate Persistence
- Add a “register-only” path that **returns token info** but does **not** upsert `codex_register_accounts`.
- This avoids inserting incomplete or unverified records.

### 4) PlanType Verification Before Persistence
- Use existing session exchange (`/api/auth/session?exchange_workspace_token=true...`).
- Parse `payload.account.planType` (new) plus existing fields (`subscription.plan_type`, `accounts[ws].account.plan_type`).
- If verification fails or planType is missing → **do not persist**.

### 5) Persist After Verification
- Once verified, write to `codex_register_accounts` with planType/organization/workspace populated.
- Existing promotion (`promote_recent_child_records_to_pool`) remains the mechanism to enter the account pool.

## Retry & Idempotency
- Invite handling (including 409) follows **Invite 409 Handling (Single Rule)** below.
- **Identity reuse on retry**: if a round is retried, reuse the same generated email for that round when possible to avoid invite spam.
- If the identity cannot be recovered (process restart), generate a new email and treat previous invites as orphaned.

## Ephemeral Token Handling
- The register-only path must return **access_token + refresh_token + workspace_id** directly to the round flow.
- The verification step uses this in-memory token; no DB read is required before persistence.
- Tokens are never logged.

## Legacy Records
- Existing child records with empty plan_type are **ignored** for new rounds.
- No automatic cleanup in this change; operators can prune old rows separately if needed.

## Workspace Scoping
- The `workspace_id` used for verification is the **business workspace chosen at registration** (parent workspace_id or CODEX_PARENT_WORKSPACE_ID override).
- When parsing `payload.accounts[workspace_id]`, the same target workspace_id is used to avoid cross-workspace mismatches.

## Invite Input Source
- The invite step no longer queries `codex_register_accounts`.
- It uses the **in-memory generated child email** plus the parent’s access token and workspace metadata.
- The target workspace_id for invite/membership lookup follows the same override rule as registration (parent workspace_id or CODEX_PARENT_WORKSPACE_ID).
- `invite_recent_children` will be adapted to accept a direct `target_email` and skip DB lookups when provided.

## Retry State Storage
- Store the generated child identity (email + password) in the workflow state for the current round.
- On retry within the same process, reuse this stored identity.
- If the process restarts, fall back to generating a new identity (previous invites may remain pending).

## Legacy Record Filtering
- Validation/promote queries should continue to filter by `created_at >= NOW() - INTERVAL '30 minutes'` and require non-empty plan_type.
- This naturally excludes old rows with empty plan_type; no schema changes required.

## Retry After Registration Failure
- If registration succeeds but planType verification fails, **do not re-register** the same email.
- Instead, attempt a fresh session exchange using the existing access token; if token is expired, perform a login/token refresh path (using refresh_token if available).
- If no valid token can be obtained, abandon that identity and generate a new one on the next round.

## Token Persistence for Retry
- Store **access_token + refresh_token + workspace_id** in the in-memory workflow state for the current round.
- If verification fails, reuse the stored access_token for a second verification attempt before any re-login.
- If access_token is expired and refresh_token is present, refresh via OAuth token endpoint; otherwise abandon identity.
- No token persistence across process restarts.

## Invite 409 Handling (Single Rule)
- If invite returns 409:
  - If response explicitly indicates existing invite/membership → treat as success.
  - Else perform one follow-up membership lookup; if member or pending invite → treat as success.
  - Otherwise treat as failure.

## Validation Step
- `validate_recent_child_records` becomes a **no-op consistency check** after verification succeeds in step 4.
- It should not re-run session exchange or block the round unless persisted records are missing.

## Persistence Data Requirements
- The register-only path must return: `email`, `account_id`, `access_token`, `refresh_token`, `workspace_id`, `organization_id` (if available).
- `plan_type` is added **after verification** and included at persistence time.
- The **target workspace_id** (parent/override) is what is persisted to `codex_register_accounts`.
- Any register-only workspace_id mismatch is logged (redacted) but does not alter the persisted target.
- The **verification endpoint is always** `/api/auth/session?exchange_workspace_token=true...`.
- Acceptable planType sources in that response are:
  1) `payload.account.planType` / `payload.account.plan_type`
  2) `user.account.current_account.workspace.subscription.plan_type`
  3) `payload.accounts[workspace_id].account.plan_type` / `workspace_plan_type`
- If the response contains multiple sources, the above precedence applies.

## Registration Failure Handling
- If registration fails after a successful invite (e.g., transient error), retry registration **once** with the same identity.
- If the retry fails or the email already exists, abandon the identity and generate a new one on the next round.


## Verification Rules
- Use `access_token` (Bearer) with `/api/auth/session?exchange_workspace_token=true...`; no separate workspace token is required.
- Accept `planType` in `{team, business}`.
- Precedence order for planType:
  1) `payload.account.planType` / `payload.account.plan_type`
  2) `user.account.current_account.workspace.subscription.plan_type`
  3) `payload.accounts[workspace_id].account.plan_type` / `workspace_plan_type`
- If no planType found, treat as verification failure.
- Workspace ID matching rules follow **Workspace ID Source of Truth**.

## Persistence Timing
- Persistence to `codex_register_accounts` happens **in the same child round**, immediately after verification succeeds.
- Promotion to the pool remains in the same round via `promote_recent_child_records_to_pool`.

## Workspace Target
- Child registration uses the **parent’s workspace_id** (the business workspace) as the target selection.
- If `CODEX_PARENT_WORKSPACE_ID` is set, it remains the override for workspace selection.

## Resume Behavior
- Resume re-runs invite/register/verify **only if** no successful registration/token is stored for the round.
- If registration already succeeded and a token is available, resume skips re-registration and re-runs verify → persist.
- If the process restarted and no token is recoverable, resume generates a new identity and follows the full flow.

## Redaction Guidance
- Log emails in redacted form (e.g., `oc***@domain.tld`).
- Never log access tokens, refresh tokens, or full workspace IDs.
