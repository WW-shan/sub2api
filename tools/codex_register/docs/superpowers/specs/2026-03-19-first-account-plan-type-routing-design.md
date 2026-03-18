# First Account planType-Based Group Routing Design

## Goal
Ensure the first account imported through the codex register flow is grouped based on the actual ChatGPT session `account.planType` value observed after the existing gpt-team login flow, without adding extra heuristic checks.

## Scope
- Modify `tools/codex_register/gpt-team-new.py`
- Modify `tools/codex_register/codex_register_service.py`
- Do not add new session-detection heuristics such as workspace/organization inference
- Reuse the existing `/api/auth/session` call already present in `gpt-team-new.py`

## Design
`gpt-team-new.py` already calls `https://chatgpt.com/api/auth/session` after ChatGPT login. The response contains:

```json
{
  "account": {
    "planType": "team"
  }
}
```

The change should:
1. Read `account.planType` directly from that existing session response.
2. Persist it on the emitted importable account record as `plan_type`.
3. Let `codex_register_service.py` choose account groups from `plan_type`.

## Record contract
The emitted JSONL/importable record should include:
- `plan_type`

Optional derived helper fields such as `is_team_plan` are not required for correctness. The service can use `plan_type` directly.

## Group routing rule
Service-side group routing must follow this rule:
- if `plan_type == "team"` → use `CODEX_GROUP_IDS_TEAM`
- else if `plan_type` exists but is not `team` → use `CODEX_GROUP_IDS_FREE`
- else (legacy records without `plan_type`) → fall back to existing `invited` logic for backward compatibility

## Non-goals
- No additional `auth/session` request from the service layer
- No inference from workspace, organization, projects, or other account/session fields
- No broader workflow redesign

## Acceptance criteria
- `gpt-team-new.py` extracts `account.planType` from the existing session response
- emitted account records include `plan_type`
- `codex_register_service.py` routes team/free groups from `plan_type`
- legacy records without `plan_type` still import correctly using fallback logic
