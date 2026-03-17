# gpt-team-new Remove config.yaml Design

## Goal
Remove `config.yaml` dependency from `gpt-team-new.py` and use hardcoded fixed values for all runtime settings.

## Scope
- Modify only `gpt-team-new.py`
- Remove config loading and yaml dependency
- Replace all `_cfg`-derived values with module-level constants
- Keep existing register/login/invite/token workflow unchanged

## Fixed values to hardcode
- `TOTAL_ACCOUNTS`
- `MAIL_WORKER_BASE_URL`, `MAIL_WORKER_TOKEN`, `MAIL_DOMAIN`, `MAIL_POLL_SECONDS`, `MAIL_POLL_MAX_ATTEMPTS`
- `CLI_PROXY_API_BASE`, `CLI_PROXY_PASSWORD`, `CPA_UPLOAD_ENABLED`
- `ACCOUNTS_FILE`, `INVITE_TRACKER_FILE`
- `TEAMS`

## Implementation notes
- Delete `_CONFIG_FILE`, `_load_config()`, `_cfg`
- Delete `import yaml`
- Update startup logs to indicate fixed constants are loaded
- Ensure no code path still references config data

## Validation
- `python -m py_compile gpt-team-new.py`
- grep checks for: `_cfg`, `_load_config`, `config.yaml`, `yaml`
- smoke import/execution of module header without config file
