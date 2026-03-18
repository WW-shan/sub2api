# gpt-team-new Accounts JSONL + Service Upsert Design

## Goal
Make `gpt-team-new.py` emit a structured success-only `accounts.jsonl` file, then let `codex_register_service.py` read that file and upsert accounts into the Docker-managed Postgres account system using newly implemented logic in the current service.

## Scope
- Modify `tools/codex_register/gpt-team-new.py`
- Modify `tools/codex_register/codex_register_service.py`
- Do not import or depend on `codex_register_service_old.py`
- Keep the existing register/invite/token workflow intact
- Add env-driven team/free group routing in the service layer

## Output contract
`gpt-team-new.py` should write one JSON object per line to a new success-output file such as `accounts.jsonl`.

Only write a record when the account is directly importable by the service. In practice that means the record contains the minimum fields required for upsert, especially:
- `email`
- `access_token`
- preferably `refresh_token`
- `account_id` when available

Recommended JSONL fields:
- `email`
- `password`
- `access_token`
- `refresh_token`
- `id_token`
- `account_id`
- `auth_file`
- `expires_at`
- `invited`
- `team_name`
- `created_at`
- `source`

`invited` is a first-class field. It determines group binding during service-side upsert.

## Service-side responsibilities
`codex_register_service.py` should gain a new in-file implementation of the old account-management logic:
- connect to Postgres
- parse JSONL success records
- locate existing accounts by `email` or `account_id`
- build merged `credentials` and `extra`
- update existing rows when needed
- insert new rows when missing
- bind account groups after upsert

The current service should not import helpers from the old file. It should contain its own implementations of the needed helpers.

## Group routing
The service should choose account groups based on the JSONL record's `invited` field:
- `invited == true` → bind team groups
- `invited == false` → bind free groups

Group IDs must come from Docker Compose environment variables, not hardcoded constants.

Recommended env names:
- `CODEX_GROUP_IDS_TEAM`
- `CODEX_GROUP_IDS_FREE`

Both use the same comma-separated integer format as the old service group parsing style.

## Data flow
1. `gpt-team-new.py` finishes registration/login for one account.
2. If the result is directly importable, it appends one JSONL record to `accounts.jsonl`.
3. `codex_register_service.py` reads only newly appended JSONL records.
4. For each valid record, the service upserts the account into Postgres.
5. The service binds team or free groups based on `invited`.
6. Successfully processed records are not reprocessed on the next cycle.

## Validation rules
- Records missing `email` or `access_token` are skipped.
- `account_id` is optional; if absent, email-based lookup is still allowed.
- `invited` defaults to `false` if missing.
- A failure on one record should not corrupt or block unrelated valid records.

## Non-goals
- No dependency on the old service module
- No new standalone worker process
- No broader workflow redesign
- No migration of historical txt outputs into JSONL as part of this change

## Acceptance criteria
- `gpt-team-new.py` produces structured JSONL success records only for importable accounts
- `codex_register_service.py` can read those JSONL records and upsert into Postgres without using the old module
- invited accounts bind to env-configured team groups
- non-invited accounts bind to env-configured free groups
- repeated runs do not create duplicate rows for the same account when an update path is appropriate
